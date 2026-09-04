"""Unit tests for make_agent_tools — Strands @tool wrappers.

Covers tool count/composition (including the opt-in web_search / http_request
tools added in Phase 5), and the security-relevant behavior of both: Brave
Search error handling and the http_request domain allowlist (an SSRF /
prompt-injection guard — the tool is disabled entirely unless the operator
configures HTTP_REQUEST_ALLOWED_DOMAINS).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.agent.strands_tools import make_agent_tools


def _make_settings(brave_search_api_key: str = "", http_request_allowed_domains: str = "") -> MagicMock:
    settings = MagicMock()
    settings.brave_search_api_key = brave_search_api_key
    settings.http_request_allowed_domains = http_request_allowed_domains
    return settings


def _tool_names(tools) -> set:
    return {t.tool_name for t in tools}


class TestToolComposition:
    def test_default_config_registers_only_the_core_eight_tools(self) -> None:
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=MagicMock(), user_id=uuid.uuid4())
        assert len(tools) == 8
        assert "web_search" not in _tool_names(tools)
        assert "http_request" not in _tool_names(tools)

    def test_web_search_registered_when_brave_key_configured(self) -> None:
        with patch("app.core.config.get_settings", return_value=_make_settings(brave_search_api_key="bsk-test")):
            tools = make_agent_tools(db=MagicMock(), user_id=uuid.uuid4())
        assert "web_search" in _tool_names(tools)
        assert len(tools) == 9

    def test_http_request_registered_when_allowlist_configured(self) -> None:
        with patch(
            "app.core.config.get_settings",
            return_value=_make_settings(http_request_allowed_domains="docs.python.org"),
        ):
            tools = make_agent_tools(db=MagicMock(), user_id=uuid.uuid4())
        assert "http_request" in _tool_names(tools)
        assert len(tools) == 9

    def test_both_optional_tools_registered_when_both_configured(self) -> None:
        settings = _make_settings(
            brave_search_api_key="bsk-test",
            http_request_allowed_domains="docs.python.org",
        )
        with patch("app.core.config.get_settings", return_value=settings):
            tools = make_agent_tools(db=MagicMock(), user_id=uuid.uuid4())
        assert len(tools) == 10


def _get_tool(tools, name: str):
    return next(t for t in tools if t.tool_name == name)


class TestWebSearch:
    @pytest.mark.asyncio
    async def test_returns_parsed_results(self) -> None:
        settings = _make_settings(brave_search_api_key="bsk-test")
        with patch("app.core.config.get_settings", return_value=settings):
            tools = make_agent_tools(db=MagicMock(), user_id=uuid.uuid4())
        web_search = _get_tool(tools, "web_search")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "web": {"results": [
                {"title": "Result 1", "url": "https://example.com/1", "description": "First"},
                {"title": "Result 2", "url": "https://example.com/2", "description": "Second"},
            ]}
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await web_search.__wrapped__(query="test query")

        assert len(results) == 2
        assert results[0]["title"] == "Result 1"
        assert results[0]["url"] == "https://example.com/1"

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_list(self) -> None:
        settings = _make_settings(brave_search_api_key="bsk-test")
        with patch("app.core.config.get_settings", return_value=settings):
            tools = make_agent_tools(db=MagicMock(), user_id=uuid.uuid4())
        web_search = _get_tool(tools, "web_search")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await web_search.__wrapped__(query="test query")

        assert results == []

    @pytest.mark.asyncio
    async def test_count_is_clamped_to_ten(self) -> None:
        settings = _make_settings(brave_search_api_key="bsk-test")
        with patch("app.core.config.get_settings", return_value=settings):
            tools = make_agent_tools(db=MagicMock(), user_id=uuid.uuid4())
        web_search = _get_tool(tools, "web_search")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"web": {"results": []}}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await web_search.__wrapped__(query="test", count=999)

        call_kwargs = mock_client.get.call_args.kwargs
        assert call_kwargs["params"]["count"] == 10


class TestHttpRequest:
    def _make_http_request_tool(self, allowed_domains: str = "docs.python.org"):
        settings = _make_settings(http_request_allowed_domains=allowed_domains)
        with patch("app.core.config.get_settings", return_value=settings):
            tools = make_agent_tools(db=MagicMock(), user_id=uuid.uuid4())
        return _get_tool(tools, "http_request")

    @pytest.mark.asyncio
    async def test_disallowed_domain_is_blocked(self) -> None:
        http_request = self._make_http_request_tool(allowed_domains="docs.python.org")
        result = await http_request.__wrapped__(url="https://evil.example.com/exfiltrate")
        assert "not in the allowed list" in result

    @pytest.mark.asyncio
    async def test_non_http_scheme_is_rejected(self) -> None:
        http_request = self._make_http_request_tool(allowed_domains="docs.python.org")
        result = await http_request.__wrapped__(url="file:///etc/passwd")
        assert "unsupported URL scheme" in result

    @pytest.mark.asyncio
    async def test_allowed_domain_returns_body(self) -> None:
        http_request = self._make_http_request_tool(allowed_domains="docs.python.org")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html>hello</html>"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await http_request.__wrapped__(url="https://docs.python.org/3/")

        assert result == "<html>hello</html>"

    @pytest.mark.asyncio
    async def test_unsupported_content_type_is_rejected(self) -> None:
        http_request = self._make_http_request_tool(allowed_domains="docs.python.org")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "application/octet-stream"}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await http_request.__wrapped__(url="https://docs.python.org/binary")

        assert "unsupported content-type" in result

    @pytest.mark.asyncio
    async def test_response_body_truncated(self) -> None:
        http_request = self._make_http_request_tool(allowed_domains="docs.python.org")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = "x" * 20000
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await http_request.__wrapped__(url="https://docs.python.org/big")

        assert len(result) == 8000

    @pytest.mark.asyncio
    async def test_request_failure_returns_error_string(self) -> None:
        http_request = self._make_http_request_tool(allowed_domains="docs.python.org")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await http_request.__wrapped__(url="https://docs.python.org/3/")

        assert result.startswith("Error: request failed")
