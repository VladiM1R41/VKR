"""Application settings for Layer 1."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from .env."""

    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")
    app_log_json: bool = Field(default=True, alias="APP_LOG_JSON")
    app_log_dir: str = Field(default="logs", alias="APP_LOG_DIR")

    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="jarvis", alias="POSTGRES_DB")
    postgres_user: str = Field(default="postgres", alias="POSTGRES_USER")
    postgres_password: str = Field(default="postgres", alias="POSTGRES_PASSWORD")

    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")

    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, alias="QDRANT_PORT")
    qdrant_collection_alias: str = Field(default="news_chunks", alias="QDRANT_COLLECTION_ALIAS")

    source_budget_seconds: int = Field(default=300, alias="SOURCE_BUDGET_SECONDS")
    source_lock_ttl_seconds: int = Field(default=600, alias="SOURCE_LOCK_TTL_SECONDS")
    scheduler_tick_seconds: int = Field(default=60, alias="SCHEDULER_TICK_SECONDS")
    crawl_jitter_ratio: float = Field(default=0.30, alias="CRAWL_JITTER_RATIO")
    processing_batch_size: int = Field(default=24, alias="PROCESSING_BATCH_SIZE")
    processing_tick_seconds: int = Field(default=120, alias="PROCESSING_TICK_SECONDS")
    processing_lock_ttl_seconds: int = Field(default=900, alias="PROCESSING_LOCK_TTL_SECONDS")
    processing_analytics_max_articles: int = Field(default=0, alias="PROCESSING_ANALYTICS_MAX_ARTICLES")
    processing_embedding_backend: str = Field(default="auto", alias="PROCESSING_EMBEDDING_BACKEND")
    celery_enable_layer4_schedule: bool = Field(default=False, alias="CELERY_ENABLE_LAYER4_SCHEDULE")

    jarvis_llm_provider: str = Field(default="gigachat", alias="JARVIS_LLM_PROVIDER")
    jarvis_llm_model: str = Field(default="gigachat-max", alias="JARVIS_LLM_MODEL")
    jarvis_llm_timeout_sec: float = Field(default=30.0, alias="JARVIS_LLM_TIMEOUT_SEC")
    jarvis_llm_retry_attempts: int = Field(default=2, alias="JARVIS_LLM_RETRY_ATTEMPTS")
    jarvis_llm_max_input_tokens: int = Field(default=20000, alias="JARVIS_LLM_MAX_INPUT_TOKENS")
    jarvis_llm_max_output_tokens: int = Field(default=1200, alias="JARVIS_LLM_MAX_OUTPUT_TOKENS")
    jarvis_llm_temperature: float = Field(default=0.2, alias="JARVIS_LLM_TEMPERATURE")
    jarvis_llm_fallback_provider: str = Field(default="", alias="JARVIS_LLM_FALLBACK_PROVIDER")
    jarvis_rag_mode: str = Field(default="standard", alias="JARVIS_RAG_MODE")
    jarvis_rag_enable_cache: bool = Field(default=True, alias="JARVIS_RAG_ENABLE_CACHE")
    jarvis_rag_streaming_enabled: bool = Field(default=False, alias="JARVIS_RAG_STREAMING_ENABLED")
    jarvis_tts_enabled: bool = Field(default=False, alias="JARVIS_TTS_ENABLED")
    gigachat_api_key: str | None = Field(default=None, alias="GIGACHAT_API_KEY")
    gigachat_auth_key: str | None = Field(default=None, alias="GIGACHAT_AUTH_KEY")
    gigachat_base_url: str | None = Field(default=None, alias="GIGACHAT_BASE_URL")
    gigachat_scope: str = Field(default="GIGACHAT_API_PERS", alias="GIGACHAT_SCOPE")
    gigachat_tls_verify: bool = Field(default=True, alias="GIGACHAT_TLS_VERIFY")
    gigachat_ca_bundle: str | None = Field(default=None, alias="GIGACHAT_CA_BUNDLE")
    yandexgpt_api_key: str | None = Field(default=None, alias="YandexGPT_API_KEY")
    yandexgpt_base_url: str | None = Field(default=None, alias="YandexGPT_BASE_URL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def validate_runtime_invariants(self) -> "Settings":
        if self.source_lock_ttl_seconds <= self.source_budget_seconds:
            raise ValueError(
                "SOURCE_LOCK_TTL_SECONDS must stay strictly above SOURCE_BUDGET_SECONDS."
            )
        if self.processing_batch_size <= 0:
            raise ValueError("PROCESSING_BATCH_SIZE must be positive.")
        if self.processing_tick_seconds <= 0:
            raise ValueError("PROCESSING_TICK_SECONDS must be positive.")
        if self.processing_lock_ttl_seconds <= 0:
            raise ValueError("PROCESSING_LOCK_TTL_SECONDS must be positive.")
        if self.processing_analytics_max_articles < 0:
            raise ValueError("PROCESSING_ANALYTICS_MAX_ARTICLES must be non-negative.")
        if self.processing_embedding_backend not in {"auto", "flagembedding", "sentence-transformers"}:
            raise ValueError(
                "PROCESSING_EMBEDDING_BACKEND must be one of: auto, flagembedding, sentence-transformers."
            )
        if self.jarvis_llm_timeout_sec <= 0:
            raise ValueError("JARVIS_LLM_TIMEOUT_SEC must be positive.")
        if self.jarvis_llm_retry_attempts < 0:
            raise ValueError("JARVIS_LLM_RETRY_ATTEMPTS must be non-negative.")
        if self.jarvis_llm_max_input_tokens <= 0:
            raise ValueError("JARVIS_LLM_MAX_INPUT_TOKENS must be positive.")
        if self.jarvis_llm_max_output_tokens <= 0:
            raise ValueError("JARVIS_LLM_MAX_OUTPUT_TOKENS must be positive.")
        if not 0.0 <= self.jarvis_llm_temperature <= 2.0:
            raise ValueError("JARVIS_LLM_TEMPERATURE must stay between 0.0 and 2.0.")
        if self.app_env.strip().lower() in {"prod", "production"} and not self.gigachat_tls_verify:
            raise ValueError("GIGACHAT_TLS_VERIFY cannot be disabled in production.")
        return self

    @property
    def sqlalchemy_async_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sqlalchemy_sync_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings object."""
    return Settings()
