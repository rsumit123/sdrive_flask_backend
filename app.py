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
from list_files import list_files_v2
import asyncio
import concurrent.futures
from functools import partial
from file_details import get_file_details
from list_files_optimized import list_files_optimized

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Enable CORS
CORS(app, supports_credentials=True)

# Configure Flask app
app.config["MONGO_URI"] = os.getenv('MONGO_URI')
app.config["SECRET_KEY"] = os.getenv('SECRET_KEY')

# Set up logging
logger = logging.getLogger('flask_app')
logger.setLevel(logging.DEBUG)  # Set the desired logging level
# Use MongoClient directly from pymongo
client = MongoClient(app.config["MONGO_URI"])

# Access the database
db = client["db"]

# Create indexes for better performance
try:
    # Create index for the cache collection
    db.cache.create_index("key", unique=True)
    
    # Create TTL index to automatically expire cache entries after 1 hour
    db.cache.create_index("timestamp", expireAfterSeconds=3600)
    
    logger.debug("Created indexes for cache collection")
except Exception as e:
    logger.warning(f"Error creating cache indexes: {str(e)}")


# Create and add the MongoDB handler
mongo_handler = MongoDBHandler(db.logs)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
mongo_handler.setFormatter(formatter)
logger.addHandler(mongo_handler)

MAX_FILE_SIZE = 1024 * 1024 * 800  # 800MB

# Handle the OPTIONS request manually to avoid 404 errors
@app.before_request
def handle_options_request():
    if request.method == 'OPTIONS':
        return '', 200

# Registration API endpoint
@app.route('/api/auth/register/', methods=['POST', 'OPTIONS'])
def register():
    if request.method == 'OPTIONS':
        # Allow the preflight OPTIONS request
        return '', 200

    # Get email and password from the request body
    email = request.json.get('email')
    password = request.json.get('password')

    if not email or not password:
        return jsonify({"error": "Missing email or password"}), 400

    # Check if user with the same email already exists
    if db.users.find_one({"email": email}):
        return jsonify({"error": "Email already registered"}), 409

    # Hash the password
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    # Insert new user into the database
    db.users.insert_one({
        "email": email,
        "password": hashed_password
    })

    # Generate JWT token
    token = jwt.encode({
        'email': email,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, app.config['SECRET_KEY'], algorithm='HS256')

    # Return success message along with the token
    return jsonify({"message": "User created successfully", "token": token}), 201


# Health check route
@app.route('/api/health/', methods=['GET'])
def health_check():
    return jsonify({"message": "Server is running"}), 200

@app.route('/api/auth/login/', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        # Handle preflight OPTIONS request
        return '', 200
    
    # Get email and password from the request body
    email = request.json.get('email')
    password = request.json.get('password')

    # logger.debug(f"Received Login attempt for {email}")

    if not email or not password:
        return jsonify({"error": "Missing email or password"}), 400

    # logger.debug(f"=== Trying to find {email}====")

    # Find user by email
    user = db.users.find_one({"email": email})

    # logger.debug(f"=== Checking password===")

    # Check if user exists and if the password matches
    if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
        # Generate a token
        token = jwt.encode({
            'email': email,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, app.config['SECRET_KEY'], algorithm='HS256')

        # Return login success message along with the token
        return jsonify({"message": "Login successful", "token": token}), 200
    else:
        return jsonify({"error": "Invalid credentials"}), 401


@app.route('/api/v2/files/', methods=['GET'])
@token_required
def list_files_pagination(current_user):
    return list_files_v2(current_user)

@app.route('/api/v3/files/', methods=['GET'])
@token_required
def list_files_pagination_optimized(current_user):
    """
    Optimized endpoint for listing files.
    
    This endpoint uses S3's list_objects_v2 API instead of individual head_object calls,
    which significantly reduces the number of API calls and improves performance.
    
    Query Parameters:
    - page: Page number for offset-based pagination (default: 1)
    - per_page: Number of items per page (default: 50, max: 1000)
    - cursor: Cursor for cursor-based pagination (overrides page parameter)
    - use_cache: Whether to use cached results (default: true)
    
    Returns a paginated list of files with metadata.
    """
    return list_files_optimized(current_user, db)

@app.route('/api/files/<file_identifier>/download_file/', methods=['GET'])
@token_required
def download_file(current_user, file_identifier):
    """
    Download a file directly from S3.
    
    This endpoint supports multiple ways to identify a file:
    - An s3_key (e.g., "username/filename.jpg")
    - A file_id (e.g., "username-filename.jpg")
    - A MongoDB ObjectId
    - A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically
    
    Returns the file content with appropriate headers for download.
    """
    logger.debug(f"Downloading file {file_identifier} for {current_user['email']}")
    
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
    
    # Determine the S3 key for the file
    s3_key = None
    file_record = None
    
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
                    # Check if this file exists in S3
                    try:
                        s3.head_object(Bucket=bucket_name, Key=s3_key)
                        # File exists in S3 but not in our database
                        logger.debug(f"File {s3_key} exists in S3 but not in database")
                    except Exception as e:
                        logger.debug(f"File {s3_key} not found in S3: {str(e)}")
                        return jsonify({'error': 'File not found'}), 404
            except Exception as e:
                # If not a valid ObjectId, try to construct an s3_key
                s3_key = f"{username_prefix}/{file_identifier}"
                # Check if this file exists in S3
                try:
                    s3.head_object(Bucket=bucket_name, Key=s3_key)
                    # File exists in S3 but not in our database
                    logger.debug(f"File {s3_key} exists in S3 but not in database")
                except Exception as e:
                    logger.debug(f"File {s3_key} not found in S3: {str(e)}")
                    return jsonify({'error': 'File not found'}), 404
    
    if not s3_key:
        return jsonify({'error': 'File not found'}), 404

    try:
        logger.debug(f"Requesting S3")
        head_response = s3.head_object(Bucket=bucket_name, Key=s3_key)
        storage_class = head_response.get('StorageClass', 'STANDARD')
        logger.debug(f"Storage class: {storage_class}")

        if storage_class in ['GLACIER', 'DEEP_ARCHIVE']:
            if 'Restore' not in head_response or 'ongoing-request="true"' in head_response.get('Restore', '') or 'ongoing-request="true"' in head_response.get('x-amz-restore', ''):
                try:
                    s3_response = s3.restore_object(
                        Bucket=bucket_name,
                        Key=s3_key,
                        RestoreRequest={'Days': 1, 'GlacierJobParameters': {'Tier': 'Standard'}}
                    )
                    logger.debug(f"s3_response while downloading: {s3_response}")
                    
                    # Update metadata in database if the file exists there
                    if file_record:
                        db.files.update_one(
                            {"_id": file_record['_id']}, 
                            {"$set": {"metadata.tier": "unarchiving"}}
                        )

                    return jsonify({'message': 'File is being restored. Try again later.'}), 202
    
                except Exception as e:
                    if 'RestoreAlreadyInProgress' in str(e):
                        return jsonify({'message': 'File is being restored. Try again later.'}), 203
                    logger.exception(f"Error restoring file: {str(e)}")
                    return jsonify({'error': str(e)}), 500
    
        logger.debug(f"Getting file from S3 to return")
        file_obj = s3.get_object(Bucket=bucket_name, Key=s3_key)
        file_data = file_obj['Body'].read()
        
        # Get the file name from the S3 key or file record
        file_name = s3_key.split("/")[-1]
        if file_record and 'file_name' in file_record:
            file_name = file_record['file_name']
        
        # Get content type from S3 or use a default
        content_type = file_obj.get('ContentType', 'application/octet-stream')
        
        # Create a response with the file data
        response = Response(
            file_data,
            mimetype=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={file_name}",
                "Content-Length": str(len(file_data))
            }
        )
        
        return response

    except Exception as e:
        logger.exception(f"Error downloading file: {str(e)}")
        return jsonify({'error': str(e)}), 500



@app.route('/api/files/<file_identifier>/download_presigned_url/', methods=['GET'])
@token_required
def download_presigned_url(current_user, file_identifier):
    """
    Generate a presigned URL for downloading a file directly from S3.
    
    This endpoint supports multiple ways to identify a file:
    - An s3_key (e.g., "username/filename.jpg")
    - A file_id (e.g., "username-filename.jpg")
    - A MongoDB ObjectId
    - A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically
    
    Returns a presigned URL that can be used to download the file directly from S3.
    """
    logger.debug(f"Generating presigned URL for file {file_identifier} for user {current_user['email']}")
    
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
    
    # Determine the S3 key for the file
    s3_key = None
    file_record = None
    
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
                    # Check if this file exists in S3
                    try:
                        s3.head_object(Bucket=bucket_name, Key=s3_key)
                        # File exists in S3 but not in our database
                        logger.debug(f"File {s3_key} exists in S3 but not in database")
                    except Exception as e:
                        logger.debug(f"File {s3_key} not found in S3: {str(e)}")
                        return jsonify({'error': 'File not found'}), 404
            except Exception as e:
                # If not a valid ObjectId, try to construct an s3_key
                s3_key = f"{username_prefix}/{file_identifier}"
                # Check if this file exists in S3
                try:
                    s3.head_object(Bucket=bucket_name, Key=s3_key)
                    # File exists in S3 but not in our database
                    logger.debug(f"File {s3_key} exists in S3 but not in database")
                except Exception as e:
                    logger.debug(f"File {s3_key} not found in S3: {str(e)}")
                    return jsonify({'error': 'File not found'}), 404
    
    if not s3_key:
        return jsonify({'error': 'File not found'}), 404
    
    try:
        # Check the storage class
        head_response = s3.head_object(Bucket=bucket_name, Key=s3_key)
        storage_class = head_response.get('StorageClass', 'STANDARD')
        logger.debug(f"Storage class: {storage_class}")

        if storage_class in ['GLACIER', 'DEEP_ARCHIVE']:
            # Check if the object is already being restored
            restore_status = head_response.get('Restore', '')
            if 'ongoing-request="true"' in restore_status or 'x-amz-restore' in head_response and 'ongoing-request="true"' in head_response['x-amz-restore']:
                return jsonify({'message': 'File is being restored. Try again later.'}), 202

            # Initiate restoration
            s3.restore_object(
                Bucket=bucket_name,
                Key=s3_key,
                RestoreRequest={'Days': 1, 'GlacierJobParameters': {'Tier': 'Standard'}}
            )
            logger.debug("Restore request initiated.")
            return jsonify({'message': 'File is being restored. Try again later.'}), 202

        # Generate a presigned URL
        presigned_url = s3.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket_name,
                'Key': s3_key
            },
            ExpiresIn=3600  # URL expires in 1 hour
        )

        logger.debug(f"Presigned URL generated: {presigned_url}")
        
        # Get the file name from the S3 key or file record
        file_name = s3_key.split("/")[-1]
        if file_record and 'file_name' in file_record:
            file_name = file_record['file_name']

        return jsonify({'presigned_url': presigned_url, 'file_name': file_name}), 200

    except Exception as e:
        logger.exception(f"Error generating presigned URL: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/<file_identifier>/refresh', methods=['GET'])
@token_required
def refresh_file_metadata(current_user, file_identifier):
    """
    Refresh metadata for a file from S3.
    
    This endpoint supports multiple ways to identify a file:
    - An s3_key (e.g., "username/filename.jpg")
    - A file_id (e.g., "username-filename.jpg")
    - A MongoDB ObjectId
    - A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically
    
    Returns updated metadata for the file.
    """
    logger.debug(f"Refreshing metadata for file {file_identifier} for {current_user['email']}")
    
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
    
    # Determine the S3 key for the file
    s3_key = None
    file_record = None
    
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
                    # Check if this file exists in S3
                    try:
                        s3.head_object(Bucket=bucket_name, Key=s3_key)
                        # File exists in S3 but not in our database
                        logger.debug(f"File {s3_key} exists in S3 but not in database")
                        
                        # Create a minimal file record for this file
                        file_record = {
                            'file_name': s3_key.split("/")[-1],
                            'user': str(current_user['_id']),
                            's3_key': s3_key,
                            'metadata': {},
                            'id': s3_key.replace("/", "-")
                        }
                        
                        # Insert the record into the database
                        db.files.insert_one(file_record)
                        logger.debug(f"Created new file record for {s3_key}")
                    except Exception as e:
                        logger.debug(f"File {s3_key} not found in S3: {str(e)}")
                        return jsonify({'error': 'File not found'}), 404
            except Exception as e:
                # If not a valid ObjectId, try to construct an s3_key
                s3_key = f"{username_prefix}/{file_identifier}"
                # Check if this file exists in S3
                try:
                    s3.head_object(Bucket=bucket_name, Key=s3_key)
                    # File exists in S3 but not in our database
                    logger.debug(f"File {s3_key} exists in S3 but not in database")
                    
                    # Create a minimal file record for this file
                    file_record = {
                        'file_name': s3_key.split("/")[-1],
                        'user': str(current_user['_id']),
                        's3_key': s3_key,
                        'metadata': {},
                        'id': s3_key.replace("/", "-")
                    }
                    
                    # Insert the record into the database
                    db.files.insert_one(file_record)
                    logger.debug(f"Created new file record for {s3_key}")
                except Exception as e:
                    logger.debug(f"File {s3_key} not found in S3: {str(e)}")
                    return jsonify({'error': 'File not found'}), 404
    
    if not s3_key or not file_record:
        return jsonify({'error': 'File not found'}), 404

    try:
        head_response = s3.head_object(Bucket=bucket_name, Key=s3_key)
        storage_class = head_response.get('StorageClass', 'STANDARD')
        content_type = head_response.get('ContentType', 'application/octet-stream')
        content_length = head_response.get('ContentLength', 0)
        
        # Initialize metadata if it doesn't exist
        if 'metadata' not in file_record:
            file_record['metadata'] = {}
        
        # Update the metadata
        file_record['metadata']['tier'] = 'standard' if storage_class == 'STANDARD' else 'glacier'
        file_record['metadata']['content_type'] = content_type
        file_record['metadata']['size'] = content_length
        
        # Check if the file is being restored from Glacier
        if storage_class in ['GLACIER', 'DEEP_ARCHIVE'] and 'Restore' in head_response:
            if 'ongoing-request="true"' not in head_response['Restore']:
                file_record['metadata']['tier'] = 'unarchiving'
        
        # Update the record in the database
        db.files.update_one(
            {"_id": file_record['_id']}, 
            {"$set": {"metadata": file_record['metadata']}}
        )

        return jsonify({'message': 'Metadata refreshed', 'metadata': file_record['metadata']}), 200

    except Exception as e:
        logger.exception(f"Error refreshing metadata: {str(e)}")
        return jsonify({'error': str(e)}), 500



def generate_simple_url(s3_key):
    s3_url = f"https://{os.getenv('AWS_APP_STORAGE_BUCKET_NAME')}.s3.amazonaws.com/{s3_key}"
    simple_url = requests.get(f"https://ks0bm06q4a.execute-api.us-west-2.amazonaws.com/dev?long_url={s3_url}").json()
    return "https://simple-url.skdev.one/"+simple_url['short_url']

@app.route('/api/files/upload/', methods=['POST'])
@token_required
def upload_file(current_user):
    """
    Generate presigned URLs for uploading files to S3.
    
    This endpoint supports both single file and multiple file uploads:
    
    1. Single file upload (backward compatibility):
       {
         "file_name": "example.jpg",
         "content_type": "image/jpeg",
         "file_size": 1024000,
         "tier": "standard"
       }
       
    2. Multiple file upload:
       {
         "files": [
           {
             "file_name": "example1.jpg",
             "content_type": "image/jpeg",
             "file_size": 1024000,
             "tier": "standard"
           },
           {
             "file_name": "example2.pdf",
             "content_type": "application/pdf",
             "file_size": 2048000,
             "tier": "glacier"
           }
         ]
       }
       
    The response will include presigned URLs for each file that can be used
    for direct upload to S3 from the client.
    
    After uploading files to S3, call /api/files/confirm_uploads/ with the s3_keys
    to mark the uploads as complete.
    """
    try:
        logger.debug("Generating presigned URLs for file uploads")

        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Check if we're receiving a single file or multiple files
        if isinstance(data, dict) and 'files' not in data:
            # Handle single file upload (backward compatibility)
            files_data = [data]
        elif isinstance(data, dict) and 'files' in data:
            # Handle multiple file upload
            files_data = data.get('files', [])
        else:
            return jsonify({'error': 'Invalid request format'}), 400

        if not files_data:
            return jsonify({'error': 'No files specified for upload'}), 400

        # Initialize S3 client
        s3 = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_APP_S3_REGION_NAME')
        )

        # Generate username from email
        email_parts = current_user['email'].split('@')
        username = f"{email_parts[0]}-{email_parts[1].split('.')[0]}"

        # Process each file in parallel
        results = []
        
        # Function to process a single file
        def process_file(file_data):
            try:
                tier = file_data.get('tier', 'standard')
                file_name = file_data.get('file_name')
                content_type = file_data.get('content_type')
                file_size = file_data.get('file_size', 0)

                if file_size > MAX_FILE_SIZE:
                    return {
                        'file_name': file_name,
                        'error': f'File size exceeds the limit of {MAX_FILE_SIZE/(1024*1024)}MB',
                        'status': 'error'
                    }

                if not file_name or not content_type:
                    return {
                        'file_name': file_name if file_name else 'unknown',
                        'error': 'file_name and content_type are required',
                        'status': 'error'
                    }

                # Ensure filename is secure
                filename = secure_filename(file_name)

                # Generate S3 key
                s3_key = f"{username}/{filename}"

                # Generate presigned URL
                presigned_url = s3.generate_presigned_url(
                    'put_object',
                    Params={
                        'Bucket': os.getenv('AWS_APP_STORAGE_BUCKET_NAME'),
                        'Key': s3_key,
                        'ContentType': content_type,
                        'StorageClass': 'GLACIER' if tier == 'glacier' else 'STANDARD',
                    },
                    ExpiresIn=3600  # URL valid for 1 hour
                )

                # Store file metadata with upload_pending flag
                store_file_metadata(current_user, filename, s3_key, content_type, tier, upload_complete=False)

                return {
                    'file_name': file_name,
                    'presigned_url': presigned_url,
                    's3_key': s3_key,
                    'id': s3_key.replace("/", "-"),
                    'status': 'success'
                }
            except Exception as e:
                logger.exception(f"Error processing file {file_data.get('file_name', 'unknown')}: {str(e)}")
                return {
                    'file_name': file_data.get('file_name', 'unknown'),
                    'error': str(e),
                    'status': 'error'
                }

        # Use ThreadPoolExecutor to process files in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(process_file, files_data))

        # Separate successful and failed uploads
        successful = [r for r in results if r.get('status') == 'success']
        failed = [r for r in results if r.get('status') == 'error']

        response = {
            'message': f'Successfully generated presigned URLs for {len(successful)} files. {len(failed)} files failed.',
            'successful': successful,
            'failed': failed
        }

        return jsonify(response), 200 if successful else 500 if not successful else 207  # 207 Multi-Status

    except Exception as e:
        logger.exception(f"Error generating presigned URLs: {str(e)}")
        return jsonify({'error': 'Failed to generate presigned URLs.'}), 500

def store_file_metadata(current_user, filename, s3_key, content_type, tier, upload_complete=True):
    # Implement your metadata storage logic here (e.g., MongoDB)
    file_metadata = {
        'file_name': filename,
        'user': str(current_user['_id']),
        's3_key': s3_key,
        'metadata': {
            'content_type': content_type,
            'tier': tier
        },
        'upload_complete': 'complete' if upload_complete else 'pending',
        "id": s3_key.replace("/", "-")
        # Add other necessary fields as required
    }

    # Insert into the database (MongoDB)
    db.files.insert_one(file_metadata)

@app.route('/api/files/confirm_uploads/', methods=['POST'])
@token_required
def confirm_uploads(current_user):
    """
    Confirm that multiple files have been successfully uploaded to S3.
    
    This endpoint should be called after uploading files to S3 using the presigned URLs
    generated by the /api/files/upload/ endpoint.
    
    Request format:
    {
      "s3_keys": [
        "username/file1.jpg",
        "username/file2.pdf"
      ]
    }
    
    The response will include the status of each confirmation.
    """
    data = request.get_json()
    s3_keys = data.get('s3_keys', [])

    if not s3_keys:
        return jsonify({'error': 's3_keys is required'}), 400

    # Update the file metadata to mark uploads as complete
    results = []
    for s3_key in s3_keys:
        try:
            result = db.files.update_one(
                {'s3_key': s3_key, 'user': str(current_user['_id'])},
                {'$set': {'upload_complete': 'complete'}}
            )
            
            if result.matched_count == 0:
                results.append({'s3_key': s3_key, 'status': 'error', 'message': 'File not found'})
            else:
                results.append({'s3_key': s3_key, 'status': 'success', 'message': 'Upload confirmed'})
        except Exception as e:
            logger.exception(f"Error confirming upload for {s3_key}: {str(e)}")
            results.append({'s3_key': s3_key, 'status': 'error', 'message': str(e)})

    return jsonify({
        'message': 'Upload confirmation processed',
        'results': results
    }), 200

@app.route('/api/files/confirm_upload/', methods=['POST'])
@token_required
def confirm_upload(current_user):
    data = request.get_json()
    s3_key = data.get('s3_key')

    if not s3_key:
        return jsonify({'error': 's3_key is required'}), 400

    # Update the file metadata to mark upload as complete
    result = db.files.update_one(
        {'s3_key': s3_key, 'user': str(current_user['_id'])},
        {'$set': {'upload_complete': 'complete'}}
    )

    if result.matched_count == 0:
        return jsonify({'error': 'File not found'}), 404

    return jsonify({'message': 'Upload confirmed successfully'}), 200

@app.route('/api/files/presign/', methods=['GET'])
@token_required
def generate_presigned_url(current_user):
    logger.debug(f"Generating pre-signed URL for {current_user['email']}")
    # Initialize S3 client
    s3_client = boto3.client('s3',
                             aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
                             aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
                             region_name=os.getenv('AWS_APP_S3_REGION_NAME'))

    # Get file name from query parameters
    file_name = request.args.get('file_name')
    if not file_name:
        return jsonify({"error": "File name parameter is missing."}), 400

    # Optionally get metadata from query params
    logger.debug(f"Getting metadata from query params: {request.args}")
    file_metadata = request.args.get('metadata', {"tier": "standard"})

    # Generate a username-based key from the current user's email
    username = current_user['email'].split('@')[0] + "-" + current_user['email'].split('@')[1].split('.')[0]

    # Generate the S3 key for the file
    s3_key = f"{username}/{file_name}"

    # Get the bucket name from environment variables
    bucket_name = os.getenv('AWS_APP_STORAGE_BUCKET_NAME')

    try:
        # Generate a pre-signed URL for PUT operation
        presigned_url = s3_client.generate_presigned_url('put_object',
                                                         Params={'Bucket': bucket_name, 'Key': s3_key},
                                                         ExpiresIn=3600)  # URL expires in 1 hour
    except Exception as e:
        logger.exception(f"Error generating pre-signed URL: {str(e)}")
        return jsonify({'error': str(e)}), 500

    # Create a temporary file record in MongoDB
    file_record = {
        'file_name': file_name,
        'user': current_user['_id'],
        's3_key': s3_key,
        'metadata': file_metadata,
        'simple_url': '',  # Placeholder for now
        'upload_complete': 'pending',  # Track the completion status
        'created_at': datetime.datetime.utcnow(),
        "id": s3_key.replace("/", "-")
    }

    # Insert the temporary record in the files collection
    temp_file_id = db.files.insert_one(file_record).inserted_id

    # Return the pre-signed URL and temporary file ID
    return jsonify({
        "presigned_url": presigned_url,
        "file_name": s3_key,
        "id": s3_key.replace("/", "-")
    }), 200

@app.route('/api/logs/', methods=['GET'])
# @token_required  # Ensure this decorator checks for valid authentication
def get_logs():
    try:
        # Fetch the latest 100 logs, sorted by timestamp descending
        logs_cursor = db.logs.find().sort("timestamp", -1).limit(100)
        logs = []
        for log in logs_cursor:
            logs.append({
                "timestamp": log.get("timestamp"),
                "level": log.get("level"),
                "message": log.get("message"),
                "module": log.get("module"),
                "function": log.get("funcName"),
                "line": log.get("lineno")
            })
        logger.debug("Logs retrieved successfully")
        return jsonify({"logs": logs}), 200
    except Exception as e:
        logger.error(f"Error fetching logs: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


# DELETE
@app.route('/api/files/', methods=['DELETE'])
@token_required
def delete_file(current_user):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON payload.'}), 400
        s3_key = data.get('s3_key')
        if not s3_key:
            return jsonify({'error': 's3_key is required.'}), 400
        
        logger.debug(f"Attempting to delete file with s3 key: {s3_key} for user: {current_user['email']}")


        # Fetch the file document from MongoDB
        file_doc = db.files.find_one({'s3_key': s3_key, 'user': str(current_user['_id'])})

        if not file_doc:
            logger.error(f"File not found or unauthorized for ID: {s3_key}")
            # return jsonify({'error': 'File not found or unauthorized.'}), 404

        logger.info(f"Deleting file with ID: {s3_key} for user: {current_user['email']} via S3")
        if file_doc:
            s3_key = file_doc.get('s3_key')
        else:
            s3_key = s3_key

        if not s3_key:
            return jsonify({'error': 'Invalid file metadata.'}), 400

        # Initialize S3 client
        s3 = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_APP_S3_REGION_NAME')
        )

        # Delete the file from S3
        try:
            s3.delete_object(Bucket=os.getenv('AWS_APP_STORAGE_BUCKET_NAME'), Key=s3_key)
            logger.debug(f"Deleted file from S3: {s3_key}")
        except Exception as e:
            logger.exception(f"Error deleting file from S3: {str(e)}")
            return jsonify({'error': 'Failed to delete file from storage.'}), 500

        # Delete the file metadata from MongoDB
        try:
            result = db.files.delete_one({'s3_key': s3_key, 'user': str(current_user['_id'])})
            if result.deleted_count == 0:
                logger.error(f"File metadata not found for ID: {s3_key}")
                return jsonify({'error': 'File metadata not found in db.'}), 200
            logger.debug(f"Deleted file metadata from MongoDB for ID: {s3_key}")
        except Exception as e:
            logger.exception(f"Error deleting file metadata from MongoDB: {str(e)}")
            return jsonify({'error': 'Failed to delete file metadata.'}), 200

        return jsonify({'message': 'File deleted successfully.'}), 200

    except Exception as e:
        logger.exception(f"Unexpected error during file deletion: {str(e)}")
        print("Unexpected error during file deletion: ", str(e))
        return jsonify({'error': 'An unexpected error occurred.'}), 500

@app.route('/api/files/rename/', methods=['POST'])
@token_required
def rename_file(current_user):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON payload.'}), 400

        s3_key = data.get('s3_key')
        new_filename = data.get('new_filename')

        if not s3_key or not new_filename:
            return jsonify({'error': 's3_key and new_filename are required.'}), 400

        logger.debug(f"User {current_user['email']} is attempting to rename file {s3_key} to {new_filename}")

        # Fetch the file document from MongoDB
        file_doc = db.files.find_one({'s3_key': s3_key, 'user': str(current_user['_id'])})

        if not file_doc:
            return jsonify({'error': 'File not found or unauthorized.'}), 404

        # Extract current s3 key details
        bucket_name = os.getenv('AWS_APP_STORAGE_BUCKET_NAME')
        current_key = file_doc.get('s3_key')
        if not current_key:
            return jsonify({'error': 'Invalid file metadata.'}), 400

        # Determine the new S3 key
        # Assuming the new filename is in the same directory as the current key
        # Adjust this logic if your keys include paths
        new_key = '/'.join(current_key.split('/')[:-1] + [new_filename])

        # Initialize S3 client
        s3 = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_APP_S3_REGION_NAME')
        )

        # Check if the new key already exists to prevent overwriting
        try:
            s3.head_object(Bucket=bucket_name, Key=new_key)
            return jsonify({'error': 'A file with the new filename already exists.'}), 409
        except s3.exceptions.ClientError as e:
            if e.response['Error']['Code'] != '404':
                logger.exception(f"Error checking existence of new key: {str(e)}")
                return jsonify({'error': 'Error checking file existence.'}), 500
            # If 404, the object does not exist, which is desired

        # Copy the object to the new key
        copy_source = {
            'Bucket': bucket_name,
            'Key': current_key
        }

        try:
            s3.copy_object(CopySource=copy_source, Bucket=bucket_name, Key=new_key)
            logger.debug(f"Copied file from {current_key} to {new_key} in S3.")
        except Exception as e:
            logger.exception(f"Error copying file in S3: {str(e)}")
            return jsonify({'error': 'Failed to copy file in storage.'}), 500

        # Delete the original object from S3
        try:
            s3.delete_object(Bucket=bucket_name, Key=current_key)
            logger.debug(f"Deleted original file from S3: {current_key}")
        except Exception as e:
            logger.exception(f"Error deleting original file from S3: {str(e)}")
            # Optionally, you might want to delete the copied file to maintain consistency
            try:
                s3.delete_object(Bucket=bucket_name, Key=new_key)
                logger.debug(f"Deleted copied file due to failure: {new_key}")
            except Exception as delete_e:
                logger.exception(f"Error deleting copied file after failure: {str(delete_e)}")
            return jsonify({'error': 'Failed to delete original file from storage.'}), 500

        # Update the MongoDB document with the new s3_key and filename
        try:
            update_result = db.files.update_one(
                {'_id': file_doc['_id']},
                {'$set': {'s3_key': new_key, 'filename': new_filename}}
            )
            if update_result.modified_count == 0:
                logger.error(f"Failed to update MongoDB document for file ID: {file_doc['_id']}")
                return jsonify({'error': 'Failed to update file metadata.'}), 500
            logger.debug(f"Updated MongoDB document with new filename and s3_key for file ID: {file_doc['_id']}")
        except Exception as e:
            logger.exception(f"Error updating file metadata in MongoDB: {str(e)}")
            # Optionally, attempt to revert S3 changes to maintain consistency
            try:
                s3.copy_object(CopySource=copy_source, Bucket=bucket_name, Key=current_key)
                s3.delete_object(Bucket=bucket_name, Key=new_key)
                logger.debug("Reverted S3 changes due to MongoDB update failure.")
            except Exception as revert_e:
                logger.exception(f"Error reverting S3 changes: {str(revert_e)}")
            return jsonify({'error': 'Failed to update file metadata.'}), 500

        return jsonify({'message': 'File renamed successfully.', 'new_s3_key': new_key, 'new_filename': new_filename}), 200

    except Exception as e:
        logger.exception(f"Unexpected error during file rename: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred.'}), 500

@app.route('/api/files/<file_identifier>/change_tier/', methods=['POST'])
@token_required
def change_storage_tier(current_user, file_identifier):
    """
    Change the storage tier of a file between standard and glacier.
    
    This endpoint supports multiple ways to identify a file:
    - An s3_key (e.g., "username/filename.jpg")
    - A file_id (e.g., "username-filename.jpg")
    - A MongoDB ObjectId
    - A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically
    
    Request body:
    {
      "target_tier": "standard" or "glacier"
    }
    
    Returns the updated file metadata.
    """
    logger.debug(f"Changing storage tier for file {file_identifier} for user {current_user['email']}")
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload.'}), 400
    
    target_tier = data.get('target_tier')
    if not target_tier or target_tier not in ['standard', 'glacier']:
        return jsonify({'error': 'target_tier is required and must be either "standard" or "glacier".'}), 400
    
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
    
    # Determine the S3 key for the file
    s3_key = None
    file_record = None
    
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
                    # Check if this file exists in S3
                    try:
                        s3.head_object(Bucket=bucket_name, Key=s3_key)
                        # File exists in S3 but not in our database
                        logger.debug(f"File {s3_key} exists in S3 but not in database")
                        
                        # Create a minimal file record for this file
                        file_record = {
                            'file_name': s3_key.split("/")[-1],
                            'user': str(current_user['_id']),
                            's3_key': s3_key,
                            'metadata': {},
                            'id': s3_key.replace("/", "-"),
                            'upload_complete': 'complete'
                        }
                        
                        # Insert the record into the database
                        result = db.files.insert_one(file_record)
                        file_record['_id'] = result.inserted_id
                        logger.debug(f"Created new file record for {s3_key}")
                    except Exception as e:
                        logger.debug(f"File {s3_key} not found in S3: {str(e)}")
                        return jsonify({'error': 'File not found'}), 404
            except Exception as e:
                # If not a valid ObjectId, try to construct an s3_key
                s3_key = f"{username_prefix}/{file_identifier}"
                # Check if this file exists in S3
                try:
                    s3.head_object(Bucket=bucket_name, Key=s3_key)
                    # File exists in S3 but not in our database
                    logger.debug(f"File {s3_key} exists in S3 but not in database")
                    
                    # Create a minimal file record for this file
                    file_record = {
                        'file_name': s3_key.split("/")[-1],
                        'user': str(current_user['_id']),
                        's3_key': s3_key,
                        'metadata': {},
                        'id': s3_key.replace("/", "-"),
                        'upload_complete': 'complete'
                    }
                    
                    # Insert the record into the database
                    result = db.files.insert_one(file_record)
                    file_record['_id'] = result.inserted_id
                    logger.debug(f"Created new file record for {s3_key}")
                except Exception as e:
                    logger.debug(f"File {s3_key} not found in S3: {str(e)}")
                    return jsonify({'error': 'File not found'}), 404
    
    if not s3_key or not file_record:
        return jsonify({'error': 'File not found'}), 404
    
    try:
        # Get the current object metadata
        head_response = s3.head_object(Bucket=bucket_name, Key=s3_key)
        current_storage_class = head_response.get('StorageClass', 'STANDARD')
        
        # Check if the file is already in the requested tier
        if (current_storage_class == 'STANDARD' and target_tier == 'standard') or \
           (current_storage_class in ['GLACIER', 'DEEP_ARCHIVE'] and target_tier == 'glacier'):
            return jsonify({
                'message': f'File is already in {target_tier} tier',
                'metadata': {
                    'tier': target_tier,
                    'content_type': head_response.get('ContentType', 'application/octet-stream'),
                    'size': head_response.get('ContentLength', 0),
                    'last_modified': head_response.get('LastModified', datetime.datetime.now()).isoformat()
                }
            }), 200
        
        # For Glacier to Standard, we need to restore the object first
        if current_storage_class in ['GLACIER', 'DEEP_ARCHIVE'] and target_tier == 'standard':
            # Check if the object is already being restored
            restore_status = head_response.get('Restore', '')
            if 'ongoing-request="true"' in restore_status:
                return jsonify({'message': 'File is already being restored. Try again later.'}), 202
            
            # If the object has been restored, we can copy it with the new storage class
            if 'ongoing-request="false"' in restore_status:
                # Copy the object to itself with the new storage class
                copy_source = {'Bucket': bucket_name, 'Key': s3_key}
                s3.copy_object(
                    CopySource=copy_source,
                    Bucket=bucket_name,
                    Key=s3_key,
                    StorageClass='STANDARD',
                    MetadataDirective='COPY'
                )
                
                # Update the metadata in the database
                db.files.update_one(
                    {"_id": file_record['_id']},
                    {"$set": {"metadata.tier": "standard"}}
                )
                
                return jsonify({
                    'message': 'File successfully changed to standard tier',
                    'metadata': {
                        'tier': 'standard',
                        'content_type': head_response.get('ContentType', 'application/octet-stream'),
                        'size': head_response.get('ContentLength', 0),
                        'last_modified': datetime.datetime.now().isoformat()
                    }
                }), 200
            
            # Initiate restoration
            s3.restore_object(
                Bucket=bucket_name,
                Key=s3_key,
                RestoreRequest={'Days': 1, 'GlacierJobParameters': {'Tier': 'Standard'}}
            )
            
            # Update the metadata in the database
            db.files.update_one(
                {"_id": file_record['_id']},
                {"$set": {"metadata.tier": "unarchiving"}}
            )
            
            return jsonify({'message': 'File restoration initiated. Try changing the tier again after restoration is complete.'}), 202
        
        # For Standard to Glacier, we can directly copy the object with the new storage class
        if current_storage_class == 'STANDARD' and target_tier == 'glacier':
            # Copy the object to itself with the new storage class
            copy_source = {'Bucket': bucket_name, 'Key': s3_key}
            s3.copy_object(
                CopySource=copy_source,
                Bucket=bucket_name,
                Key=s3_key,
                StorageClass='GLACIER',
                MetadataDirective='COPY'
            )
            
            # Update the metadata in the database
            db.files.update_one(
                {"_id": file_record['_id']},
                {"$set": {"metadata.tier": "glacier"}}
            )
            
            return jsonify({
                'message': 'File successfully changed to glacier tier',
                'metadata': {
                    'tier': 'glacier',
                    'content_type': head_response.get('ContentType', 'application/octet-stream'),
                    'size': head_response.get('ContentLength', 0),
                    'last_modified': datetime.datetime.now().isoformat()
                }
            }), 200
        
        return jsonify({'error': 'Unsupported storage class transition'}), 400
        
    except Exception as e:
        logger.exception(f"Error changing storage tier: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/<file_identifier>/details/', methods=['GET'])
@token_required
def file_details(current_user, file_identifier):
    """
    Get detailed information about a specific file.
    
    This endpoint retrieves metadata for a specific file, even if it only exists in S3 and not in the database.
    The file_identifier can be:
    - An s3_key (e.g., "username/filename.jpg")
    - A file_id (e.g., "username-filename.jpg")
    - A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically
    
    Returns detailed metadata about the file, including:
    - File name
    - URL
    - Size
    - Content type
    - Storage tier
    - Last modified date
    - Whether the file exists in the database
    
    If the file is not found in S3, a 404 error is returned.
    """
    return get_file_details(current_user, file_identifier)

if __name__ == '__main__':
    print("* Loading..." + "please wait until server has fully started")
    app.run(host="0.0.0.0", debug=True, port=5005)
    # app.run(debug=True, host="0.0.0.0", port=5005)

else:
    gunicorn_app = app
