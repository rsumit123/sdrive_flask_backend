from flask import Flask, request, jsonify
import boto3
import os
from dotenv import load_dotenv
import logging
import datetime
from botocore.exceptions import ClientError
from utils import get_bucket_url
import concurrent.futures # Keep for parallel S3 calls
from bson.objectid import ObjectId # If needed for DB queries

# Load environment variables
load_dotenv()

# Set up logging
logger = logging.getLogger('flask_app')

def list_files_optimized(current_user, db):
    """
    Simplified version of list_files using page-based pagination.
    Queries the database first and then fetches S3 metadata.
    NOTE: This approach can be less performant than S3 cursor pagination
          for very large datasets due to multiple S3 API calls.
    
    Args:
        current_user: The authenticated user object
        db: MongoDB database connection
        
    Returns:
        A tuple containing (response_json, status_code)
    """
    try:
        start_time = datetime.datetime.now()
        logger.debug(f"Starting DB-paginated file listing for {current_user['email']}")

        # Setup S3 client
        s3 = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_APP_S3_REGION_NAME')
        )

        # Generate username prefix from email
        prefix = current_user['email'].split('.com')[0].replace("@", "-") + "/"
        bucket_name = os.getenv('AWS_APP_STORAGE_BUCKET_NAME')

        # Get pagination parameters (page-based)
        try:
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 50))
            if page < 1 or per_page < 1 or per_page > 100: # Limit per_page for head_object calls
                raise ValueError("page must be >= 1, per_page must be between 1 and 100")
        except ValueError as e:
            return jsonify({"error": f"Invalid pagination parameters: {str(e)}"}), 400

        logger.debug(f"Requesting page {page} with per_page={per_page}")

        # --- Query Database for Pagination and File List ---
        query = {
            "user": str(current_user['_id']),
            "upload_complete": "complete",
            "s3_key": {"$regex": f"^{prefix}"}
        }
        
        try:
            # Get total count first
            total_files = db.files.count_documents(query)
            total_pages = (total_files + per_page - 1) // per_page if total_files > 0 else 0
            logger.debug(f"Total files in DB: {total_files}, Total pages: {total_pages}")

            # Calculate skip value
            skip = (page - 1) * per_page

            # Fetch file records for the current page, sorted
            file_records_cursor = db.files.find(query, {
                # Project fields needed for response + S3 lookup
                '_id': 1, # Needed for potential updates if we add caching back
                's3_key': 1,
                'file_name': 1,
                'metadata': 1,
                'upload_complete': 1,
                'id': 1, # The username-filename id
                'last_modified': 1, # For sorting
                'created_at': 1 
            }).sort([("last_modified", -1), ("created_at", -1)]).skip(skip).limit(per_page)
            
            file_records = list(file_records_cursor)

        except Exception as e:
            logger.exception(f"Error querying database: {str(e)}")
            return jsonify({"error": "Database query failed."}), 500

        if not file_records:
             return jsonify({
                "files": [],
                "total": total_files,
                "total_pages": total_pages,
                "page": page,
                "per_page": per_page
            }), 200

        # --- Fetch S3 Metadata for the retrieved records in parallel ---
        files_output = []
        
        def get_s3_metadata(record):
            s3_key = record.get('s3_key')
            if not s3_key:
                return None # Skip records without s3_key
                
            try:
                s3_object = s3.head_object(Bucket=bucket_name, Key=s3_key)
                
                # Construct the file object using DB record and S3 metadata
                file_obj = {
                    'file_name': record.get('file_name', s3_key.split("/")[-1]),
                    'simple_url': get_bucket_url() + s3_key,
                    'metadata': {
                        "tier": s3_object.get('StorageClass', 'standard').lower(),
                        "size": s3_object.get('ContentLength', 0),
                        "content_type": s3_object.get('ContentType', record.get('metadata', {}).get('content_type', 'unknown'))
                    },
                    'upload_complete': record.get('upload_complete', 'unknown'),
                    # Use S3 last modified if available, otherwise fallback to DB field or created_at
                    "last_modified": s3_object.get('LastModified').isoformat() if s3_object.get('LastModified') else record.get('last_modified', record.get('created_at', datetime.datetime.min)).isoformat(),
                    'id': record.get('id', s3_key.replace("/", "-")),
                    "s3_key": s3_key,
                    "exists_in_db": True # We queried from DB
                }
                return file_obj
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    logger.warning(f"File record exists in DB but not found in S3: {s3_key}")
                    # Optionally, update DB record status here?
                else:
                    logger.exception(f"Error retrieving S3 metadata for {s3_key}: {str(e)}")
                return None # Skip file if S3 error occurs
            except Exception as e:
                 logger.exception(f"Unexpected error processing S3 metadata for {s3_key}: {str(e)}")
                 return None

        # Use ThreadPoolExecutor for parallel head_object calls
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            s3_results = list(executor.map(get_s3_metadata, file_records))
            
        # Filter out None results (records skipped due to errors or missing key)
        files_output = [result for result in s3_results if result is not None]
        
        # Note: The sorting is primarily handled by the database query now.
        # We could re-sort here if needed, but it should be mostly correct.
        
        # Build the final response payload
        response_payload = {
            "files": files_output,
            "total": total_files,
            "total_pages": total_pages,
            "page": page,
            "per_page": per_page,
            # No next_cursor
        }
        
        end_time = datetime.datetime.now()
        logger.debug(f"DB-paginated listing completed in {(end_time - start_time).total_seconds()} seconds")
        
        return jsonify(response_payload), 200
            
    except Exception as e:
        logger.exception(f"Unhandled error in list_files_optimized: {str(e)}")
        return jsonify({"error": "An unexpected error occurred."}), 500 