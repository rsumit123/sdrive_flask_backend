from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import bcrypt
import jwt
import datetime
import os
from dotenv import load_dotenv
from auth import token_required
import boto3
from flask import send_file, Response
from werkzeug.utils import secure_filename
import requests
from utils import get_bucket_url
from mongo_handler import MongoDBHandler
import logging

# Load environment variables
load_dotenv()


# Configure Flask app
MONGO_URI = os.getenv('MONGO_URI')
SECRET_KEY = os.getenv('SECRET_KEY')

# Use MongoClient directly from pymongo
client = MongoClient(MONGO_URI)

# Access the database
db = client["db"]

# Set up logging
logger = logging.getLogger('flask_app')
logger.setLevel(logging.DEBUG)  # Set the desired logging level
# Create and add the MongoDB handler
mongo_handler = MongoDBHandler(db.logs)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
mongo_handler.setFormatter(formatter)
logger.addHandler(mongo_handler)

MAX_FILE_SIZE = 1024 * 1024 * 800  # 800MB

def list_files_v2(current_user):
    try:
        logger.debug(f"Listing files for {current_user['email']}")

        # Setup S3 client
        logger.debug(f"Setting up S3 client")
        s3 = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_APP_S3_REGION_NAME')
        )

        prefix = current_user['email'].split('.com')[0].replace("@", "-")
        bucket_name = os.getenv('AWS_APP_STORAGE_BUCKET_NAME')

        # Fetch pagination parameters from query args with default values
        try:
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 50))
            if page < 1 or per_page < 1:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Invalid pagination parameters. 'page' and 'per_page' must be positive integers."}), 400

        logger.debug(f"Pagination parameters - Page: {page}, Per Page: {per_page}")

        # Step 1: Get the total count of files from the database
        total_files = db.files.count_documents({
            "upload_complete": "complete",
            "s3_key": {"$regex": f"^{prefix}/"}
        })
        logger.debug(f"Total files in DB for user: {total_files}")

        # Calculate total pages
        total_pages = (total_files + per_page - 1) // per_page

        # Step 2: Fetch the s3_keys for the current page
        # Sorting by 'last_modified' descending for consistency
        file_records_cursor = db.files.find(
            {"upload_complete": "complete", "s3_key": {"$regex": f"^{prefix}/"}},
            {"s3_key": 1, "upload_complete": 1, "last_modified": 1}
        ).sort("last_modified", -1).skip((page - 1) * per_page).limit(per_page)
        file_records = list(file_records_cursor)
        valid_keys = [record['s3_key'] for record in file_records]

        if not valid_keys:
            return jsonify({
                "files": [],
                "total": total_files,
                "total_pages": total_pages,
                "page": page,
                "per_page": per_page
            }), 200

        # Step 3: Retrieve metadata from S3 for the valid_keys
        files = []
        for key in valid_keys:
            try:
                s3_object = s3.head_object(Bucket=bucket_name, Key=key)
                files.append({
                    'file_name': key.split("/")[-1],
                    'simple_url': get_bucket_url() + key,
                    'metadata': {
                        "tier": s3_object.get('StorageClass', 'standard').lower(),
                        "size": s3_object.get('ContentLength', 0)
                    },
                    'upload_complete': 'complete',
                    "last_modified": s3_object.get('LastModified').isoformat(),  # Use ISO format for consistency
                    'id': key,  # Ensure 'id' is unique
                    "s3_key": key
                })
            except Exception as e:
                logger.exception(f"Error retrieving S3 metadata for {key}: {str(e)}")
                # Optionally, skip or handle missing S3 metadata
                continue

        # **Ensure that 'files' array has up to 'per_page' items**
        # If some 'head_object' calls failed, fetch additional records
        if len(files) < per_page and (page * per_page) < total_files:
            remaining = per_page - len(files)
            extra_skip = (page - 1) * per_page + len(files)
            extra_file_records_cursor = db.files.find(
                {"upload_complete": "complete", "s3_key": {"$regex": f"^{prefix}/"}},
                {"s3_key": 1, "upload_complete": 1, "last_modified": 1}
            ).sort("last_modified", -1).skip(extra_skip).limit(remaining)
            extra_file_records = list(extra_file_records_cursor)
            for record in extra_file_records:
                key = record['s3_key']
                try:
                    s3_object = s3.head_object(Bucket=bucket_name, Key=key)
                    files.append({
                        'file_name': key.split("/")[-1],
                        'simple_url': get_bucket_url() + key,
                        'metadata': {
                            "tier": s3_object.get('StorageClass', 'standard').lower(),
                            "size": s3_object.get('ContentLength', 0)
                        },
                        'upload_complete': 'complete',
                        "last_modified": s3_object.get('LastModified').isoformat(),
                        'id': key,  # Ensure 'id' is unique
                        "s3_key": key
                    })
                    if len(files) >= per_page:
                        break
                except Exception as e:
                    logger.exception(f"Error retrieving S3 metadata for {key}: {str(e)}")
                    continue

        # Now, 'files' should have up to 'per_page' items
        response_payload = {
            "files": files,
            "total": total_files,
            "total_pages": total_pages,
            "page": page,
            "per_page": per_page
        }

        return jsonify(response_payload), 200

    except Exception as e:
        logger.exception(f"Error listing files: {str(e)}")
        return jsonify({"error": str(e)}), 500
