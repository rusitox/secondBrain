"""CLI entry point — initialization, argument parsing, main loop."""
import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

from cli.api_client import APIClient
from cli.config import CLIConfig, DEFAULT_CONFIG_FILE
from cli.display import console, print_error, print_welcome, print_info

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="secondbrain",
        description="secondBrain — Your AI Chief of Staff",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default=None,
        choices=["install"],
        help="Subcommand: 'install' to run the installer",
    )
    parser.add_argument(
        "--server",
        default=None,
        help="Backend server URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--config",
        default=None,
        type=Path,
        help="Path to config file (default: ~/.secondbrain/config.json)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset local configuration and restart onboarding",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    """Async entry point."""
    # Load config
    config_path = args.config or DEFAULT_CONFIG_FILE
    config = CLIConfig.load(config_path)

    if args.server:
        config.server_url = args.server

    if args.reset:
        config.reset()
        print_info("Configuration reset. Starting fresh.")

    # Handle install subcommand
    if args.command == "install":
        from cli.installer import Installer
        installer = Installer(config=config)
        success = await installer.run()
        if not success:
            return 1
        # After install, continue to onboarding
        # Update API client with potentially new server URL
        api = APIClient(
            server_url=config.server_url,
            user_id=config.user_id,
        )
        from cli.onboarding import OnboardingFlow
        flow = OnboardingFlow(api=api, config=config)
        completed = await flow.run()
        if not completed:
            print_info("Onboarding incomplete. Run again to continue.")
            return 0
        from cli.chat import ChatSession
        session = ChatSession(api=api, config=config)
        await session.run()
        return 0

    # Warn if sending tokens over plain HTTP to a remote server
    if (
        config.server_url.startswith("http://")
        and not config.server_url.startswith("http://localhost")
        and not config.server_url.startswith("http://127.0.0.1")
    ):
        from cli.display import print_warning
        print_warning(
            "Server URL uses plain HTTP. Credentials may be sent unencrypted.\n"
            "  Consider using HTTPS for non-localhost connections."
        )

    # Create API client
    api = APIClient(
        server_url=config.server_url,
        user_id=config.user_id,
    )

    # Check backend connectivity — try auto-start if installed
    from cli.display import spinner
    with spinner("Connecting to backend..."):
        connected = await api.health_check()

    if not connected and config.installed:
        # Auto-start: try to bring up DB + server
        from cli.server import ServerManager
        server = ServerManager(config)

        print_info("Backend not running. Starting it...")

        if not server.is_db_running():
            with spinner("Starting database..."):
                db_ok = await server.start_db()
            if not db_ok:
                print_error("Failed to start database. Is Docker running?")
                return 1

        with spinner("Starting backend server..."):
            srv_ok = await server.start_server()
        if not srv_ok:
            print_error("Failed to start backend server.")
            return 1

        # Update API client with potentially new URL
        api = APIClient(
            server_url=config.server_url,
            user_id=config.user_id,
        )
        with spinner("Connecting to backend..."):
            connected = await api.health_check()

    if not connected:
        if not config.installed:
            print_error(
                "secondBrain is not installed yet.\n"
                "  Run the installer first:\n"
                "    python -m cli install"
            )
        else:
            print_error(
                f"Cannot reach backend at {config.server_url}\n"
                "  Make sure Docker is running, then try:\n"
                "    python -m cli install  (to reinstall)\n"
                "\n"
                "  Or specify a different URL:\n"
                "    python -m cli --server http://host:port"
            )
        return 1

    # Route to onboarding or chat
    if not config.onboarding_completed:
        from cli.onboarding import OnboardingFlow
        flow = OnboardingFlow(api=api, config=config)
        completed = await flow.run()
        if not completed:
            print_info("Onboarding incomplete. Run again to continue.")
            return 0

    # Start chat session
    from cli.chat import ChatSession
    session = ChatSession(api=api, config=config)
    await session.run()
    return 0


def main() -> None:
    """Synchronous entry point."""
    args = parse_args()

    # Configure logging
    level = logging.DEBUG if args.debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    try:
        exit_code = asyncio.run(async_main(args))
    except KeyboardInterrupt:
        console.print("\n[muted]Goodbye![/muted]")
        exit_code = 0
    except asyncio.CancelledError:
        # Python 3.8: CancelledError is not a subclass of Exception
        console.print("\n[muted]Cancelled.[/muted]")
        exit_code = 0
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        logger.exception("Fatal error")
        exit_code = 1

    sys.exit(exit_code)
