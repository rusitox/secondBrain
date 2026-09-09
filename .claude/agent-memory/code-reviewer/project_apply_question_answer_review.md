---
name: apply-question-answer-review
description: Review of extracting confirm_pending_answer's logic into reconciliation.apply_question_answer, shared by the chat tool and the backoffice answer endpoint (fixes the endpoint never touching the graph)
metadata:
  type: project
---

Review completed 2026-09-09 of the fix for "closing a same_as pending question in the backoffice
looked done but never merged anything" (the backoffice's `POST /backoffice/graph/questions/{id}/answer`
previously only called `store.resolve_question`, unlike the chat orchestrator's
`confirm_pending_answer`, which actually wrote a `same_as` `EntityLink` or a `CONFIRMED_BY_USER`
`EntityClaim`). Fix: extracted the write logic into
`reconciliation.apply_question_answer(db, user_id, question_id, answer_text, confirmed=True)`, made
both `strands_tools.confirm_pending_answer` (chat) and `backoffice.answer_question` (HTTP) thin
wrappers around it, added `AnswerQuestionRequest.confirmed`, and updated `static/backoffice/app.js` to
show two explicit buttons ("✅ Son la misma" / "❌ Son distintas") for a same_as-shaped question instead
of one generic "Responder" that always sent `confirmed=true`.

**No criticals.** The specific risk the task was scoped around — answering "these are distinct" in
the backoffice silently sending `confirmed=true` and merging them anyway — is closed: the two new
buttons explicitly pass `true`/`false` (verified both wiring sites in `app.js`, no shared default
path), and `apply_question_answer`'s same_as branch only fires when `confirmed` is true. The
extraction itself checks out against the pre-existing test suite
(`tests/integration/test_strands_tools_knowledge.py::TestConfirmPendingAnswerTool`, unchanged and
still describing the same behavior: not-found error, already-resolved error/no-double-write,
single-entity claim, same_as link, `confirmed=false` no-op) plus new equivalent tests through the
HTTP path (`test_backoffice_api.py`) and the shared function's own error paths
(`test_reconciliation.py::TestApplyQuestionAnswer`). The new `try/except` around
`uuid.UUID(question_id)` in `strands_tools.confirm_pending_answer` is a pure crash-safety fix (matches
the existing `{"error": f"invalid ... {e}"}` pattern already used by `correct_knowledge`/
`ask_domain_agents` in the same file) — not a behavior change beyond "no longer raises."

**Warning — `answer_question` collapses every `apply_question_answer` error to HTTP 404
(`app/api/routers/backoffice.py`):** "not found", "already resolved/dismissed" (closer to 409), and
any other exception string (e.g. `store.link_entities`'s `ValueError` when a context-referenced
entity no longer exists) all become 404 with `result["error"]` as the detail text. Checked whether
this matters to the frontend: it doesn't functionally — `apiSend()` in `app.js` never branches on
status code, only surfaces `err.detail` (the original message) in a toast — so today this is a REST-
purity nit, not a live bug. No test exercises the already-resolved case through the HTTP layer though
(only through `reconciliation.apply_question_answer` directly) — worth adding, and worth tightening
the status codes (409 for conflict, 404 only for genuinely missing) before anything ever starts
switching on status code instead of message text.

**Confirmed fine, no reachable bug today, but a latent coupling worth knowing about:** the
backoffice UI decides which action buttons to render (`renderQuestions` in `app.js`) based on whether
`entity_name`/`candidate_entity_name` *resolved* (via `store.list_entities_by_ids`), while
`apply_question_answer` decides whether to write a same_as link based on whether
`context.entity_id`/`candidate_entity_id` are merely *present* — these two checks are equivalent only
because nothing in the app currently deletes an `Entity` row (`store.delete_entity` exists per
[[project_reconciliation_symmetric_threshold_review]] but has no caller anywhere — `correct_knowledge`
only links/unlinks, never deletes). If entity deletion is ever wired up, a same_as question
referencing a since-deleted entity would silently fall back to the generic single "Responder" button
(confirmed defaults `true`), and the resulting `link_entities` `ValueError` would roll back the whole
`begin_nested()` block — including `resolve_question` — so the human's typed answer is silently lost
(generic error toast, question stays open) instead of resolving one way or the other.
`PendingQuestionRead` already exposes raw `context` to the frontend, so a future fix could switch the
button-selection condition to `q.context.entity_id && q.context.candidate_entity_id` (or have the
backend send an explicit `is_identity_question` flag) instead of piggybacking on name-resolution
success, decoupling "can I render a friendly label" from "which write path does this trigger."

**How to apply:** When reviewing future changes to `apply_question_answer` or the questions
answer/dismiss endpoints, check whether entity deletion has been wired up anywhere yet — if so, the
latent coupling above becomes a real bug and should be fixed then, not before. Also the general
pattern from [[project_reconciliation_symmetric_threshold_review]] still applies: any write path in
this subsystem driven by free-form context (chat tool args, or stored `PendingQuestion.context`)
should be checked for what happens when a referenced id no longer resolves — silently failing whole
transactions instead of partially recording intent is the recurring shape of risk here, even when
(as in this review) it isn't currently reachable.
