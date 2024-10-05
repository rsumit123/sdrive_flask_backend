import jwt
from functools import wraps
from flask import request, jsonify
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from mongo_handler import MongoDBHandler
import logging

load_dotenv()

mongo_uri = os.getenv('MONGO_URI')
secret_key = os.getenv('SECRET_KEY')


client = MongoClient(mongo_uri)

# Access the database
db = client["db"]

# Set up logging
logger = logging.getLogger('flask_auth')
logger.setLevel(logging.DEBUG)  # Set the desired logging level
# Create and add the MongoDB handler
mongo_handler = MongoDBHandler(db.logs)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
mongo_handler.setFormatter(formatter)
logger.addHandler(mongo_handler)

# Custom decorator for token-based authentication
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # logger.debug(request)

        # logger.debug(request.headers)
        
        # Check for token in headers
        if 'x-access-token' in request.headers:
            token = request.headers['x-access-token']
        elif 'Authorization' in request.headers:
            token = request.headers['Authorization'].split()[1]
            # logger.debug("Received token successfully from Authorization header")
        else:
            return jsonify({'error': 'Token is missing!'}), 403
        
        # Return an error if token is missing
        if not token:
            return jsonify({'error': 'Token is missing!'}), 403

        try:
            # Decode the token and get the user's email
            # logger.debug(f"validating data with token and secret key {token} {secret_key}")
            data = jwt.decode(token, secret_key, algorithms=['HS256'])
            # logger.debug(f"Decoded token: {data}")
            current_user = db.users.find_one({'email': data['email']})
            # logger.debug(f"Current user: {current_user}")
            if not current_user:
                return jsonify({'error': 'Invalid token!'}), 403
        except Exception as e:
            return jsonify({'error': 'Token is invalid!', 'message': str(e)}), 403

        return f(current_user, *args, **kwargs)
    
    return decorated