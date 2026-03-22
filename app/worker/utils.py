import boto3
from app.core.config import settings


def ensure_bucket_exists():
    """Создаёт бакет S3 если он не существует"""
    s3_client = boto3.client(
        's3',
        endpoint_url=settings.S3_ENDPOINT,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY
    )

    try:
        s3_client.head_bucket(Bucket=settings.S3_BUCKET)
        print(f"✓ Bucket '{settings.S3_BUCKET}' exists")
    except Exception:
        print(f"Creating bucket '{settings.S3_BUCKET}'...")
        s3_client.create_bucket(Bucket=settings.S3_BUCKET)
        print(f"✓ Bucket '{settings.S3_BUCKET}' created")