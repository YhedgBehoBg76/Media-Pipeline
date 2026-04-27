import os
import shutil
import logging
from datetime import datetime, timezone

import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from sqlalchemy import func
from sqlalchemy.orm import attributes

from app.models.media import MediaItem, MediaStatus
from app.models.publication import Publication, PublicationStatus
from app.core.config import settings
from app.models.sources import Source
from app.modules.stateMachines import MediaItemSM

logger = logging.getLogger(__name__)


class MediaOrchestrator:
    NEXT_TRIGGER = {
        MediaStatus.PENDING: "start_download",
        MediaStatus.DOWNLOADED: "start_segment",
        MediaStatus.SOURCE: "",
        MediaStatus.SEGMENTED: "start_process",
        MediaStatus.PROCESSED: "start_upload",
    }

    TASKS_PATH = "/tmp/media"
    # при скачивании - создается папка /tmp/media/item_{item_id}
    # при сегментации - создается папка /tmp/media/item_{item_id}/segments

    def __init__(
            self,
            download_task,
            segment_task,
            process_task,
            upload_task,

            platfroms_config_path: Optional[str] = settings.PLATFORMS_CONFIG_PATH,
            segmenter_config_path: Optional[str] = settings.SEGMENTERS_CONFIG_PATH,
            segmenter_params: Optional[Dict[str, Any]] = {}
    ):
        """
        Производит переход MediaItem к следующему состоянию, \n
        НЕ ПУБЛИКУЕТ\n
        DOWNLOADED -> SEGMENTED/SOURCE
        -> PROCESSED
        -> UPLOADED

        :param download_task: celery.task, скачивающий исходник
        :param segment_task: celery.task, запускающий сегментер
        :param process_task: celery.task, запускающий обработку
        :param upload_task: celery.task, загружающий в s3
        :param platfroms_config_path: конфиг платформ yaml
        :param segmenter_config_path: конфиг сегментеров yaml
        :param segmenter_params: настройки сегментера, по умолчанию берутся из конфига
        """
        self.download_task = download_task
        self.segment_task = segment_task
        self.process_task = process_task
        self.upload_task = upload_task

        self.platforms_config_path = self._resolve_config_path(platfroms_config_path)
        self.platforms_config = self._load_config(self.platforms_config_path)
        self.segmenter_config = self._load_config(segmenter_config_path)
        self.segmenter_params = segmenter_params

    def next_state(self, db_session, media_id):
        item = db_session.query(MediaItem).filter(
            MediaItem.id == media_id
        ).with_for_update().first()

        source = db_session.query(Source).filter(
            Source.id == item.source_id
        ).first()

        required_platforms = source.publishers

        remaining_quota = {}
        for p in required_platforms:
            remaining_quota[p] = self._get_remaining_quota(db_session, p)

        if not any(remaining_quota.values()):
            logger.warning(f"Quotas have ended for platforms: {list(remaining_quota.keys())}")
            return

        next_trigger = self.NEXT_TRIGGER.get(item.status)
        if not next_trigger:
            logger.warning(f"Skipping MediaItem with status: '{item.status.value}'")

        logger.info(f"NEXT STATE MediaItem {media_id}")
        try:
            getattr(self, f"_{next_trigger}")(media_id, db_session)
        except AttributeError as e:
            logger.error(f"Cannot find next trigger: '{next_trigger}' ({e})")

    def get_all_rem_quota(self, db) -> Dict:
        remaining = {}

        for platform in self.platforms_config.keys():
            remaining[platform] = self._get_remaining_quota(db, platform)

        return remaining

    def advance_item(self, db, media: MediaItem, trigger_name: str = None):
        sm = MediaItemSM.MediaStateMachine(model=media, state_field="status")
        # logger.info(f"CURRENT STATE: {sm.current_state.value}")
        # logger.info(f"NEXT TRIGGERS KEYS: {list(self.NEXT_TRIGGER.keys())}")

        if not trigger_name:
            trigger_name = self.NEXT_TRIGGER.get(sm.current_state.value)

        if not trigger_name:
            return {"action": "skip", "state": sm.current_state.value}

        logger.info(f"ADVANCE MediaItem {media.id}")
        getattr(sm, trigger_name)()
        db.commit()
        return {"action": "success", "state": sm.current_state.value}

    def _start_download(self, media_id, db_session):
        item = db_session.query(MediaItem).filter(
            MediaItem.id == media_id
        ).with_for_update().first()

        logger.info(f"START DOWNLOAD MediaItem {media_id}")
        self.advance_item(db_session, item)
        self.download_task.delay(media_id)

    def _start_segment(self, media_id, db_session):
        item = db_session.query(MediaItem).filter(
            MediaItem.id == media_id
        ).with_for_update().first()

        try:
            self._check_disk_space(Path(self.TASKS_PATH), Path(item.local_path))
        except (RuntimeError, FileNotFoundError) as e:
            logger.error(f"Start segmenting error: {e}")
            db_session.rollback(item)
            return

        platforms = self._get_source_by_media_id(media_id, db_session).publishers

        segmenter = self.segmenter_config.get("segmenter")
        segmenter_params = self.segmenter_config.get(segmenter).copy()
        constraints = self._resolve_constraints(platforms)

        segmenter_params.update(self.segmenter_params)
        segmenter_params["output_dir"] = segmenter_params["output_dir"].format(media_id=media_id)

        segmenter_params.update(constraints)

        self.advance_item(db_session, item)
        self.segment_task.delay(media_id, segmenter, segmenter_params)

    def _start_process(self, media_id, db_session):
        item = db_session.query(MediaItem).filter(
            MediaItem.id == media_id
        ).with_for_update().first()

        input_path = item.local_path
        mid = media_id if not item.parent_id else item.parent_id
        output_path = f"{self.TASKS_PATH}/{mid}/segments/processed_{media_id}_segment_{int(datetime.now(timezone.utc).timestamp())}.mp4"

        if not os.path.isfile(input_path):
            self.advance_item(db_session, item, "fail_process")
            raise ValueError(f"Start processing error(media_id={media_id}): input_path = '{str(input_path)}' is not a file")

        platforms = self._get_source_by_media_id(media_id, db_session).publishers
        constraints = self._resolve_constraints(platforms)

        self.advance_item(db_session, item)
        self.process_task.delay(media_id, input_path, output_path, constraints)

    def _start_upload(self, media_id, db_session):
        item = db_session.query(MediaItem).filter(
            MediaItem.id == media_id
        ).with_for_update().first()

        params = {"prefix": "processed"}

        self.advance_item(db_session, item)
        self.upload_task.delay(media_id, params)

    def _resolve_constraints(self, platforms: List[str]) -> Dict:
        max_duration = None
        aspect_ratio = None

        for platform in platforms:
            cons = self.platforms_config[platform].get("constraints", {})
            dur = cons.get("max_duration")

            if dur is not None:
                max_duration = min(max_duration, dur) if max_duration is not None else dur

            ar = cons.get("aspect_ratio")
            if ar:
                if aspect_ratio and aspect_ratio != ar:
                    raise ValueError(f"Aspect ratio conflict: {aspect_ratio} vs {ar}")
                aspect_ratio = ar

        return {"max_duration": max_duration, "aspect_ratio": aspect_ratio}

    def _get_remaining_quota(self, db, platform: str) -> int | float:
        if platform == "s3":
            return 0
        try:
            limit = self.platforms_config.get(platform, {}).get("quotas", {}).get("daily_limit")
        except AttributeError:
            logger.error(f"Cannot get remaining quota for platform: '{platform}', return 0")
            return 0
        if limit is None: return float("inf")
        today = datetime.now(timezone.utc).date()
        published = db.query(Publication).filter(
            Publication.platform == platform,
            Publication.status == PublicationStatus.PUBLISHED,
            func.date(Publication.published_at) == today
        ).count()
        return max(0, limit - published)

    # def _build_publish_params(self, platform: str, base_metadata: dict) -> dict:
    #     """Собирает publish_params для конкретной платформы: дефолты + метаданные"""
    #     defaults = self.platforms_config.get(platform, {}).get("upload_defaults", {})
    #     merged = {**defaults, **base_metadata}
    #
    #     merged["title"] = merged.get("title")
    #     merged["description"] = merged.get("description")[:5000]
    #     merged.setdefault("tags", [])
    #     merged.setdefault("platform", platform)
    #
    #     return merged


    @staticmethod
    def _get_source_by_media_id(media_id, db_session):
        item = db_session.query(MediaItem).filter(
            MediaItem.id == media_id
        ).with_for_update().first()

        return db_session.query(Source).filter(
            Source.id == item.source_id
        ).first()


    @staticmethod
    def _load_config(config_path) -> dict:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError("platforms.yaml must contain a valid YAML mapping")
        return data


    @staticmethod
    def _resolve_config_path(explicit_path: Optional[str]) -> Path:
        """Ищет platforms.yaml в нескольких локациях (local, docker, packaged)."""
        if explicit_path:
            path = Path(explicit_path)
            if not path.is_file():
                raise FileNotFoundError(f"Config not found at explicit path: {path}")
            return path

        candidates = [
            Path("platforms.yaml"),
            Path(__file__).resolve().parents[2] / "platforms.yaml",
            Path("/app/platforms.yaml")
        ]

        for p in candidates:
            if p.is_file():
                return p
        raise FileNotFoundError("platforms.yaml not found. Provide config_path or place it in project root.")


    @staticmethod
    def _check_disk_space(task_dir: Path, source_path: Path) -> None:
        required = os.path.getsize(source_path) * 2
        free = shutil.disk_usage(task_dir).free
        if free < required:
            raise RuntimeError(
                f"Insufficient disk space. Required ~{required / 1024**3:.1f}GB, "
                f"Available {free / 1024**3:.1f}GB"
            )


    @staticmethod
    def cleanup(media_id: int) -> None:
        task_dir = Path(f"/tmp/media/{media_id}")

        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)