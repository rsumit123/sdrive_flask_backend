from flask import jsonify
import boto3
import os
from dotenv import load_dotenv
import logging
from botocore.exceptions import ClientError
from utils import get_bucket_url

# Load environment variables
load_dotenv()

# Set up logging
logger = logging.getLogger('flask_app')

def get_file_details(current_user, file_identifier):
    """
    Get details of a specific file from S3, even if it's not in MongoDB.
    
    Args:
        current_user: The authenticated user object
        file_identifier: Can be either an s3_key or a file_id
        
    Returns:
        A tuple containing (response_json, status_code)
    """
    try:
        logger.debug(f"Getting file details for {file_identifier} for user {current_user['email']}")
        
        # Initialize S3 client
        s3 = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_APP_S3_REGION_NAME')
        )
        
        bucket_name = os.getenv('AWS_APP_STORAGE_BUCKET_NAME')
        
        # Generate username prefix from email
        username_prefix = current_user['email'].split('.com')[0].replace("@", "-")
        
        # First, try to find the file in MongoDB
        from app import db  # Import here to avoid circular imports
        
        # Check if the identifier is a file_id or an s3_key
        if '/' in file_identifier:
            # Looks like an s3_key
            s3_key = file_identifier
            file_record = db.files.find_one({"s3_key": s3_key, "user": str(current_user['_id'])})
        else:
            # Try as a file_id
            file_record = db.files.find_one({"id": file_identifier, "user": str(current_user['_id'])})
            if file_record:
                s3_key = file_record['s3_key']
            else:
                # Try as a MongoDB _id
                try:
                    from bson.objectid import ObjectId
                    file_record = db.files.find_one({"_id": ObjectId(file_identifier), "user": str(current_user['_id'])})
                    if file_record:
                        s3_key = file_record['s3_key']
                    else:
                        # Last attempt: try to construct an s3_key from the identifier
                        s3_key = f"{username_prefix}/{file_identifier}"
                except:
                    # If not a valid ObjectId, try to construct an s3_key
                    s3_key = f"{username_prefix}/{file_identifier}"
        
        # If we have a file record from MongoDB, check if it has cached metadata
        if file_record and 'cached_metadata' in file_record and 'metadata_cached_at' in file_record:
            # Check if cache is recent (less than 1 hour old)
            import datetime
            cache_time = file_record['metadata_cached_at']
            if datetime.datetime.utcnow() - cache_time < datetime.timedelta(hours=1):
                logger.debug(f"Using cached metadata for {s3_key}")
                return jsonify(file_record['cached_metadata']), 200
        
        # If we don't have a record or the cache is old, try to get the file from S3
        try:
            # Check if the file exists in S3
            s3_object = s3.head_object(Bucket=bucket_name, Key=s3_key)
            
            # File exists in S3, create a response with the metadata
            file_details = {
                'file_name': s3_key.split("/")[-1],
                'simple_url': get_bucket_url() + s3_key,
                'metadata': {
                    "tier": s3_object.get('StorageClass', 'standard').lower(),
                    "size": s3_object.get('ContentLength', 0),
                    "content_type": s3_object.get('ContentType', 'application/octet-stream'),
                    "last_modified": s3_object.get('LastModified').isoformat(),
                },
                'upload_complete': 'complete',
                'id': s3_key.replace("/", "-"),
                's3_key': s3_key,
                'exists_in_db': file_record is not None
            }
            
            # If we have a file record but no cache or old cache, update the cache
            if file_record:
                db.files.update_one(
                    {"_id": file_record['_id']},
                    {"$set": {
                        "cached_metadata": file_details,
                        "metadata_cached_at": datetime.datetime.utcnow()
                    }}
                )
            
            return jsonify(file_details), 200
            
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                # The file doesn't exist in S3
                return jsonify({'error': 'File not found in S3'}), 404
            else:
                # Some other error occurred
                logger.exception(f"Error retrieving file from S3: {str(e)}")
                return jsonify({'error': str(e)}), 500
                
    except Exception as e:
        logger.exception(f"Error getting file details: {str(e)}")
        return jsonify({'error': str(e)}), 500 