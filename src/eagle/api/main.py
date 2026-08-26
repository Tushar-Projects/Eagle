from fastapi import FastAPI
from eagle.core.config import settings

app = FastAPI(title="Eagle AI Finance Controller")

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "provider": settings.MODEL_PROVIDER
    }
