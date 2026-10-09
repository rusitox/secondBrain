---
name: project-relationship-intelligence-review
description: Review of the relationship-intelligence feature (claim_type taxonomy, get_entity_profile aggregator, /people REST API, get_person_profile chat tool, PeoplePanel.svelte) on branch feat/relationship-intelligence
metadata:
  type: project
---

Reviewed 2026-10-09, feat/relationship-intelligence worktree. Extends the existing
multi-agent knowledge graph (Entity/EntityClaim) with a passive-extraction
relationship-intelligence layer: `add_claim` gained `claim_type` (fixed taxonomy for
PERSON: role/relationship_to_user/communication_style/decision_authority/
agreement_style), a new `store.get_entity_profile` aggregator (entity + claims
grouped by claim_type newest-first + links), reused by both `GET /people`
(`app/api/routers/people.py`) and a new chat tool `get_person_profile`
(`strands_tools.py`), plus `frontend/src/components/PeoplePanel.svelte`.

**No criticals.** Ownership scoping verified clean end-to-end (get_entity_profile,
the REST detail endpoint, and the chat tool all funnel through user_id-scoped
`store.get_entity`/`get_entity_profile`; cross-user 404 tested at both the store
and endpoint level). `PEOPLE_LIST_LIMIT` cap (sort-by-confidence-then-slice
*before* profiling, fixing a real ~5s/1937-entity live perf issue) has no
off-by-one and is tested with exactly `LIMIT+5` entities. Claim grouping/sort
(newest-first within each claim_type bucket, untyped claims bucketed as
"general") is correct and well tested including a tie-breaking-by-explicit-
timestamp test (SQLite's func.now() is only second-resolution). Orchestrator
prompt renumbering (new step 3 for get_person_profile) is internally
consistent — a later step's "mismo mecanismo del paso 7" cross-reference still
points at the right step after the shift. tool_registry.py's ORCHESTRATOR_TOOLS
count (21) and strands_tools.py's CORE_TOOL_COUNT (16) both verified against the
*real* tool lists via dedicated diff tests, not just hardcoded counts — this
project's tool-count tests consistently do this right (see
[[project_phase2_agentconfig_review]] for the one place historically that
didn't). CSS (PeoplePanel's `.card`/blur/border values, `98px 44px 32px`
padding) matches Dashboard.svelte's glass-panel convention exactly.

**Findings (Warning level, nothing data-loss/security):**

1. **Stale error masks a successful retry** —
   `frontend/src/components/PeoplePanel.svelte`'s `toggle()` never clears
   `profileErrors[entityId]` before a retry fetch. If a profile fetch fails once
   (collapsed, not panel-closed) and a later re-expand succeeds, the `{:else if
   profileErrors[...]}` branch still wins over `{:else if profiles[...]}` in the
   template (checked first), so the UI shows the old error forever for that
   card until the whole panel unmounts (closing peopleOpen, not just collapsing
   the card). Fix: clear the entry at the start of a retry.

2. **N+1 + duplicated related-entity resolution, despite an existing batch
   helper** — both `app/api/routers/people.py` (GET /people/{entity_id}) and
   `strands_tools.py`'s `get_person_profile` independently loop over
   `profile["links"]` calling `store.get_entity()` once per link, instead of
   using `store.list_entities_by_ids` (already exists, docstring literally says
   "one query instead of one per id"). This reintroduces, on the detail path,
   the same N+1 anti-pattern this PR explicitly fixed on the list path — and
   is made worse by the task's own flagged pre-existing data bug (some PERSON
   entities have dozens of spurious same_as EntityLink rows from
   reconciliation.py). Also: the per-link resolution logic itself is
   copy-pasted between the router and the tool rather than folded into
   `get_entity_profile`, partially defeating that function's stated purpose as
   "the one place" that assembles a profile.

3. **claim_type is free text with zero normalization/validation** —
   `store.add_claim`/`domain_agent.add_claim` accept any string; the 5-value
   taxonomy is only described in the tool's docstring for the LLM to follow.
   A case/spelling slip (e.g. "Role" vs "role") silently lands in its own
   claim_groups bucket, invisible to `people.py`'s `_role_from_profile`
   (exact-matches lowercase "role") and sorted to the bottom by the frontend's
   hardcoded `CLAIM_TYPE_ORDER`/`claimTypeLabel` — no error, just quietly
   degraded data. Same family as the project's recurring
   "typo with no warning" pattern ([[project_phase2_agentconfig_review]]).

4. **Wake-word-triggered recording doesn't close the People panel like
   push-to-talk does** — `ChatView.svelte`'s `handlePushToTalkStart` explicitly
   resets `peopleOpen = false` before recording; `handleWake` calls
   `startRecording()` directly, skipping that reset. If wake-word is on and
   the People panel is open, saying the wake word starts recording with no
   visible indicator (the push-to-talk UI lives inside the `{:else}` branch
   peopleOpen suppresses) until the eventual `send()` call flips peopleOpen
   back off. Narrow (needs wake-word enabled + panel open) but a real,
   one-line-fix asymmetry.

**Suggestions (not urgent):** `/people` still loads every PERSON entity's full
ORM row to sort-by-confidence in Python (`store.list_entities` has no
order-by-confidence+limit option) — fine at 1937 rows, worth moving to SQL if
entity counts grow another order of magnitude. `PersonSummary.role` is
`Optional[str]=None` on the backend (serializes as JSON `null`) but typed
`role?: string` (absent, not nullable) on the frontend — harmless today since
`{#if person.role}` treats both as falsy, but imprecise.

**How to apply:** For any future knowledge-graph feature that adds a new
free-text classification field read by both a Python aggregator and a
TypeScript frontend that hardcodes the same vocabulary twice (claim_type here,
CLAIM_TYPE_ORDER/claimTypeLabel there), check whether the write path
normalizes/validates against that vocabulary — if the only enforcement is a
tool docstring the LLM might not follow exactly, that's a silent-data-quality
gap, not a crash, so it won't show up in tests unless someone writes one
exercising a near-miss value. Also: when a function is introduced specifically
to be "the one aggregation point" to avoid duplication (get_entity_profile
here), check every caller actually stops at that boundary — a sub-loop over
the aggregator's own output (the related-entity name resolution) can still get
re-implemented independently at each call site even when the aggregator itself
isn't duplicated.
