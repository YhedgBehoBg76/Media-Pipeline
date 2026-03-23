
import json
from importlib.metadata import metadata
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.models.publication import Publication, PublicationStatus
from app.worker.tasks import process_media_pipeline
from app.core.database import get_db
from app.models.media import MediaItem, MediaStatus
from app.models.sources import Source
from app.modules.sources.adapter_factory import SourceAdapterFactory
from app.schemas.media import ScanResponse, MediaItemResponse
from app.schemas.source import SourceResponse, SourceCreate


router = APIRouter()


@router.get("/sources/available-types")
def get_available_source_types():
    """Возвращает список поддерживаемых типов источников"""
    return {
        "available_types": SourceAdapterFactory.get_available_types()
    }


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    return db.query(Source).all()


@router.post("/sources/{source_id}/scan", response_model=ScanResponse)
def scan_source(source_id: int, db: Session = Depends(get_db)):
    source = db.query(Source).filter(Source.id == source_id).first()

    if not source:
        raise HTTPException(status_code=404, detail="source not found")
    if not source.is_active:
        raise HTTPException(status_code=400, detail="source is not active")

    try:
        adapter = SourceAdapterFactory.get_adapter(source.type)

        if hasattr(adapter, '_db_session'):
            adapter._db_session = db

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    config = source.config if source.config else {}

    def on_state_update(state:dict):
        config.update(state)
        source.config = json.dumps(config)
        db.commit()

    if hasattr(adapter, '_on_state_update'):
        adapter._on_state_update = on_state_update

    if not adapter.validate_config(config):
        raise HTTPException(
            status_code=400,
            detail="Invalid source configuration"
        )

    videos = adapter.get_new_content(config)

    created_items: List[MediaItem] = []
    for video in videos:
        media_item = MediaItem(
            external_id=video['external_id'],
            source_id=source.id,
            original_url=video['url'],
            status=MediaStatus.PENDING,
            used_strategy=source.strategy,
            video_metadata=video["metadata"]
        )

        db.add(media_item)
        db.commit()
        db.refresh(media_item)

        for platform in source.publishers:
            publication = Publication(
                media_id=media_item.id,
                platform=platform,
                status=PublicationStatus.PENDING
            )
            db.add(publication)

        db.commit()

        created_items.append(media_item)
        process_media_pipeline.delay(media_item.id)


    return {
        "source_id": source_id,
        "videos_found": len(videos),
        "tasks_created": len(created_items),
        "media_items": created_items
    }


@router.post("/sources", response_model=SourceResponse)
def create_source(source: SourceCreate, db: Session = Depends(get_db)):
    # Создание нового источника
    config_json = source.config if source.config else None

    db_source = Source(
        type=source.type,
        config=config_json,
        strategy=source.strategy,
        is_active=source.is_active,
        publishers=source.publishers
    )

    db.add(db_source)
    db.commit()
    db.refresh(db_source)

    return db_source
