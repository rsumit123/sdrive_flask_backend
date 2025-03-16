from flask import Flask, request, jsonify
import boto3
import os
from dotenv import load_dotenv
import logging
import datetime
from botocore.exceptions import ClientError
from utils import get_bucket_url

# Load environment variables
load_dotenv()

# Set up logging
logger = logging.getLogger('flask_app')

def list_files_optimized(current_user, db):
    """
    Optimized version of list_files that uses S3's list_objects_v2 API instead of individual head_object calls.
    This significantly reduces the number of API calls to S3 and improves performance.
    
    Args:
        current_user: The authenticated user object
        db: MongoDB database connection
        
    Returns:
        A tuple containing (response_json, status_code)
    """
    try:
        start_time = datetime.datetime.now()
        logger.debug(f"Starting optimized file listing for {current_user['email']}")

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

        # Check if we should use cached metadata (default to true)
        use_cache = request.args.get('use_cache', 'true').lower() == 'true'
        
        # Check if cursor-based pagination is requested
        cursor = request.args.get('cursor', None)
        use_cursor_pagination = cursor is not None

        # Fetch pagination parameters
        try:
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 50))
            if page < 1 or per_page < 1 or per_page > 1000:  # Set a reasonable upper limit
                raise ValueError
        except ValueError:
            return jsonify({"error": "Invalid pagination parameters. 'page' and 'per_page' must be positive integers."}), 400

        logger.debug(f"Pagination parameters - Page: {page}, Per Page: {per_page}")

        # Try to get from cache first
        cache_key = f"files_list_{current_user['_id']}_{page}_{per_page}"
        if use_cache:
            cache_entry = db.cache.find_one({"key": cache_key})
            if cache_entry and (datetime.datetime.utcnow() - cache_entry['timestamp'] < datetime.timedelta(minutes=5)):
                logger.debug(f"Using cached file list (age: {datetime.datetime.utcnow() - cache_entry['timestamp']})")
                return jsonify(cache_entry['data']), 200

        # Determine the starting point for pagination
        start_after = None
        if use_cursor_pagination and cursor:
            start_after = cursor
        elif page > 1:
            # For offset-based pagination, we need to calculate the start_after key
            # This is less efficient than cursor-based pagination but maintains compatibility
            try:
                # Get all keys up to the starting point of the requested page
                all_keys_response = s3.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=prefix,
                    MaxKeys=(page - 1) * per_page
                )
                
                if 'Contents' in all_keys_response and all_keys_response['Contents']:
                    # The last key will be our start_after for the next page
                    start_after = all_keys_response['Contents'][-1]['Key']
                else:
                    # Not enough objects to reach the requested page
                    return jsonify({
                        "files": [],
                        "total": 0,
                        "total_pages": 0,
                        "page": page,
                        "per_page": per_page,
                        "next_cursor": None
                    }), 200
            except Exception as e:
                logger.exception(f"Error calculating pagination offset: {str(e)}")
                return jsonify({"error": str(e)}), 500

        # Get the total count (this is a separate API call but necessary for pagination info)
        try:
            total_count_response = s3.list_objects_v2(
                Bucket=bucket_name,
                Prefix=prefix
            )
            total_files = total_count_response.get('KeyCount', 0)
            logger.debug(f"Total files in S3 for user: {total_files}")
        except Exception as e:
            logger.exception(f"Error getting total file count: {str(e)}")
            total_files = 0  # Default if we can't get the count

        # Calculate total pages
        total_pages = (total_files + per_page - 1) // per_page if total_files > 0 else 0

        # Get the files for the current page
        try:
            # Use start_after for pagination if we have it
            if start_after:
                response = s3.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=prefix,
                    MaxKeys=per_page,
                    StartAfter=start_after
                )
            else:
                response = s3.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=prefix,
                    MaxKeys=per_page
                )
            
            # Process the response
            files = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    # Check if we have this file in MongoDB for additional metadata
                    file_record = db.files.find_one({"s3_key": obj['Key'], "user": str(current_user['_id'])})
                    
                    # Build the file object
                    file_obj = {
                        'file_name': obj['Key'].split("/")[-1],
                        'simple_url': get_bucket_url() + obj['Key'],
                        'metadata': {
                            "tier": obj.get('StorageClass', 'standard').lower(),
                            "size": obj.get('Size', 0),
                            # Note: Content-Type is not available in list_objects_v2 response
                        },
                        'upload_complete': 'complete',
                        "last_modified": obj.get('LastModified').isoformat(),
                        'id': obj['Key'].replace("/", "-"),
                        "s3_key": obj['Key'],
                        "exists_in_db": file_record is not None
                    }
                    
                    # Add additional metadata from MongoDB if available
                    if file_record and 'metadata' in file_record:
                        # Merge metadata, prioritizing S3 for common fields
                        for key, value in file_record['metadata'].items():
                            if key not in file_obj['metadata']:
                                file_obj['metadata'][key] = value
                    
                    files.append(file_obj)
            
            # Determine the next cursor for cursor-based pagination
            next_cursor = None
            if files and response.get('IsTruncated', False):
                next_cursor = response.get('NextContinuationToken')
            
            # Build the response
            response_payload = {
                "files": files,
                "total": total_files,
                "total_pages": total_pages,
                "page": page,
                "per_page": per_page,
                "next_cursor": next_cursor
            }
            
            # Cache the response
            if use_cache:
                db.cache.update_one(
                    {"key": cache_key},
                    {"$set": {
                        "key": cache_key,
                        "data": response_payload,
                        "timestamp": datetime.datetime.utcnow()
                    }},
                    upsert=True
                )
            
            end_time = datetime.datetime.now()
            logger.debug(f"File listing completed in {(end_time - start_time).total_seconds()} seconds")
            
            return jsonify(response_payload), 200
            
        except Exception as e:
            logger.exception(f"Error listing files: {str(e)}")
            return jsonify({"error": str(e)}), 500
            
    except Exception as e:
        logger.exception(f"Error in list_files_optimized: {str(e)}")
        return jsonify({"error": str(e)}), 500 