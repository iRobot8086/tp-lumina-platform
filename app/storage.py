import os
import uuid
from google.cloud import storage
from dotenv import load_dotenv

load_dotenv()

# Ensure this is set in your .env and Cloud Run variables
BUCKET_NAME = os.getenv("GCP_STORAGE_BUCKET")

def upload_file_to_gcs(file_obj, filename: str, content_type: str) -> str:
    """
    Uploads a file to Google Cloud Storage and returns the public URL.
    """
    if not BUCKET_NAME:
        raise ValueError("GCP_STORAGE_BUCKET environment variable not set")

    # Initialize GCS Client
    # In Cloud Run, this uses the default service account automatically.
    # Locally, it looks for GOOGLE_APPLICATION_CREDENTIALS.
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)

    # Generate a unique filename to prevent collisions
    # e.g. "banners/a1b2c3d4-logo.png"
    unique_name = f"banners/{uuid.uuid4()}-{filename}"
    blob = bucket.blob(unique_name)

    # Upload the file
    blob.upload_from_file(file_obj, content_type=content_type)

    # Attempt to make public (if bucket policy allows per-object ACLs)
    try:
        blob.make_public()
    except Exception:
        # If Uniform Bucket Level Access is on, the bucket itself must be public.
        pass

    return blob.public_url