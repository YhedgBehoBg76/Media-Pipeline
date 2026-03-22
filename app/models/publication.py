from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class PublicationStatus(enum.Enum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class Publication(Base):
    __tablename__ = "publications"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(Integer, ForeignKey("media_items.id"), nullable=False)
    platform = Column(String, nullable=False)  # "youtube_shorts", "tiktok"
    status = Column(Enum(PublicationStatus), default=PublicationStatus.PENDING)
    external_url = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    retry_count = Column(Integer, default=0)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())