from fastapi import FastAPI
from app.api.routes import sources

app = FastAPI(title="Media Pipeline")
app.include_router(sources.router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "ok"}