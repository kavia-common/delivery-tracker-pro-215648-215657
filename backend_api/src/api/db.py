from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base

from src.api.config import settings

# SQLAlchemy base for models to inherit
Base = declarative_base()

# Create SQLAlchemy Engine and SessionLocal (synchronous)
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# PUBLIC_INTERFACE
def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a SQLAlchemy session.

    Yields:
        Session: SQLAlchemy session bound to the configured engine.
    Ensures:
        Session is closed after request is handled.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
