from fastapi import FastAPI
from app.api.routes import sources, media
from app.core.database import engine, Base


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Media Pipeline")

app.include_router(sources.router, tags=['sources'])
app.include_router(media.router, tags=['media'])