from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.config import settings
from src.api.db import Base, engine
# Import models so SQLAlchemy metadata is populated before create_all
from src.api import models as _models  # noqa: F401

app = FastAPI(
    title="Delivery Tracker API",
    description="Backend API for the Delivery Tracker application.",
    version="0.1.0",
    openapi_tags=[
        {"name": "Health", "description": "Service health and readiness endpoints"},
    ],
)

# Configure CORS based on environment settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database metadata (now with models imported)
def init_db() -> None:
    """Create database tables based on SQLAlchemy models.

    This imports the ORM models module to ensure Base.metadata is populated,
    then creates tables on the configured database engine.
    """
    Base.metadata.create_all(bind=engine)


# Run DB initialization at import time to ensure tables exist in simple deployments
init_db()


@app.get("/", tags=["Health"], summary="Health Check")
def health_check():
    """Health check endpoint.

    Returns:
        dict: JSON payload indicating service status.
    """
    return {"message": "Healthy"}
