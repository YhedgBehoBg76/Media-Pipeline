from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


#TODO: сделать отдельные схемы config для разных типов источников
#  и убрать метод validate_config из SourceAdapter

class SourceBase(BaseModel):
    type: str = Field(..., description="Type of source(e.g. youtube, twich, ...)")
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Source configuration(JSON. e.g.: query, max_requests, ...)"
    )
    strategy: str = Field(default="simple_cut", description="Video processing strategy")
    is_active: bool = Field(default=True, description="Is source active")

class SourceCreate(SourceBase):
    pass

class SourceResponse(SourceBase):
    id: int

    class Config:
        from_attributes = True

