from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Index
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
    platform = Column(String, nullable=False)
    status = Column(Enum(PublicationStatus), default=PublicationStatus.PENDING)
    external_url = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    retry_count = Column(Integer, default=0)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('idx_publication_platform_status', 'platform', 'status'),
        Index('idx_publication_media_status', 'media_id', 'status'),
        Index('idx_publication_published_at', 'published_at'),
    )