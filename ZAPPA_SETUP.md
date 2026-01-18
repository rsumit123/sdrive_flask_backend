# Zappa Setup and Deployment Guide

Zappa is used to deploy your Flask application to AWS Lambda. This guide will help you install and configure Zappa.

## Installation

### 1. Install Zappa

Zappa is already included in `requirements.txt`. To install it:

```bash
cd sdrive_flask_backend
source venv/bin/activate  # Activate your virtual environment
pip install -r requirements.txt
```

Or install Zappa directly:
```bash
pip install zappa
```

### 2. Verify Installation

```bash
zappa --version
```

## Configuration

Your Zappa configuration is in `zappa_settings.json`:

```json
{
    "dev": {
        "app_function": "app.app",
        "aws_region": "us-east-1",
        "exclude": [
            "boto3",
            "dateutil",
            "botocore",
            "s3transfer",
            "concurrent"
        ],
        "profile_name": "default",
        "project_name": "sdrive-flask-ba",
        "runtime": "python3.9",
        "s3_bucket": "zappa-sdrive-flask"
    }
}
```

## AWS Setup

Before deploying with Zappa, you need to:

### 1. Configure AWS Credentials

Zappa uses AWS credentials to deploy your application. You can configure them in several ways:

**Option A: AWS CLI (Recommended)**
```bash
pip install awscli
aws configure
```

Enter your:
- AWS Access Key ID
- AWS Secret Access Key
- Default region (e.g., `us-east-1`)
- Default output format (e.g., `json`)

**Option B: Environment Variables**
```bash
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=us-east-1
```

**Option C: IAM Profile**
If you're using an IAM role or profile, make sure it's configured in `zappa_settings.json`:
```json
"profile_name": "your-profile-name"
```

### 2. Create S3 Bucket for Zappa

Zappa needs an S3 bucket to store deployment packages. The bucket name is specified in `zappa_settings.json`:

```json
"s3_bucket": "zappa-sdrive-flask"
```

Make sure this bucket exists in your AWS account:
```bash
aws s3 mb s3://zappa-sdrive-flask --region us-east-1
```

Or create it via AWS Console.

## Deployment Commands

### Initial Deployment

For the first deployment:
```bash
cd sdrive_flask_backend
zappa deploy dev
```

This will:
1. Package your Flask application
2. Upload it to S3
3. Create a Lambda function
4. Set up API Gateway
5. Return the API endpoint URL

### Update Deployment

To update an existing deployment:
```bash
zappa update dev
```

### Check Deployment Status

```bash
zappa status dev
```

### View Logs

```bash
zappa tail dev
```

Or follow logs in real-time:
```bash
zappa tail dev --follow
```

### Undeploy (Remove)

To completely remove the deployment:
```bash
zappa undeploy dev
```

## Environment Variables

For production deployments, you'll need to set environment variables in your Lambda function. You can do this in `zappa_settings.json`:

```json
{
    "dev": {
        "app_function": "app.app",
        "aws_region": "us-east-1",
        "environment_variables": {
            "MONGO_URI": "your-mongo-uri",
            "SECRET_KEY": "your-secret-key",
            "AWS_APP_ACCESS_KEY_ID": "your-aws-key",
            "AWS_APP_SECRET_ACCESS_KEY": "your-aws-secret",
            "AWS_APP_S3_REGION_NAME": "us-west-2",
            "AWS_APP_STORAGE_BUCKET_NAME": "your-bucket-name"
        },
        "exclude": [
            "boto3",
            "dateutil",
            "botocore",
            "s3transfer",
            "concurrent"
        ],
        "profile_name": "default",
        "project_name": "sdrive-flask-ba",
        "runtime": "python3.9",
        "s3_bucket": "zappa-sdrive-flask"
    }
}
```

**⚠️ Security Note:** For sensitive values, consider using AWS Systems Manager Parameter Store or AWS Secrets Manager instead of hardcoding in the config file.

## Common Issues

### 1. "Bucket does not exist"
- Make sure the S3 bucket specified in `zappa_settings.json` exists
- Check that you have permissions to access the bucket

### 2. "Access Denied" errors
- Verify your AWS credentials have the necessary permissions:
  - Lambda: CreateFunction, UpdateFunctionCode, etc.
  - API Gateway: CreateApi, CreateDeployment, etc.
  - IAM: CreateRole, AttachRolePolicy, etc.
  - S3: PutObject, GetObject, etc.

### 3. "Module not found" in Lambda
- Check the `exclude` list in `zappa_settings.json`
- Some packages like `boto3` are already available in Lambda, so they're excluded

### 4. Timeout errors
- Increase the timeout in `zappa_settings.json`:
  ```json
  "timeout_seconds": 300
  ```

### 5. Memory issues
- Increase Lambda memory:
  ```json
  "memory_size": 512
  ```

## Local Testing with Zappa

You can test your Zappa deployment locally:

```bash
zappa invoke dev 'app.app'
```

## Multiple Environments

You can define multiple environments in `zappa_settings.json`:

```json
{
    "dev": {
        "app_function": "app.app",
        "aws_region": "us-east-1",
        "s3_bucket": "zappa-sdrive-flask-dev",
        ...
    },
    "production": {
        "app_function": "app.app",
        "aws_region": "us-east-1",
        "s3_bucket": "zappa-sdrive-flask-prod",
        "domain": "api.yourdomain.com",
        ...
    }
}
```

Then deploy to specific environments:
```bash
zappa deploy dev
zappa deploy production
```

## Useful Zappa Commands

```bash
# Deploy
zappa deploy <environment>

# Update
zappa update <environment>

# Status
zappa status <environment>

# Logs
zappa tail <environment>
zappa tail <environment> --follow

# Rollback
zappa rollback <environment> -n <version>

# Undeploy
zappa undeploy <environment>

# Schedule (for cron jobs)
zappa schedule <environment>

# Package (without deploying)
zappa package <environment>
```

## Additional Resources

- [Zappa Documentation](https://github.com/Miserlou/Zappa)
- [Zappa GitHub](https://github.com/Miserlou/Zappa)
- [AWS Lambda Documentation](https://docs.aws.amazon.com/lambda/)
