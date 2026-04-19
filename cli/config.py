"""CLI configuration — persisted in ~/.secondbrain/config.json."""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".secondbrain"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_SERVER_URL = "http://localhost:8000"


def _check_file_permissions(path: Path) -> None:
    """Warn if config file is readable by group or others (unix only)."""
    try:
        import stat
        mode = path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            logger.warning(
                "Config file %s is readable by other users (mode %o). "
                "Run: chmod 600 %s",
                path, stat.S_IMODE(mode), path,
            )
    except (OSError, AttributeError):
        pass  # Windows or filesystem that doesn't support unix permissions


@dataclass
class CLIConfig:
    """Persisted CLI configuration."""

    server_url: str = DEFAULT_SERVER_URL
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    onboarding_completed: bool = False
    onboarding_step: int = 0
    platforms_connected: List[str] = field(default_factory=list)
    identity_configured: bool = False
    initial_import_done: bool = False
    preferences: Dict[str, Any] = field(default_factory=dict)

    # Installer fields
    installed: bool = False
    db_port: int = 5432
    server_port: int = 8000
    server_pid: Optional[int] = None

    # Notion integration
    notion: Optional[Dict[str, Any]] = None

    # API key (added for Phase 5, prepared now)
    api_key: Optional[str] = None

    _config_path: Path = field(default=DEFAULT_CONFIG_FILE, repr=False)

    @property
    def is_remote_mode(self) -> bool:
        """True if server_url is not localhost."""
        url = self.server_url.lower()
        return not any(
            h in url for h in ("localhost", "127.0.0.1", "0.0.0.0")
        )

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "CLIConfig":
        """Load config from disk, or return defaults if not found."""
        path = config_path or DEFAULT_CONFIG_FILE
        if not path.exists():
            config = cls(_config_path=path)
            return config

        # Warn if config file permissions are too open (unix only)
        _check_file_permissions(path)

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read config from %s: %s", path, e)
            return cls(_config_path=path)

        return cls(
            server_url=raw.get("server_url", DEFAULT_SERVER_URL),
            user_id=raw.get("user_id"),
            user_name=raw.get("user_name"),
            user_email=raw.get("user_email"),
            onboarding_completed=raw.get("onboarding_completed", False),
            onboarding_step=raw.get("onboarding_step", 0),
            platforms_connected=raw.get("platforms_connected", []),
            identity_configured=raw.get("identity_configured", False),
            initial_import_done=raw.get("initial_import_done", False),
            preferences=raw.get("preferences", {}),
            installed=raw.get("installed", False),
            db_port=raw.get("db_port", 5432),
            server_port=raw.get("server_port", 8000),
            server_pid=raw.get("server_pid"),
            notion=raw.get("notion"),
            api_key=raw.get("api_key"),
            _config_path=path,
        )

    def save(self) -> None:
        """Persist config to disk."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "server_url": self.server_url,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "user_email": self.user_email,
            "onboarding_completed": self.onboarding_completed,
            "onboarding_step": self.onboarding_step,
            "platforms_connected": self.platforms_connected,
            "identity_configured": self.identity_configured,
            "initial_import_done": self.initial_import_done,
            "preferences": self.preferences,
            "installed": self.installed,
            "db_port": self.db_port,
            "server_port": self.server_port,
            "server_pid": self.server_pid,
            "notion": self.notion,
            "api_key": self.api_key,
        }
        self._config_path.write_text(
            json.dumps(data, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        # Restrict permissions — config may contain user_id and server URL
        try:
            self._config_path.chmod(0o600)
        except OSError:
            pass  # Windows or restricted filesystem
        logger.debug("Config saved to %s", self._config_path)

    def reset(self) -> None:
        """Reset config to defaults (keeps server_url, install state, and config path)."""
        server = self.server_url
        path = self._config_path
        installed = self.installed
        db_port = self.db_port
        server_port = self.server_port
        server_pid = self.server_pid
        notion = self.notion
        self.user_id = None
        self.user_name = None
        self.user_email = None
        self.api_key = None
        self.onboarding_completed = False
        self.onboarding_step = 0
        self.platforms_connected = []
        self.identity_configured = False
        self.initial_import_done = False
        self.preferences = {}
        self.server_url = server
        self.installed = installed
        self.db_port = db_port
        self.server_port = server_port
        self.server_pid = server_pid
        self.notion = notion
        self._config_path = path
        self.save()

    def apply_server_state(self, data: Dict[str, Any]) -> None:
        """Apply state fetched from GET /users/me/preferences to local cache.

        Called on CLI startup to sync server state into local config.
        """
        onboarding = data.get("onboarding", {})
        self.onboarding_step = onboarding.get("step", self.onboarding_step)
        self.onboarding_completed = onboarding.get("completed", self.onboarding_completed)

        server_prefs = data.get("preferences", {})
        if server_prefs:
            self.preferences = {**self.preferences, **server_prefs}

        notion = data.get("notion_config")
        if notion is not None:
            self.notion = notion

        self.save()
