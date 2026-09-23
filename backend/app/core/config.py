from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings validated using Pydantic Settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application Information
    APP_NAME: str = "SupportFlow AI"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Database Configuration (PostgreSQL 16 + pgvector)
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5434
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "supportflow_db"
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5434/supportflow_db"
    )
    TEST_DATABASE_URL: Optional[str] = None

    @property
    def async_test_database_url(self) -> str:
        """Isolated database URL for automated testing.

        Ensures test suites never connect to or mutate the development database.
        Defaults to 'supportflow_test_db' on the same PostgreSQL host/port.
        """
        if self.TEST_DATABASE_URL:
            return self.TEST_DATABASE_URL
        return self.DATABASE_URL.rsplit("/", 1)[0] + "/supportflow_test_db"

    # Redis Configuration
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security & JWT Tokens
    JWT_SECRET_KEY: str = (
        "change-this-to-a-secure-random-secret-key-in-production-min-32-chars"
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # LLM Provider Configuration (Groq)
    GROQ_API_KEY: str = Field(default="", description="Groq API key")
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # RAG & Embedding Settings
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384
    RERANKER_MODEL_NAME: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    RAG_TOP_K: int = 5
    CONFIDENCE_THRESHOLD: float = 0.75


# Global singleton settings instance
settings = Settings()
