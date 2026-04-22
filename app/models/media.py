from email.policy import default

from sqlalchemy import Column, Integer, String, DateTime, Enum, JSON
from sqlalchemy.sql import func

from app.core.database import Base

import enum


class MediaStatus(enum.Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    SEGMENTING = "segmenting"
    SEGMENTED = "segmented"
    SOURCE = "source"
    PROCESSING = "processing"
    PROCESSED = "processed"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    PUBLISHING = "publishing"
    PARTIALLY_PUBLISHED = "partially_published"
    PUBLISHED = "published"
    FAILED = "failed"


class MediaItem(Base):
    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, default=0, index=True)
    external_id = Column(String, index=True)
    source_id = Column(Integer, nullable=False)
    original_url = Column(String, nullable=True)
    s3_path = Column(String, nullable=True)
    local_path = Column(String)
    status = Column(Enum(MediaStatus), default=MediaStatus.PENDING)
    used_strategy = Column(String)
    video_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
