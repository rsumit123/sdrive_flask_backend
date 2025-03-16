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
import concurrent.futures
from bson.objectid import ObjectId

# Load environment variables
load_dotenv()

# Set up logging
logger = logging.getLogger('flask_app')
logger.setLevel(logging.DEBUG)  # Set the desired logging level
# Create and add the MongoDB handler
# Configure Flask app
MONGO_URI = os.getenv('MONGO_URI')
SECRET_KEY = os.getenv('SECRET_KEY')

# Use MongoClient directly from pymongo
client = MongoClient(MONGO_URI)

# Access the database
db = client["db"]

# Create indexes for better performance
try:
    # Index for s3_key prefix queries and upload_complete status
    db.files.create_index([("s3_key", 1), ("upload_complete", 1)])
    
    # Index for sorting by last_modified
    db.files.create_index([("last_modified", -1)])
    
    # Compound index for the most common query pattern
    db.files.create_index([
        ("upload_complete", 1),
        ("s3_key", 1),
        ("last_modified", -1)
    ])
except Exception as e:
    logger.warning(f"Error creating indexes: {str(e)}")


mongo_handler = MongoDBHandler(db.logs)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
mongo_handler.setFormatter(formatter)
logger.addHandler(mongo_handler)

MAX_FILE_SIZE = 1024 * 1024 * 800  # 800MB

def update_file_metadata_cache(file_id, s3_metadata):
    """Update the cached S3 metadata in MongoDB to reduce future S3 API calls"""
    try:
        db.files.update_one(
            {"_id": file_id},
            {"$set": {
                "cached_metadata": s3_metadata,
                "metadata_cached_at": datetime.datetime.utcnow()
            }}
        )
    except Exception as e:
        logger.warning(f"Failed to update metadata cache: {str(e)}")

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

        # Check if cursor-based pagination is requested
        cursor = request.args.get('cursor', None)
        use_cursor_pagination = cursor is not None
        
        # Check if we should use cached metadata (default to true)
        use_cache = request.args.get('use_cache', 'true').lower() == 'true'
        
        # Cache expiration time (default 1 hour)
        cache_ttl = datetime.timedelta(hours=1)

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
        # Use cursor-based pagination if a cursor is provided
        if use_cursor_pagination and cursor:
            try:
                # Decode the cursor (assuming it's a timestamp or ObjectId)
                if cursor.startswith('ts:'):
                    # Timestamp-based cursor
                    timestamp = cursor[3:]
                    query = {
                        "upload_complete": "complete", 
                        "s3_key": {"$regex": f"^{prefix}/"},
                        "last_modified": {"$lt": timestamp}
                    }
                else:
                    # ObjectId-based cursor
                    query = {
                        "upload_complete": "complete", 
                        "s3_key": {"$regex": f"^{prefix}/"},
                        "_id": {"$lt": ObjectId(cursor)}
                    }
                
                file_records_cursor = db.files.find(
                    query,
                    {"s3_key": 1, "upload_complete": 1, "last_modified": 1, "_id": 1}
                ).sort("last_modified", -1).limit(per_page)
            except Exception as e:
                logger.exception(f"Error with cursor pagination: {str(e)}")
                return jsonify({"error": "Invalid cursor format"}), 400
        else:
            # Traditional offset-based pagination
            file_records_cursor = db.files.find(
                {"upload_complete": "complete", "s3_key": {"$regex": f"^{prefix}/"}},
                {"s3_key": 1, "upload_complete": 1, "last_modified": 1, "_id": 1}
            ).sort("last_modified", -1).skip((page - 1) * per_page).limit(per_page)
        
        file_records = list(file_records_cursor)
        valid_keys = [record['s3_key'] for record in file_records]

        if not valid_keys:
            return jsonify({
                "files": [],
                "total": total_files,
                "total_pages": total_pages,
                "page": page,
                "per_page": per_page,
                "next_cursor": None
            }), 200

        # Step 3: Retrieve metadata from S3 for the valid_keys in parallel
        files = []
        
        # Function to get S3 metadata for a key and record
        def get_s3_metadata(record):
            key = record['s3_key']
            record_id = record.get('_id')
            
            # Check if we have cached metadata that's not expired
            if use_cache and 'cached_metadata' in record and 'metadata_cached_at' in record:
                cache_time = record['metadata_cached_at']
                if datetime.datetime.utcnow() - cache_time < cache_ttl:
                    # Use cached metadata
                    logger.debug(f"Using cached metadata for {key}")
                    return record['cached_metadata']
            
            # If no cache or expired, fetch from S3
            try:
                s3_object = s3.head_object(Bucket=bucket_name, Key=key)
                metadata = {
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
                }
                
                # Update cache in the background if we have a record ID
                if record_id:
                    update_file_metadata_cache(record_id, metadata)
                    
                return metadata
            except Exception as e:
                logger.exception(f"Error retrieving S3 metadata for {key}: {str(e)}")
                return None

        # Use ThreadPoolExecutor to make S3 API calls in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            s3_results = list(executor.map(get_s3_metadata, file_records))
            
        # Filter out None results (failed S3 calls)
        files = [result for result in s3_results if result is not None]

        # If we have fewer files than requested and there are more files available,
        # fetch additional records
        if len(files) < per_page and (page * per_page) < total_files and not use_cursor_pagination:
            remaining = per_page - len(files)
            extra_skip = (page - 1) * per_page + len(files)
            extra_file_records_cursor = db.files.find(
                {"upload_complete": "complete", "s3_key": {"$regex": f"^{prefix}/"}},
                {"s3_key": 1, "upload_complete": 1, "last_modified": 1, "_id": 1}
            ).sort("last_modified", -1).skip(extra_skip).limit(remaining)
            extra_file_records = list(extra_file_records_cursor)
            
            if extra_file_records:
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    extra_s3_results = list(executor.map(get_s3_metadata, extra_file_records))
                    
                # Add non-None results to files
                files.extend([result for result in extra_s3_results if result is not None])

        # Generate next cursor for cursor-based pagination
        next_cursor = None
        if files and len(files) == per_page:  # There might be more results
            # Use the last_modified of the last item as the next cursor
            last_item = files[-1]
            if 'last_modified' in last_item:
                next_cursor = f"ts:{last_item['last_modified']}"

        # Now, 'files' should have up to 'per_page' items
        response_payload = {
            "files": files,
            "total": total_files,
            "total_pages": total_pages,
            "page": page,
            "per_page": per_page,
            "next_cursor": next_cursor
        }

        return jsonify(response_payload), 200

    except Exception as e:
        logger.exception(f"Error listing files: {str(e)}")
        return jsonify({"error": str(e)}), 500
