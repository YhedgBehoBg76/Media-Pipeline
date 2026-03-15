
import boto3
import uuid
import os
from app.core.config import settings
from app.modules.uploaders.base import UploaderAdapter


class S3Uploader(UploaderAdapter):
    """Загрузчик в S3-совместимое хранилище (MinIO)"""

    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION
        )
        self.bucket = settings.S3_BUCKET

    @property
    def name(self) -> str:
        return "s3"

    def upload(self, file_path, params: dict) -> str:
        """
        Загружает файл в S3 хранилище.

        Args:
            file_path: Путь к локальному файлу
            params: Параметры (bucket, prefix, etc.)

        Returns:
            S3 ключ загруженного файла

        Raises:
            Exception: Если загрузка не удалась
        """

        prefix = params.get("prefix")
        filename = f"{uuid.uuid4()}.mp4"
        s3_key = f"{prefix}/{filename}"

        try:
            self.s3_client.upload_file(
                file_path,
                self.bucket,
                s3_key,
                ExtraArgs={
                    'ContentType': 'video/mp4',
                    'ACL': 'private'
                }
            )

            return f"s3://{self.bucket}/{s3_key}"

        except Exception as e:
            raise Exception(f"Failed to upload to S3: {str(e)}")
