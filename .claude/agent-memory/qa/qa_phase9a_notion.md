---
name: Phase 9A Notion Connector QA
description: QA validation results for Phase 9A NotionConnector — all checklist items passed, comments ingestion deferred
type: project
---

Phase 9A (NotionConnector read-only) validated 2026-04-18. All 9 checklist items PASS, 44 tests pass on Python 3.8.19.

**Why:** Cross-check spec vs implementation before advancing to Phase 9B.

**How to apply:**
- Comments ingestion (`GET /v1/comments`, `notion_comment` type) is in the spec table but not in Phase 9A scope — track as follow-up
- `clean_notion()` has no dedicated unit test — add before Phase 9B
- 5 uncovered edge cases in `notion.py` (retry exhaustion, block pagination, db query filter, db query failure, `_get_blocks` max depth) — consider adding
- Coverage: blocks.py 100%, notion.py 95%, cleaner.py 48% (pre-existing cleaners account for misses)
