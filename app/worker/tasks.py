from celery import Celery, chain
from celery.schedules import crontab

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.media import MediaItem, MediaStatus
from app.models.sources import Source
from app.models.publication import Publication, PublicationStatus

from app.modules.downloaders.factory import DownloaderFactory
from app.modules.processors.factory import ProcessorFactory
from app.modules.uploaders.factory import UploaderFactory

from typing import Optional, Dict, Any
from sqlalchemy.sql import func
from sqlalchemy import update
from datetime import datetime, timezone

import json
import os
import logging
import boto3


celery_app = Celery('worker', broker=settings.RABBITMQ_URL)

logger = logging.getLogger(__name__)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def get_db_session():
    """Создаёт новую сессию БД (локально для каждой задачи)"""
    return SessionLocal()


def update_status(media_id: int, status: MediaStatus):
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


def calculate_aggregated_status(publications: list[Publication]) -> MediaStatus:
    """Определяет агрегированный статус по списку публикаций"""
    if not publications:
        return MediaStatus.PROCESSED

    statuses = [pub.status for pub in publications]

    # ← Чёткие правила в порядке приоритета
    if all(s == PublicationStatus.FAILED for s in statuses):
        return MediaStatus.FAILED

    if all(s == PublicationStatus.PUBLISHED for s in statuses):
        return MediaStatus.PUBLISHED

    if any(s == PublicationStatus.PUBLISHED for s in statuses) and \
            any(s in [PublicationStatus.FAILED, PublicationStatus.PENDING] for s in statuses):
        return MediaStatus.PARTIALLY_PUBLISHED

    if any(s in [PublicationStatus.PENDING, PublicationStatus.PUBLISHING] for s in statuses):
        return MediaStatus.PUBLISHING

    return MediaStatus.PROCESSED


def update_aggregated_media_status(db, media_id: int) -> bool:
    """Обновляет статус, используя вычисленную логику"""
    publications = db.query(Publication).filter(
        Publication.media_id == media_id
    ).all()

    if not publications:
        return False

    new_status = calculate_aggregated_status(publications)

    result = db.execute(
        update(MediaItem)
        .where(
            MediaItem.id == media_id,
            MediaItem.status != new_status
        )
        .values(
            status=new_status,
            updated_at=func.now()
        )
    )

    db.commit()
    return result.rowcount > 0


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
    """Скачивание видео"""
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
        update_status(media_id, MediaStatus.DOWNLOADING)

        # Скачиваем
        downloader = DownloaderFactory.get_downloader(source.type)
        local_path = downloader.download(media)
        logger.info(f"Downloaded to: {local_path}")

        update_status(media_id, MediaStatus.DOWNLOADED)

        # ← Возвращаем путь для следующей задачи (через chain)
        return {"media_id": media_id, "local_path": local_path}

    except Exception as e:
        logger.error(f"Download failed: {str(e)}")
        update_status(media_id, MediaStatus.FAILED)
        raise self.retry(exc=e, countdown=60)

    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def process_video_task(self, task_result: dict):
    """Обработка видео"""
    media_id = task_result["media_id"]
    local_path = task_result["local_path"]
    processed_path = None

    db = get_db_session()

    try:

        source = get_source(media_id)
        if not source:
            raise Exception(f"Source not found for media {media_id}")

        try:
            strategy_config = json.loads(source.strategy)
        except (json.JSONDecodeError, TypeError):
            strategy_config = source.strategy

        update_status(media_id, MediaStatus.PROCESSING)

        processor = ProcessorFactory.get_processor(strategy_config)
        processed_path = f"/tmp/media/{media_id}_processed.mp4"

        processor.process(local_path, processed_path, params={"duration": 55})
        logger.info(f"Processed to: {processed_path}")

        update_status(media_id, MediaStatus.PROCESSED)

        return {"media_id": media_id, "processed_path": processed_path}

    except Exception as e:
        logger.error(f"Processing failed: {str(e)}")
        update_status(media_id, MediaStatus.FAILED)
        raise self.retry(exc=e, countdown=60)

    finally:
        db.close()
        if local_path and os.path.exists(local_path):
            os.remove(local_path)


@celery_app.task(bind=True, max_retries=3)
def upload_video_task(self, task_result: dict):
    """Загрузка в S3"""
    media_id = task_result["media_id"]
    processed_path = task_result["processed_path"]

    try:
        update_status(media_id, MediaStatus.UPLOADING)

        uploader = UploaderFactory.get_uploader("s3")
        s3_path = uploader.upload(processed_path, params={"prefix": "processed"})
        logger.info(f"Uploaded to: {s3_path}")

        db = get_db_session()
        try:
            media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
            if media:
                media.s3_path = s3_path
                media.status = MediaStatus.UPLOADED
                db.commit()
        finally:
            db.close()

        return {"media_id": media_id, "s3_path": s3_path}

    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        update_status(media_id, MediaStatus.FAILED)
        raise self.retry(exc=e, countdown=60)

    finally:
        if processed_path and os.path.exists(processed_path):
            os.remove(processed_path)


@celery_app.task(bind=True, max_retries=5, autoretry_for=(Exception,))
def publish_to_platform(self, publication_id: int) -> Dict[str, Any]:
    """
    Args:
        publication_id: ID записи в таблице publications

    Returns:
        Dict с результатом публикации
    """
    db = get_db_session()
    temp_path: Optional[str] = None
    publication = None

    try:
        publication = db.query(Publication).filter(
            Publication.id == publication_id
        ).first()

        if not publication:
            logger.error(f"[tasks.publish_to_platform] Publication {publication_id} not found")
            return {
                "publication_id": publication_id,
                "status": "failed",
                "error": "Publication not found"
            }

        if publication.status == PublicationStatus.PUBLISHED:
            logger.warning(f"Publication {publication_id} already published, skipping")
            return {
                "publication_id": publication_id,
                "status": "skipped",
                "reason": "already_published"
            }

        media = db.query(MediaItem).filter(
            MediaItem.id == publication.media_id
        ).first()

        if not media:
            raise Exception(f"MediaItem {publication.media_id} not found")

        # Проверяем готовность видео
        if media.status not in [MediaStatus.UPLOADED, MediaStatus.PUBLISHING, MediaStatus.PARTIALLY_PUBLISHED]:
            raise Exception(f"Media {publication.media_id} not ready (status={media.status.value})")

        if not media.s3_path:
            raise Exception(f"Media {publication.media_id}: s3_path is None")

        # ← Обновляем статус ТОЛЬКО этой публикации
        publication.status = PublicationStatus.PUBLISHING
        publication.retry_count += 1
        publication.error_message = None
        db.commit()

        logger.info(f"Publication {publication_id}: publishing to {publication.platform}")

        # Скачиваем из S3 во временный файл
        temp_path = f"/tmp/media/{media.id}_{publication.platform}.mp4"
        download_from_s3(media.s3_path, temp_path)

        metadata = {}
        if media.video_metadata:
            try:
                metadata = media.video_metadata
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"[publish_to_platform] metadata JSON error: {e}")

        uploader = UploaderFactory.get_uploader(publication.platform)

        upload_result = uploader.upload(
            temp_path,
            params={
                "title": metadata.get("title"),
                "description": metadata.get("description"),
                "tags": metadata.get("tags", []),
                "media_id": media.id
            }
        )

        publication.status = PublicationStatus.PUBLISHED
        publication.external_url = upload_result.url
        publication.external_id = upload_result.external_id
        publication.published_at = func.now()
        publication.error_message = None
        db.commit()

        update_aggregated_media_status(db, media.id)

        logger.info(f"Publication {publication_id}: published to {publication.platform} at {upload_result.url}")

        return {
            "publication_id": publication_id,
            "media_id": media.id,
            "platform": publication.platform,
            "status": "published",
            "url": upload_result.url
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(
            f"Publication {publication_id}: failed - {error_msg}. "
        )

        if db:
            publication.status = PublicationStatus.FAILED
            publication.error_message = error_msg
            db.commit()

            update_aggregated_media_status(db, publication.media_id)

        if publication.retry_count < publication.max_retries:
            countdown = 300 * publication.retry_count  # Экспоненциальная задержка
            raise self.retry(exc=e, countdown=countdown)
        else:
            logger.error(f"Publication {publication_id}: max retries reached")
            return {
                "publication_id": publication_id,
                "status": "failed",
                "error": error_msg
            }

    finally:
        if db:
            db.close()
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@celery_app.task
def publish_scheduler() -> Dict[str, int]:
    """
    Запускается Celery Beat каждые 30 минут.
    Проверяет лимиты по платформам и отправляет публикации в очередь.

    Returns:
        Dict с количеством отправленных публикаций по платформам
    """
    db = get_db_session()

    quotas = {
        "youtube_shorts": int(os.getenv("YOUTUBE_DAILY_LIMIT", "6"))
    }

    result = {}

    try:
        today = datetime.now(timezone.utc).date()

        for platform, limit in quotas.items():
            published_today = db.query(Publication).filter(
                Publication.platform == platform,
                Publication.status == PublicationStatus.PUBLISHED,
                func.date(Publication.published_at) == today  # ← func.date() преобразует на стороне БД
            ).count()

            remaining = limit - published_today

            if remaining <= 0:
                logger.info(f"Quota reached for {platform}: {published_today}/{limit}")
                result[platform] = 0
                continue

            pending = db.query(Publication).join(
                MediaItem, Publication.media_id == MediaItem.id
            ).filter(
                Publication.platform == platform,
                Publication.status == PublicationStatus.PENDING,
                # ← Только готовые MediaItem
                MediaItem.status.in_([
                    MediaStatus.UPLOADED,
                    MediaStatus.PUBLISHING,
                    MediaStatus.PARTIALLY_PUBLISHED
                ])
            ).order_by(Publication.created_at).limit(remaining).all()

            for pub in pending:
                publish_to_platform.delay(pub.id)
                logger.info(f"Queued publication {pub.id} for {platform}")

            result[platform] = len(pending)

        logger.info(f"Scheduler completed: {result}")
        return result

    except Exception as e:
        logger.error(f"Scheduler failed: {str(e)}")
        raise

    finally:
        db.close()


@celery_app.task
def retry_failed_publications(max_retries: int = 3) -> int:
    """
    Находит FAILED публикации и отправляет на retry.
    Можно запускать вручную или по расписанию.

    Args:
        max_retries: Максимальное количество попыток

    Returns:
        Количество отправленных на retry
    """
    db = get_db_session()
    count = 0

    try:
        failed = db.query(Publication).filter(
            Publication.status == PublicationStatus.FAILED,
            Publication.retry_count < max_retries
        ).all()

        for pub in failed:
            pub.status = PublicationStatus.PENDING
            pub.error_message = None
            db.commit()

            publish_to_platform.delay(pub.id)
            count += 1
            logger.info(f"Retrying publication {pub.id} for {pub.platform}")

        logger.info(f"Retry task: queued {count} failed publications")
        return count

    finally:
        db.close()

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
    )

    result = workflow.apply_async()

    logger.info(f"Media {media_id}: processing pipeline started, task_id={result.id}")

    return {
        "media_id": media_id,
        "task_id": result.id,
        "status": "processing"
    }


celery_app.conf.beat_schedule = {
    "publish-scheduler": {
        "task": "app.worker.tasks.publish_scheduler",
        "schedule": crontab(minute="*/2"),  # Каждые 30 минут
    },
    "retry-failed-publications": {
        "task": "app.worker.tasks.retry_failed_publications",
        "schedule": crontab(minute=0, hour="*/2"),  # Каждые 2 часа
    },
}
