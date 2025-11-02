import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError

load_dotenv()

logger = logging.getLogger('flask_app')

# Email configuration from environment variables
SMTP_HOST = os.getenv('SMTP_HOST')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
SMTP_FROM_EMAIL = os.getenv('SMTP_FROM_EMAIL', SMTP_USER)

# AWS SES configuration
USE_AWS_SES = os.getenv('USE_AWS_SES', 'false').lower() == 'true'
AWS_REGION = os.getenv('AWS_SES_REGION', 'us-east-1')
AWS_SES_FROM_EMAIL = os.getenv('AWS_SES_FROM_EMAIL')

# Frontend URL for verification links
FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://yourdomain.com')


def send_verification_email(email, verification_token):
    """
    Send a verification email to the user.
    
    Args:
        email: Recipient email address
        verification_token: The token to include in the verification link
        
    Returns:
        True if email was sent successfully, False otherwise
    """
    verification_link = f"{FRONTEND_URL}/verify-email?token={verification_token}"
    
    subject = "Verify Your Email Address"
    body_text = f"""
    Thank you for registering!
    
    Please verify your email address by clicking the following link:
    {verification_link}
    
    This link will expire in 24 hours.
    
    If you did not create this account, please ignore this email.
    """
    
    body_html = f"""
    <html>
      <body>
        <h2>Thank you for registering!</h2>
        <p>Please verify your email address by clicking the following link:</p>
        <p><a href="{verification_link}">Verify Email Address</a></p>
        <p>Or copy and paste this URL into your browser:</p>
        <p>{verification_link}</p>
        <p>This link will expire in 24 hours.</p>
        <p>If you did not create this account, please ignore this email.</p>
      </body>
    </html>
    """
    
    if USE_AWS_SES:
        return send_email_ses(email, subject, body_text, body_html)
    else:
        return send_email_smtp(email, subject, body_text, body_html)


def send_email_ses(recipient, subject, body_text, body_html):
    """
    Send email using AWS SES.
    
    Args:
        recipient: Recipient email address
        subject: Email subject
        body_text: Plain text body
        body_html: HTML body
        
    Returns:
        True if email was sent successfully, False otherwise
    """
    try:
        # Use AWS credentials from environment (same as S3)
        ses_client = boto3.client(
            'ses',
            aws_access_key_id=os.getenv('AWS_APP_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_APP_SECRET_ACCESS_KEY'),
            region_name=AWS_REGION
        )
        
        from_email = AWS_SES_FROM_EMAIL or SMTP_FROM_EMAIL
        if not from_email:
            logger.error("No FROM email address configured for AWS SES")
            return False
        
        response = ses_client.send_email(
            Source=from_email,
            Destination={'ToAddresses': [recipient]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': body_text, 'Charset': 'UTF-8'},
                    'Html': {'Data': body_html, 'Charset': 'UTF-8'}
                }
            }
        )
        
        logger.info(f"Verification email sent via AWS SES to {recipient}. MessageId: {response['MessageId']}")
        return True
        
    except ClientError as e:
        logger.error(f"Error sending email via AWS SES: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email via AWS SES: {str(e)}")
        return False


def send_email_smtp(recipient, subject, body_text, body_html):
    """
    Send email using SMTP.
    
    Args:
        recipient: Recipient email address
        subject: Email subject
        body_text: Plain text body
        body_html: HTML body
        
    Returns:
        True if email was sent successfully, False otherwise
    """
    try:
        if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
            logger.error("SMTP configuration incomplete. Please set SMTP_HOST, SMTP_USER, and SMTP_PASSWORD")
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM_EMAIL
        msg['To'] = recipient
        
        # Add both plain text and HTML parts
        part1 = MIMEText(body_text, 'plain')
        part2 = MIMEText(body_html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"Verification email sent via SMTP to {recipient}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending email via SMTP: {str(e)}")
        return False

