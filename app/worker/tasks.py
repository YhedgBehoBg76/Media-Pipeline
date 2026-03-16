
from celery import Celery, chain

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.media import MediaItem, Status
from app.models.sources import Source

from app.modules.downloaders.factory import DownloaderFactory
from app.modules.processors.factory import ProcessorFactory
from app.modules.uploaders.factory import UploaderFactory

import json
import os
import logging
import boto3

# ← Инициализация Celery
celery_app = Celery('worker', broker=settings.RABBITMQ_URL)

# ← Исправлено: __name__ вместо name
logger = logging.getLogger(__name__)


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

DEFAULT_UPLOADER = "youtube_shorts"

def get_db_session():
    """Создаёт новую сессию БД (локально для каждой задачи)"""
    return SessionLocal()


def update_status(media_id: int, status: Status):
    """Обновляет статус MediaItem в БД"""
    db = get_db_session()
    try:
        media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
        if media:
            media.status = status
            db.commit()
            logger.info(f"Media {media_id}: status = {status.value}")
    finally:
        db.close()


def get_source(media_id: int):
    """Получает Source для MediaItem (кэшируем в одной задаче)"""
    db = get_db_session()
    try:
        media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
        if media:
            source = db.query(Source).filter(Source.id == media.source_id).first()
            return source
    finally:
        db.close()
    return None


def download_from_s3(s3_path: str, local_path: str) -> str:
    """
    Скачивает файл из S3 хранилища на локальный диск.

    Args:
        s3_path: Полный S3 путь (например, "s3://media-pipeline/processed/uuid.mp4")
        local_path: Локальный путь для сохранения файла

    Returns:
        Путь к скачанному файлу

    Raises:
        Exception: Если скачивание не удалось
    """
    # Парсим S3 путь: s3://bucket/key → bucket, key
    if not s3_path.startswith("s3://"):
        raise ValueError(f"Invalid S3 path format: {s3_path}")

    # Удаляем "s3://" и разделяем bucket и key
    s3_path_without_prefix = s3_path[5:]  # "media-pipeline/processed/uuid.mp4"
    parts = s3_path_without_prefix.split("/", 1)

    if len(parts) != 2:
        raise ValueError(f"Invalid S3 path: {s3_path}")

    bucket = parts[0]
    key = parts[1]

    # Инициализация S3 клиента (те же настройки, что и для upload)
    s3_client = boto3.client(
        's3',
        endpoint_url=settings.S3_ENDPOINT,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION
    )

    try:
        # Скачиваем файл
        s3_client.download_file(bucket, key, local_path)
        return local_path

    except Exception as e:
        raise Exception(f"Failed to download from S3: {str(e)}")

# ========== ЗАДАЧИ ==========

@celery_app.task(bind=True, max_retries=3)
def download_video_task(self, media_id: int):
    """Задача 1: Скачивание видео"""
    local_path = None
    db = get_db_session()

    try:
        media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
        if not media:
            raise Exception(f"MediaItem {media_id} not found")

        source = db.query(Source).filter(Source.id == media.source_id).first()
        if not source:
            raise Exception(f"Source not found for media {media_id}")

        # Обновляем статус
        update_status(media_id, Status.DOWNLOADING)

        # Скачиваем
        downloader = DownloaderFactory.get_downloader(source.type)
        local_path = downloader.download(media)
        logger.info(f"Downloaded to: {local_path}")

        update_status(media_id, Status.DOWNLOADED)

        # ← Возвращаем путь для следующей задачи (через chain)
        return {"media_id": media_id, "local_path": local_path}

    except Exception as e:
        logger.error(f"Download failed: {str(e)}")
        update_status(media_id, Status.FAILED)
        raise self.retry(exc=e, countdown=60)

    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def process_video_task(self, task_result: dict):
    """Задача 2: Обработка видео"""
    media_id = task_result["media_id"]
    local_path = task_result["local_path"]
    processed_path = None

    db = get_db_session()

    try:

        source = get_source(media_id)
        if not source:
            raise Exception(f"Source not found for media {media_id}")

        # Парсим стратегию
        try:
            strategy_config = json.loads(source.strategy)
        except (json.JSONDecodeError, TypeError):
            strategy_config = source.strategy

        update_status(media_id, Status.PROCESSING)

        # Обрабатываем
        processor = ProcessorFactory.get_processor(strategy_config)
        processed_path = f"/tmp/media/{media_id}_processed.mp4"

        processor.process(local_path, processed_path, params={"duration": 55})
        logger.info(f"Processed to: {processed_path}")

        update_status(media_id, Status.PROCESSED)

        # ← Передаём путь дальше
        return {"media_id": media_id, "processed_path": processed_path}

    except Exception as e:
        logger.error(f"Processing failed: {str(e)}")
        update_status(media_id, Status.FAILED)
        raise self.retry(exc=e, countdown=60)

    finally:
        db.close()
        # ← Очищаем скачанный файл
        if local_path and os.path.exists(local_path):
            os.remove(local_path)


@celery_app.task(bind=True, max_retries=3)
def upload_video_task(self, task_result: dict):
    """Задача 3: Загрузка в S3"""
    media_id = task_result["media_id"]
    processed_path = task_result["processed_path"]

    try:
        update_status(media_id, Status.UPLOADING)

        # Загружаем
        uploader = UploaderFactory.get_uploader("s3")
        s3_path = uploader.upload(processed_path, params={"prefix": "processed"})
        logger.info(f"Uploaded to: {s3_path}")

        # ← Обновляем s3_path в БД
        db = get_db_session()
        try:
            media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
            if media:
                media.s3_path = s3_path
                media.status = Status.PUBLISHED
                db.commit()
        finally:
            db.close()

        return {"media_id": media_id, "s3_path": s3_path}

    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        update_status(media_id, Status.FAILED)
        raise self.retry(exc=e, countdown=60)

    finally:
        # ← Очищаем обработанный файл
        if processed_path and os.path.exists(processed_path):
            os.remove(processed_path)


@celery_app.task(bind=True, max_retries=3)
def publish_video_task(self, task_result: dict):
    """Задача 4: Публикация на YouTube"""
    media_id = task_result["media_id"]
    s3_path = task_result.get("s3_path")  # ← Из предыдущей задачи
    db = get_db_session()
    temp_path = f"/tmp/media/{media_id}_for_upload.mp4"

    try:


        # Обновляем статус
        update_status(media_id, Status.PUBLISHING)

        # Получаем метаданные из Source или MediaItem
        media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
        source = db.query(Source).filter(Source.id == media.source_id).first()

        # ← Загружаем из S3 во временный файл для YouTube API
        # (YouTube API требует локальный файл)
        download_from_s3(s3_path, temp_path)  # ← Нужна helper-функция

        # Публикуем
        uploader = UploaderFactory.get_uploader(DEFAULT_UPLOADER)
        url = uploader.upload(
            temp_path,
            params={
                "title": f"Shorts #{media_id}",
                "description": f"Auto-generated from {source.type}",
                "media_id": media_id
            }
        )

        logger.info(f"Published to: {url}")

        # Обновляем БД
        media.status = Status.PUBLISHED
        db.commit()

        return {"media_id": media_id, "url": url}

    except Exception as e:
        logger.error(f"Publishing failed: {str(e)}")
        update_status(media_id, Status.FAILED)
        raise self.retry(exc=e, countdown=60)

    finally:
        db.close()
        # Очищаем временный файл
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


# ========== ГЛАВНАЯ ЗАДАЧА ==========

@celery_app.task
def process_media_pipeline(media_id: int):
    """
    Запускает цепочку задач.
    chain() автоматически передаёт результат каждой задачи в следующую.
    """
    workflow = chain(
        download_video_task.s(media_id),
        process_video_task.s(),
        upload_video_task.s(),
        publish_video_task.s()
    )

    return workflow.apply_async()