import uuid
from datetime import datetime
from typing import Optional

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
        import pytz
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
