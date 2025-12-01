import os
from typing import List

from pydantic import BaseModel, Field
from dotenv import load_dotenv


class Settings(BaseModel):
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = Field(..., description="SQLAlchemy database URL string")

    # Auth
    JWT_SECRET: str = Field(..., description="Secret used for signing JWT tokens")
    JWT_EXPIRES_MIN: int = Field(
        60, description="JWT expiration time in minutes", ge=1
    )

    # CORS
    CORS_ORIGINS: List[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="List of allowed CORS origins",
    )

    # Server
    PORT: int = Field(3001, description="Application port")

    # PUBLIC_INTERFACE
    @staticmethod
    def load() -> "Settings":
        """Load environment variables and return a Settings instance.

        This function loads .env (if present) and reads environment variables to build
        a Settings object. It supports comma-separated CORS origins.

        Behavior:
        - If DATABASE_URL is not set or empty, falls back to a safe local default suitable
          for development: postgresql://appuser:dbuser123@localhost:5000/myapp
        - JWT_SECRET defaults to empty string; downstream code should validate on use.
        """
        load_dotenv()  # loads .env into environment if present

        cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
        cors_list = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]

        # Provide safe default for local dev when env is missing
        default_db = "postgresql://appuser:dbuser123@localhost:5000/myapp"

        # Build settings from environment variables
        values = {
            "DATABASE_URL": os.getenv("DATABASE_URL") or default_db,
            "JWT_SECRET": os.getenv("JWT_SECRET", ""),
            "JWT_EXPIRES_MIN": int(os.getenv("JWT_EXPIRES_MIN", "60")),
            "CORS_ORIGINS": cors_list,
            "PORT": int(os.getenv("PORT", "3001")),
        }

        # Validate using Pydantic
        return Settings(**values)

    # PUBLIC_INTERFACE
    def has_valid_database_url(self) -> bool:
        """Return True if DATABASE_URL looks non-empty and with a scheme."""
        return isinstance(self.DATABASE_URL, str) and "://" in self.DATABASE_URL and len(self.DATABASE_URL.strip()) > 0


# Singleton-like settings instance for app modules to import safely.
settings = Settings.load()
