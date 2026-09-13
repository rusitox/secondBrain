---
name: backoffice-ui-phase6-review
description: Phase 6 knowledge-backoffice UI review (graph focus/map mode rewrite, Conversations view, Architecture view) -- no criticals; verdict-card misleads on crashed negotiations, participant filter blind spot, missing stats test coverage
metadata:
  type: project
---

Phase 6 review completed 2026-09-08, on top of [[project_backoffice_ui_phase5_review]]. Scope: graph
view rewrite (focus/BFS-neighborhood mode + map mode with isolated-node tray) in
`static/backoffice/app.js`, new "Conversations" view (negotiation transcripts), new "Architecture"
view (mermaid diagram + actor cards), backend support (`run_query_service.list_runs`'s `top_level`
filter, `AgentRunSummary.stats` field, `finish_run(..., stats=...)` at the two negotiation call sites
in `domain_agent.py`/`reconciliation.py`).

**No CRITICALs.** Backend (`run_query_service.py`, `backoffice.py` router, `backoffice.py` schemas)
is correct: `top_level` filter, `stats` field typing (non-nullable `Dict[str, Any]` matching the
model's `server_default="{}"`), user-scoping on every query all check out. The graph rewrite's BFS
neighborhood (`graphNeighborhood`), concentric-layout distance mapping (`-dist`, correctly puts the
center node at the highest concentric value), and edge-inclusion logic (induced subgraph over the
visited set, not just the BFS tree) are all correct with no off-by-one. The Phase 5-flagged
`loadGraph()` unguarded-render bug is now fixed — `renderCurrentGraphMode()` sits inside the same
try/catch as the fetch. The Phase 5-flagged `.nav-item span:not(.nav-icon)` CSS/markup mismatch is
also fixed — nav labels are now wrapped in `<span class="nav-label">` and the CSS targets that class
directly. No missing/dead CSS classes; every id app.js references exists in index.html (verified by
cross-reading both files fully) — no broken event wiring found this pass, addressing the specific
"couldn't verify in a browser" risk flagged for this session.

Findings (this pass, all 🟡, no 🔴 or blocking issues):

- **`renderVerdictCard` (app.js) can render a crashed negotiation as a confident conclusion**: both
  negotiation call sites initialize a `verdict` dict with default values *before* the swarm runs
  (`{"resolved": False, "answer": None, "confidence": None}` for `ask_peer_agents`;
  `{"same_entity": False, "confidence": None, "reasoning": None}` for `negotiate_same_as`), and
  `record_verdict_event`/`finish_run` are called unconditionally afterward — including when
  `swarm_result is None` (the swarm itself crashed, run ends up `RunStatus.FAILED`). Because a
  `verdict` event with a payload is *always* present, `renderVerdictCard`'s `if (!payload)` fallback
  (which is the only branch that checks `run.status`) is effectively unreachable. For
  `negotiate_same_as` specifically this means a crashed reconciliation negotiation renders as
  "🧬 Veredicto de duplicado — Son entidades distintas." — a confident, wrong-looking claim for what
  was actually just a failure, in a view whose whole purpose is trustworthy observability into these
  negotiations. Fix: have `renderVerdictCard` (or `buildConversationBodyHtml`) branch on
  `run.status !== 'completed'` before trusting `verdictEvent.payload`, not just on payload presence.
- **Conversations "Filtrar por participante" silently doesn't work for reconciliation-triggered
  negotiations**: `ask_peer_agents`' Swarm node names are `f"{source}_negotiator"` (e.g.
  `slack_negotiator`), so `stats.participants` is searchable by source name as the UI's placeholder
  ("ej: slack") implies. `negotiate_same_as`'s node names are always the literal
  `entity_a_negotiator`/`entity_b_negotiator` regardless of which sources are actually involved —
  the real source lists (`sources_a`/`sources_b`) are baked into the system prompt but never make it
  into `stats`. A user filtering Conversations by source name will never find a reconciliation
  negotiation, with no indication why. Fix: add `sources_a`/`sources_b` (or similar) to
  `negotiate_same_as`'s `stats` dict and match against those too in `loadConversations`.
- **No test coverage for the new `stats` content itself**: `tests/integration/test_reconciliation.py`
  and `test_domain_agent.py` both exercise `negotiate_same_as`/`_ask_peer_agents` end-to-end against a
  real tracing DB session (confirmed `get_session_factory` is overridden in `tests/conftest.py`, so
  `tracing.finish_run` really writes rows in these tests) but only assert on the function's *return
  value*, never on the persisted `AgentRun.stats` column. `tests/unit/test_tracing.py` tests
  `finish_run(stats=...)` generically but not with the specific keys
  (`question`/`participants`/`entity_name`/`entity_a_name`/`entity_b_name`) the new Conversations UI
  actually depends on. A typo in one of those keys (e.g. `entity_a_name` → `entity_aname`) would
  silently break `buildConversationBodyHtml`'s entity-label rendering with nothing in CI catching it.
  Also true of `tests/integration/test_backoffice_api.py`: `top_level` has a dedicated test, but no
  test asserts `AgentRunSummary.stats` round-trips through `GET /backoffice/runs`.
- **Minor: Architecture view's "Ver corridas →" button double-fetches `/backoffice/runs`**:
  `switchView('runs')` synchronously fires its own dispatcher-driven `loadRuns()` (unfiltered), then
  the click handler sets `runs-type-filter.value` and calls `loadRuns()` again — two concurrent
  requests whose responses can theoretically resolve out of order (last-render-wins race), plus one
  wasted request every time. Set the filter value before calling `switchView('runs')` instead.

Confirmed fine, no action needed: escaping discipline is as strong as Phase 5 found it (every new
template literal in the graph/conversation/architecture render functions escapes user/agent-controlled
strings; `ARCH_DIAGRAM` is a static constant so mermaid's `securityLevel: 'strict'` isn't covering any
actual untrusted input); `cy` instance lifecycle (destroy-before-rebuild on every `loadGraph()`, and on
every mode switch) has no leak or stale-state bug; drill-down navigation between Runs/Conversations
(`selectRun`'s shared `containerId` param, `wireRunDetailEvents`'s back/jump actions) correctly handles
both "negotiation viewed inside a parent run's sub_runs list" and "negotiation viewed directly from the
Conversations list" cases, including that a negotiation's `parent_run_id` is always a top-level run
(so "jump to runs" navigation's assumption that the parent is in the `top_level=true` list always holds).
