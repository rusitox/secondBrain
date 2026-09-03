---
name: Voice interface backend patterns
description: STT/TTS endpoints, SSE streaming, stream_callback in LLMClient — added in feat/voice-interface
type: project
---

Voice interface feature added on feat/voice-interface branch (2026-09-02).

**New files:**
- `app/api/schemas/voice.py` — TranscribeResponse, SpeakRequest schemas
- `app/services/voice/transcriber.py` — WhisperTranscriber (mode="api"|"local", lazy local model load)
- `app/services/voice/tts.py` — synthesize() returns bytes (not async generator) via client.audio.speech.create().content
- `app/api/routers/voice.py` — POST /voice/transcribe (UploadFile + Content-Length + content-type pre-checks), POST /voice/speak (Response with buffered bytes, not StreamingResponse)

**Modified:**
- `app/core/config.py` — 5 new voice settings: stt_mode, whisper_model, tts_voice, tts_model, voice_max_audio_mb
- `app/services/llm/claude_client.py` — generate_with_tools() + _generate_with_tools_anthropic() gained stream_callback: Optional[Callable[[str], Awaitable[None]]]. Tool iterations remain non-streaming; final answer re-issues as client.messages.stream() when callback is set.
- `app/api/schemas/briefing.py` — AgentStreamRequest added
- `app/api/routers/agent.py` — POST /agent/stream SSE endpoint using EventSourceResponse; calls internal AgentOrchestrator methods (_resolve_session, _make_* factories, _persist_turns) to inject callbacks
- `app/main.py` — voice router registered; conditional StaticFiles mount at /voice-ui
- `requirements.txt` — sse-starlette>=1.6,<3.0; python-multipart>=0.0.9; openai-whisper>=20231117
- `Dockerfile` — ffmpeg + libsndfile1 in runtime stage apt-get

**Key implementation note:** AsyncOpenAI is imported lazily inside transcriber methods (inside `from openai import AsyncOpenAI`). Unit tests must patch `openai.AsyncOpenAI`, not `app.services.voice.transcriber.AsyncOpenAI`.

**Code review fixes (2026-09-02):**
- voice.py: Content-Length pre-check before read; content_type validation against ALLOWED_AUDIO_TYPES; speak endpoint uses Response(bytes) not StreamingResponse to prevent resource leaks
- tts.py: synthesize() now returns bytes via response.content (no async generator leak on disconnect)
- transcriber.py: get_running_loop() replaces get_event_loop(); suffix derived from filename; language param is Optional[str]=None (auto-detect when None)
- voice schema: VoiceName Literal type replaces str; voice validation moved to schema, removed manual check in router
- agent.py: SSE except catches CancelledError+specific errors (no bare except); try/finally in event_generator cancels task on disconnect
- claude_client.py: tool_choice={"type":"none"} on streaming call to prevent tool invocation in final answer
- briefing.py: AgentStreamRequest = AgentQueryRequest (alias, not duplicate class)
- static/voice: DOMPurify@3.2.4 added; marked pinned to @15.0.7; Google Fonts @import removed; validateApiKey uses GET /users/ (lightweight, no LLM calls)

**SSE event protocol:** tool_call, tool_result, token, done, error — queue-based bridge between async task and async generator.

**Why:** stt_mode=api is default (uses OpenAI Whisper API). Local mode uses openai-whisper package with ffmpeg dependency.
