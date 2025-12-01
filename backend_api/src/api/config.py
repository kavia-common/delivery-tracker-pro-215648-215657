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
        """
        load_dotenv()  # loads .env into environment if present

        cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
        cors_list = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]

        # Build settings from environment variables
        values = {
            "DATABASE_URL": os.getenv("DATABASE_URL", ""),
            "JWT_SECRET": os.getenv("JWT_SECRET", ""),
            "JWT_EXPIRES_MIN": int(os.getenv("JWT_EXPIRES_MIN", "60")),
            "CORS_ORIGINS": cors_list,
            "PORT": int(os.getenv("PORT", "3001")),
        }

        # Validate using Pydantic
        return Settings(**values)


# Singleton-like settings instance for app modules to import safely.
settings = Settings.load()
