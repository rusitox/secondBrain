"""Authentication flows — login and logout for remote CLI usage."""
import logging
from typing import Optional

import httpx

from cli.api_client import APIClient, APIError
from cli.config import CLIConfig
from cli.display import console, print_error, print_info, print_success, spinner

logger = logging.getLogger(__name__)

DEFAULT_REMOTE_URL = "http://oracle-vm:8080"


def _ask(prompt: str, password: bool = False) -> str:
    """Prompt user for input."""
    try:
        if password:
            import getpass
            return getpass.getpass(prompt + " ").strip()
        return console.input(prompt + " ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


async def login(config: CLIConfig) -> bool:
    """Interactive login flow.

    1. Prompt for server URL
    2. Prompt for API key (masked)
    3. Validate via health check + GET /users/me
    4. Store credentials in config

    Returns True on success.
    """
    if config.api_key:
        print_info(
            "Already logged in as %s." % (config.user_name or config.user_email or "unknown")
        )
        console.print("  Run [bold]secondbrain logout[/bold] first to switch accounts.")
        return False

    console.print("[bold]secondBrain Login[/bold]")
    console.print()

    # Server URL
    default_url = config.server_url if config.is_remote_mode else DEFAULT_REMOTE_URL
    console.print("Server URL (default: %s)" % default_url)
    url_input = _ask(">")
    server_url = url_input if url_input else default_url

    # API key
    console.print()
    console.print("API key (starts with sb_):")
    api_key = _ask(">", password=True)
    if not api_key:
        print_error("No API key provided.")
        return False

    if not api_key.startswith("sb_"):
        print_error("Invalid API key format — must start with 'sb_'.")
        return False

    # Validate connection
    api = APIClient(server_url=server_url, api_key=api_key)
    try:
        with spinner("Connecting..."):
            healthy = await api.health_check()
        if not healthy:
            print_error("Cannot reach server at %s" % server_url)
            return False

        # Validate API key by fetching user info
        with spinner("Authenticating..."):
            user_data = await api.get_me()
    except APIError as e:
        if e.status_code == 401:
            print_error("Invalid or revoked API key.")
        else:
            print_error("Authentication failed: %s" % e.detail)
        return False
    except (httpx.HTTPError, OSError) as e:
        print_error("Connection failed: %s" % str(e))
        return False
    finally:
        await api.close()

    # Store credentials
    config.server_url = server_url
    config.api_key = api_key
    config.user_id = user_data.get("id")
    config.user_name = user_data.get("full_name")
    config.user_email = user_data.get("email")
    config.save()

    print_success("Logged in as %s (%s)" % (config.user_name, config.user_email))
    return True


async def logout(config: CLIConfig) -> None:
    """Clear local credentials.

    Keeps server_url so the user can re-login easily.
    """
    if not config.api_key:
        print_info("Not logged in.")
        return

    name = config.user_name or config.user_email or "unknown"
    config.api_key = None
    config.user_id = None
    config.user_name = None
    config.user_email = None
    config.save()

    print_success("Logged out. (was: %s)" % name)
