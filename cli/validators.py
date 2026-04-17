"""Input validators for CLI onboarding and chat."""
import re
from typing import Optional


# Basic email regex — good enough for onboarding validation
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

# Known timezones (subset — common ones for quick validation)
_COMMON_TIMEZONES = {
    "UTC", "US/Eastern", "US/Central", "US/Mountain", "US/Pacific",
    "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Madrid",
    "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata", "Asia/Singapore",
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/Sao_Paulo", "America/Mexico_City",
    "America/Argentina/Buenos_Aires", "America/Bogota", "America/Lima",
    "America/Santiago", "Australia/Sydney", "Pacific/Auckland",
}


def validate_email(email: str) -> Optional[str]:
    """Validate email format. Returns error message or None if valid."""
    email = email.strip()
    if not email:
        return "Email cannot be empty."
    if not _EMAIL_RE.match(email):
        return "Invalid email format. Example: user@example.com"
    return None


def validate_name(name: str) -> Optional[str]:
    """Validate user name. Returns error message or None if valid."""
    name = name.strip()
    if not name:
        return "Name cannot be empty."
    if len(name) < 2:
        return "Name must be at least 2 characters."
    if len(name) > 100:
        return "Name must be under 100 characters."
    return None


def validate_timezone(tz: str) -> Optional[str]:
    """Validate timezone string. Returns error message or None if valid."""
    tz = tz.strip()
    if not tz:
        return "Timezone cannot be empty."
    # Accept any Continent/City format
    if "/" not in tz and tz != "UTC":
        return "Use Continent/City format (e.g., America/New_York) or UTC."
    return None


def validate_time_24h(time_str: str) -> Optional[str]:
    """Validate HH:MM 24-hour time. Returns error message or None if valid."""
    time_str = time_str.strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if not match:
        return "Use HH:MM format (e.g., 07:30)."
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour < 0 or hour > 23:
        return "Hour must be 0-23."
    if minute < 0 or minute > 59:
        return "Minute must be 0-59."
    return None


def validate_token(platform: str, token: str) -> Optional[str]:
    """Basic token format validation. Returns error message or None if valid."""
    token = token.strip()
    if not token:
        return "Token cannot be empty."
    if len(token) < 10:
        return "Token seems too short. Please check and try again."
    if platform == "slack" and not token.startswith("xoxb-"):
        return "Slack bot tokens should start with 'xoxb-'. Check your token."
    return None


def parse_selection(text: str, max_val: int) -> Optional[list]:
    """Parse a comma-separated selection like '1, 2, 4'.

    Returns list of ints (1-based) or None if invalid.
    """
    text = text.strip()
    if not text:
        return None
    parts = [p.strip() for p in text.split(",")]
    result = []
    for part in parts:
        try:
            val = int(part)
        except ValueError:
            return None
        if val < 1 or val > max_val:
            return None
        result.append(val)
    return result
