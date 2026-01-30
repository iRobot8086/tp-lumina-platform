import os
from google.cloud import storage
from datetime import timedelta

# Set your GCS Bucket Name (Created in GCP Console)
BUCKET_NAME = os.getenv("GCP_STORAGE_BUCKET", "lumina-assets")

def upload_blob(file_obj, destination_blob_name):
    """
    Uploads a file to the GCS bucket.
    :param file_obj: The file content (from FastAPI's UploadFile)
    :param destination_blob_name: The name it will have in the bucket (e.g., 'logos/client_a.png')
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)

    # Upload the file
    blob.upload_from_file(file_obj)
    
    # Return the public URL
    # Note: Make sure the bucket or file has 'Storage Object Viewer' permission for 'allUsers' 
    # if you want them to be public, OR use signed URLs for private assets.
    return f"https://storage.googleapis.com/{BUCKET_NAME}/{destination_blob_name}"

def generate_signed_url(blob_name):
    """
    Generates a temporary URL that expires in 1 hour. 
    Great for private/secure assets.
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_name)

    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=60),
        method="GET"
    )
    return url