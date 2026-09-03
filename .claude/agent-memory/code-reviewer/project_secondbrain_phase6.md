---
name: secondBrain Phase 6 Review Patterns
description: Daily briefing + agent orchestration review -- str.format on prompts (3rd time), prompt injection (2nd time), API key validation (4th time), bare except, calendar N+1
type: project
---

Phase 6 code review completed on 2026-04-16. Key findings:

- `str.format()` used on both AGENT_SYSTEM_PROMPT and BRIEFING_SYSTEM_PROMPT with user-sourced `style_context`. 3rd consecutive phase with this vulnerability.
- User question and tool results (emails, messages, calendar) concatenated into LLM prompt without `<document>` tags -- prompt injection. 2nd consecutive phase.
- `openai_api_key` not validated in agent router (4th consecutive phase with API key validation gap).
- Bare `except Exception` in scheduler.py `remove_briefing` -- should catch `JobLookupError`.
- CalendarSyncTool loads ALL Outlook documents then filters in Python -- N+1/memory issue.
- BriefingGenerator catches RuntimeError/ValueError from Claude but not AnthropicAPIError -- fallback bypassed.
- TOOL_ROUTING_PROMPT defined but never used (dead code with .format() vulnerability).
- Module-level `_scheduler` singleton not using @lru_cache pattern.
- `format_briefing_context` uses bare `list` params instead of `List[Dict[str, Any]]`.
- Integration test type hints say `AsyncMock` but probably receive real `AsyncSession`.

**Recurring patterns confirmed across ALL 6 phases:**
1. str.format() with user/external input (phases 4, 5, 6)
2. Prompt injection / no document delimiters (phases 5, 6)
3. API key validation gaps (phases 1, 3, 4, 6)
4. Bare/broad exception handling (phases 3, 4, 5, 6)
5. Plain classes instead of @dataclass for tool classes (phases 3, 4, 5, 6)

**Why:** These patterns are now confirmed systemic across the entire MVP. A project-wide sweep is warranted before shipping.

**How to apply:** Recommend a hardening pass across all phases addressing these 5 recurring patterns before MVP release.
