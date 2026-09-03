---
name: Notion Sync Review (Phase 9C)
description: Bidirectional commitment sync, /notion and /prep CLI commands -- background sync no-op, missing config_ attr, duplicate briefing gen, bare exceptions
type: project
---

Phase 9C code review completed 2026-04-18. Key findings:

- Background Notion sync in cli/background.py is a no-op: the try block only logs, never calls sync_notion_commitments(). Core deliverable doesn't execute.
- Integration model has no config_ attribute. Server endpoints use hasattr() guard which always returns False, so workspace config is always empty. Endpoints will always fail with "no commitments database".
- except (RuntimeError, Exception) -- Exception subsumes RuntimeError. 9th+ occurrence of bare except Exception across project.
- _cmd_briefing generates briefing via get_briefing(), then publish endpoint generates a SECOND independent briefing. User sees one, Notion gets a different one.
- NotionSync accesses publisher private members (_config, _build_headers, _api_call) -- tight coupling.
- No priority bounds validation on Notion-to-local sync (allows P0, P6-P9 bypassing 1-5 constraint).
- Integration tests missing @pytest.mark.asyncio on async methods.
- No integration tests for the two new API endpoints.
- Notion page ID normalization missing -- dashed vs dashless IDs could cause duplicate creation.

**Why:** Confirms systemic patterns: (1) bare exceptions (9th), (2) CLI/server config split, (3) prompt injection (3rd), (4) missing endpoint tests. New pattern: no-op background task (looks like code was stubbed but never completed).

**How to apply:** For future background sync additions, verify the actual API call is present (not just logging). For any endpoint that needs config from CLI setup flow, verify the server can actually access that config. Check async test methods have @pytest.mark.asyncio.
