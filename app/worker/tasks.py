import os
import logging

from pathlib import Path
from typing import Dict
from celery import Celery, chain
from celery.schedules import crontab
from sqlalchemy.sql import func

from app.api.routes.sources import scan_source
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.media import MediaItem, MediaStatus
from app.models.sources import Source
from app.models.publication import Publication, PublicationStatus
from app.modules.processors.factory import ProcessorFactory
from app.modules.downloaders.factory import DownloaderFactory
from app.modules.uploaders.factory import UploaderFactory
from app.modules.processors.segmenters.factory import get_segmenter
from app.services.media_orchestrator import MediaOrchestrator

from app.worker.utils import s3_client

celery_app = Celery('worker', broker=settings.RABBITMQ_URL)
logger = logging.getLogger(__name__)


@celery_app.task
def update_unpublished_status():
    db = SessionLocal()
    unpublished_items = db.query(MediaItem.id).filter(
        MediaItem.status != MediaStatus.PUBLISHED and
        MediaItem.status != MediaStatus.UPLOADED
    ).all()

    if unpublished_items:
        for item in unpublished_items:
            orchestrator.next_state(db, item[0])
    else:
        qouta = orchestrator.get_all_rem_quota(db).values()
        if any(qouta):
            sources = db.query(Source.id).filter(
                Source.is_active == True
            ).all()
            for source in sources:
                scan_source(source[0], db)


@celery_app.task(max_retries=3, default_retry_delay=60)
def download_from_s3(s3_key: str, dest_path: str) -> None:
    """Скачивает файл из S3. Автоматически очищает ключ от префиксов."""
    bucket = settings.S3_BUCKET

    # 1. Очистка ключа от s3://, http://, имени бакета
    if s3_key.startswith("s3://"):
        s3_key = s3_key[5:]
        if "/" in s3_key:
            bucket, s3_key = s3_key.split("/", 1)
        else:
            raise ValueError(f"Invalid s3:// path (missing key): {s3_key}")
    elif s3_key.startswith(("http://", "https://")):
        raise ValueError(f"Expected S3 key, got URL: {s3_key}")

    s3_key = s3_key.strip().lstrip("/")
    if not s3_key:
        raise ValueError("S3 key is empty after sanitization")

    path = Path(dest_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("⬇️ Downloading s3://%s/%s → %s", bucket, s3_key, dest_path)
    s3_client.download_file(bucket, s3_key, dest_path)



@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def download_media(self, media_id: int):
    db = SessionLocal()
    item = db.query(MediaItem).filter(
        MediaItem.id == media_id
    ).with_for_update().first()

    if self.retry > 0:
        orchestrator.advance_item(db, item, "retry_download")

    try:
        if not item or not item.original_url:
            raise ValueError(f"MediaItem {media_id} missing or no original_url('{item.original_url}')")

        source = db.query(Source).filter(Source.id == item.source_id).first()
        if not source:
            raise ValueError(f"Source not found for MediaItem {media_id}")

        downloader = DownloaderFactory.get_downloader(source.type)
        local_path = downloader.download(item)

        if not local_path or not os.path.exists(local_path):
            raise FileNotFoundError(f"Downloader returned invalid or missing path: '{local_path}'")

        item.local_path = local_path
        orchestrator.advance_item(db, item, "finish_download")
    except Exception as e:
        db.rollback()
        orchestrator.advance_item(db, item, "fail_download")
        logger.error(f"Download failed for MediaItem %d: %s. Retrying in {60 * (self.request.retries + 1)} seconds...", media_id, e)
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def segment_media(self, media_id: int, segmenter_name: str, params: Dict):
    db = SessionLocal()
    item = db.query(MediaItem).filter(
        MediaItem.id == media_id
    ).with_for_update().first()

    if self.retry > 0:
        orchestrator.advance_item(db, item, "retry_segment")

    segmenter = get_segmenter(segmenter_name)()

    try:
        rem_quotas = orchestrator.get_all_rem_quota(db)
        max_segments = sum(rem_quotas.values())

        if max_segments == 0:
            logger.warning(f"Skipping segment MediaItem {media_id} because remaining_quotas is 0")
            return

        params["max_segments"] = max_segments

        segments = segmenter.split(item.local_path, params)

        for segment in segments:
            media_item = MediaItem(
                external_id=item.external_id,
                source_id=item.source_id,
                parent_id=media_id,
                original_url=item.original_url,
                local_path=segment,
                status=MediaStatus.SEGMENTED,
                used_strategy=item.used_strategy,
                video_metadata=item.video_metadata
            )

            db.add(media_item)

        orchestrator.advance_item(db, item, "finish_segment")
    except Exception as e:
        db.rollback()
        orchestrator.advance_item(db, item, "fail_segment")
        logger.error(f"Segmenting failed for MeadiaItem %d: %s", media_id, e)
        raise self.retry(exc=e, countdown=30 * (self.request.retries + 1))


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def process_media(self, media_id: int, input_path: str, output_path: str, params: Dict):
    db = SessionLocal()
    item = db.query(MediaItem).filter(
        MediaItem.id == media_id
    ).with_for_update().first()

    strategy = db.query(Source).filter(
        Source.id == item.source_id
    ).first().strategy

    if self.retry > 0:
        orchestrator.advance_item(db, item, "retry_process")

    try:
        processor = ProcessorFactory.get_processor(strategy)
        success = processor.process(input_path, output_path, params)

        if success:
            item.local_path = output_path
            item.used_strategy = ", ".join(strategy)
            orchestrator.advance_item(db, item, "finish_process")
        else:
            raise RuntimeError
    except Exception as e:
        db.rollback()
        orchestrator.advance_item(db, item, "fail_process")
        logger.error(f"Processing failed for MeadiaItem %d: %s", media_id, e)
        raise self.retry(exc=e, countdown=30 * (self.request.retries + 1))


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def upload_to_s3_media(self, media_id: int, params: Dict):
    db = SessionLocal()
    item = db.query(MediaItem).filter(
        MediaItem.id == media_id
    ).with_for_update().first()

    s3_uploader = UploaderFactory.get_uploader("s3")
    if self.retry > 0:
        orchestrator.advance_item(db, item, "retry_upload")

    try:
        s3_path = s3_uploader.upload(item.local_path, params)
        item.s3_path = s3_path
        orchestrator.advance_item(db, item, "finish_upload")
    except Exception as e:
        db.rollback()
        orchestrator.advance_item(db, item, "fail_upload")
        logger.error(f"Uploading to s3 failed for MeadiaItem %d: %s", media_id, e)
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))


@celery_app.task(bind=True, max_retries=4, default_retry_delay=60)
def publish_media(self, item_id: int, platform: str, path: str, params: Dict):
    db = SessionLocal()

    item = db.query(MediaItem).filter(
        MediaItem.id == item_id
    ).with_for_update().first()
    next_trigger = "start_publish" if self.retry == 0 else "retry_publish"
    orchestrator.advance_item(db, item, next_trigger)
    publisher = UploaderFactory.get_uploader(platform)

    publication = db.query(Publication).filter(
        Publication.media_id == item_id and
        Publication.platform == platform
    ).first()

    try:
        result = publisher.upload(path, params)

        if not publication:
            publication = Publication(
                media_id=item_id,
                platform=platform,
                error_message=result.metadata,
                published_at=func.now(),
                external_url=result.url
            )

        publication.status = PublicationStatus.PUBLISHED if result.status else PublicationStatus.FAILED

        db.add(publication)

        orchestrator.advance_item(db, item, "finish_publish")
    except Exception as e:
        db.rollback()
        orchestrator.advance_item(db, item, "fail_publish")
        logger.error(f"Publishing to {platform} failed for MeadiaItem %d: %s", item.id, e)
        raise self.retry(exc=e, countdown=120 * (self.request.retries + 1))


@celery_app.task
def publish_uploaded_media():
    db = SessionLocal()
    remaining_quota = orchestrator.get_all_rem_quota(db)
    if not any(remaining_quota.values()):
        logger.info("Quotas have ended, skipping publishing")
        return

    item = db.query(MediaItem).filter(
        MediaItem.status == MediaStatus.UPLOADED
    ).first()

    if not item:
        return

    publish_platforms = db.query(Source.publishers).filter(
        Source.id == item.source_id
    ).first()

    for platform in publish_platforms:
        platform = platform[0]
        # logger.warning(f"REM QUOTA FOR '{platform}': {remaining_quota[platform]}, type: {type(remaining_quota[platform])}")
        if remaining_quota[platform] == 0:
            continue

        upload_params = orchestrator.platforms_config[platform].get("upload_defaults", {})
        if upload_params is None:
            logger.warning(f"UPLOAD PARAMS IS NONE for platform: '{platform}'")
        upload_params.update(item.video_metadata)
        path = Path(item.local_path)
        local_path = f"{path.stem}_from_s3{path.suffix}"

        download_from_s3(item.s3_path, local_path)

        publish_media.delay(item.id, platform, local_path, upload_params)


@celery_app.task
def cleanup_sources_task():
    db = SessionLocal()

    source_items = db.query(MediaItem).filter(
        MediaItem.status == MediaStatus.SOURCE
    ).all()

    for item in source_items:
        child_items = db.query(MediaItem).filter(
            MediaItem.parent_id == item.id
        )
        child_status = set([i.status for i in child_items])

        if not len(child_status) == 1:
            logger.info(f"Skipping cleaning MediaItem {item.id} folder...")
            continue

        status = list(child_status)[0]
        if not status in (MediaStatus.UPLOADED, MediaStatus.PUBLISHED):
            logger.info(f"Skipping cleaning MediaItem {item.id} folder...")
            continue

        if status == MediaStatus.PUBLISHED:
            orchestrator.advance_item(db, item, "finish_publish")
        orchestrator.cleanup(item.id)


orchestrator = MediaOrchestrator(
    download_task=download_media,
    segment_task=segment_media,
    process_task=process_media,
    upload_task=upload_to_s3_media
)


celery_app.conf.beat_schedule = {
    # "update-unpublished-media-status": {
    #     "task": "app.worker.tasks.update_unpublished_status",
    #     "schedule": crontab(minute="*/30"),
    # },

    "publish-uploaded-to-s3-media": {
        "task": "app.worker.tasks.publish_uploaded_media",
        "schedule": crontab(minute="*/5")
    },

    "cleanup-sources-media":{
        "task": "app.worker.tasks.cleanup_sources_task",
        "schedule": crontab(minute="*/30")
    }
}