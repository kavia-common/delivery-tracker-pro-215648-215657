from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load settings early to ensure .env is processed before any DB work.
# Settings.load() is side-effect free for DB and only reads environment.
from src.api.config import settings

app = FastAPI(
    title="Delivery Tracker API",
    description="Backend API for the Delivery Tracker application.",
    version="0.1.0",
    openapi_tags=[
        {"name": "Health", "description": "Service health and readiness endpoints"},
        {"name": "Auth", "description": "Authentication and user identity endpoints"},
        {"name": "Deliveries", "description": "CRUD, status, and location tracking for deliveries"},
        {"name": "History", "description": "Historical queries for deliveries and status events with filters"},
        {"name": "Notifications", "description": "Notification listing and read acknowledgements"},
        {"name": "Realtime", "description": "WebSocket endpoints for realtime updates and notifications"},
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

# Import after app is created to avoid import-time DB initialization.
# db.get_engine() defers actual engine creation until called at runtime.
from src.api.db import Base, get_engine  # noqa: E402
from src.api import models as _models  # noqa: F401, E402
from src.api.auth import router as auth_router  # noqa: E402
from src.api.deliveries import router as deliveries_router  # noqa: E402
from src.api.history import router as history_router  # noqa: E402
from src.api.notifications import router as notifications_router  # noqa: E402
from src.api.realtime import router as realtime_router, get_ws_usage_help  # noqa: E402
from src.api.seed import run_startup_seed  # noqa: E402

def _init_db() -> None:
    """Create database tables based on SQLAlchemy models.

    This ensures Base.metadata is populated by importing models, then creates
    tables on the configured database engine. Errors are raised with concise messages.
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


@app.on_event("startup")
def on_startup() -> None:
    """Application startup hook to initialize the database and perform seeding.

    Notes:
        - If DATABASE_URL is empty or malformed, get_engine() will raise a RuntimeError.
        - Ensure a valid .env or environment variables are set before starting the app.
    """
    try:
        _init_db()
        # Open a short-lived session for seeding to keep things simple and isolated
        from sqlalchemy.orm import Session
        from src.api.db import get_engine as _get_engine, sessionmaker as _sessionmaker  # type: ignore

        # Create a temporary sessionmaker bound to the existing engine (no globals mutated)
        engine = _get_engine()
        LocalSession = _sessionmaker(bind=engine, autoflush=False, autocommit=False)  # type: ignore
        with LocalSession() as db:  # type: ignore
            assert isinstance(db, Session)
            run_startup_seed(db)
    except RuntimeError as exc:
        # Provide a concise log-friendly error; let process exit gracefully
        # by re-raising for the server to handle.
        # In production you might integrate a structured logger here.
        raise RuntimeError(f"Startup failed: {exc}") from exc

# Register routers
app.include_router(auth_router)
app.include_router(deliveries_router)
app.include_router(history_router)
app.include_router(notifications_router)
app.include_router(realtime_router)

@app.get("/", tags=["Health"], summary="Health Check")
def health_check():
    """Health check endpoint.

    Returns:
        dict: JSON payload indicating service status.
    """
    return {"message": "Healthy"}

@app.get(
    "/realtime",
    tags=["Realtime"],
    summary="WebSocket usage help",
    description="Describe how to connect to the WebSocket endpoints for realtime features.",
)
def realtime_help() -> dict:
    """Return information on connecting to WebSocket endpoints and expected messages."""
    return get_ws_usage_help()
