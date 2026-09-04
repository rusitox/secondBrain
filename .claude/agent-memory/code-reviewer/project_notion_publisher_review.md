---
name: Notion Publisher Review (Phase 9B)
description: Review of NotionPublisher, text_to_blocks, CLI setup -- partial failure in setup_workspace, 429/retry conflation, 2000-char limit, CLI imports server-side modules
type: project
---

Phase 9B code review completed 2026-04-18. Key findings:

- setup_workspace mutates config in-place during 4 sequential API calls. Partial failure leaves orphaned Notion pages and inconsistent config state.
- 429 rate-limit retries consume the same 3-attempt budget as transport errors. Sustained throttling exhausts retries with no error context.
- Notion text.content 2000-char limit not enforced in _rich_text(). Code blocks from text_to_blocks can exceed this.
- CLI (notion_setup.py) directly imports and runs server-side NotionConnector.validate_token and NotionPublisher.setup_workspace, violating the CLI-talks-to-API-only architecture.
- TestFullFlow test missing NotionSetup mock -- will hang waiting for console input.
- Bare except Exception (8th occurrence across all phases).
- NotionPublisher not exported from __init__.py.
- Each publisher method creates its own httpx.AsyncClient, missing connection pooling.

**Why:** New architectural anti-pattern: CLI importing server-side service classes directly. Combined with recurring bare-except pattern, indicates need for architectural guidelines enforcement.

**How to apply:** Future CLI additions must go through REST API. Verify Notion text payloads against 2000-char limit. Check retry logic separates rate-limit vs error budgets.
