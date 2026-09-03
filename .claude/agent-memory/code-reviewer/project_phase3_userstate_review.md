---
name: Phase 3 User State Review
description: Server-side user state (prefs/onboarding/notion-config) review -- server_default mismatch, 4 more bare excepts, no input validation
type: project
---

Phase 3 (Server-Side User State) code review completed on 2026-04-19. Key findings:

- server_default mismatch between model ("0") and migration ("false") for onboarding_completed Boolean column -- will fail on PostgreSQL
- 4 more bare `except Exception: pass` instances (main.py startup sync, onboarding sync, preferences sync, notion config sync) -- all swallow CancelledError on Python 3.8
- No validation on onboarding_step range or preferences dict size -- accepts arbitrary values
- preferences setter treats empty dict {} same as None (falsy check instead of `is not None`)
- notion-config endpoints return bare dict with no response_model -- inconsistent with other endpoints
- apply_server_state merge lets stale server prefs overwrite local on every startup with no conflict resolution
- api_key field stored plaintext in config.json (recurring from Phase 7B)

**Why:** Bare except pattern is now 11th+ instance across the project. The server_default mismatch is a production-breaking issue that SQLite tests won't catch.

**How to apply:** Check for: (1) model/migration column default alignment, (2) bare excepts (still recurring), (3) input validation on new schemas, (4) response_model consistency across related endpoints.
