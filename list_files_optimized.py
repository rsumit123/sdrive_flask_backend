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
                    # Check if there are any files in the database that might not be in S3 yet
                    db_count = db.files.count_documents({
                        "user": str(current_user['_id']),
                        "upload_complete": "complete",
                        "s3_key": {"$regex": f"^{prefix}"}
                    })
                    
                    if db_count == 0:
                        # No files in database either
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

        # Get the total count from S3
        try:
            total_count_response = s3.list_objects_v2(
                Bucket=bucket_name,
                Prefix=prefix
            )
            s3_total_files = total_count_response.get('KeyCount', 0)
            logger.debug(f"Total files in S3 for user: {s3_total_files}")
        except Exception as e:
            logger.exception(f"Error getting total file count from S3: {str(e)}")
            s3_total_files = 0  # Default if we can't get the count
            
        # Also get the total count from the database to account for recently uploaded files
        db_total_files = db.files.count_documents({
            "user": str(current_user['_id']),
            "upload_complete": "complete",
            "s3_key": {"$regex": f"^{prefix}"}
        })
        logger.debug(f"Total files in DB for user: {db_total_files}")
        
        # Use the higher count to ensure we don't miss any files
        total_files = max(s3_total_files, db_total_files)

        # Calculate total pages
        total_pages = (total_files + per_page - 1) // per_page if total_files > 0 else 0

        # Get the files for the current page from S3
        s3_files = []
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
                    
                    s3_files.append(file_obj)
            
            # Determine the next cursor for cursor-based pagination
            next_cursor = None
            if s3_files and response.get('IsTruncated', False):
                next_cursor = response.get('NextContinuationToken')
                
        except Exception as e:
            logger.exception(f"Error listing files from S3: {str(e)}")
            return jsonify({"error": str(e)}), 500
            
        # Get recently uploaded files from the database that might not be in S3 yet
        # Only do this if we're on the first page or if we're not using cursor pagination
        recently_uploaded_files = []
        if page == 1 or not use_cursor_pagination:
            try:
                # Calculate the time threshold for recent uploads (e.g., last 5 minutes)
                recent_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
                
                # Find recently uploaded files in the database
                recent_files_cursor = db.files.find({
                    "user": str(current_user['_id']),
                    "upload_complete": "complete",
                    "s3_key": {"$regex": f"^{prefix}"},
                    # Either created recently or has no last_modified field
                    "$or": [
                        {"created_at": {"$gte": recent_time}},
                        {"last_modified": {"$exists": False}}
                    ]
                }).sort("created_at", -1).limit(per_page)
                
                for file_record in recent_files_cursor:
                    s3_key = file_record.get('s3_key')
                    
                    # Skip if this file is already in our S3 files list
                    if any(f['s3_key'] == s3_key for f in s3_files):
                        continue
                    
                    # Try to get metadata from S3
                    try:
                        s3_object = s3.head_object(Bucket=bucket_name, Key=s3_key)
                        
                        file_obj = {
                            'file_name': s3_key.split("/")[-1],
                            'simple_url': get_bucket_url() + s3_key,
                            'metadata': {
                                "tier": s3_object.get('StorageClass', 'standard').lower(),
                                "size": s3_object.get('ContentLength', 0),
                                "content_type": s3_object.get('ContentType', 'application/octet-stream')
                            },
                            'upload_complete': 'complete',
                            "last_modified": s3_object.get('LastModified').isoformat(),
                            'id': s3_key.replace("/", "-"),
                            "s3_key": s3_key,
                            "exists_in_db": True
                        }
                    except Exception as e:
                        # If we can't get S3 metadata, use what we have in the database
                        logger.warning(f"Could not get S3 metadata for {s3_key}: {str(e)}")
                        
                        file_obj = {
                            'file_name': s3_key.split("/")[-1],
                            'simple_url': get_bucket_url() + s3_key,
                            'metadata': file_record.get('metadata', {
                                "tier": "standard",
                                "size": 0
                            }),
                            'upload_complete': 'complete',
                            "last_modified": file_record.get('created_at', datetime.datetime.utcnow()).isoformat(),
                            'id': s3_key.replace("/", "-"),
                            "s3_key": s3_key,
                            "exists_in_db": True,
                            "recently_uploaded": True
                        }
                    
                    recently_uploaded_files.append(file_obj)
                    
            except Exception as e:
                logger.exception(f"Error getting recently uploaded files from database: {str(e)}")
                # Continue with what we have from S3
        
        # Combine and sort the files
        all_files = s3_files + recently_uploaded_files
        all_files.sort(key=lambda x: x.get('last_modified', ''), reverse=True)
        
        # Limit to per_page
        files = all_files[:per_page]
            
        # Build the response
        response_payload = {
            "files": files,
            "total": total_files,
            "total_pages": total_pages,
            "page": page,
            "per_page": per_page,
            "next_cursor": next_cursor
        }
        
        # Cache the response only if we're not including recently uploaded files
        # or if we're explicitly told to use the cache
        if use_cache and not recently_uploaded_files:
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
        logger.exception(f"Error in list_files_optimized: {str(e)}")
        return jsonify({"error": str(e)}), 500 