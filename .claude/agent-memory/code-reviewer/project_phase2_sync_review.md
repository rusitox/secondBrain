---
name: Phase 2 Server-Side Sync Review
description: APScheduler-based sync scheduler review -- CancelledError (8th+9th), duplicated sync logic, error leaking, missing tests
type: project
---

Phase 2 review (2026-04-19): Server-side sync via APScheduler (SyncScheduler, sync router, CLI detection).

CRITICALs:
- scheduler.py:177 and sync.py:181 -- bare `except Exception` swallows asyncio.CancelledError on Py3.8 (8th and 9th occurrences project-wide)
- sync.py:188 -- raw str(e) returned in API response leaks internal details

WARNINGs:
- scheduler.py:111 -- bare `except Exception: pass` in remove_job (briefing scheduler does it correctly with JobLookupError)
- scheduler.py:88 -- no None guard on sync_interval_minutes, max(None, 5) raises TypeError
- Duplicated sync logic between _run_sync and trigger_sync endpoint (DRY violation)
- last_sync_at advanced unconditionally (same Phase 3 bug)
- configure_sync uses flush() not commit(), scheduler reschedule can diverge from DB on rollback
- CLI accesses private APIClient internals (_get_client, _base_url, _headers)
- CLI server detection has bare except Exception: pass (CancelledError again)
- No tests for _run_sync execution, trigger_sync error paths, or CLI detection

Recurring patterns confirmed:
1. asyncio.CancelledError -- now 9 occurrences across phases 1-7D + Phase 2
2. Partial sync timestamp advancement (3rd occurrence: phases 3, 7D, now Phase 2)
3. Bare except with pass (11th+ occurrence)

**Why:** Server-side sync is a critical reliability path; silent failures mean data stops syncing with no user feedback.
**How to apply:** Any new async error handler must re-raise CancelledError before generic except.
