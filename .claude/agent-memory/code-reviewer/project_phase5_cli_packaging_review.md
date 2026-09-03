---
name: Phase 5 CLI Packaging Review
description: CLI packaging + login flow review -- plaintext api_key (8th), bare except swallows CancelledError (11th+), double-close, HTTP default, reset omits api_key
type: project
---

Phase 5 review (2026-04-19): CLI packaging (pyproject.toml), login/logout flow, remote mode, /users/me endpoint.

CRITICALs:
- api_key stored plaintext in config.json (8th+ plaintext credential instance)
- Bare `except Exception` in auth.py swallows CancelledError on Py3.8 (11th+ instance)
- Double api.close() -- explicit calls in except branches + finally block

WARNINGs:
- DEFAULT_REMOTE_URL uses plain HTTP; login flow bypasses main.py's HTTP warning
- reset() does not clear api_key -- surprising credential retention
- pyproject.toml uses internal setuptools backend (`_legacy:_Backend`)
- is_remote_mode uses substring match on URL, vulnerable to evil-localhost.com
- No integration test for Bearer auth on /users/me (primary feature path untested)
- install.sh suppresses all stderr with 2>/dev/null before fallback

SUGGESTIONs:
- API key format check too loose (sb_ vs sb_live_)
- _get_client ignores timeout param on existing client -- latent bug for sync ops

**Why:** This is the remote access entry point; credential handling and auth flow correctness are table stakes.
**How to apply:** C1 (plaintext api_key) and C2 (CancelledError) are systemic -- track as must-fix across all phases.
