"""Integration tests for voice endpoints (POST /voice/transcribe, POST /voice/speak)."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


async def _create_user_and_key(client: AsyncClient) -> dict:
    resp = await client.post("/users/", json={
        "email": f"voice_{uuid.uuid4().hex[:8]}@test.com",
        "full_name": "Voice Test User",
    })
    assert resp.status_code == 201
    user_id = resp.json()["id"]
    resp = await client.post("/auth/api-keys", json={"name": "test-key"}, headers={"X-User-Id": user_id})
    assert resp.status_code == 201
    return {"Authorization": f"Bearer {resp.json()['key']}"}


class TestTranscribeEndpoint:
    @pytest.mark.asyncio
    async def test_transcribe_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post("/voice/transcribe", files={"file": ("audio.webm", b"fake", "audio/webm")})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_transcribe_empty_file_returns_422(self, client: AsyncClient) -> None:
        headers = await _create_user_and_key(client)
        resp = await client.post(
            "/voice/transcribe",
            files={"file": ("audio.webm", b"", "audio/webm")},
            headers=headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_transcribe_returns_transcript(self, client: AsyncClient) -> None:
        headers = await _create_user_and_key(client)
        mock_transcriber = MagicMock()
        from app.api.schemas.voice import TranscribeResponse
        mock_transcriber.transcribe = AsyncMock(return_value=TranscribeResponse(
            transcript="hola mundo", language="es", duration_seconds=1.5
        ))
        with patch("app.api.routers.voice._get_transcriber", return_value=mock_transcriber):
            resp = await client.post(
                "/voice/transcribe",
                files={"file": ("audio.webm", b"fake-audio-data", "audio/webm")},
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcript"] == "hola mundo"
        assert data["language"] == "es"


class TestSpeakEndpoint:
    @pytest.mark.asyncio
    async def test_speak_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post("/voice/speak", json={"text": "hola"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_speak_empty_text_returns_422(self, client: AsyncClient) -> None:
        headers = await _create_user_and_key(client)
        resp = await client.post("/voice/speak", json={"text": ""}, headers=headers)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_speak_invalid_voice_returns_422(self, client: AsyncClient) -> None:
        headers = await _create_user_and_key(client)
        resp = await client.post("/voice/speak", json={"text": "hola", "voice": "invalid"}, headers=headers)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_speak_returns_audio_stream(self, client: AsyncClient) -> None:
        headers = await _create_user_and_key(client)

        async def fake_audio():
            yield b"fake-mp3-data"

        with patch("app.api.routers.voice.tts_service.synthesize", return_value=fake_audio()):
            resp = await client.post("/voice/speak", json={"text": "hola mundo"}, headers=headers)
        assert resp.status_code == 200
        assert "audio" in resp.headers["content-type"]
