from pydantic import BaseModel
from typing import Optional, Dict, Any


class SourceBase(BaseModel):
    type: str
    config: Optional[Dict[str, Any]] = None
    strategy: str = "simple_cut"
    is_active: bool = True

class SourceCreate(SourceBase):
    pass

class SourceResponse(SourceBase):
    id: int

    class Config:
        from_attributes = True