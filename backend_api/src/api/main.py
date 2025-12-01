from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load settings early to ensure .env is processed before any DB work
from src.api.config import settings

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

# Import after app is created to avoid import-time DB initialization
from src.api.db import Base, get_engine  # noqa: E402
from src.api import models as _models  # noqa: F401, E402


def _init_db() -> None:
    """Create database tables based on SQLAlchemy models.

    This ensures Base.metadata is populated by importing models, then creates
    tables on the configured database engine. Errors are raised with concise messages.
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


@app.on_event("startup")
def on_startup() -> None:
    """Application startup hook to initialize the database."""
    try:
        _init_db()
    except RuntimeError as exc:
        # Provide a concise log-friendly error; let process exit gracefully
        # by re-raising for the server to handle.
        # In production you might integrate a structured logger here.
        raise RuntimeError(f"Startup failed: {exc}") from exc


@app.get("/", tags=["Health"], summary="Health Check")
def health_check():
    """Health check endpoint.

    Returns:
        dict: JSON payload indicating service status.
    """
    return {"message": "Healthy"}
