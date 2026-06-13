import os
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from werkzeug.utils import secure_filename

# Read S3 Configuration from environment
S3_BUCKET = os.getenv('S3_BUCKET')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')

# Local upload fallback configuration
LOCAL_UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
os.makedirs(LOCAL_UPLOAD_FOLDER, exist_ok=True)

# Determine if S3 is active
USE_S3 = all([S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY])

s3_client = None
if USE_S3:
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        print(f"Connected to AWS S3 Bucket: {S3_BUCKET}")
    except Exception as e:
        print(f"Failed to connect to S3: {e}. Falling back to local file storage.")
        USE_S3 = False

def upload_file(file_obj, candidate_id=None):
    """
    Uploads a file to AWS S3 or fallback local storage.
    Returns: (s3_key_or_local_path, download_url_or_filepath)
    """
    filename = secure_filename(file_obj.filename)
    if not filename:
        return None, None

    # Prefix with candidate ID to prevent overwrites
    prefix = f"candidate_{candidate_id}/" if candidate_id else "general/"
    unique_key = f"{prefix}{filename}"

    if USE_S3 and s3_client:
        try:
            # Upload to S3
            # We can set ACL to private and generate pre-signed URLs for downloads (best practice)
            s3_client.upload_fileobj(
                file_obj,
                S3_BUCKET,
                unique_key,
                ExtraArgs={'ContentType': file_obj.content_type}
            )
            
            # Generate pre-signed URL valid for 1 hour
            download_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': S3_BUCKET, 'Key': unique_key},
                ExpiresIn=3600
            )
            return unique_key, download_url
        except ClientError as e:
            print(f"S3 Upload ClientError: {e}. Falling back to local storage.")
        except Exception as e:
            print(f"S3 Upload Error: {e}. Falling back to local storage.")

    # Local storage fallback
    local_dir = os.path.join(LOCAL_UPLOAD_FOLDER, prefix)
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, filename)
    
    # Reset file pointer and save locally
    file_obj.seek(0)
    file_obj.save(local_path)
    
    # Return relative path for routing
    relative_path = f"static/uploads/{prefix}{filename}"
    return relative_path, "/" + relative_path

def get_download_url(s3_key):
    """
    Generates a download URL for a file. If local, returns the local static URL.
    If S3, generates a pre-signed URL.
    """
    if not s3_key:
        return "#"

    # Check if it is a local upload path
    if s3_key.startswith("static/uploads/"):
        return "/" + s3_key

    if USE_S3 and s3_client:
        try:
            # Generate pre-signed URL valid for 1 hour
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': S3_BUCKET, 'Key': s3_key},
                ExpiresIn=3600
            )
            return url
        except Exception as e:
            print(f"Error generating presigned URL: {e}")
            
    # Fallback to local link check just in case
    return "/" + s3_key

def delete_file(s3_key):
    """Deletes a file from S3 or local storage."""
    if not s3_key:
        return False

    if s3_key.startswith("static/uploads/"):
        local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), s3_key)
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
                return True
            except Exception as e:
                print(f"Error deleting local file: {e}")
                return False
        return False

    if USE_S3 and s3_client:
        try:
            s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)
            return True
        except Exception as e:
            print(f"Error deleting S3 object: {e}")
            return False
            
    return False
