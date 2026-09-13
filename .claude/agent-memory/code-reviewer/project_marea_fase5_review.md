---
name: project-marea-fase5-review
description: MAREA liquid UI Fase 5 review (systems status endpoint + water shader/state machine/header) — backlog-threshold gap and Web Audio node leak found
metadata:
  type: project
---

Fase 5 of the MAREA liquid-UI redesign (see [[project_marea_redesign]]) added
`GET /systems/status` (backend traffic-light aggregation) and the frontend
WebGL water shader + event-driven state machine + dynamic header. Reviewed
2026-09-10.

Findings from this pass, useful for later MAREA phases (Fase 6+ builds
directly on `water-engine.ts`'s `getBallScreenPositions` for orbiting agent
labels, and on `marea-state.ts`'s event-driven derivation):

- `app/api/routers/systems.py`'s two-pass merge (Integration rows, then
  connector-less `pending_documents_by_source`-only sources) only applies
  `BACKLOG_STALE_THRESHOLD` in the first pass. A source with no Integration
  row (e.g. the `rd`/knowledge-agent source) always reports health "ok"
  regardless of backlog size — the downgrade-to-"stale" rule silently
  doesn't apply to exactly the kind of source the endpoint was built to
  handle generically. Watch for this "handled once, not applied
  symmetrically to the dynamic/fallback branch" shape recurring elsewhere
  in this endpoint if it grows more per-source rules.
- `frontend/src/lib/tts.ts`'s `TTSPlayer.watchLevel()` creates a fresh
  `MediaElementAudioSourceNode` per played utterance (correct, required —
  a source node can only ever be created once per media element) but never
  disconnects it once the utterance ends. Every TTS utterance leaks one
  audio-graph node into the shared `AnalyserNode` for the life of the
  `AudioContext`. Given pipelined per-sentence playback (`enqueue`), a
  single long reply can leak several nodes; over a session this grows
  unbounded. Fix is a `.disconnect()` call in `finish()`/
  `stopWatchingLevel()`. Related, lower-likelihood bug: `stopWatchingLevel()`
  cancels the single shared `this.levelRaf` unconditionally — a stale
  watchdog `finish()` firing late for an already-stopped utterance can
  cancel a *different*, currently-playing utterance's live-level rAF loop
  if a new play starts within the watchdog's ~100ms poll window right
  after `stop()`. Narrow race, but the same shared-mutable-field-without-
  identity-guard pattern is worth checking again if this file changes.
- Everything else in this phase (WebGL context/rAF/ResizeObserver cleanup
  in `WaterCanvas.svelte`, the manual-override release paths in
  `marea-state.ts`, the shader math vs. the design handoff prototype, the
  new endpoint's auth/user-scoping) checked out clean — ported shader
  constants matched `design/design_handoff_marea/reference/IA Liquida -
  Propuestas.dc.html` verbatim, and `/systems/status` correctly scopes all
  queries to `current_user_id` (including the APScheduler job-info lookup,
  which iterates *all* users' jobs internally but the router only ever
  reads keys for the caller's own integration IDs — no cross-user leak).

See [[project_marea_redesign]] for the overall build's branch/phase status,
and the recurring-patterns memories ([[project_secondbrain_phase6]] etc.)
for this project's other common issue shapes (bare except, CancelledError,
prompt injection) — none of those recurred in this phase's files.
