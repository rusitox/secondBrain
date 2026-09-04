---
name: Voice Interface Review
description: Voice STT/TTS endpoints, SSE streaming agent, vanilla JS UI — feat/voice-interface branch
type: project
---

Phase "voice interface" code review completed on 2026-09-02. Key findings:

**Criticals:**
- `voice.py`: ALLOWED_AUDIO_TYPES defined but never checked — any content-type passes, including non-audio. Check file.content_type before reading.
- `agent.py:160`: bare `except Exception` in `run_query()` catches CancelledError — 14th+ recurrence. Use `except Exception` + re-raise `asyncio.CancelledError`, or catch specific exceptions.
- `agent.py:160`: `str(e)` leaks internal exception details (stack traces, DB errors) directly to SSE client — use sanitized message.
- `transcriber.py:59`: `asyncio.get_event_loop()` deprecated in Python 3.10+ and broken on Python 3.12. Use `asyncio.get_running_loop()` instead.
- `tts.py`: `async with ... as response: yield chunk` — the async generator outlives the `async with` context if the client disconnects mid-stream; resource leak.
- `claude_client.py:204`: Final streaming call re-issues the full conversation without the previously-fetched non-streaming response result; if the LLM decides to call a tool again in the streaming call (no `tool_choice="none"` guard), you get a double tool-use loop. Should pass `tool_choice={"type": "none"}` to force text-only output.

**Warnings:**
- `transcriber.py:50,70`: language hardcoded to `"es"` — makes the tool useless for non-Spanish audio. Expose as config or schema field.
- `voice.py:86`: bare `except Exception` on TTS path — 15th+ recurrence.
- `voice.py:43`: audio bytes read entirely into memory before size check — should check Content-Length header first, or stream-read with a limit.
- `agent.py:107`: `run_query` task is `create_task` but if the SSE client disconnects before SENTINEL, the task keeps running and DB session may be used after the request scope ends.
- `app/api/schemas/briefing.py`: `AgentStreamRequest` is a duplicate of `AgentQueryRequest` with identical fields — should inherit or alias.
- `app.js:161-168`: `validateApiKey` calls `/agent/query` with `{ question: 'ping' }` — triggers full LLM call + tool loop on every login. Use a lightweight endpoint (e.g., `/auth/me`) instead.
- `app.js:813`: `renderMarkdown` feeds LLM-generated text to `marked.parse()` with no sanitization — XSS risk if marked output is set as `innerHTML`. Add DOMPurify or use `marked` with a sanitizer.

**Info:**
- `index.html:11`: marked.js loaded from CDN (unpinned) — pin to specific version for reproducibility.
- `static/voice/style.css`: Google Fonts CDN call on load — leaks user IP to Google on every page view; self-host the font.
- `transcriber.py:46`: temp file suffix hardcoded to `.webm` regardless of actual format — local Whisper may fail on `.ogg` uploads.

**Recurring systemic patterns confirmed:**
- bare `except Exception` (now 15+ occurrences)
- `asyncio.get_event_loop()` vs `get_running_loop()` (Python 3.8 compat risk)
- lru_cache singleton holding async clients (same concern as agent.py)
