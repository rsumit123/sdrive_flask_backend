#!/usr/bin/env python3
"""
Script to recover environment variables from AWS Lambda deployment.
This script checks multiple sources where environment variables might be stored.
"""

import json
import boto3
import sys
import os
from botocore.exceptions import ClientError

def get_lambda_env_vars(function_name, region='us-east-1'):
    """Get environment variables from Lambda function configuration."""
    print(f"\n🔍 Checking Lambda function: {function_name}")
    lambda_client = boto3.client('lambda', region_name=region)
    
    try:
        response = lambda_client.get_function_configuration(FunctionName=function_name)
        env_vars = response.get('Environment', {}).get('Variables', {})
        
        if env_vars:
            print(f"✅ Found {len(env_vars)} environment variables in Lambda configuration:")
            return env_vars
        else:
            print("❌ No environment variables found in Lambda configuration")
            return {}
    except ClientError as e:
        print(f"❌ Error getting Lambda configuration: {e}")
        return {}

def check_parameter_store(prefix='sdrive', region='us-east-1'):
    """Check AWS Systems Manager Parameter Store for environment variables."""
    print(f"\n🔍 Checking Parameter Store (prefix: /{prefix}/)...")
    ssm_client = boto3.client('ssm', region_name=region)
    
    env_vars = {}
    try:
        paginator = ssm_client.get_paginator('describe_parameters')
        for page in paginator.paginate(ParameterFilters=[
            {'Key': 'Name', 'Values': [f'/{prefix}/*']}
        ]):
            for param in page['Parameters']:
                try:
                    param_value = ssm_client.get_parameter(
                        Name=param['Name'],
                        WithDecryption=True
                    )['Parameter']['Value']
                    # Extract key name (remove prefix)
                    key = param['Name'].split('/')[-1]
                    env_vars[key] = param_value
                except ClientError as e:
                    print(f"  ⚠️  Could not retrieve {param['Name']}: {e}")
        
        if env_vars:
            print(f"✅ Found {len(env_vars)} parameters in Parameter Store")
        else:
            print("❌ No parameters found in Parameter Store")
    except ClientError as e:
        print(f"❌ Error checking Parameter Store: {e}")
    
    return env_vars

def check_secrets_manager(secret_name='sdrive', region='us-east-1'):
    """Check AWS Secrets Manager for environment variables."""
    print(f"\n🔍 Checking Secrets Manager (secret: {secret_name})...")
    secrets_client = boto3.client('secretsmanager', region_name=region)
    
    env_vars = {}
    try:
        # Try common secret names
        secret_names = [
            secret_name,
            f'{secret_name}-env',
            f'{secret_name}-secrets',
            'sdrive-flask-ba-dev-env'
        ]
        
        for name in secret_names:
            try:
                response = secrets_client.get_secret_value(SecretId=name)
                secret_data = json.loads(response['SecretString'])
                env_vars.update(secret_data)
                print(f"✅ Found secret: {name}")
                break
            except secrets_client.exceptions.ResourceNotFoundException:
                continue
            except json.JSONDecodeError:
                # If not JSON, treat as single value
                env_vars[name] = response['SecretString']
                print(f"✅ Found secret: {name} (non-JSON)")
                break
        
        if not env_vars:
            print("❌ No secrets found in Secrets Manager")
    except ClientError as e:
        print(f"❌ Error checking Secrets Manager: {e}")
    
    return env_vars

def download_lambda_package(function_name, region='us-east-1', output_dir='./lambda_package'):
    """Download Lambda function package to check for .env file."""
    print(f"\n🔍 Downloading Lambda package to check for .env file...")
    lambda_client = boto3.client('lambda', region_name=region)
    
    try:
        response = lambda_client.get_function(FunctionName=function_name)
        code_location = response['Code']['Location']
        
        import urllib.request
        import zipfile
        import tempfile
        
        print(f"  Downloading from: {code_location[:50]}...")
        
        # Download to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
            urllib.request.urlretrieve(code_location, tmp_file.name)
            
            # Extract and look for .env
            with zipfile.ZipFile(tmp_file.name, 'r') as zip_ref:
                os.makedirs(output_dir, exist_ok=True)
                zip_ref.extractall(output_dir)
                
                # Check for .env file
                env_file_path = os.path.join(output_dir, '.env')
                if os.path.exists(env_file_path):
                    print(f"✅ Found .env file in Lambda package!")
                    return env_file_path
                else:
                    # Check in subdirectories
                    for root, dirs, files in os.walk(output_dir):
                        if '.env' in files:
                            env_file_path = os.path.join(root, '.env')
                            print(f"✅ Found .env file in Lambda package at: {env_file_path}")
                            return env_file_path
                    
                    print("❌ No .env file found in Lambda package")
                    print(f"  Package extracted to: {output_dir}")
                    print(f"  You can manually check the extracted files")
                    return None
        
    except ClientError as e:
        print(f"❌ Error downloading Lambda package: {e}")
        return None

def main():
    function_name = 'sdrive-flask-ba-dev'
    region = 'us-east-1'
    
    print("=" * 60)
    print("🔐 Environment Variable Recovery Tool")
    print("=" * 60)
    
    all_env_vars = {}
    
    # Check Lambda configuration
    lambda_vars = get_lambda_env_vars(function_name, region)
    all_env_vars.update(lambda_vars)
    
    # Check Parameter Store
    param_vars = check_parameter_store('sdrive', region)
    all_env_vars.update(param_vars)
    
    # Check Secrets Manager
    secret_vars = check_secrets_manager('sdrive', region)
    all_env_vars.update(secret_vars)
    
    # Download Lambda package to check for .env
    env_file = download_lambda_package(function_name, region)
    
    # If .env file found, read it
    if env_file:
        print(f"\n📄 Reading .env file from Lambda package...")
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    all_env_vars[key.strip()] = value.strip()
    
    # Output results
    print("\n" + "=" * 60)
    print("📋 RECOVERED ENVIRONMENT VARIABLES")
    print("=" * 60)
    
    if all_env_vars:
        # Save to .env file
        env_file_path = '.env.recovered'
        with open(env_file_path, 'w') as f:
            for key, value in sorted(all_env_vars.items()):
                f.write(f"{key}={value}\n")
                print(f"{key}={value}")
        
        print(f"\n✅ Saved {len(all_env_vars)} environment variables to: {env_file_path}")
        print(f"\n💡 To use this file:")
        print(f"   cp {env_file_path} .env")
        print(f"   # Then review and edit .env as needed")
    else:
        print("\n❌ No environment variables found in any of the checked sources.")
        print("\n💡 Alternative methods:")
        print("   1. Check AWS Lambda Console → Configuration → Environment variables")
        print("   2. Check CloudWatch Logs for any logged environment variable names")
        print("   3. Check your deployment history/notes")
        print("   4. Check if variables are hardcoded in the code")

if __name__ == '__main__':
    main()
