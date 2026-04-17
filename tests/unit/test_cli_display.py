"""Unit tests for CLI display utilities."""
from unittest.mock import patch, MagicMock

from cli.display import (
    console,
    print_welcome,
    print_panel,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_muted,
    print_markdown,
    print_table,
    print_stats,
    spinner,
    create_progress,
)


class TestDisplayFunctions:
    """Test that display functions execute without errors."""

    def test_print_welcome(self) -> None:
        with console.capture():
            print_welcome("Test Title", "Test subtitle")

    def test_print_welcome_no_subtitle(self) -> None:
        with console.capture():
            print_welcome("Title Only")

    def test_print_panel(self) -> None:
        with console.capture():
            print_panel("Content", title="Test", style="green")

    def test_print_success(self) -> None:
        with console.capture():
            print_success("All good!")

    def test_print_error(self) -> None:
        with console.capture():
            print_error("Something failed")

    def test_print_warning(self) -> None:
        with console.capture():
            print_warning("Be careful")

    def test_print_info(self) -> None:
        with console.capture():
            print_info("FYI")

    def test_print_muted(self) -> None:
        with console.capture():
            print_muted("Dim text")

    def test_print_markdown(self) -> None:
        with console.capture():
            print_markdown("# Hello\n\n**bold** and *italic*")

    def test_print_table(self) -> None:
        with console.capture():
            print_table(
                "Test Table",
                columns=["Name", "Value"],
                rows=[["one", "1"], ["two", "2"]],
            )

    def test_print_table_with_styles(self) -> None:
        with console.capture():
            print_table(
                "Styled",
                columns=["A", "B"],
                rows=[["x", "y"]],
                styles=["cyan", "green"],
            )

    def test_print_stats(self) -> None:
        with console.capture():
            print_stats({
                "documents_total": 100,
                "commitments_pending": 5,
                "commitments_overdue": 2,
                "integrations_active": 3,
                "last_sync": "2026-04-17T10:00:00",
            })

    def test_print_stats_no_sync(self) -> None:
        with console.capture():
            print_stats({
                "documents_total": 0,
                "commitments_pending": 0,
                "integrations_active": 0,
            })

    def test_spinner_context_manager(self) -> None:
        with console.capture():
            with spinner("Loading..."):
                pass  # Just test it doesn't crash

    def test_create_progress(self) -> None:
        progress = create_progress("Testing")
        assert progress is not None
