---
name: Phase 2 Server-Side Sync QA
description: QA validation of Phase 2 (SyncScheduler, sync endpoints, CLI auto-detect). 15 tests pass but 52% coverage, 3 CRITICALs in _run_sync/trigger/load_jobs untested.
type: project
---

Phase 2 QA validated 2026-04-19. 15/15 tests pass, but scheduler coverage only 52%.

**CRITICALs:**
- `_run_sync` (core sync execution) has zero coverage
- `POST /sync/trigger/{platform}` endpoint has zero integration tests
- `_load_jobs` (startup job loading) has zero coverage

**WARNINGs:**
- `reschedule_job` untested
- `test_minimum_interval_enforced` does not verify actual interval value (false-positive risk)
- CLI BackgroundSync server-side auto-detection untested
- No test exercises scheduler_active=true path in /sync/status
- Trigger endpoint returns error as HTTP 200 (design concern)
- `last_sync_status` has no enum constraint at model level

**Why:** Coverage is well below the 80% threshold. The most important code paths (actual sync execution) have no tests at all.

**How to apply:** Before Phase 2 can be considered complete, add tests for _run_sync, trigger endpoint, _load_jobs, and CLI auto-detect. Fix the weak interval assertion.
