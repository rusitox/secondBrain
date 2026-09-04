---
name: API Key Auth Phase Review
description: Auth phase review findings — useless key_prefix (always sb_live_), duplicated key logic, bare except enabling prod bypass
type: project
---

API Key Authentication review completed 2026-04-19. Key findings:

- key_prefix stores first 8 chars of key which is always "sb_live_" for every key — prefix index is useless, causes O(n) bcrypt per auth request. Must capture random portion.
- _KEY_PREFIX constant duplicated across 3 files (auth.py, create_api_key.py, security.py) with inconsistent values ("sb_live_" vs "sb_").
- Bare `except Exception` in security.py when loading settings silently falls back to is_production=False, which enables X-User-Id bypass even in production if .env is misconfigured.
- Mapped[str] for UUID FK continues from earlier phases (11th instance now).
- Stale lifespan warning says "API key auth not yet configured" even though it is.

**Why:** The prefix issue is the most impactful — it's a design flaw that will degrade auth performance linearly with user count and make the index useless.

**How to apply:** In future auth reviews, verify that lookup indexes actually discriminate between records. Check for duplicated crypto/key logic that should be centralized.
