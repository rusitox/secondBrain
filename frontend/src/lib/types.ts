/**
 * TypeScript mirror of the backend's SSE event vocabulary
 * (app/api/schemas/stream.py) and the generative UI protocol
 * (app/api/schemas/ui_protocol.py). Kept in sync by hand — there is no
 * schema codegen step — so a backend field rename must be mirrored here.
 *
 * The "closed vocabulary, no markup" property from ui_protocol.py's
 * module docstring is enforced structurally on the backend (Pydantic
 * extra="forbid" + a schema-shape contract test); these types exist so
 * the frontend can't accidentally treat an unknown field `kind` as
 * something safe to render — see components/DynamicField.svelte (Fase 6)
 * for the widget registry this is designed to support, and the
 * `default:` case a switch over `kind` must always have.
 */

// ---------------------------------------------------------------------------
// SSE events (app/api/schemas/stream.py)
// ---------------------------------------------------------------------------

export type ThinkingCategory = 'AGENTE' | 'HERRAMIENTA' | 'SISTEMA' | 'RAZONAMIENTO';
export type ThinkingStatus = 'active' | 'done' | 'error';
export type StopReason = 'end_turn' | 'interrupt' | 'error';

export interface SessionEvent {
  session_id: string;
  turn_id: string;
}

export interface ThinkingEvent {
  id: string;
  category?: ThinkingCategory;
  label?: string;
  status: ThinkingStatus;
  detail?: string;
}

export interface TokenEvent {
  text: string;
}

export interface ToolResultEvent {
  id: string;
  tool: string;
  ok: boolean;
  summary: string;
}

/** The only way the client learns a propose_action call succeeded — its
 * tool_result summary is free text, not meant to be parsed. Fetch the
 * actual artifact via GET /interactions/actions/{id}. */
export interface ActionProposedEvent {
  id: string;
}

export interface ErrorEvent {
  detail: string;
}

export interface DoneEvent {
  session_id: string;
  turn_id: string;
  stop_reason: StopReason;
  iterations: number;
  tools_used: string[];
  awaiting: string[];
}

/** One item as delivered by the SSE stream — event name + typed payload. */
export type StreamEvent =
  | { event: 'session'; data: SessionEvent }
  | { event: 'thinking'; data: ThinkingEvent }
  | { event: 'token'; data: TokenEvent }
  | { event: 'tool_result'; data: ToolResultEvent }
  | { event: 'action_proposed'; data: ActionProposedEvent }
  | { event: 'done'; data: DoneEvent }
  | { event: 'error'; data: ErrorEvent };

// ---------------------------------------------------------------------------
// Generative UI protocol (app/api/schemas/ui_protocol.py) — Fase 6 renders
// these; declared here now so the SSE/interaction plumbing built in this
// phase can pass them through fully typed.
// ---------------------------------------------------------------------------

export type Kicker = 'needs_datum' | 'confirm_knowledge' | 'disambiguate' | 'review_draft';
export type FieldKind = 'single_select' | 'multi_select' | 'text' | 'confirm' | 'datetime' | 'entity_pick';
export type EntityKind = 'person' | 'project' | 'initiative' | 'topic' | 'organization';

export interface EntityRef {
  type: EntityKind;
  id: string;
}

export interface TextSpan {
  text: string;
  emphasis: 'none' | 'entity';
  ref?: EntityRef;
}

export interface Option {
  id: string;
  label: string;
  hint?: string;
  entity_id?: string;
}

export interface UIField {
  key: string;
  kind: FieldKind;
  label: string;
  required: boolean;
  help?: string;
  options?: Option[];
  default?: string;
  min_select?: number;
  max_select?: number;
  allow_none?: boolean;
  none_label?: string;
  multiline?: boolean;
  max_length?: number;
  placeholder?: string;
  affirm_label?: string;
  deny_label?: string;
  mode?: 'date' | 'time' | 'datetime';
  min_iso?: string;
  max_iso?: string;
}

export interface SourceRef {
  kind: 'knowledge_question';
  id: string;
}

export interface UIRequest {
  version: '1';
  request_id: string;
  kicker: Kicker;
  prompt: TextSpan[];
  fields: UIField[];
  submit_label: string;
  allow_dismiss: boolean;
  source?: SourceRef;
}

// ---------------------------------------------------------------------------
// Interactions API (app/api/routers/interactions.py)
// ---------------------------------------------------------------------------

export interface InteractionAnswer {
  [fieldKey: string]: unknown;
}

// ---------------------------------------------------------------------------
// Connected-systems status (app/api/schemas/systems.py) — MAREA header's
// traffic-light semaphore. The source list is never hardcoded on either
// side: it's whatever GET /systems/status actually returns.
// ---------------------------------------------------------------------------

export type SystemHealth = 'ok' | 'stale' | 'error' | 'disabled' | 'external';

export interface SystemStatusItem {
  source: string;
  health: SystemHealth;
  detail?: string;
  sync_enabled: boolean;
  last_sync_at?: string;
  last_sync_status?: string;
  next_scheduled_run?: string;
  pending_documents: number;
}

export interface SystemsStatusResponse {
  systems: SystemStatusItem[];
  sync_scheduler_active: boolean;
  knowledge_scheduler_active: boolean;
}
