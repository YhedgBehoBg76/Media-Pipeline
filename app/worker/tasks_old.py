import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from celery import Celery, chain
from celery.schedules import crontab
from sqlalchemy import func

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.media import MediaItem, MediaStatus
from app.models.sources import Source
from app.models.publication import Publication, PublicationStatus
from app.services.media_orchestrator import MediaProcessingOrchestrator
from app.modules.downloaders.factory import DownloaderFactory
from app.modules.uploaders.factory import UploaderFactory

#Base.metadata.create_all(bind=engine)

logger = logging.getLogger(__name__)
celery_app = Celery('orchestrator_worker', broker=settings.RABBITMQ_URL)

# =========================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================================

def _save_publications(db, media_id: int, report: Dict[str, Any]) -> None:
    """Создаёт/обновляет записи Publication на основе отчёта оркестратора"""
    for platform, plat_report in report["platforms"].items():
        results = plat_report.get("results", [])
        first_res = results[0] if results else {}

        pub = Publication(
            media_id=media_id,
            platform=platform,
            status=PublicationStatus.PUBLISHED if plat_report["status"] == "success" else PublicationStatus.FAILED,
            external_url=first_res.get("url"),
            error_message=next((r.get("error") for r in results if r.get("error")), None),
            published_at=func.now() if plat_report["status"] == "success" else None,
            retry_count=0
        )
        db.add(pub)

# =========================================================================
# CELERY TASK
# =========================================================================


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_raw_video_task(self, media_id: int) -> dict:
    """
    Скачивает original_url → сохраняет в S3 как raw-исходник → обновляет MediaItem.s3_path.
    Возвращает dict для передачи в chain().
    """
    db = SessionLocal()
    local_path = None
    try:
        media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
        if not media or not media.original_url:
            raise ValueError(f"MediaItem {media_id} missing or no original_url")

        source = db.query(Source).filter(Source.id == media.source_id).first()
        if not source:
            raise ValueError(f"Source not found for media {media_id}")

        media.status = MediaStatus.DOWNLOADING
        db.commit()

        # 1. Скачивание
        downloader = DownloaderFactory.get_downloader(source.type)
        local_path = downloader.download(media)
        if not local_path or not os.path.exists(local_path):
            raise FileNotFoundError(f"Downloader returned invalid or missing path: {local_path}")

        # 2. Загрузка в S3 как RAW
        s3_uploader = UploaderFactory.get_uploader("s3")
        # Передаём prefix="raw", загрузчик сам сформирует путь.
        s3_path = s3_uploader.upload(local_path, params={"prefix": "raw"})

        # 3. Обновление БД
        media.s3_path = s3_path
        media.status = MediaStatus.UPLOADED  # Или MediaStatus.READY, по твоей enum-логике
        db.commit()

        logger.info("✅ Ingested raw video for media %d: %s", media_id, s3_path)
        return {"media_id": media_id, "s3_path": s3_path}

    except Exception as e:
        logger.error("❌ Ingest failed for media %d: %s", media_id, e)
        if db.query(MediaItem).filter(MediaItem.id == media_id).first():
            db.query(MediaItem).filter(MediaItem.id == media_id).update({"status": MediaStatus.FAILED})
            db.commit()
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))
    finally:
        db.close()
        if local_path and os.path.exists(local_path):
            os.remove(local_path)


@celery_app.task(bind=True, max_retries=3)
def run_media_orchestrator(
    self,
    ingest_result: dict,
    platforms: List[str],
    metadata: Optional[Dict[str, Any]] = None,
    pipeline_params: Optional[Dict[str, Any]] = None,
    segmenter_params: Optional[Dict[str, Any]] = None
):
    """
    Универсальный таск: S3 → Сегментация → Пайплайн → Мульти-аплоад → БД.
    Параметры пайплайна и сегментатора динамически берутся из Source или аргументов.
    """
    db = SessionLocal()
    media_id = ingest_result["media_id"]
    try:
        # 1. Валидация сущностей
        media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
        if not media or not media.s3_path:
            raise ValueError(f"MediaItem {media_id} not found or missing s3_path")

        source = db.query(Source).filter(Source.id == media.source_id).first()
        if not source:
            raise ValueError(f"Source not found for media {media_id}")

        strategy_config = source.strategy
        final_pipeline_params = {"duration": 55, **(pipeline_params or {})}
        final_segmenter_params = {"overlap": 0, "min_chunk": 5, **(segmenter_params or {})}

        media.status = MediaStatus.PROCESSING
        db.commit()

        # 4. Запуск оркестратора
        orchestrator = MediaProcessingOrchestrator()
        task_id = f"orch_{media_id}_{int(datetime.now(timezone.utc).timestamp())}"

        report = orchestrator.run(
            task_id=task_id,
            source_s3_key=media.s3_path,
            target_platforms=platforms,
            pipeline_steps=strategy_config,
            pipeline_params=final_pipeline_params,
            upload_params=metadata or {},
            segmenter_params=final_segmenter_params,
            db_session=db
        )

        # 5. Сохранение результатов публикаций
        _save_publications(db, media_id, report)

        # 6. Агрегация финального статуса MediaItem
        has_errors = any(p.get("status") == "error" for p in report["platforms"].values())
        all_success = all(p.get("status") == "success" for p in report["platforms"].values())

        media.status = (
            MediaStatus.PUBLISHED if all_success else
            MediaStatus.PARTIALLY_PUBLISHED if has_errors else
            MediaStatus.FAILED
        )
        db.commit()

        logger.info("✅ Orchestrator task %s completed. Status: %s", media_id, report["status"])
        return report

    except Exception as e:
        logger.exception("💥 Orchestrator task %s failed: %s", media_id, e)
        # Атомарный откат статуса при критическом сбое
        if db.query(MediaItem).filter(MediaItem.id == media_id).first():
            db.query(MediaItem).filter(MediaItem.id == media_id).update({"status": MediaStatus.FAILED})
            db.commit()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()

@celery_app.task
def media_processing_scheduler() -> dict:
    """Забирает PENDING MediaItem, проверяет квоты, запускает chain"""
    db = SessionLocal()
    try:
        pending = db.query(MediaItem).filter(
            MediaItem.status == MediaStatus.PENDING
        ).limit(10).all()

        if not pending:
            return {"queued": 0, "skipped_by_quota": 0}

        orchestrator = MediaProcessingOrchestrator()
        today = datetime.now(timezone.utc).date()
        remaining_quotas = {}

        for platform, cfg in orchestrator.config.items():
            limit = cfg.get("quotas", {}).get("daily_limit")
            if limit is None:
                remaining_quotas[platform] = float("inf")
                continue

            published_today = db.query(Publication).filter(
                Publication.platform == platform,
                Publication.status == PublicationStatus.PUBLISHED,
                func.date(Publication.published_at) == today
            ).count()

            remaining_quotas[platform] = max(0, limit - published_today)

        queued = 0
        skipped = 0

        for media in pending:
            source = db.query(Source).filter(Source.id == media.source_id).first()
            if not source or not source.is_active:
                continue

            platforms = source.publishers

            available = [p for p in platforms if remaining_quotas.get(p, 0) > 0]
            if not available:
                skipped += 1
                continue

            media.status = MediaStatus.DOWNLOADING
            db.commit()

            workflow = chain(
                ingest_raw_video_task.s(media.id),
                run_media_orchestrator.s(
                    platforms=available,
                    metadata=media.video_metadata or {}
                )
            )

            workflow.apply_async()
            queued += 1

        return {"queued": queued, "skipped_by_quota": skipped}

    except Exception as e:
        logger.error("Scheduler failed: %s", e)
        raise
    finally:
        db.close()


celery_app.conf.beat_schedule = {
    "process-pending-media": {
        "task": "app.worker.tasks.media_processing_scheduler",
        "schedule": crontab(minute="*/1"),  # Каждые 1 минуту
    },
}