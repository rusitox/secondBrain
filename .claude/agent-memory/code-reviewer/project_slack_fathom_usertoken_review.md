---
name: Slack/Fathom User Token Review
description: Slack rewrite + Fathom stub + user_token column review -- ABC mismatch, raw dict endpoint, bare except in _resolve_usernames, missing commit in ingestion router, test patch path risks
type: project
---

Review date: 2026-09-01. Files: slack.py, fathom.py, scheduler.py, integration_service.py, integrations.py, ingestion.py, integration.py, migration 008, cli/commands.py, cli/api_client.py, tests.

CRITICALs:
- ABC contract broken: BaseConnector.fetch_items(access_token, since) does not declare user_token; SlackConnector adds it as extra kwarg. Python ABC does not validate extra kwargs, so SlackConnector instantiates fine — but mypy/static analysis will flag callers that try to call it through the BaseConnector type. Real risk: if any caller holds a BaseConnector reference and calls fetch_items(user_token=...), it works at runtime for Slack but silently drops user_token for other connectors.
- POST /integrations/{id}/user-token accepts raw `dict` body instead of a Pydantic model. FastAPI will silently accept any JSON object with no schema validation. An empty body `{}` bypasses the Pydantic layer and reaches `data.get("user_token", "")` which returns "" and hits the 400 guard -- acceptable. But a malformed body (e.g., list) raises an unstructured 422 with internal field paths leaked in the error. Should use a Pydantic model.
- _resolve_usernames uses bare `except Exception` (12th+ project-wide instance) -- catches CancelledError on Python 3.8 and can silently mask task cancellation.

WARNINGs:
- ingestion.py sync_platform: calls db.flush() but never db.commit() after updating last_sync_at. The scheduler's _run_sync does commit(). This inconsistency means API-triggered syncs silently lose their last_sync_at update on transaction close.
- test_sync_fathom_incremental.py patches "scripts.sync_fathom_incremental.get_session_factory" -- this only works if the script module is importable as `scripts.sync_fathom_incremental` from the test runner's working directory. The file adds repo root to sys.path manually, which is fragile in CI. If pytest is run from a subdirectory this will silently import the wrong module or fail with ImportError.
- test_run_sync_error_truncated and test_run_sync_connector_error patch "app.services.integration_service.get_decrypted_token" but scheduler.py imports integration_service and calls integration_service.get_decrypted_user_token() after get_decrypted_token(). The test does not patch get_decrypted_user_token, so the mock integration's user_token attribute (set to None via MagicMock default) is passed through -- this works but is fragile.
- DM thread replies: the same duplicate-source_id risk exists for DM threads as for channel threads (parent message ts == thread_ts) but the deduplication logic is correct -- risk is low.
- _cmd_connect_slack_user_token: getpass.getpass is synchronous and will block the event loop on Python 3.8 when called from within an async handler. Should use asyncio.get_event_loop().run_in_executor.

**Why:** user_token is a new credential type; correctness of encryption/storage/non-exposure is the primary concern. All verified correct. Remaining issues are ABC hygiene, test reliability, and the missing commit.
**How to apply:** bare except in _resolve_usernames is the 12th+ instance -- track globally. Missing db.commit() in sync_platform is a data-loss bug in the API path.
