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
    llm_sub_agent_model: str = ""   # if empty, uses llm_model
    llm_sub_agent_api_key: str = "" # if empty, uses llm_api_key

    # CORS
    cors_origins: str = ""  # comma-separated list of allowed origins

    # Sync scheduler (only enable in production or explicitly)
    enable_sync_scheduler: bool = False

    # Microsoft MSAL — used to auto-refresh Graph API tokens (Outlook + Teams)
    ms_client_id: str = ""
    ms_authority: str = ""
    ms_scopes: str = "https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Calendars.Read https://graph.microsoft.com/Chat.Read https://graph.microsoft.com/User.Read"
    msal_cache_path: str = ""  # defaults to ~/.secondbrain/msal_cache.json if empty

    # Security — required for token encryption
    fernet_key: str

    # Voice interface
    stt_mode: str = "api"           # "local" | "api"
    whisper_model: str = "base"     # tiny | base | small | medium | large
    tts_voice: str = "nova"         # alloy | echo | fable | onyx | nova | shimmer
    tts_model: str = "tts-1"        # tts-1 | tts-1-hd
    voice_max_audio_mb: int = 25

    # Portal login (voice UI)
    portal_password: str = ""       # if empty, login is disabled in production

    # Agent built-in tools (Strands) — both opt-in, disabled unless configured
    brave_search_api_key: str = ""            # if empty, web_search tool is not registered
    http_request_allowed_domains: str = ""    # comma-separated exact hostnames; empty = http_request tool disabled

    # I+D platform MCP (Phase 6 knowledge domain agent) — opt-in, disabled unless configured
    id_brain_mcp_url: str = ""
    id_brain_mcp_api_key: str = ""

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
    return Settings()  # type: ignore[call-arg]  # pydantic-settings reads from env
