from sqlalchemy import Column, Integer, String, Boolean

from app.core.database import Base


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    type = Column(String, nullable=False)  # youtube, filesystem, etc.
    config = Column(String, nullable=True)  # JSON настройки
    is_active = Column(Boolean, default=True)
    strategy = Column(String, default="simple_cut")