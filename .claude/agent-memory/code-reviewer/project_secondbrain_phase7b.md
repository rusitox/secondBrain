---
name: secondBrain Phase 7B Review
description: CLI onboarding wizard -- unverified user ID takeover, plaintext tokens recurring, timezone bug, unbounded recursion, missing commitment review tests
type: project
---

Phase 7B review (2026-04-17): CLI onboarding wizard (validators, prompts, 5-step flow).

CRITICALs:
- Duplicate-email flow accepts arbitrary user ID without verifying email match -- account takeover vector
- Plaintext token transport still unfixed (recurring since Phase 1) -- OAuth/Slack tokens sent over HTTP

WARNINGs:
- Unbounded recursion on invalid input in _step_platforms and _step_identity (should be loops)
- Timezone collected in Step 1 never saved to config.preferences -- Step 5 always uses "UTC" for briefing
- Import window menu selection captured but silently discarded (never passed to sync)
- Bare `list` and `callable` type hints instead of typed generics (Py3.8 typing)
- _COMMON_TIMEZONES defined but unused; validate_timezone accepts any string with a slash
- No tests for commitment review flow or duplicate-email-wrong-ID scenario

Recurring patterns confirmed across 8 phases:
1. Plaintext token/credential handling (phases 1, 3, 4, 6, 7A, 7B)
2. Missing tests for new code paths (phases 3, 5, 7A, 7B)
3. Weak input validation (timezone, user ID verification)

**Why:** Onboarding is the first user interaction; account takeover and token leaks here undermine trust.
**How to apply:** C2 (user ID verification) is the top priority fix. W5 (timezone) will cause wrong briefing times for all non-UTC users.
