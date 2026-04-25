from fastapi import FastAPI
from app.api.routes import sources, media
from app.modules.uploaders.youtube_auth import router as youtube_auth_router
from app.core.database import engine, Base
from app.models.publication import Publication
from app.worker.utils import ensure_bucket_exists


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Media Pipeline")

ensure_bucket_exists()

app.include_router(sources.router, tags=['sources'])
app.include_router(media.router, tags=['media'])
app.include_router(youtube_auth_router)
