---
name: Notion Connector Review (Phase 9A)
description: Review of NotionConnector -- semaphore rate limiter broken, pagination unbounded (4th occurrence!), UUID cleaner too broad, partial failure swallowed
type: project
---

Phase 9A code review completed 2026-04-18. Key findings:

- asyncio.Semaphore(3) limits concurrency not requests/second -- provides zero rate limiting in sequential flow. Need token-bucket or timed approach.
- No MAX_PAGES pagination guard on any of 3 while-True loops. This is the 4th connector with this pattern (Phase 3 flagged it as systemic).
- Notion cleaner strips ALL UUIDs from content, not just block IDs. blocks_to_text already excludes block metadata, so this may be unnecessary and destructive.
- _process_database swallows errors mid-pagination, returns partial results silently. Compounds the systemic last_sync_at-advanced-unconditionally issue.
- block_id interpolated into URL without encoding (same as Teams connector path injection).
- validate_token bypasses _api_call -- no retry, no rate limiting.
- Client-side date filter uses <= which excludes boundary items and may skip ties.

**Why:** Confirms 3 systemic patterns now at 4+ occurrences each: (1) unbounded pagination, (2) path injection via string interpolation, (3) partial failure silently swallowed. Rate limiter is a new class of bug.

**How to apply:** Future connector reviews should immediately verify: rate limiting mechanism actually limits rate (not just concurrency), pagination has MAX_PAGES, URL params are encoded, partial failures are surfaced.
