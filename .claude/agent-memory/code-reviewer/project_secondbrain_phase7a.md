---
name: secondBrain Phase 7A Review
description: Identity API, stats service, CLI scaffold -- API client pooling, config permissions, token transport, 5 sequential queries, Py3.8 CancelledError
type: project
---

Phase 7A review (2026-04-16): Identity endpoints, stats service, CLI foundation.

CRITICALs:
- APIClient creates new httpx.AsyncClient per request (no connection pooling, resource leak risk)
- OAuth tokens sent plaintext in JSON body; default server_url is HTTP; no HTTPS warning for non-localhost
- Config file at ~/.secondbrain/config.json written world-readable (0644); contains user_id used as auth token

WARNINGs:
- stats_service fires 5 sequential COUNT queries; could be 2 with conditional aggregation
- Overdue query relies on SQL NULL behavior for nullable due_date; fragile across DBs
- CLIConfig.reset() calls self.__init__() with type:ignore -- fragile
- Hardcoded Content-Type: application/json on all requests including GET/DELETE
- Bare `except Exception` in main.py catches asyncio.CancelledError on Python 3.8
- Mutable default {} on Pydantic fields instead of Field(default_factory=dict)
- Zero test coverage for all Phase 7A files

Recurring patterns confirmed across 7 phases:
1. Plaintext token/credential handling (phases 1, 3, 4, 6, 7A)
2. Broad exception handling (phases 3, 4, 5, 6, 7A)
3. Missing tests for new code (phases 3, 5, 7A)

**Why:** CLI is the user-facing entry point; security and robustness issues here are directly exploitable.
**How to apply:** Fix httpx pooling and config permissions before 7B (onboarding), as that flow makes many sequential API calls and persists sensitive state.
