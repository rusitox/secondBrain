---
name: create-commitment-executor-review
description: Review of feat/agent-task-backlog — new create_commitment executor letting the chat agent add backlog items via propose_action; found owner="assistant" sentinel breaks is_owned_by_user filtering everywhere
metadata:
  type: project
---

Review completed 2026-09-14 of `feat/agent-task-backlog` (commit `a0d54fe` on secondBrain,
one commit on top of origin/main): new `create_commitment` action executor
(`app/services/actions/executors/create_commitment.py`) lets the orchestrator agent propose adding
a task to the commitments backlog through the existing propose_action/human-approval pattern, plus a
new nullable `delivered_to` column threaded through model/schema/service/migration
(`alembic/versions/017_add_delivered_to_to_commitments.py`), and removal of the old direct-write
`create_task`/`complete_task` pair from `app/services/agent/tools/task_manager.py` (superseded by the
executor + `update_commitment`).

**Critical — `owner="assistant"` makes every agent-created commitment invisible to
`is_owned_by_user`, which is the filter every "your commitments" surface in the product uses:**
`create_commitment.py` hardcodes `owner="assistant"` (deliberately, per its own docstring, to
distinguish agent-created backlog items from commitments the passive detector extracts from ingested
documents). But `commitment_service.is_owned_by_user(owner, user)` only matches `owner` against the
user's own full name/first name/email/email-local-part — "assistant" matches none of that, and isn't
in `_AMBIGUOUS_OWNERS` either, so it's treated as *someone else's* commitment, not an ambiguous one.
Every consumer that filters on this to build a "yours" view therefore silently drops these items:
`app/services/briefing/generator.py`'s `pending_commitments`/`overdue_commitments` (the daily
briefing — `frontend/src/lib/dashboard.ts` even documents "the backend has already filtered these to
commitments that clearly belong to the user"), and `strands_tools.py`'s own `list_tasks()` tool (so
the agent that just created the task can't see it as "yours" if asked "what are my pending tasks?"
later in the same or a future conversation). End-to-end: user asks the agent to add something to
their backlog, it's created successfully, and then it never appears anywhere the product presents
"your commitments." No test in the new suite exercises this interaction (the new executor tests only
check the raw create path, not `is_owned_by_user`/briefing/`list_tasks` downstream). Fix needs to
either special-case the sentinel in `is_owned_by_user` (these are unambiguously the account holder's
own items — no LLM pulled them out of someone else's meeting) or stop using a fake person-name string
as `owner` and use something structurally distinguishable instead (e.g. keep `owner` as the real
user's name/email and use `document_id IS NULL` + a marker, or a dedicated column) so ownership
filtering doesn't need to special-case a magic string.

**Warning — `delivered_to` has no update path:** `CommitmentUpdate`
(`app/api/schemas/commitment.py`) has no `delivered_to` field, and `commitment_service.update_commitment`
never assigns it even if present — so once a commitment is created (via `create_commitment` or the
direct `POST /commitments/`) there is no way to correct `delivered_to` later, not via the
`update_commitment` executor, not via the direct `PATCH /commitments/{id}` endpoint. Every other
create-time field (`owner`, `commitment_text` via the executor; `status`, `due_date`, `priority` via
the schema) has a companion update path — this one doesn't. Low blast radius (delete+recreate works
around it) but worth closing given the field was just introduced in this diff.

**Confirmed correct, matches sibling executor conventions exactly:** `create_commitment.py` mirrors
`update_commitment.py` in every mechanical way checked — no `db.commit()` inside `execute()` (the
router commits after `mark_executing`/`mark_executed`, per `interactions.py`), `ConfigDict(extra="forbid")`,
`Field(max_length=...)` on free-text fields, `risk = "low"`, `register(...)` at module scope in
`__init__.py`. The `create_task`/`complete_task` removal is clean — grepped the whole repo for both
names; the only remaining hits are the unrelated I+D-platform MCP tool literally named `create_tasks`
(different subsystem, `app/services/agent/knowledge/rd_agent.py`, pre-existing and deliberately
excluded from that agent's tools) — no dangling references to the removed pair. The system-prompt
renumbering in `strands_orchestrator.py` is clean (steps 1-11, no gaps/dupes); minor suggestion only:
step 9's "para marcarlo resuelto más tarde, usá update_commitment (paso 6)" points at step 6, whose
own framing is about the user flagging something *wrong/misfiled*, not the ordinary act of completing
a self-created task — not contradictory (the action_type and payload are correct either way) but the
cross-reference's narrative framing is a little off.

**How to apply:** When reviewing any future feature that introduces a new sentinel/magic-string value
into a free-text field that already has an existing classifier function reading that same field
(here: `Commitment.owner` + `is_owned_by_user`), check every call site of that classifier — a new
value invisible to the classifier silently breaks every downstream "mine" filter, which is easy to
miss because the write path itself works perfectly and all new tests pass. This is a different shape
from the earlier recurring "owner dropped" issue in [[project_secondbrain_phase5]] (that was a value
never being set at all) — here the value is set, just to something the existing filter doesn't
recognize. Also keep watching for "field threaded through create but not update" gaps generally —
[[project_reconciliation_symmetric_threshold_review]] and [[project_apply_question_answer_review]]
both found related-but-different "partial threading" issues in this codebase's action/graph write
paths.
