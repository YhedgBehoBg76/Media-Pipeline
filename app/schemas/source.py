from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any


class SourceBase(BaseModel):
    type: str = Field(..., description="Type of source(e.g. youtube, twich, ...)")
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Source configuration(JSON. e.g.: query, max_requests, ...)"
    )
    publishers: List[str] = Field(
        default=None,
        description="Publishers list(e.g.: youtube_shorts, ...)"
    )
    strategy: str = Field(default="simple_cut", description="Video processing strategy")
    is_active: bool = Field(default=True, description="Is source active")

class SourceCreate(SourceBase):
    pass

class SourceResponse(SourceBase):
    id: int

    class Config:
        from_attributes = True

