"""Text cleaning by source type.

Removes noise (signatures, boilerplate, headers) to improve
embedding quality and reduce token waste.
"""
import re
import logging
from typing import Callable, Dict, List, Pattern

logger = logging.getLogger(__name__)

# Email signature patterns (common separators)
_EMAIL_SIG_PATTERNS: List[Pattern] = [
    re.compile(r"\n--\s*\n.*", re.DOTALL),                  # "-- \n" separator
    re.compile(r"\nSent from my (?:iPhone|iPad|Android).*", re.DOTALL),
    re.compile(r"\nGet Outlook for (?:iOS|Android).*", re.DOTALL),
    re.compile(r"\n_{3,}\n.*", re.DOTALL),                   # ___ separator
]

# Email reply headers
_EMAIL_REPLY_PATTERNS: List[Pattern] = [
    re.compile(r"\nOn .+ wrote:\s*\n.*", re.DOTALL),        # "On Mon, ... wrote:"
    re.compile(r"\nFrom: .+\nSent: .+\nTo: .+\n.*", re.DOTALL),  # Outlook reply headers
    re.compile(r"\n-{3,} ?Original Message ?-{3,}\n.*", re.DOTALL),
]

# Slack boilerplate (ordered: URL-with-label first, then plain URL, then others)
_SLACK_URL_LABEL = re.compile(r"<https?://[^|>]+\|([^>]+)>")  # <url|label> → label
_SLACK_URL_PLAIN = re.compile(r"<(https?://[^>]+)>")           # <url> → url text
_SLACK_REMOVE_PATTERNS: List[Pattern] = [
    re.compile(r"<@[A-Z0-9]+>"),                               # user mentions
    re.compile(r"<!channel>|<!here>|<!everyone>"),              # broadcast mentions
    re.compile(r":\w+:"),                                       # :emoji: codes
]

# Teams boilerplate
_TEAMS_PATTERNS: List[Pattern] = [
    re.compile(r"<attachment[^>]*>.*?</attachment>", re.DOTALL),
    re.compile(r"<systemEventMessage[^>]*>.*?</systemEventMessage>", re.DOTALL),
    re.compile(r"\[Meeting\] .+ has (joined|left).*\n?"),
]

# Notion block artifacts (block IDs are already excluded by blocks_to_text;
# only whitespace normalization is needed here)
_NOTION_PATTERNS: List[Pattern] = [
    re.compile(r"\n{3,}"),  # excessive newlines from block conversion
]

# Fathom transcript patterns
_FATHOM_PATTERNS: List[Pattern] = [
    re.compile(r"^\d{2}:\d{2}:\d{2}\.\d+ --> \d{2}:\d{2}:\d{2}\.\d+\s*\n", re.MULTILINE),
    re.compile(r"^WEBVTT\s*\n", re.MULTILINE),
    re.compile(r"^\d+\s*\n(?=\d{2}:\d{2})", re.MULTILINE),
]

# Whitespace normalization
_MULTI_NEWLINES = re.compile(r"\n{3,}")
_MULTI_SPACES = re.compile(r"[ \t]{2,}")


def _apply_patterns(text: str, patterns: List[Pattern]) -> str:
    """Remove all matches of the given patterns."""
    for pattern in patterns:
        text = pattern.sub("", text)
    return text


def clean_email(text: str) -> str:
    """Clean email content: remove signatures, reply chains, boilerplate."""
    result = _apply_patterns(text, _EMAIL_SIG_PATTERNS)
    result = _apply_patterns(result, _EMAIL_REPLY_PATTERNS)
    return _normalize_whitespace(result)


def clean_slack(text: str) -> str:
    """Clean Slack message: resolve mentions, remove emoji codes, clean URLs."""
    result = text
    # Handle URL with label first (capture group → keep label)
    result = _SLACK_URL_LABEL.sub(r"\1", result)
    # Then plain URLs (capture group → keep URL text)
    result = _SLACK_URL_PLAIN.sub(r"\1", result)
    # Remove user IDs, broadcasts, emoji
    result = _apply_patterns(result, _SLACK_REMOVE_PATTERNS)
    return _normalize_whitespace(result)


def clean_teams(text: str) -> str:
    """Clean Teams message: remove attachments, system events, join/leave."""
    result = _apply_patterns(text, _TEAMS_PATTERNS)
    return _normalize_whitespace(result)


def clean_notion(text: str) -> str:
    """Clean Notion content: remove block UUIDs, normalize whitespace."""
    result = _apply_patterns(text, _NOTION_PATTERNS)
    return _normalize_whitespace(result)


def clean_fathom(text: str) -> str:
    """Clean Fathom transcript: remove timestamps, VTT/SRT headers."""
    result = _apply_patterns(text, _FATHOM_PATTERNS)
    return _normalize_whitespace(result)


def _normalize_whitespace(text: str) -> str:
    """Collapse excessive whitespace."""
    result = _MULTI_SPACES.sub(" ", text)
    result = _MULTI_NEWLINES.sub("\n\n", result)
    return result.strip()


# Source → cleaner mapping
_CLEANERS: Dict[str, Callable[[str], str]] = {
    "email": clean_email,
    "outlook": clean_email,
    "slack": clean_slack,
    "teams": clean_teams,
    "fathom": clean_fathom,
    "notion": clean_notion,
}


def clean_text(text: str, source: str) -> str:
    """Clean text using the appropriate source-specific cleaner.

    Falls back to basic whitespace normalization for unknown sources.
    """
    cleaner = _CLEANERS.get(source.lower())
    if cleaner is None:
        logger.debug("No specific cleaner for source '%s', applying basic normalization", source)
        return _normalize_whitespace(text)
    return cleaner(text)
