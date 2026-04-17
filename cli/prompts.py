"""Text content for the onboarding wizard and CLI interface."""
from typing import Dict, List

# ── Welcome ──────────────────────────────────────────────────────────

WELCOME_TITLE = "Welcome to secondBrain"
WELCOME_SUBTITLE = "Your AI Chief of Staff"

WELCOME_INTRO = (
    "I'm your personal AI assistant. I'll help you connect your\n"
    "communication platforms, learn your style, and start tracking\n"
    "your commitments automatically.\n"
    "\n"
    "Let's get you set up. This will take about 5 minutes."
)

RESUME_MESSAGE = (
    "Welcome back, {name}! You left off at step {step} ({step_name}).\n"
    "\n"
    "  [c] Continue from step {step}\n"
    "  [r] Restart onboarding\n"
    "  [s] Skip to chat (finish later with /setup)"
)

# ── Step Names ───────────────────────────────────────────────────────

STEP_NAMES = {
    1: "Account Setup",
    2: "Connect Platforms",
    3: "Identity & Style",
    4: "Initial Import",
    5: "Daily Routine",
}

# ── Platforms ────────────────────────────────────────────────────────

PLATFORM_MENU = (
    "Which platforms do you use? (enter numbers separated by commas)\n"
    "\n"
    "  [1] Microsoft Outlook (emails + calendar)\n"
    "  [2] Slack (messages + channels)\n"
    "  [3] Microsoft Teams (chat)\n"
    "  [4] Fathom (meeting transcripts)\n"
    "  [s] Skip for now"
)

PLATFORM_IDS = {1: "outlook", 2: "slack", 3: "teams", 4: "fathom"}
PLATFORM_NAMES = {"outlook": "Microsoft Outlook", "slack": "Slack",
                  "teams": "Microsoft Teams", "fathom": "Fathom"}

# Per-platform token instructions
PLATFORM_INSTRUCTIONS: Dict[str, str] = {
    "outlook": (
        "I need a Microsoft Graph API access token.\n"
        "You can get one from:\n"
        "  https://developer.microsoft.com/graph/graph-explorer\n"
        "\n"
        "Required permissions: Mail.Read, Calendars.Read"
    ),
    "slack": (
        "I need a Slack Bot Token (starts with xoxb-).\n"
        "You can create one at:\n"
        "  https://api.slack.com/apps -> OAuth & Permissions\n"
        "\n"
        "Required scopes: channels:history, channels:read, im:history, users:read"
    ),
    "teams": (
        "I need a Microsoft Graph API access token (same as Outlook).\n"
        "You can get one from:\n"
        "  https://developer.microsoft.com/graph/graph-explorer\n"
        "\n"
        "Required permissions: Chat.Read"
    ),
    "fathom": (
        "I need your Fathom API key.\n"
        "Find it at:\n"
        "  https://app.fathom.video/settings -> API\n"
        "\n"
        "Read access is sufficient."
    ),
}

PLATFORM_TOKEN_ERROR = (
    "The token might be expired or missing permissions.\n"
    "Common fixes:\n"
    "  - Ensure the token has the required scopes listed above\n"
    "  - Generate a fresh token if it's expired\n"
    "\n"
    "  [r] Retry with a new token\n"
    "  [s] Skip this platform for now\n"
    "  [h] Show token instructions again"
)

# ── Identity ─────────────────────────────────────────────────────────

IDENTITY_INTRO = (
    "I'll adapt my communication style to match yours."
)

TONE_PRESETS: List[str] = [
    "Professional and formal",
    "Friendly but professional",
    "Casual and direct",
]

TONE_MENU = (
    "What tone should I use when communicating on your behalf?\n"
    "\n"
    "  [1] Professional and formal\n"
    "  [2] Friendly but professional\n"
    "  [3] Casual and direct\n"
    "  [4] Let me describe it myself"
)

HEURISTICS_PROMPT = (
    'Are there any specific rules or heuristics I should know about?\n'
    '(e.g., "Always prioritize investor requests", "Bob = CTO of PartnerCo")\n'
    "Type each one and press Enter. Empty line to finish."
)

# ── Import ───────────────────────────────────────────────────────────

IMPORT_INTRO = (
    "Now I'll pull your recent data from connected platforms.\n"
    "This first sync might take a few minutes depending on volume."
)

IMPORT_WINDOW_MENU = (
    "How far back should I go?\n"
    "\n"
    "  [1] Last 7 days\n"
    "  [2] Last 30 days (recommended)\n"
    "  [3] Last 90 days\n"
    "  [4] Everything available"
)

IMPORT_WINDOW_DAYS = {1: 7, 2: 30, 3: 90, 4: 0}

COMMITMENT_REVIEW_MENU = (
    "  [a] Accept all\n"
    "  [r] Review one by one\n"
    "  [d] Dismiss all\n"
    "  [s] Skip for now"
)

# ── Preferences ──────────────────────────────────────────────────────

PREFERENCES_INTRO = "Let's set up how I'll keep you informed."

BRIEFING_TIME_PROMPT = (
    "Daily Briefing — a morning summary of your day ahead.\n"
    "What time should I send it? (HH:MM, 24h format, your timezone)"
)

ALERT_STYLE_MENU = (
    "How should I alert you about approaching deadlines?\n"
    "\n"
    "  [1] Immediately when detected\n"
    "  [2] Only in daily briefing\n"
    "  [3] Manual only (I'll check myself)"
)

ONBOARDING_COMPLETE = (
    "You're all set! Here's a quick summary:\n"
    "\n"
    "  Platforms: {platforms}\n"
    "  Documents: {documents}\n"
    "  Commitments: {commitments} tracked\n"
    "  Briefing: {briefing_time}\n"
    "\n"
    "Type anything to ask me a question, or use /help for commands."
)
