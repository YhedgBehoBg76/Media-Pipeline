import os
import json
import pytest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.media import MediaItem, MediaStatus
from app.models.sources import Source
from app.models.publication import Publication, PublicationStatus
from app.worker.tasks import ingest_raw_video_task, run_media_orchestrator, media_processing_scheduler
from app.services.media_orchestrator import MediaProcessingOrchestrator

# ==============================================================================
# ENV & CONFIG
# ==============================================================================
os.environ["S3_BUCKET"] = "test-bucket"
os.environ["S3_ENDPOINT"] = "http://localhost:9000"
os.environ["S3_ACCESS_KEY"] = "test"
os.environ["S3_SECRET_KEY"] = "test"
os.environ["RABBITMQ_URL"] = "memory://"

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


# ==============================================================================
# FIXTURES
# ==============================================================================
@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine("sqlite:///:memory:")
    from app.models.media import Base as MediaBase
    # Регистрируем все модели
    import app.models.sources
    import app.models.publication
    MediaBase.metadata.create_all(bind=engine)
    yield engine
    MediaBase.metadata.drop_all(bind=engine)


@pytest.fixture
def db(test_engine):
    TestingSessionLocal = sessionmaker(bind=test_engine)
    session = TestingSessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def test_dir(tmp_path):
    d = tmp_path / "media_test"
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def mock_dependencies(test_dir, db):
    db.close = MagicMock()

    with \
        patch.object(MediaProcessingOrchestrator, "_load_config", return_value=TEST_CONFIG), \
        patch("app.worker.tasks.SessionLocal", return_value=db), \
        patch.object(MediaProcessingOrchestrator, "_init_s3_client", return_value=MagicMock()), \
        patch.object(MediaProcessingOrchestrator, "_download_from_s3", side_effect=lambda k, d: Path(d).write_bytes(b"fake")), \
        patch("app.worker.tasks.DownloaderFactory.get_downloader") as mock_dl, \
        patch("app.worker.tasks.UploaderFactory.get_uploader") as mock_ul, \
        patch("app.services.media_orchestrator.ProcessorFactory.get_processor") as mock_proc, \
        patch("app.services.media_orchestrator.FixedDurationSegmenter.split") as mock_split:

        # Мокаем сегментер: создаёт реальные dummy-файлы и уважает max_segments
        def fake_segment_split(input_path, params):
            max_seg = params.get("max_segments")
            count = max_seg if max_seg else 3  # по умолчанию 3 сегмента
            segs = []
            for i in range(count):
                p = test_dir / f"seg_{i:02d}.mp4"
                p.write_bytes(b"fake segment content")
                segs.append(str(p))
            return segs
        mock_split.side_effect = fake_segment_split

        def fake_dl_download(media):
            p = test_dir / f"raw_{media.id}.mp4"
            p.write_bytes(b"fake content")
            return str(p)
        mock_dl.return_value.download.side_effect = fake_dl_download

        mock_ul_inst = MagicMock()
        mock_ul_inst.upload.side_effect = lambda file_path, params=None: f"processed/{Path(file_path).name}"
        mock_ul.return_value = mock_ul_inst

        mock_proc_inst = MagicMock()
        mock_proc_inst.process.side_effect = lambda i, o, p: Path(o).write_bytes(Path(i).read_bytes())
        mock_proc.return_value = mock_proc_inst

        yield


# ==============================================================================
# HELPERS
# ==============================================================================
def _seed_data(db, quota_limit=None):
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
        external_id=f"vid_{db.query(MediaItem).count()}",
        source_id=source.id,
        original_url="https://fake.url/video.mp4",
        status=MediaStatus.PENDING,
        used_strategy=json.dumps(["simple_cut"]),
        video_metadata=json.dumps({"title": "Test Video"})
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    if quota_limit is not None:
        TEST_CONFIG["youtube_shorts"]["quotas"]["daily_limit"] = quota_limit

    return source, media


# ==============================================================================
# TESTS
# ==============================================================================
def test_full_happy_path(db, test_dir):
    _, media = _seed_data(db, quota_limit=10)
    assert media.status == MediaStatus.PENDING

    ingest_result = ingest_raw_video_task.apply(args=(media.id,)).get(timeout=10)
    assert "s3_path" in ingest_result

    media = db.query(MediaItem).filter(MediaItem.id == media.id).first()
    assert media.status == MediaStatus.UPLOADED

    report = run_media_orchestrator.apply(args=(
        ingest_result, ["youtube_shorts", "s3"], {"title": "Test"}
    )).get(timeout=15)

    assert report["status"] == "success"
    media = db.query(MediaItem).filter(MediaItem.id == media.id).first()
    assert media.status == MediaStatus.PUBLISHED


def test_quota_limits_segmentation(db, test_dir):
    _, media = _seed_data(db, quota_limit=2)
    ingest_res = ingest_raw_video_task.apply(args=(media.id,)).get(timeout=10)

    # Форсируем возврат квоты=2 из оркестратора
    with patch.object(MediaProcessingOrchestrator, "_get_remaining_quota", return_value=2):
        report = run_media_orchestrator.apply(args=(
            ingest_res, ["youtube_shorts"], {"title": "Quota Test"}
        )).get(timeout=15)

    assert report["segments_processed"] == 2
    assert report["status"] == "success"


def test_scheduler_respects_zero_quota(db, test_dir):
    _, media = _seed_data(db, quota_limit=0)
    media.status = MediaStatus.PENDING
    db.commit()

    db.add(Publication(
        media_id=media.id, platform="youtube_shorts",
        status=PublicationStatus.PUBLISHED,
        published_at=datetime.now(timezone.utc)
    ))
    db.commit()

    result = media_processing_scheduler.apply().get()
    assert result["queued"] == 0
    assert result["skipped_by_quota"] >= 1

    media = db.query(MediaItem).filter(MediaItem.id == media.id).first()
    assert media.status == MediaStatus.PENDING


def test_cleanup_on_failure(db, test_dir):
    _, media = _seed_data(db)
    with patch("app.worker.tasks.DownloaderFactory.get_downloader", side_effect=FileNotFoundError("Net")):
        with pytest.raises(FileNotFoundError):
            ingest_raw_video_task.apply(args=(media.id,)).get()

    media = db.query(MediaItem).filter(MediaItem.id == media.id).first()
    assert media.status == MediaStatus.FAILED