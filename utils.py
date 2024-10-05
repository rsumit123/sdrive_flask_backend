import os
from dotenv import load_dotenv

load_dotenv()

def get_bucket_url():

    return f"https://{os.getenv('AWS_APP_STORAGE_BUCKET_NAME')}.s3.amazonaws.com/"