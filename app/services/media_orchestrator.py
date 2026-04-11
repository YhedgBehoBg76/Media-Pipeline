"""
Оркестратор обработки и мультиплатформенной публикации видео.
Координирует: S3 → Валидация → Сегментация → Пайплайн FFmpeg → Загрузка → Очистка.
"""

import os
import shutil
import logging
from datetime import datetime, timezone

import yaml
import boto3
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from sqlalchemy import func

from app.models.publication import Publication, PublicationStatus
from app.core.config import settings
from app.modules.processors.factory import ProcessorFactory
from app.modules.processors.segmenter import FixedDurationSegmenter
from app.modules.uploaders.factory import UploaderFactory
from app.modules.uploaders.base import UploadResult

logger = logging.getLogger(__name__)


@dataclass
class TaskReport:
    """Структурированный отчёт о выполнении задачи."""
    task_id: str
    status: str # "success" | "partial_success" | "failed"
    segments_processed: int
    platforms: Dict[str, Any]
    errors: List[str]


class MediaProcessingOrchestrator:
    """
    Координирует полный цикл обработки видео для нескольких платформ.
    Не выполняет обработку сам, а управляет потоком данных, ресурсами и ошибками.
    """

    def __init__(
            self,
            config_path: Optional[str] = None,
            segmenter: Optional[Any] = None
    ):
        self.config_path = self._resolve_config_path(config_path)
        self.config = self._load_config()
        self.s3_client = self._init_s3_client()
        self.segmenter = segmenter or FixedDurationSegmenter()

    def run(
            self,
            task_id: str,
            source_s3_key: str,
            target_platforms: List[str],
            pipeline_steps: List[str],
            pipeline_params: Dict[str, Any],
            upload_params: Dict[str, Any],
            segmenter_params: Optional[Dict[str, Any]] = None,
            db_session: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Полный цикл обработки и публикации.

        Args:
            task_id: Уникальный ID задачи (изолирует временные файлы)
            source_s3_key: Ключ исходного видео в S3
            target_platforms: Список платформ для публикации
            pipeline_steps: Имена шагов для ProcessorFactory
            pipeline_params: Параметры для шагов обработки (duration, crop, audio и т.д.)
            upload_params: Параметры для загрузчиков (title, tags, metadata и т.д.)
            segmenter_params: Переопределение параметров сегментатора (duration, overlap и т.д.)

        Returns:
            Агрегированный отчёт в виде dict
        """
        report = TaskReport(
            task_id=task_id, status="failed", segments_processed=0, platforms={}, errors=[]
        )
        task_dir = Path("/tmp/media") / task_id
        source_path = task_dir / "source.mp4"

        try:
            self._validate_platforms(target_platforms)

            task_dir.mkdir(parents=True, exist_ok=True)
            self._download_from_s3(source_s3_key, str(source_path))

            constraints = self._resolve_constraints(target_platforms)

            self._check_disk_space(task_dir, source_path)

            seg_params = self._prepare_segmenter_params(constraints, segmenter_params)
            seg_params["output_dir"] = str(task_dir)

            #расчет квот и ограничение количества создаваемых сегментов
            if db_session and target_platforms:
                quotas = [self._get_remaining_quota(db_session, p) for p in target_platforms]
                min_quota = min(quotas) if quotas else float("inf")

                if min_quota <= 0:
                    logger.warning("⚠️ Quota exceeded for all platforms. Skipping task %s", task_id)
                    report.status = "skipped_quota"
                    report.platforms = {p: {"status": "skipped", "reason": "daily_quota_exceeded"} for p in target_platforms}
                    return asdict(report)

                seg_params["max_segments"] = min_quota if isinstance(min_quota, int) else None

            segments = self.segmenter.split(str(source_path), seg_params)

            if not segments:
                raise RuntimeError("Segmentation returned empty list. Check duration/overlap constraints.")

            pipeline = ProcessorFactory.get_processor(pipeline_steps)

            upload_results: Dict[str, List[Dict[str, Any]]] = {p: [] for p in target_platforms}

            for idx, seg_path in enumerate(segments):
                processed_path = task_dir / f"seg_{idx:02d}_final.mp4"
                pipeline.process(seg_path, str(processed_path), pipeline_params)

                for platform in target_platforms:
                    try:
                        uploader = UploaderFactory.get_uploader(platform)
                        platform_params = self._build_upload_params(platform, upload_params)
                        raw_result = uploader.upload(str(processed_path), platform_params)
                        upload_results[platform].append(self._normalize_result(platform, raw_result))
                    except Exception as e:
                        logger.error("Upload failed for %s (segment %d): %s", platform, idx, e)
                        upload_results[platform].append({"status": "error", "error": str(e)})

                report.segments_processed += 1

            report.platforms = {
                platform: {
                    "status": "error" if any(r.get("status") == "error" for r in results) else "success",
                    "results": results
                }
                for platform, results in upload_results.items()
            }

            has_errors = any(p["status"] == "error" for p in report.platforms.values())
            report.status = "partial_success" if has_errors else "success"
            logger.info("Task %s finished. Status: %s", task_id, report.status)

        except Exception as e:
            report.errors.append(str(e))
            logger.exception("💥 Critical failure in task %s", task_id)
        finally:
            self._cleanup(task_dir)
            logger.debug("Task %s temp dir cleaned", task_id)

        return asdict(report)

    def _load_config(self) -> dict:
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError("platforms.yaml must contain a valid YAML mapping")
        return data

    def _download_from_s3(self, s3_key: str, dest_path: str) -> None:
        """Скачивает файл из S3. Автоматически очищает ключ от префиксов."""
        bucket = os.getenv("S3_BUCKET", "media-storage")

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

        logger.info("⬇️ Downloading s3://%s/%s → %s", bucket, s3_key, dest_path)
        self.s3_client.download_file(bucket, s3_key, dest_path)

    def _validate_platforms(self, platforms: List[str]) -> None:
        for p in platforms:
            if p not in self.config:
                raise ValueError(f"Unknown platform '{p}' in platforms.yaml")

    def _resolve_constraints(self, platforms: List[str]) -> Dict:
        max_duration = None
        aspect_ratio = None

        for platform in platforms:
            cons = self.config[platform].get("constraints", {})
            dur = cons.get("max_duration")

            if dur is not None:
                max_duration = min(max_duration, dur) if max_duration is not None else dur

            ar = cons.get("aspect_ratio")
            if ar:
                if aspect_ratio and aspect_ratio != ar:
                    raise ValueError(f"Aspect ratio conflict: {aspect_ratio} vs {ar}")
                aspect_ratio = ar

        return {"max_duration": max_duration, "aspect_ratio": aspect_ratio}

    def _build_upload_params(self, platform: str, base_metadata: dict) -> dict:
        """Собирает upload_params для конкретной платформы: дефолты + метаданные + валидация."""
        defaults = self.config.get(platform, {}).get("upload_defaults", {})
        merged = {**defaults, **base_metadata}

        # Пример базовой валидации/адаптации (можно расширить)
        merged["title"] = (merged.get("title") or "Short")[:100]
        merged["description"] = (merged.get("description") or "")[:5000]
        merged.setdefault("tags", [])
        merged.setdefault("platform", platform)

        return merged

    def _check_platform_quota(self, db, platform: str) -> bool:
        """
        Проверяет дневной лимит публикаций
        """
        limit = self.config.get(platform, {}).get("quotas", {}).get("daily_limit")
        if limit is None:
            return True

        today = datetime.now(timezone.utc)

        published_count = db.query(Publication).filter(
            Publication.platform == platform,
            Publication.status == PublicationStatus.PUBLISHED,
            func.date(Publication.published_at) == today
        ).count()

        return published_count < limit

    def _get_remaining_quota(self, db, platform: str) -> int | float:
        limit = self.config.get(platform, {}).get("quotas", {}).get("daily_limit")
        if limit is None: return float("inf")
        today = datetime.now(timezone.utc).date()
        published = db.query(Publication).filter(
            Publication.platform == platform,
            Publication.status == PublicationStatus.PUBLISHED,
            func.date(Publication.published_at) == today
        ).count()
        return max(0, limit - published)

    @staticmethod
    def _init_s3_client() -> boto3.client:
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
    def _prepare_segmenter_params(
        constraints: dict, explicit_params: Optional[dict]
    ) -> dict:
        """Собирает конфиг для сегментатора с приоритетом: explicit > constraints"""
        return {
            "duration": constraints.get("max_duration") or explicit_params.get("duration", 55),
            "overlap": explicit_params.get("overlap", 0),
            "output_dir": "/tmp/media",  # переопределяется в split(), но оставляем для ясности
            "min_chunk": explicit_params.get("min_chunk", 5),
            "max_segments": explicit_params.get("max_segments"),
        }


    @staticmethod
    def _cleanup(task_dir: Path) -> None:
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)


    @staticmethod
    def _normalize_result(platform: str, raw_result: Any) -> Dict[str, Any]:
        """Приводит результат загрузчика к единому формату отчёта (Pydantic v1/v2 safe)."""
        if isinstance(raw_result, UploadResult):
            # Совместимо с Pydantic v1 (.dict()) и v2 (.model_dump())
            dump = raw_result.model_dump() if hasattr(raw_result, "model_dump") else raw_result.dict()
            dump["platform"] = platform
            return dump

        # Fallback для S3Uploader (возвращает str)
        return {
            "success": True,
            "url": str(raw_result),
            "external_id": str(raw_result),
            "platform": platform,
            "metadata": {}
        }


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
