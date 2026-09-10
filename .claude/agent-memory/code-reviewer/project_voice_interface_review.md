---
name: Voice Interface Review (updated 2026-09-03)
description: Voice STT/TTS endpoints, SSE streaming agent, vanilla JS UI, auth login — updated after fixes confirmed
type: project
---

Phase "voice interface" initial review completed 2026-09-02. Re-reviewed 2026-09-03 after merge to main.

**Issues FIXED since initial review:**
- ALLOWED_AUDIO_TYPES is now checked before reading file body.
- asyncio.get_event_loop() replaced with get_running_loop() in transcriber.py.
- TTS resource leak (async generator outliving context) fixed — tts.py now returns bytes directly (no streaming generator).
- bare except in voice.py TTS path now catches specific (RuntimeError, ValueError) with explicit CancelledError re-raise.
- XSS: DOMPurify added alongside marked.js in index.html; renderMarkdown() uses DOMPurify.sanitize() when available.
- Language hardcoded to "es" removed — language is now Optional[str] and caller-controlled.
- validateApiKey no longer calls full agent query for login validation (login flow replaced by POST /auth/login).
- marked.js now pinned to specific version (15.0.7) on CDN, DOMPurify also pinned (3.2.4).

**Remaining / new issues (2026-09-03 review):**

CRITICAL:
- auth.py:57 — portal_password compared with == (timing attack). The portal password is a shared secret; timing-safe comparison required.
- auth.py:84 — db.flush() without commit. get_db() commits on yield exit, but if an exception is raised between flush and the route return, the transaction rolls back and the new API key is silently lost. Same applies to /api-keys, /bootstrap, and /regenerate. The key has already been returned to the client — data inconsistency.
- base.py:116 — _make_get_calendar() does not forward user_timezone. CalendarSyncTool.get_today_events() defaults to "UTC" silently. Calendar times shown in UI will be wrong for non-UTC users. orchestrator.py's _executor_get_calendar DOES pass user_timezone correctly — base.py is the legacy version used by agents that inherit BaseSubAgent.

WARNING:
- auth.py:225-227 — bootstrap endpoint: bare `except Exception` swallows any Settings load error and defaults is_prod=False, meaning the bootstrap endpoint stays open even if config is broken. Should propagate the error instead.
- orchestrator.py:578 — _route_agents receives augmented_question (with identity prefix) for keyword matching — the prefix text "IDENTIDAD DEL USUARIO" won't interfere but "FECHA DE HOY" could theoretically match future keywords. Low risk, but cleaner to pass original question to router.
- orchestrator.py:672-677 — synthesis prompt uses % formatting: `_SYNTHESIS_SYSTEM.format(style=style)`. If style_text contains a literal { or }, format() will raise KeyError. This is the same str.format() prompt injection pattern flagged in Phase 6 (5th+ recurrence). Use Template or f-string at construction time.
- app.js:473 — sentenceBuf TTS flush threshold is 90 chars OR sentence-ending punctuation. If the agent streams a very long sentence (>300 chars, no punctuation), multiple segments are enqueued. The finalizeAgentMessage() then checks `ttsQueue.length === 0` and re-enqueues the full answer — resulting in double TTS playback of the last segment. The condition should be `if (!ttsPlaying)` without the queue check, or skip re-enqueue if streaming TTS was already fired.

INFO:
- auth.py:21 — _KEY_LABEL = "sb_live_" duplicated from security.py (flagged in API Key Auth Review). Still not DRY.
- voice.py — lru_cache on _get_transcriber() holds the WhisperTranscriber singleton forever. If openai_api_key is rotated at runtime (settings reload), the cached transcriber retains the old key. Minor in practice; documented.
- index.html — marked.js and DOMPurify loaded from CDN (jsDelivr). Still leaks user IP to CDN on page load; acceptable trade-off for now but self-hosting is cleaner long-term.

**Recurring systemic patterns confirmed in this pass:**
- str.format() on system prompts (now 6th recurrence — orchestrator.py synthesis prompt)
- bare except Exception in non-agent code (bootstrap endpoint)
- flush-without-commit risk (auth.py — same as agent memory review)
- user_timezone not forwarded through all code paths (base.py vs orchestrator.py divergence)
