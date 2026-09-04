---
name: Phase 9D Digest Review
description: Weekly digest, meeting prep, auto-publish -- FastAPI body param mismatch breaks endpoints, prompt injection (4th), bare except (10th+)
type: project
---

Phase 9D code review completed 2026-04-19. Key findings:

- FastAPI body parameter mismatch: endpoints with `workspace_config: dict` + `str` params treat strings as query params, but CLI sends them as JSON body. `/notion/publish-meeting-prep` returns 422 on every call (title/prep_text are required query params). `/notion/publish-briefing` silently ignores briefing_text. Need `Body()` annotation or Pydantic schemas.
- Prompt injection in digest context builder: raw commitment_text and owner interpolated into Claude prompt without sanitization. 4th occurrence across project.
- Bare `except Exception` at lines 86, 124 in background.py. 10th+ occurrence across project.
- `_maybe_publish_digest` reads timezone preference but ignores it, uses UTC weekday. Also uses `%W` week numbering which breaks at year boundaries.
- Digest generator doesn't catch Anthropic SDK exceptions (same as Phase 6 briefing generator).
- No tests for 2 new API endpoints, 3 new CLI commands, background digest scheduler.
- Claude client recreated per request instead of cached.

**Why:** FastAPI body param bug is a new anti-pattern -- all Notion endpoints with mixed dict+str params are affected. Combined with recurring prompt injection and bare exceptions, indicates need for project-wide remediation pass.

**How to apply:** All Notion POST endpoints need Pydantic request schemas or Body() annotations. Verify any future endpoint with mixed body parameter types. Check all LLM prompt builders for unsanitized user content.
