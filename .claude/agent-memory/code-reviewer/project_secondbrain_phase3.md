---
name: secondBrain Phase 3 Review Patterns
description: Ingestion pipeline review findings -- connector error handling, sync state management, dead code, missing API-level tests
type: project
---

Phase 3 code review completed on 2026-04-16. Key findings:

- Connector sync endpoint (`/ingest/sync/{platform}`) lacks error handling for decryption failures and HTTP errors from external APIs. External API calls should always be wrapped in try/except with structured error responses.
- `last_sync_at` timestamp is advanced unconditionally after sync, even if items were partially ingested. This can cause data loss on re-sync.
- Pipeline only calls `db.flush()`, never `db.commit()` -- relies on caller's session management. Both the pipeline and endpoints should be explicit about commit boundaries.
- OpenAI API key defaults to empty string in config and is not validated. Embedder initialization should fail fast if key is missing.
- Pre-compiled regex patterns in `cleaner.py` (`_SLACK_PATTERNS`) are dead code -- `clean_slack` uses inline `re.sub` instead. Should be consolidated.
- `IngestionResult` and `ConnectorItem` are plain classes, should be dataclasses per project conventions.
- No API-level endpoint tests for ingestion router -- only unit and component-level integration tests exist.
- Empty `source_id` + multi-chunk documents create collision-prone chunk IDs (`#chunk0`, `#chunk1`).
- Connector pagination loops have no upper bound -- risk of infinite loops.

**Why:** These findings follow the same patterns from Phase 1: missing error handling at integration boundaries, implicit state management, and incomplete test coverage at the API layer.

**How to apply:** In future phases, check for: (1) error handling around all external API calls, (2) explicit commit boundaries, (3) validation of required config values, (4) API-level endpoint tests, (5) pagination safety limits.
