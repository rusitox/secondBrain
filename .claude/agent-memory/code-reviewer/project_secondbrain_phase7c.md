---
name: secondBrain Phase 7C Review
description: CLI chat session and command router -- prompt_toolkit async misuse, CancelledError swallowed, no cleanup guarantee, duplicated command list
type: project
---

Phase 7C review (2026-04-17): ChatSession (chat.py) and CommandRouter (commands.py).

CRITICALs:
- get_event_loop() instead of get_running_loop() in _get_input; deprecated and risky
- prompt_toolkit prompt() run via run_in_executor instead of native prompt_async(); stdin contention with console.input in /identity

WARNINGs:
- Bare `except Exception` in dispatch catches asyncio.CancelledError on Py3.8 (recurring since Phase 3)
- /connect and /identity call private _step_platforms()/_step_identity() on OnboardingFlow -- tight coupling
- /sync sends arbitrary user input to API without local validation
- Main chat loop has no try/finally -- unhandled exceptions skip api.close()
- Hardcoded command list in _create_prompt_session duplicates CommandRouter.COMMANDS
- /disconnect deletes all integrations with no confirmation prompt
- Tests mostly assert "should not raise" / API called, but not output content

Py3.8 compat: clean -- no modern syntax issues found (improvement over prior phases).

Recurring patterns confirmed across 9 phases:
1. asyncio.CancelledError swallowed by bare except Exception (phases 3-7C)
2. Missing try/finally for resource cleanup (phases 7A, 7C)
3. Tests assert call-made but not output-produced (phases 5, 7B, 7C)

**Why:** Chat session is the primary user interaction surface; reliability of the input loop and cleanup are essential.
**How to apply:** Fix prompt_async and try/finally first (user-facing stability), then CancelledError (correctness under cancellation).
