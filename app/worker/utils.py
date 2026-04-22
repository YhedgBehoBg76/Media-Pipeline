import boto3
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

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

def init_s3_client() -> boto3.client:
    """Инициализирует S3-клиент с валидацией обязательных переменных."""
    endpoint = settings.S3_ENDPOINT
    bucket = settings.S3_BUCKET

    if not endpoint:
        logger.warning("S3_ENDPOINT not set. Using boto3 defaults (AWS).")
    if not bucket:
        raise ValueError("S3 bucket is None (Orchestrator._init_s3_client)")

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION
    )

s3_client = init_s3_client()