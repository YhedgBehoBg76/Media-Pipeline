
from app.models.media import MediaItem
from app.core.database import get_db
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends


router = APIRouter()

@router.get("/media/")
def get_all_media_items(db: Session = Depends(get_db)):
    media = db.query(MediaItem).first()

    return media