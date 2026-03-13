from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class MediaItemBase(BaseModel):
    source_id: int
    original_url: Optional[str] = None
    strategy_used: Optional[str] = None

class MediaItemCreate(MediaItemBase):
    pass

class MediaItemResponse(MediaItemBase):
    id: int
    s3_path: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class ScanResponse(BaseModel):
    source_id: int
    videos_found: int
    tasks_created: int
    media_items: Optional[list[MediaItemResponse]]