---
name: orchestrator-ask-domain-agents-review
description: Orchestrator "validate before answering" review (ask_domain_agents tool, _consult_peer_agents extraction) -- format-string crash in negotiator prompt building, orphaned RUNNING run on tracing.start_run reorder
metadata:
  type: project
---

Review completed 2026-09-08 of the "orchestrator validates a doubt with domain agents before
answering" feature (`app/services/agent/knowledge/domain_agent.py`'s `_ask_peer_agents` refactored
into shared `_consult_peer_agents` + new `consult_domain_agents_for_orchestrator`;
`strands_orchestrator.py`'s `tracing.start_run` moved before `_build_agent`; new `ask_domain_agents`
tool in `strands_tools.py`). No bash/git-diff access in this session — reviewed by reading the
current file state and reasoning about the described refactor, not a literal before/after diff.

**Critical found:** `_consult_peer_agents` (domain_agent.py, the negotiator-prompt-building block
right before `run_negotiation`) builds `negotiator_prompt_template` by *eagerly* embedding
`entity_name`/`question` into the string via an f-string, then calls
`negotiator_prompt_template.format(src=src)` per node. If `question` or `entity_name` contains a
literal `{`/`}` (very plausible — domain-agent prompts explicitly model attributes as
`{"email": "..."}"`, and the new `ask_domain_agents` path lets the orchestrator LLM compose
`question` from free-form conversation/document content, which regularly quotes JSON-ish or
bracketed text), `.format(src=src)` raises `KeyError`/`ValueError` on the leftover braces from the
*already-substituted* text. This is unguarded — `run_negotiation`'s own try/except only wraps
`swarm.invoke_async`, not `node_specs` construction — so it crashes `_consult_peer_agents` outright,
and neither `_ask_peer_agents`'s caller (a domain agent's `ask_peer_agents` tool, which only catches
`SQLAlchemyError`) nor `ask_domain_agents` (strands_tools.py, only catches `ValueError` from UUID
parsing) catches it — it propagates out to `agent.invoke_async`/`StrandsOrchestrator.query`'s generic
`except Exception`, failing the entire chat turn (or the domain-agent batch run). Fix: build the
template as one plain string with `{src}`/`{entity_name}`/`{question}` all as placeholders and pass
all three to a single `.format(...)` call, so user/LLM-supplied text is substituted *values*, never
re-parsed as format syntax.

**Regression risk (Warning):** `strands_orchestrator.py`'s `tracing.start_run` was intentionally moved
before `_build_agent(...)` so `run_id` can thread into `ask_domain_agents`' `parent_run_id`. But
nothing wraps the `_build_agent` call in try/except to call `tracing.finish_run(run_id,
RunStatus.FAILED, ...)` on failure — if `_build_agent` raises (e.g. `build_openai_model` or
`make_agent_tools`/`filter_tools` failure), the chat's own `AgentRun` row is left permanently
`RUNNING` with no `finished_at`, something that couldn't happen pre-reorder (no run_id existed yet at
that point). Same latent gap already exists in `run_domain_agent` (`make_domain_agent` is also called
unguarded after `start_run`) — this isn't a new *class* of bug, but it is a new instance of it for
chat runs specifically, and `_build_agent` here has materially more failure surface (multiple lazy
imports, `make_agent_tools`, `filter_tools`) than `make_domain_agent`.

**Test coverage gap:** no test exercises `StrandsOrchestrator.query()`'s actual reordered wiring
end-to-end (start_run → `_build_agent(run_id=...)` → `ask_domain_agents` sees the real chat run_id as
parent). `tests/integration/test_strands_tools_knowledge.py` only tests `make_agent_tools` directly
with a manually-constructed `chat_run`/`parent_run_id`, not `query()` itself threading its own
`start_run` result through.

**Confirmed correct / well-covered:** `_consult_peer_agents`'s core logic (question de-dup via
`_find_open_question_for_entity`, `no_peers_result` shape, `db.begin_nested()` +
`SQLAlchemyError` handling, tracing start/finish + `stats` payload, asking_source joining the swarm
only when not None) all check out against the new `TestConsultDomainAgentsForOrchestrator` tests and
the pre-existing `TestAskPeerAgentsNegotiation` regression suite — both exercise the same shared core
with real assertions on `AgentRun.stats`/`parent_run_id`, not just return-value shape. The
`ask_domain_agents` tool's docstring/contract is good on the "no invente" requirement: explicitly
tells the orchestrator LLM not to present an unresolved/low-confidence result as settled fact.

**Minor duplication:** `_ask_peer_agents`'s `if not peer_sources: return {...}` short-circuit
duplicates the exact `no_peers_result` dict literal defined inside `_consult_peer_agents` (which would
return the same shape anyway if called with an empty `peer_candidates`, just after one extra
avoidable `list_claims` query). Not worth a full flag but noted for next touch.

**Recurring pattern reinforced:** LLM-composed / document-derived text (`question`) still flows
directly into an agent system prompt without sanitization — the "prompt injection via f-string/.format
with external content" pattern tracked in [[project_agent_memory_review]] (5 prior phases). This
negotiator-prompt code is now reachable from *two* entry points (a domain agent's own `ask_peer_agents`
and the orchestrator's new `ask_domain_agents`), doubling exposure without a fix.

**How to apply:** When reviewing any future negotiator/swarm-prompt code in this codebase, check for
double-formatting (f-string pre-embedding + later `.format()`) specifically — it's an easy-to-miss
crash pattern distinct from the usual prompt-injection framing. Also check that every `tracing.start_run`
call site either has its immediately-following agent-construction step wrapped in try/except with a
matching `finish_run(FAILED)`, or explicitly accept the orphaned-RUNNING-row risk as this codebase's
existing `run_domain_agent`/`run_rd_domain_agent` do.
