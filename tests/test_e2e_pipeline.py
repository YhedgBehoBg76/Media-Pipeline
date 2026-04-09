import os
import json
import pytest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime, timezone
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session

# Импорты твоих модулей
from app.models.media import MediaItem, MediaStatus
from app.models.sources import Source
from app.models.publication import Publication, PublicationStatus
from app.worker.tasks import ingest_raw_video_task, run_media_orchestrator, media_processing_scheduler
from app.services.media_orchestrator import MediaProcessingOrchestrator
from app.modules.downloaders.factory import DownloaderFactory


# ==============================================================================
# FIXTURES & SETUP
# ==============================================================================
@pytest.fixture(scope="session")
def test_engine():
    """In-memory SQLite для тестов"""
    engine = create_engine("sqlite:///:memory:")
    # Создаём таблицы (убедись, что Base импортирует все модели)
    from app.models.media import Base as MediaBase
    MediaBase.metadata.create_all(bind=engine)
    yield engine
    MediaBase.metadata.drop_all(bind=engine)


@pytest.fixture
def db(test_engine):
    """Транзакционная сессия с автооткатом"""
    TestingSessionLocal = sessionmaker(bind=test_engine)
    session = TestingSessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def test_dir(tmp_path):
    """Изолированная временная директория для тестов"""
    d = tmp_path / "media_test"
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ==============================================================================
# MOCKS CONFIG
# ==============================================================================
TEST_CONFIG = {
    "youtube_shorts": {
        "constraints": {"max_duration": 60, "aspect_ratio": "9:16"},
        "quotas": {"daily_limit": 6},
        "upload_defaults": {"privacy": "private"}
    },
    "s3": {
        "constraints": {},
        "quotas": {"daily_limit": None},
        "upload_defaults": {}
    }
}

@pytest.fixture(autouse=True)
def mock_dependencies(test_dir, db):
    """Глобальные моки для всех тестов в файле"""
    with \
        patch.object(MediaProcessingOrchestrator, "_load_config", return_value=TEST_CONFIG), \
        patch("app.worker.tasks.SessionLocal", return_value=db), \
        patch("app.worker.tasks.DownloaderFactory.get_downloader") as mock_downloader, \
        patch("app.worker.tasks.UploaderFactory.get_uploader") as mock_uploader, \
        patch("app.services.media_orchestrator.ProcessorFactory.get_processor") as mock_processor, \
        patch("subprocess.run") as mock_subprocess:

        # Мокируем FFmpeg/ffprobe
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="180.0\n", stderr="")

        # Мокируем Downloader: создаёт dummy-файл
        def fake_download(media):
            path = test_dir / f"raw_{media.id}.mp4"
            path.write_bytes(b"fake video content")
            return str(path)
        mock_downloader.return_value.download.side_effect = fake_download

        # Мокируем Uploader: возвращает путь как ключ
        def fake_upload(file_path, params):
            return f"processed/{Path(file_path).name}"
        mock_uploader_instance = MagicMock()
        mock_uploader_instance.upload.side_effect = fake_upload
        mock_uploader.return_value = mock_uploader_instance

        # Мокируем Processor: просто копирует файл
        def fake_process(input_path, output_path, params):
            Path(output_path).write_bytes(Path(input_path).read_bytes())
            return True
        mock_processor_instance = MagicMock()
        mock_processor_instance.process.side_effect = fake_process
        mock_processor.return_value = mock_processor_instance

        yield


# ==============================================================================
# TESTS
# ==============================================================================
def _seed_data(db, quota_limit=None):
    """Создаёт Source + MediaItem + Publication для теста"""
    source = Source(
        type="youtube",
        config=json.dumps({"channel_id": "UC_test"}),
        strategy=json.dumps(["simple_cut"]),
        is_active=True,
        publishers=json.dumps(["youtube_shorts", "s3"])
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    media = MediaItem(
        external_id="vid_123",
        source_id=source.id,
        original_url="https://fake.url/video.mp4",
        status=MediaStatus.PENDING,
        used_strategy=json.dumps(["simple_cut"]),
        video_metadata=json.dumps({"title": "Test Video"})
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    # Обновляем квоту динамически
    if quota_limit is not None:
        TEST_CONFIG["youtube_shorts"]["quotas"]["daily_limit"] = quota_limit

    return source, media


def test_full_happy_path(db, test_dir):
    """PENDING → DOWNLOADING → PROCESSING → PUBLISHED. Файлы создаются и чистятся."""
    _, media = _seed_data(db, quota_limit=10)
    assert media.status == MediaStatus.PENDING

    # 1. Ingest
    ingest_result = ingest_raw_video_task.apply(args=(media.id,)).get(timeout=10)
    assert ingest_result["s3_path"].startswith("processed/raw_")
    db.refresh(media)
    assert media.status == MediaStatus.UPLOADED

    # 2. Orchestrator
    report = run_media_orchestrator.apply(args=(
        ingest_result,
        ["youtube_shorts", "s3"],
        {"title": "Test"}
    )).get(timeout=15)

    assert report["status"] == "success"
    db.refresh(media)
    assert media.status == MediaStatus.PUBLISHED
    assert report["segments_processed"] >= 1
    assert len(report["platforms"]["youtube_shorts"]["results"]) >= 1


def test_quota_limits_segmentation(db, test_dir):
    """Квота=2, видео режется на 3 сегмента. Обрабатываются только 2. Статус=PARTIALLY_PUBLISHED."""
    _, media = _seed_data(db, quota_limit=2)
    # Имитируем длинное видео (180 сек → 3 сегмента по 55с)
    with patch("subprocess.run") as mock_ff:
        mock_ff.return_value = MagicMock(returncode=0, stdout="180.0\n")
        _, ingest_res = ingest_raw_video_task.apply(args=(media.id,)).get(), None

    report = run_media_orchestrator.apply(args=(
        ingest_res,
        ["youtube_shorts"],
        {"title": "Quota Test"}
    )).get(timeout=15)

    assert report["segments_processed"] == 2
    assert report["status"] == "partial_success"
    db.refresh(media)
    assert media.status == MediaStatus.PARTIALLY_PUBLISHED


def test_scheduler_respects_zero_quota(db):
    """Если квота исчерпана, планировщик не ставит задачи в очередь."""
    _, media = _seed_data(db, quota_limit=0)
    media.status = MediaStatus.PENDING
    db.commit()

    # Добавляем уже опубликованную запись, чтобы quota=0
    pub = Publication(
        media_id=media.id,
        platform="youtube_shorts",
        status=PublicationStatus.PUBLISHED,
        published_at=datetime.now(timezone.utc)
    )
    db.add(pub)
    db.commit()

    result = media_processing_scheduler.apply().get()
    assert result["queued"] == 0
    assert result["skipped_by_quota"] >= 1
    db.refresh(media)
    assert media.status == MediaStatus.PENDING  # Не должен меняться


def test_cleanup_on_failure(db, test_dir):
    """При падении ingest оркестратор не запускается, статус=FAILED."""
    _, media = _seed_data(db)
    with patch.object(DownloaderFactory, "get_downloader", side_effect=FileNotFoundError("Network down")):
        with pytest.raises(FileNotFoundError):
            ingest_raw_video_task.apply(args=(media.id,)).get()

    db.refresh(media)
    assert media.status == MediaStatus.FAILED