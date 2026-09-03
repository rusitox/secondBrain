---
name: secondBrain Phase 7D Review
description: Background sync + alerts -- CancelledError swallowed (again), unvalidated preference type, silent task death, alert list mutation, sync not restarted after /connect
type: project
---

Phase 7D review (2026-04-17): BackgroundSync (background.py), AlertManager (alerts.py), updated ChatSession (chat.py).

CRITICALs:
- background.py:82 -- bare `except Exception` inside `_sync_all` swallows asyncio.CancelledError on Py3.8 (7th occurrence of this pattern across the codebase, phases 3-7D)

WARNINGs:
- background.py:54 -- `sync_interval` preference not cast to int; string or None value causes TypeError that silently kills the background task
- background.py:39 -- no task done_callback; if task dies unexpectedly the exception is only surfaced when stop() is called at shutdown, with no contextual log
- alerts.py:69 -- show_pending iterates _pending then clears; if print_panel raises mid-loop, alerts are partially shown but never cleared; fix: snapshot list first (`alerts, self._pending = self._pending, []`)
- chat.py:81 -- background sync started once at session open; if user runs /connect mid-session, new platform never gets synced until CLI restart
- tests -- no test for task cancellation mid-sync; test_sync_failure_continues missing callback assertion for the successful second platform

Py3.8 compat: clean -- no modern syntax issues found.

Recurring patterns confirmed:
1. asyncio.CancelledError swallowed by bare except Exception -- now 7 occurrences (phases 3, 4, 5, 6, 7A, 7C, 7D)
2. Unvalidated config/preference values used in arithmetic without type casting
3. Background tasks with no done_callback for unexpected death logging

**Why:** Background task reliability is user-facing; a silently dead sync task gives no feedback and loses data.
**How to apply:** Every new background asyncio.Task needs: (1) CancelledError re-raised before generic except, (2) add_done_callback for logging, (3) preference values cast with fallback.
