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

app = Flask(__name__)

# Enable CORS
CORS(app, supports_credentials=True)

# Configure Flask app
app.config["MONGO_URI"] = os.getenv('MONGO_URI')
app.config["SECRET_KEY"] = os.getenv('SECRET_KEY')

# Use MongoClient directly from pymongo
client = MongoClient(app.config["MONGO_URI"])

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

MAX_FILE_SIZE = 1024 * 1024 * 400  # 400MB

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


@app.route('/api/files/', methods=['GET'])
@token_required
def list_files(current_user):
    try:
    
        logger.debug(f"Listing files for {current_user['email']}")
        # Setup S3 client
        logger.debug(f"Setting up S3 client")
        # logger.debug(f"App Access key: {os.getenv('AWS_APP_ACCESS_KEY_ID')}")
        s3 = boto3.client('s3',
                        aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
                        aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
                        region_name=os.getenv('AWS_APP_S3_REGION_NAME'))
        
        prefix = current_user['email'].split('.com')[0].replace("@", "-")

        # List objects in the S3 bucket with the user's prefix
        response = s3.list_objects_v2(Bucket=os.getenv('AWS_APP_STORAGE_BUCKET_NAME'), Prefix=f"{prefix}/")
        
        files = []
        for item in response.get('Contents', []):
            if 'Key' not in item:
                continue
            print(item)
            file_key = item['Key']
            file_record = db.files.find_one({"s3_key": file_key, "upload_complete": "complete"})
            if not file_record:
                files.append({
                'file_name': file_key.split("/")[-1],
                'simple_url': get_bucket_url() + file_key,
                'metadata': {"tier": item['StorageClass'].lower(), "size": item['Size']},
                'upload_complete': 'complete',
                "last_modified": item['LastModified'],
                'id': file_key
                })
            else:
                files.append({
                    'file_name': file_record['file_name'],
                    'simple_url': get_bucket_url() + file_key,
                    'metadata': file_record['metadata'],
                    'upload_complete': file_record['upload_complete'],
                    'id': file_record['id'],
                    "last_modified": item['LastModified']
                })
        files = sorted(files, key=lambda x: x['last_modified'], reverse=True)
            
        
        return jsonify(files), 200
    except Exception as e:
        logger.exception(f"Error listing files: {str(e)}")
        print("Error listing files: ", str(e))
        return jsonify({"error": str(e)}), 500
    

@app.route('/api/files/<file_id>/download_file/', methods=['GET'])
@token_required
def download_file(current_user, file_id):
    # Check if the file exists and belongs to the current user
    logger.debug(f"Downloading file {file_id} for {current_user['email']}")
    logger.debug(f"Finding file from db")
    file_record = db.files.find_one({"id": file_id, "user": str(current_user['_id'])})
    if not file_record:
        return jsonify({'error': 'File not found'}), 404

    s3 = boto3.client('s3',
                      aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
                      aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
                      region_name=os.getenv('AWS_APP_S3_REGION_NAME'))

    try:
        logger.debug(f"Requesting S3")
        head_response = s3.head_object(Bucket=os.getenv('AWS_APP_STORAGE_BUCKET_NAME'), Key=file_record['s3_key'])
        storage_class = head_response.get('StorageClass', 'STANDARD')
        # print("storage_class => ", storage_class)
        logger.debug(f"Storage class: {storage_class}")

        if storage_class in ['GLACIER', 'DEEP_ARCHIVE']:
            # print("head response => ", head_response)
            if 'Restore' not in head_response or 'ongoing-request="true"' in head_response['Restore'] or 'ongoing-request="true"' in head_response['x-amz-restore']:
                try:
                    s3_response = s3.restore_object(
                        Bucket=os.getenv('AWS_APP_STORAGE_BUCKET_NAME'),
                        Key=file_record['s3_key'],
                        RestoreRequest={'Days': 1, 'GlacierJobParameters': {'Tier': 'Standard'}}
                    )
                    logger.debug("s3_response while downloading=> ", s3_response)
                    # db.files.update_one({"id": file_id}, {"$set": {"metadata.tier": "unarchiving"}})

                    return jsonify({'message': 'File is being restored. Try again later.'}), 202
    
                except Exception as e:
                    if 'RestoreAlreadyInProgress' in str(e):
                        return jsonify({'message': 'File is being restored. Try again later.'}), 203
                    logger.exception(f"Error restoring file: {str(e)}")
                    return jsonify({'error': str(e)}), 500
                    
    
        logger.debug(f"Getting file from S3 to return")
        file_obj = s3.get_object(Bucket=os.getenv('AWS_APP_STORAGE_BUCKET_NAME'), Key=file_record['s3_key'])
        file_data = file_obj['Body'].read()

        # Return the file
        return Response(file_data, mimetype=file_record['metadata']['content_type'],
                        headers={"Content-Disposition": f"attachment; filename={file_record['file_name']}"})
    except Exception as e:
        logger.exception(f"Error downloading file: {str(e)}")
        return jsonify({'error': str(e)}), 500



@app.route('/api/files/<file_id>/download_presigned_url/', methods=['GET'])
@token_required
def download_presigned_url(current_user, file_id):
    logger.debug(f"Generating presigned URL for file {file_id} for user {current_user['email']}")

    # Check if the file exists and belongs to the current user
    file_record = db.files.find_one({"id": file_id, "user": str(current_user['_id'])})
    if not file_record:
        return jsonify({'error': 'File not found'}), 404

    s3 = boto3.client('s3',
                      aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
                      aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
                      region_name=os.getenv('AWS_APP_S3_REGION_NAME'))

    try:
        # Check the storage class
        head_response = s3.head_object(Bucket=os.getenv('AWS_APP_STORAGE_BUCKET_NAME'), Key=file_record['s3_key'])
        storage_class = head_response.get('StorageClass', 'STANDARD')
        logger.debug(f"Storage class: {storage_class}")

        if storage_class in ['GLACIER', 'DEEP_ARCHIVE']:
            # Check if the object is already being restored
            restore_status = head_response.get('Restore', '')
            if 'ongoing-request="true"' in restore_status or 'x-amz-restore' in head_response and 'ongoing-request="true"' in head_response['x-amz-restore']:
                return jsonify({'message': 'File is being restored. Try again later.'}), 202

            # Initiate restoration
            s3.restore_object(
                Bucket=os.getenv('AWS_APP_STORAGE_BUCKET_NAME'),
                Key=file_record['s3_key'],
                RestoreRequest={'Days': 1, 'GlacierJobParameters': {'Tier': 'Standard'}}
            )
            logger.debug("Restore request initiated.")
            return jsonify({'message': 'File is being restored. Try again later.'}), 202

        # Generate a presigned URL
        presigned_url = s3.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': os.getenv('AWS_APP_STORAGE_BUCKET_NAME'),
                'Key': file_record['s3_key']
            },
            ExpiresIn=3600  # URL expires in 1 hour
        )

        logger.debug(f"Presigned URL generated: {presigned_url}")

        return jsonify({'presigned_url': presigned_url, 'file_name': file_record['file_name']}), 200

    except Exception as e:
        logger.exception(f"Error generating presigned URL: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/<file_id>/refresh', methods=['GET'])
@token_required
def refresh_file_metadata(current_user, file_id):
    logger.debug(f"Refreshing metadata for file {file_id} for {current_user['email']}")
    file_record = db.files.find_one({"_id": file_id, "user": current_user['_id']})
    if not file_record:
        return jsonify({'error': 'File not found'}), 404

    s3 = boto3.client('s3',
                      aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
                      aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
                      region_name=os.getenv('AWS_APP_S3_REGION_NAME'))

    try:
        head_response = s3.head_object(Bucket=os.getenv('AWS_APP_STORAGE_BUCKET_NAME'), Key=file_record['s3_key'])
        storage_class = head_response.get('StorageClass', 'STANDARD')

        # Update the storage class in the metadata
        if storage_class == 'STANDARD':
            file_record['metadata']['tier'] = 'standard'
        elif storage_class in ['GLACIER', 'DEEP_ARCHIVE']:
            file_record['metadata']['tier'] = 'glacier' if 'Restore' not in head_response else 'unarchiving'

        db.files.update_one({"id": file_id}, {"$set": {"metadata": file_record['metadata']}})

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
    try:
        logger.debug("Generating presigned URL for file upload")

        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        tier = data.get('tier', 'standard')
        file_name = data.get('file_name')
        content_type = data.get('content_type')
        file_size = data.get('file_size')

        if file_size > MAX_FILE_SIZE:
            logger.debug(f"File size exceeds the limit of 400MB")
            return jsonify({'error': 'File size exceeds the limit of 400MB'}), 400

        if not file_name or not content_type:
            return jsonify({'error': 'file_name and content_type are required'}), 400

        # Ensure filename is secure
        filename = secure_filename(file_name)

        # Generate username from email
        email_parts = current_user['email'].split('@')
        username = f"{email_parts[0]}-{email_parts[1].split('.')[0]}"

        # Generate S3 key
        s3_key = f"{username}/{filename}"

        logger.debug(f"Generating presigned URL for {filename} (Tier: {tier})")

        # Initialize S3 client
        s3 = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_APP_S3_REGION_NAME')
        )

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

        return jsonify({
            'message': 'Use the provided URL to upload directly to S3.',
            'presigned_url': presigned_url,
            's3_key': s3_key
        }), 200

    except Exception as e:
        logger.exception(f"Error generating presigned URL: {str(e)}")
        return jsonify({'error': 'Failed to generate presigned URL.'}), 500

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


@app.route('/api/files/<file_id>/', methods=['DELETE'])
@token_required
def delete_file(current_user, file_id):
    try:
        logger.debug(f"Attempting to delete file with ID: {file_id} for user: {current_user['email']}")


        # Fetch the file document from MongoDB
        file_doc = db.files.find_one({'id': file_id, 'user': str(current_user['_id'])})

        if not file_doc:
            return jsonify({'error': 'File not found or unauthorized.'}), 404

        s3_key = file_doc.get('s3_key')

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
            result = db.files.delete_one({'id': file_id, 'user': str(current_user['_id'])})
            if result.deleted_count == 0:
                logger.error(f"File metadata not found for ID: {file_id}")
                return jsonify({'error': 'File metadata not found.'}), 404
            logger.debug(f"Deleted file metadata from MongoDB for ID: {file_id}")
        except Exception as e:
            logger.exception(f"Error deleting file metadata from MongoDB: {str(e)}")
            return jsonify({'error': 'Failed to delete file metadata.'}), 500

        return jsonify({'message': 'File deleted successfully.'}), 200

    except Exception as e:
        logger.exception(f"Unexpected error during file deletion: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred.'}), 500



if __name__ == '__main__':
    print("* Loading..." + "please wait until server has fully started")
    app.run(host="0.0.0.0", debug=True, port=5005)
    # app.run(debug=True, host="0.0.0.0", port=5005)

else:
    gunicorn_app = app
