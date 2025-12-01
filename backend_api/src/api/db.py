from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base

from src.api.config import settings

# SQLAlchemy base for models to inherit
Base = declarative_base()

# Lazily created engine and sessionmaker to avoid crashing at import time
_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _ensure_engine_initialized() -> None:
    """Create the global SQLAlchemy engine and session factory if not initialized.

    This performs runtime validation of the DATABASE_URL and avoids creating an engine
    on module import. It raises a concise RuntimeError if configuration is invalid.
    """
    global _engine, _SessionLocal
    if _engine is not None and _SessionLocal is not None:
        return

    db_url = (settings.DATABASE_URL or "").strip()
    if not db_url or "://" not in db_url:
        raise RuntimeError(
            "Invalid configuration: DATABASE_URL is not set or malformed. "
            "Provide a valid SQLAlchemy URL via environment or .env."
        )

    _engine = create_engine(db_url, pool_pre_ping=True)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


# PUBLIC_INTERFACE
def get_engine() -> Engine:
    """Get or create the SQLAlchemy Engine.

    Returns:
        Engine: The initialized SQLAlchemy engine.

    Raises:
        RuntimeError: If DATABASE_URL is missing or malformed.
    """
    _ensure_engine_initialized()
    assert _engine is not None  # for type checkers
    return _engine


# PUBLIC_INTERFACE
def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a SQLAlchemy session.

    Yields:
        Session: SQLAlchemy session bound to the configured engine.
    Ensures:
        Session is closed after request is handled.
    """
    _ensure_engine_initialized()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
