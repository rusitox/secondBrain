import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, EmailStr, field_validator

# Valid IANA timezones subset for Python 3.8 compatibility
# Full validation would use pytz.all_timezones, but we keep it simple
_COMMON_TIMEZONES = {
    "UTC", "US/Eastern", "US/Central", "US/Mountain", "US/Pacific",
    "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Madrid",
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Sao_Paulo", "America/Argentina/Buenos_Aires", "America/Mexico_City",
    "America/Bogota", "America/Lima", "America/Santiago",
    "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata", "Asia/Dubai",
    "Australia/Sydney", "Pacific/Auckland",
}


def _is_valid_timezone(tz: str) -> bool:
    """Check timezone validity using pytz if available, else fallback to common list."""
    try:
        import pytz  # type: ignore[import-untyped]
        return tz in pytz.all_timezones
    except ImportError:
        return tz in _COMMON_TIMEZONES


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        if not _is_valid_timezone(v):
            raise ValueError(f"Invalid timezone: '{v}'")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    timezone: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _is_valid_timezone(v):
            raise ValueError(f"Invalid timezone: '{v}'")
        return v


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    timezone: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Onboarding ---

class OnboardingState(BaseModel):
    step: int
    completed: bool


class OnboardingUpdate(BaseModel):
    step: Optional[int] = None
    completed: Optional[bool] = None

    @field_validator("step")
    @classmethod
    def validate_step(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 0 or v > 10):
            raise ValueError("step must be between 0 and 10")
        return v


# --- Preferences ---

class UserPreferencesResponse(BaseModel):
    preferences: Dict[str, Any]
    onboarding: OnboardingState
    notion_config: Optional[Dict[str, Any]] = None


class UserPreferencesUpdate(BaseModel):
    """Partial update — merges into existing preferences."""
    preferences: Dict[str, Any]


# --- Notion Config ---

class NotionConfigResponse(BaseModel):
    """Notion workspace config response."""
    config: Optional[Dict[str, Any]] = None


class NotionConfigUpdate(BaseModel):
    """Replace entire Notion config."""
    config: Optional[Dict[str, Any]] = None
