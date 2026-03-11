from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.sources import Source

router = APIRouter()

@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    return db.query(Source).all()

@router.post("/sources")
def create_source(source: dict, db: Session = Depends(get_db)):
    # Создание нового источника
    new_source = Source(**source)
    db.add(new_source)
    db.commit()
    return new_source