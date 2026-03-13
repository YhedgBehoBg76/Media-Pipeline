
from app.models.media import MediaItem
from app.core.database import get_db
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends


router = APIRouter()

@router.get("/media/")
def get_downloaded_media(media_id: int, db: Session = Depends(get_db)):
    media = db.query(MediaItem).filter(MediaItem.id == media_id).first()

    return {
        "url": media.original_url,
    }