from email.policy import default

from sqlalchemy import Column, Integer, String, DateTime, Enum
from sqlalchemy.sql import func

from app.core.database import Base

import enum


class Status(enum.Enum):
    PENDING = "pending"
    DOWNLOADED = "downloaded"
    PROCESSED = "processed"
    PUBLISHED = "published"
    FAILED = "failed"


class MediaItem(Base):
    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, nullable=False)
    original_url = Column(String, nullable=True)
    s3_path = Column(String, nullable=True)
    status = Column(Enum(Status), default=Status.PENDING)
    used_strategy = Column(String)
    created_at = Column(DateTime, server_default=func.now())