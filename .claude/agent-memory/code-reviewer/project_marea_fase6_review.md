---
name: project-marea-fase6-review
description: MAREA Fase 6 review (generative-UI panels — InteractionModal/DynamicField/ActionCard/Dashboard) — found an optional-select-field validation gap and an SSE partial-result-loss pattern
metadata:
  type: project
---

Fase 6 of the MAREA liquid-UI redesign (see [[project_marea_redesign]]) built the
frontend renderers for the generative-UI protocol: `DynamicField.svelte` (widget
registry), `InteractionModal.svelte` (request_user_input), `ActionCard.svelte`
(propose_action approve/reject), `Dashboard.svelte` (read-only briefing grid), plus
two new backend GETs (`/interactions/{id}`, `/interactions/actions/{id}`) and an
`ActionProposedEvent` SSE addition. Reviewed 2026-09-10.

Two real findings, not yet fixed as of this review pass:

- **Critical** — an optional (`required=false`) `single_select` field with no
  `default`, or an optional `entity_pick` field (which can *never* have a
  `default` — forbidden by `ui_protocol.py`'s own `_check_kind_shape`
  validator), is unsubmittable. `InteractionModal.svelte`'s `onMount` seeds
  `answers[key] = ''` for any select-kind field without a default (only
  `confirm` correctly uses `undefined`, which `JSON.stringify` then drops the
  key for — the working pattern that select/entity_pick fields don't follow).
  `_validate_answer` in `app/api/routers/interactions.py` runs its per-kind
  check unconditionally once the key is present in the answer dict — it never
  re-checks `required` before validating the value against `option_ids`, and
  `''` is never `None` so even `allow_none=True` doesn't save it. Net effect:
  the only way to submit such a field is to pick a *real* option that doesn't
  reflect the user's actual (non-)answer — and if the interaction carries a
  `learn` directive, that fake pick becomes a `CONFIRMED_BY_USER/1.0`
  knowledge-graph claim. Compounding it, the 422's per-field error list never
  reaches the user — both `InteractionModal.svelte` and `ActionCard.svelte`'s
  catch blocks collapse every failure into the same generic toast
  ("No se pudo enviar la respuesta"/"No se pudo aprobar la acción"), discarding
  `err.message` (only `console.error`'d). This gap was invisible until this
  phase because Fase 2/3's `_validate_answer` unit tests and Fase 2's
  integration tests only ever exercise required fields with a real default —
  no test sends a present-but-empty key for an optional select field. Fix
  needs both sides: seed untouched select/entity_pick fields the same way
  `confirm` does (a sentinel that gets dropped, or explicit `null`), AND make
  `_validate_answer` skip the per-kind check for a non-required field holding
  an empty/`None` placeholder.
- **Warning** — `frontend/src/lib/agent.ts`'s `consumeStream()` accumulates
  `proposedActionIds`/`resolvedSessionId`/`fullAnswer` in local variables
  across the whole SSE stream, but `case 'error': throw new Error(...)` exits
  the function via exception the instant an `error` event arrives — discarding
  everything accumulated so far instead of returning it. Since `propose_action`
  commits its DB row independently of the rest of the turn succeeding, a
  turn that proposes an action and *then* hits an unrelated tool error later
  in the same turn leaves a real, durable `PROPOSED` row with zero client-side
  trace — no `ActionCard` ever renders, and there's no other UI surface that
  lists pending actions, so it just silently expires in 24h. Both callers
  (`ChatView.svelte`'s `send()`, `InteractionModal.svelte`'s `submit()`) only
  catch-and-toast, they don't attempt to recover partial results. Same root
  cause as the Critical above in spirit: an error path (backend 422, or a
  mid-turn SSE `error` event) throws away information the success path
  already collected.
- Minor/narrow, not fixed: `_extract_proposed_action_id` in
  `strands_orchestrator.py` only matches payload `status == "proposed"`, but
  `propose_action`'s idempotency-revival branch (`strands_tools.py`) can
  legitimately return an *existing* action's status as `approved`/
  `executing`/`executed` when the model re-proposes an identical payload —
  none of those emit `action_proposed`, so the client never learns that
  action_id exists. Requires a duplicate propose_action call while an
  identical one is mid-flight; narrow but not purely theoretical given the
  documented "stuck-EXECUTING-forever-on-crash" gap (`interactions.py`'s
  `approve_action` comment) means `executing` can persist a while.

Everything else checked out clean: both new GET endpoints correctly scope by
`user_id` (`interactions_store.get_interaction`'s WHERE clause,
`get_proposed_action`'s explicit `action.user_id != current_user_id` check —
verified via cross-user-404 integration tests). `_parsed_json_block` (the
json-vs-text-block asymmetry fix) handles malformed JSON and JSON scalars
correctly — `json.loads` failures are caught (`ValueError`/`TypeError`), and
`isinstance(payload, dict)` guards in both call sites. `DynamicField.svelte`
never uses `{@html}` or a markdown renderer anywhere — confirmed the "closed
vocabulary, no markup" contract holds end-to-end; its "kind not supported"
fallback is currently unreachable in practice since `FieldKind` on both sides
matches exactly (6 kinds), so no real dead-end there today (would only bite if
the protocol adds a 7th kind before the frontend catches up). `Dashboard.svelte`'s
module-level briefing cache correctly resets via `resetDashboardCache()` on
logout, and a failed initial load isn't a dead end — the refresh button
(`forceRefresh=true`) always bypasses the cache, including a previously-
rejected cached promise. `ActionCard.svelte`'s approve() error path (e.g. a
502 from "Notion workspace not configured") correctly returns to the
reviewable state (`busy=false`, `resolution` stays null) rather than getting
stuck. `WaterCanvas.svelte`'s new try/catch around `draw()` is exactly as
described — a defensive log-and-continue, nothing else touched.

See [[project_marea_fase5_review]] for the prior phase's findings (backlog-
threshold asymmetry, TTS node leak — both fixed, don't recur here) and
[[project_marea_redesign]] for overall build status.
