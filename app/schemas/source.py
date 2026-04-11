from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any


class SourceBase(BaseModel):
    type: str = Field(..., description="Type of source (e.g. youtube, filesystem, ...)")
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Source configuration (JSON. e.g.: query, max_requests, ...)"
    )
    publishers: List[str] = Field(
        default_factory=list,
        description="Publishers list (e.g.: youtube_shorts, ...)"
    )
    strategy: List[str] = Field(
        default_factory=lambda: ["simple_cut"],
        description="Video processing strategy (JSON array of steps)"
    )
    is_active: bool = Field(default=True, description="Is source active")

class SourceCreate(SourceBase):
    pass

class SourceResponse(SourceBase):
    id: int

    class Config:
        from_attributes = True

