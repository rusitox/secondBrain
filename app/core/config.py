from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_name: str = "Digital Twin API"
    app_env: str = "development"
    debug: bool = False

    # Database — required, no defaults with credentials
    database_url: str
    database_url_sync: str

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # AI Models
    openai_api_key: str = ""
    llm_api_key: str = ""
    llm_model: str = "anthropic/claude-haiku-4-5-20251001"

    # CORS
    cors_origins: str = ""  # comma-separated list of allowed origins

    # Sync scheduler (only enable in production or explicitly)
    enable_sync_scheduler: bool = False

    # Security — required for token encryption
    fernet_key: str

    @field_validator("fernet_key")
    @classmethod
    def validate_fernet_key(cls, v: str) -> str:
        if not v or len(v) < 32:
            raise ValueError(
                "FERNET_KEY must be a valid Fernet key (44 url-safe base64 chars). "
                "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
