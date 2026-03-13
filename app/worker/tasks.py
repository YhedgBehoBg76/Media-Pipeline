from celery import Celery
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.media import MediaItem, Status

celery_app = Celery('worker', broker=settings.RABBITMQ_URL)

@celery_app.task
def process_media_pipeline(media_id: int):
    download_video_task.delay(media_id)

@celery_app.task
def download_video_task(media_id: int):
    # TODO: Логика скачивания (yt-dlp)
    # После скачивания обновить статус в БД
    db = SessionLocal()
    media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
    media.status = Status.DOWNLOADED
    db.commit()

    process_video_task.delay(media_id)

@celery_app.task
def process_video_task(media_id: int):
    # TODO: Логика обработки (выбор стратегии + FFmpeg)
    db = SessionLocal()
    media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
    media.status = Status.PROCESSED
    db.commit()

    upload_video_task()

@celery_app.task
def upload_video_task(media_id: int):
    # TODO: Логика загрузки видео
    db = SessionLocal()

    media_item = db.query(MediaItem).filter(MediaItem.id == media_id).first()

    return {
        "status": "success",
        "url": media_item.original_url
    }
