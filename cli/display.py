"""Display utilities — wraps rich for formatted terminal output."""
import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskID
from rich.table import Table
from rich.theme import Theme

logger = logging.getLogger(__name__)

# Custom theme
_THEME = Theme({
    "info": "cyan",
    "success": "green",
    "warning": "yellow",
    "error": "red bold",
    "title": "bold blue",
    "muted": "dim",
})

# Module-level console instance
console = Console(theme=_THEME)


def print_welcome(title: str, subtitle: str = "") -> None:
    """Print a welcome banner."""
    content = f"[title]{title}[/title]"
    if subtitle:
        content += f"\n{subtitle}"
    console.print(Panel(content, border_style="blue", padding=(1, 2)))


def print_panel(content: str, title: str = "", style: str = "blue") -> None:
    """Print content in a bordered panel."""
    console.print(Panel(content, title=title, border_style=style, padding=(0, 1)))


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[success]{message}[/success]")


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"[error]{message}[/error]")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[warning]{message}[/warning]")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[info]{message}[/info]")


def print_muted(message: str) -> None:
    """Print a muted/dim message."""
    console.print(f"[muted]{message}[/muted]")


def print_markdown(text: str) -> None:
    """Render markdown text."""
    console.print(Markdown(text))


def print_table(
    title: str,
    columns: List[str],
    rows: List[List[str]],
    styles: Optional[List[str]] = None,
) -> None:
    """Print a formatted table."""
    table = Table(title=title, show_header=True, header_style="bold")
    for i, col in enumerate(columns):
        col_style = styles[i] if styles and i < len(styles) else ""
        table.add_column(col, style=col_style)
    for row in rows:
        table.add_row(*row)
    console.print(table)


def print_stats(stats: Dict[str, Any]) -> None:
    """Print user statistics in a formatted panel."""
    lines = [
        f"  Documents: {stats.get('documents_total', 0)}",
        f"  Commitments: {stats.get('commitments_pending', 0)} pending"
        + (f", {stats.get('commitments_overdue', 0)} overdue" if stats.get("commitments_overdue") else ""),
        f"  Integrations: {stats.get('integrations_active', 0)} active",
    ]
    last_sync = stats.get("last_sync")
    if last_sync:
        lines.append(f"  Last sync: {last_sync}")
    console.print(Panel("\n".join(lines), title="Stats", border_style="cyan"))


@contextmanager
def spinner(message: str) -> Iterator[None]:
    """Show a spinner while an operation runs."""
    with console.status(f"[info]{message}[/info]", spinner="dots"):
        yield


def create_progress(description: str = "Processing") -> Progress:
    """Create a progress bar for long operations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    )
