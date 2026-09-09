---
name: reconciliation-symmetric-threshold-review
description: Review of raising SAME_AS_CONFIDENCE_THRESHOLD 0.7->0.9 + symmetric auto-resolve of confident "distinct" verdicts, and the new correct_knowledge orchestrator tool for graph corrections
metadata:
  type: project
---

Review completed 2026-09-09 of the fix for the pending-questions flood (1029 open questions in
under a day): `reconciliation._run_reconciliation_pass` previously escalated to a human on
*every* "distinct" verdict from the same_as negotiation swarm regardless of confidence, even
though most verdicts were "distinct" at 0.9-0.99 confidence. Fix: raised
`SAME_AS_CONFIDENCE_THRESHOLD` 0.7->0.9 and made it symmetric — a confident `same_entity=False`
verdict is now a silent no-op (`auto_resolved_distinct` counter) instead of always escalating.
Also added the `correct_knowledge` orchestrator tool (chat-driven graph correction: dispute a
claim, add a corrected claim, merge/unmerge two entities) plus `store.delete_entity` /
`dispute_claim` / `unlink_entities` / `links_exist`.

**No criticals.** Everything checked out structurally: `delete_entity`'s cascade claim was
verified against the *real* FK (`ondelete="CASCADE"` on both `EntityClaim.entity_id` and
`EntityLink.entity_id_a/b`), and the integration test genuinely exercises DB-level cascade
because `tests/conftest.py` sets `PRAGMA foreign_keys=ON` for the SQLite test DB — this matters
because without that pragma the cascade test would pass for the wrong reason (or not at all).
`unlink_entities`' `result.rowcount` is directly asserted (`== 1`) in a test, so the
`# type: ignore[attr-defined]` is safe in practice for both the SQLite test driver and asyncpg.
All UUID parsing in `correct_knowledge` happens before any DB write (no partial-write-before-
validation risk). Nested-transaction rollback semantics (`db.begin_nested()` wrapping
dispute+add_claim+link/unlink in one call) are correct by SQLAlchemy savepoint semantics, matching
the pre-existing `confirm_pending_answer` pattern — but this specific rollback interaction
(second write raising after first write already flushed) has no dedicated test, only inferred
correct.

**Warning — cost regression, not correctness bug:** the "confidently distinct" branch fixes the
question flood but removes the *only* thing that was throttling repeat swarm negotiations for
that pair: previously the (excessive) escalated `PendingQuestion`, while it stayed `OPEN` (which
in practice was most of the 1029 flood), caused `_find_open_reconciliation_question` to skip
re-negotiating that pair on every subsequent cycle. Now a confidently-distinct pair leaves **no
persistent record at all** — `_already_linked` only recognizes `relation_type == "same_as"`, there
is no "not_same_as"/decided-distinct marker — so `find_candidate_duplicates` (embedding similarity,
recomputed fresh every cycle) will keep resurfacing the same pair and `negotiate_same_as` will
re-run a full LLM swarm negotiation for it on *every future reconciliation cycle, forever*. The
negotiation is still traced (`record_verdict_event`/`record_swarm_negotiation` run unconditionally)
so there's no audit-trail gap, but there's an unbounded recurring-cost gap. Worth a follow-up:
persist a lightweight "already decided distinct" marker (e.g. a dedicated `EntityLink.relation_type`
or a small dedup table) so distinct pairs get skipped on future passes the same way `same_as` pairs
already are.

**Warning — validation gap in `store.dispute_claim`:** scoped only by `user_id`, not by
`entity_id`. `correct_knowledge(entity_id=..., claim_id=...)` never checks
`claim.entity_id == entity_id` before disputing — an LLM-composed call with a mismatched
entity_id/claim_id pair (typo, stale conversation context, or [[project_agent_memory_review]]'s
tracked prompt-injection pattern) would silently dispute a claim belonging to a *different* entity
than the one named. Low real-world likelihood (claim_ids only ever come from `query_knowledge`,
which is already scoped per-entity) but cheap to close: check `claim.entity_id == entity_id` after
fetch in `dispute_claim`, or pass `entity_id` through as an extra filter.

**Confirmed correct / no knock-on effects:** `auto_link_by_email`'s deterministic branch is
untouched by the threshold bump (unrelated code path). The `same_entity=True` auto-link branch
just requires higher confidence now (0.7->0.9) — safe, more conservative, no bug. Prompt
renumbering in both `domain_agent.py`'s `DOMAIN_AGENT_SYSTEM_PROMPT` (new promotional-content-skip
step) and `strands_orchestrator.py`'s workflow prompt (new correct_knowledge step) is internally
consistent — no duplicate/skipped step numbers, and every tool referenced is actually in that
agent's toolset. `resolution.consult_knowledge_base`'s new `claim_id` key in each claim dict has
no caller that assumes a fixed key set — checked all 3 non-test call sites. Tool count bump (13
core tools, `CORE_TOOL_COUNT` in `tests/unit/test_strands_tools.py`) matches the actual
`strands_tools.py` tools list.

**How to apply:** When reviewing future reconciliation/dedup-engine changes in this codebase,
check whether a "no-op" resolution path leaves any persistent marker preventing the same
expensive re-computation next cycle — a silent no-op that isn't remembered is a recurring-cost
bug even when it isn't a correctness bug. Also, for any new tool that writes to the knowledge
graph from free-form LLM/conversation input (the `correct_knowledge` pattern), check that
every foreign-key-shaped parameter is validated *relationally* against the other parameters in
the same call, not just checked for existence/ownership independently — cheap now, easy to miss
once tool count grows. Xref [[project_orchestrator_ask_domain_agents_review]] for prior findings
in this same subsystem (negotiator prompt building, tracing.start_run ordering).
