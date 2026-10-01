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

    # CORS & Security Headers
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]
    ENABLE_SECURITY_HEADERS: bool = True
    HSTS_ENABLED: bool = False
    CONTENT_SECURITY_POLICY: str = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; img-src 'self' data: https:; "
        "connect-src 'self' http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*"
    )
    ENABLE_DOCS: bool = True

    # Request Size & Upload Limits
    MAX_REQUEST_BODY_SIZE: int = 10 * 1024 * 1024  # 10 MB
    MAX_FILE_UPLOAD_SIZE: int = 10 * 1024 * 1024   # 10 MB
    ALLOWED_UPLOAD_EXTENSIONS: set[str] = {".pdf", ".md", ".txt", ".json"}
    ALLOWED_UPLOAD_MIME_TYPES: set[str] = {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "application/json",
        "application/octet-stream",  # often sent by generic clients for text/md
    }

    # API Rate Limiting Configuration (Per Minute)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: int = 100
    RATE_LIMIT_AUTH: int = 10
    RATE_LIMIT_AI: int = 20
    RATE_LIMIT_UPLOAD: int = 10

    # LLM Provider Configuration (Groq)
    GROQ_API_KEY: str = Field(default="", description="Groq API key")
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # RAG & Embedding Settings
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSION: int = 384
    RERANKER_MODEL_NAME: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    RAG_TOP_K: int = 5
    CONFIDENCE_THRESHOLD: float = 0.75
    MAX_AI_INPUT_CHARS: int = 4000
    MAX_GRAPH_STEPS: int = 15

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS allowed origins normalized as a list."""
        if isinstance(self.CORS_ORIGINS, str):
            return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        return self.CORS_ORIGINS


# Global singleton settings instance
settings = Settings()
