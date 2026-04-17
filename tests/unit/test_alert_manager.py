"""Unit tests for alert manager."""
from cli.alerts import AlertManager


class TestAlertManagerQueue:
    def test_initially_empty(self) -> None:
        am = AlertManager()
        assert am.has_pending is False

    def test_on_sync_result_adds_alert(self) -> None:
        am = AlertManager()
        am.on_sync_result("slack", {
            "documents_created": 5,
            "documents_updated": 0,
            "commitments_detected": 2,
        })
        assert am.has_pending is True

    def test_on_sync_result_zero_results_no_alert(self) -> None:
        am = AlertManager()
        am.on_sync_result("slack", {
            "documents_created": 0,
            "documents_updated": 0,
            "commitments_detected": 0,
        })
        assert am.has_pending is False

    def test_add_alert(self) -> None:
        am = AlertManager()
        am.add_alert("commitment", "slack", "New commitment found")
        assert am.has_pending is True

    def test_clear(self) -> None:
        am = AlertManager()
        am.add_alert("test", "test", "msg")
        am.clear()
        assert am.has_pending is False


class TestAlertManagerShow:
    def test_show_pending_clears_queue(self) -> None:
        am = AlertManager()
        am.on_sync_result("slack", {
            "documents_created": 3,
            "commitments_detected": 1,
        })
        assert am.has_pending is True

        # Import console for capture
        from cli.display import console
        with console.capture():
            am.show_pending()

        assert am.has_pending is False

    def test_show_pending_empty_is_noop(self) -> None:
        am = AlertManager()
        from cli.display import console
        with console.capture():
            am.show_pending()
        # Should not raise

    def test_multiple_alerts_shown(self) -> None:
        am = AlertManager()
        am.on_sync_result("slack", {
            "documents_created": 5, "commitments_detected": 0,
        })
        am.on_sync_result("outlook", {
            "documents_created": 10, "commitments_detected": 3,
        })
        assert am.has_pending is True

        from cli.display import console
        with console.capture() as capture:
            am.show_pending()

        output = capture.get()
        assert "Slack" in output
        assert "Outlook" in output
        assert am.has_pending is False


class TestAlertMessage:
    def test_message_includes_doc_count(self) -> None:
        am = AlertManager()
        am.on_sync_result("slack", {
            "documents_created": 5,
            "documents_updated": 2,
            "commitments_detected": 0,
        })
        alert = am._pending[0]
        assert "5 new documents" in alert.message
        assert "2 updated" in alert.message

    def test_message_includes_commitment_count(self) -> None:
        am = AlertManager()
        am.on_sync_result("outlook", {
            "documents_created": 0,
            "documents_updated": 0,
            "commitments_detected": 3,
        })
        alert = am._pending[0]
        assert "3 new commitments" in alert.message

    def test_message_uses_platform_name(self) -> None:
        am = AlertManager()
        am.on_sync_result("outlook", {
            "documents_created": 1,
            "commitments_detected": 0,
        })
        alert = am._pending[0]
        assert "Microsoft Outlook" in alert.message
