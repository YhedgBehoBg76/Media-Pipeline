from sqlalchemy import Column, Integer, String, Boolean, JSON
from app.core.database import Base
from app.core.types import JSONString

class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    type = Column(String, nullable=False)  # youtube, filesystem, etc.
    config = Column(JSONString, nullable=True)  # JSON настройки
    is_active = Column(Boolean, default=True)
    strategy = Column(JSON, default="simple_cut")
    publishers = Column(JSON, default="youtube_shorts")