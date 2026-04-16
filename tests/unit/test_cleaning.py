"""Unit tests for text cleaning by source type."""
import pytest

from app.services.ingestion.cleaner import (
    clean_email,
    clean_fathom,
    clean_slack,
    clean_teams,
    clean_text,
)


class TestCleanEmail:
    def test_remove_dash_signature(self) -> None:
        text = "Hello, please review.\n-- \nJohn Doe\nSenior Engineer"
        result = clean_email(text)
        assert "John Doe" not in result
        assert "Hello, please review." in result

    def test_remove_sent_from_iphone(self) -> None:
        text = "Quick reply.\nSent from my iPhone"
        result = clean_email(text)
        assert "iPhone" not in result
        assert "Quick reply." in result

    def test_remove_get_outlook(self) -> None:
        text = "Thanks!\nGet Outlook for iOS"
        result = clean_email(text)
        assert "Outlook" not in result

    def test_remove_reply_chain(self) -> None:
        text = "Sounds good.\n\nOn Mon, Jan 1, 2024 John wrote:\nOriginal message here"
        result = clean_email(text)
        assert "Original message here" not in result
        assert "Sounds good." in result

    def test_remove_outlook_reply_headers(self) -> None:
        text = "Noted.\n\nFrom: Alice\nSent: Monday\nTo: Bob\nPrevious message"
        result = clean_email(text)
        assert "Previous message" not in result
        assert "Noted." in result

    def test_remove_underscore_signature(self) -> None:
        text = "Let me know.\n___\nConfidentiality notice blah"
        result = clean_email(text)
        assert "Confidentiality" not in result

    def test_preserves_body(self) -> None:
        text = "Important meeting notes from today.\nWe agreed on the budget."
        result = clean_email(text)
        assert "Important meeting notes" in result
        assert "agreed on the budget" in result


class TestCleanSlack:
    def test_remove_user_mentions(self) -> None:
        text = "Hey <@U1234ABCD> can you check this?"
        result = clean_slack(text)
        assert "<@U1234ABCD>" not in result
        assert "can you check this?" in result

    def test_resolve_url_with_label(self) -> None:
        text = "Check <https://example.com/doc|the doc>"
        result = clean_slack(text)
        assert result == "Check the doc"

    def test_resolve_plain_url(self) -> None:
        text = "See <https://example.com/page>"
        result = clean_slack(text)
        assert result == "See https://example.com/page"

    def test_remove_broadcasts(self) -> None:
        text = "<!channel> please review <!here>"
        result = clean_slack(text)
        assert "<!channel>" not in result
        assert "<!here>" not in result
        assert "please review" in result

    def test_remove_emoji_codes(self) -> None:
        text = "Great job :thumbsup: :rocket:"
        result = clean_slack(text)
        assert ":thumbsup:" not in result
        assert "Great job" in result

    def test_combined_cleaning(self) -> None:
        text = "<@U123> <!here> check <https://ex.com|link> :wave:"
        result = clean_slack(text)
        assert result == "check link"


class TestCleanTeams:
    def test_remove_attachment_tags(self) -> None:
        text = "See the file <attachment id='123'>file.pdf</attachment>"
        result = clean_teams(text)
        assert "<attachment" not in result

    def test_remove_join_leave(self) -> None:
        text = "Let's discuss.\n[Meeting] John has joined the meeting\nAny updates?"
        result = clean_teams(text)
        assert "has joined" not in result
        assert "Let's discuss." in result

    def test_remove_system_events(self) -> None:
        text = "Hello <systemEventMessage type='call'>Call started</systemEventMessage> world"
        result = clean_teams(text)
        assert "Call started" not in result
        assert "Hello" in result


class TestCleanFathom:
    def test_remove_vtt_timestamps(self) -> None:
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nHello everyone"
        result = clean_fathom(text)
        assert "WEBVTT" not in result
        assert "-->" not in result
        assert "Hello everyone" in result

    def test_remove_srt_sequence_numbers(self) -> None:
        text = "1\n00:00:01,000 --> 00:00:05,000\nWelcome to the meeting"
        result = clean_fathom(text)
        assert "Welcome to the meeting" in result

    def test_preserves_speaker_content(self) -> None:
        text = "Speaker 1: We need to finalize the budget.\nSpeaker 2: Agreed."
        result = clean_fathom(text)
        assert "finalize the budget" in result
        assert "Agreed" in result


class TestCleanText:
    def test_dispatches_to_correct_cleaner(self) -> None:
        """clean_text should dispatch based on source."""
        slack_text = "Hey <@U123> :wave:"
        result = clean_text(slack_text, "slack")
        assert "<@U123>" not in result
        assert ":wave:" not in result

    def test_unknown_source_normalizes_whitespace(self) -> None:
        text = "Hello    world\n\n\n\nfoo"
        result = clean_text(text, "unknown_source")
        assert "Hello world" in result
        assert "\n\n\n\n" not in result

    def test_empty_text(self) -> None:
        assert clean_text("", "slack") == ""

    def test_whitespace_only(self) -> None:
        assert clean_text("   \n\n   ", "email") == ""

    def test_source_case_insensitive(self) -> None:
        text = "Hey <@U123>"
        result = clean_text(text, "Slack")
        assert "<@U123>" not in result
