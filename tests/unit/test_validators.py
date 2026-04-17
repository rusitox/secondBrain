"""Unit tests for CLI input validators."""
import pytest

from cli.validators import (
    parse_selection,
    validate_email,
    validate_name,
    validate_time_24h,
    validate_timezone,
    validate_token,
)


class TestValidateEmail:
    def test_valid_email(self) -> None:
        assert validate_email("user@example.com") is None

    def test_valid_email_with_dots(self) -> None:
        assert validate_email("first.last@company.co.uk") is None

    def test_empty_email(self) -> None:
        assert validate_email("") is not None

    def test_no_at(self) -> None:
        assert validate_email("not-an-email") is not None

    def test_no_domain(self) -> None:
        assert validate_email("user@") is not None

    def test_whitespace_stripped(self) -> None:
        assert validate_email("  user@example.com  ") is None


class TestValidateName:
    def test_valid_name(self) -> None:
        assert validate_name("Mariano Ortega") is None

    def test_empty_name(self) -> None:
        assert validate_name("") is not None

    def test_too_short(self) -> None:
        assert validate_name("A") is not None

    def test_too_long(self) -> None:
        assert validate_name("x" * 101) is not None

    def test_two_chars_ok(self) -> None:
        assert validate_name("Mo") is None


class TestValidateTimezone:
    def test_utc(self) -> None:
        assert validate_timezone("UTC") is None

    def test_continent_city(self) -> None:
        assert validate_timezone("America/New_York") is None

    def test_argentina(self) -> None:
        assert validate_timezone("America/Argentina/Buenos_Aires") is None

    def test_empty(self) -> None:
        assert validate_timezone("") is not None

    def test_no_slash(self) -> None:
        assert validate_timezone("EST") is not None


class TestValidateTime24h:
    def test_valid_time(self) -> None:
        assert validate_time_24h("07:30") is None

    def test_midnight(self) -> None:
        assert validate_time_24h("00:00") is None

    def test_end_of_day(self) -> None:
        assert validate_time_24h("23:59") is None

    def test_single_digit_hour(self) -> None:
        assert validate_time_24h("7:30") is None

    def test_invalid_hour(self) -> None:
        assert validate_time_24h("25:00") is not None

    def test_invalid_minute(self) -> None:
        assert validate_time_24h("12:60") is not None

    def test_bad_format(self) -> None:
        assert validate_time_24h("noon") is not None

    def test_empty(self) -> None:
        assert validate_time_24h("") is not None


class TestValidateToken:
    def test_valid_generic_token(self) -> None:
        assert validate_token("outlook", "eyJ0eXAiOiJKV1Qi_long_token_here") is None

    def test_empty_token(self) -> None:
        assert validate_token("slack", "") is not None

    def test_too_short(self) -> None:
        assert validate_token("outlook", "abc") is not None

    def test_slack_valid(self) -> None:
        assert validate_token("slack", "xoxb-1234-5678-abcdef") is None

    def test_slack_wrong_prefix(self) -> None:
        assert validate_token("slack", "xoxp-1234-5678-abcdef") is not None

    def test_fathom_valid(self) -> None:
        assert validate_token("fathom", "fathom_key_abc123def") is None


class TestParseSelection:
    def test_single(self) -> None:
        assert parse_selection("2", 4) == [2]

    def test_multiple(self) -> None:
        assert parse_selection("1, 2, 4", 4) == [1, 2, 4]

    def test_no_spaces(self) -> None:
        assert parse_selection("1,3", 4) == [1, 3]

    def test_out_of_range(self) -> None:
        assert parse_selection("5", 4) is None

    def test_zero(self) -> None:
        assert parse_selection("0", 4) is None

    def test_non_numeric(self) -> None:
        assert parse_selection("abc", 4) is None

    def test_empty(self) -> None:
        assert parse_selection("", 4) is None
