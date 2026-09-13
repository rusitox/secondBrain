/**
 * MAREA's conversation-state machine: idle | listen | think | respond |
 * panel. Two ways a state gets set:
 *
 * - Event-driven (the real production path): deriveMareaState() is a pure
 *   function of real signals (recording, streaming, an active thinking
 *   step, a pending interaction, TTS playback) — see ChatView.svelte's
 *   reactive statement that feeds it. This is what actually reflects
 *   "what MAREA is doing" during real use.
 * - Manual: the state chips + tapping the water (design spec: "Chips:
 *   saltan a un estado directo y desactivan el auto" / "Tap sobre el
 *   agua: avanza al siguiente estado"). Setting mareaManualOverride
 *   suspends the event-driven derivation until the next real interaction
 *   (starting to record, or sending a question) releases it — see
 *   ChatView.svelte's startRecording()/send().
 *
 * autoDemo is the prototype's automatic state-cycling, explicitly scoped
 * as a debug/demo aid only (per the Fase 5 plan) — never turned on by
 * default, and releasing manual override also turns it off.
 */
import { get, writable } from 'svelte/store';
import type { MareaVisualState } from './water-engine';

export const mareaState = writable<MareaVisualState>('idle');
export const mareaManualOverride = writable<boolean>(false);
export const mareaAutoDemo = writable<boolean>(false);

const ORDER: MareaVisualState[] = ['idle', 'listen', 'think', 'respond', 'panel'];
// Same order and rough proportions as the design prototype's demo cycle
// (reposo 3000ms / escucha 3400 / pensando 3400 / respuesta 5800 / panel
// 8000), for a convincing debug preview of every state's morphosis.
const AUTO_DEMO_DURATIONS_MS: Record<MareaVisualState, number> = {
  idle: 3000,
  listen: 3400,
  think: 3400,
  respond: 5800,
  panel: 8000,
};

export function setMareaState(state: MareaVisualState, opts: { manual?: boolean } = {}): void {
  if (opts.manual) mareaManualOverride.set(true);
  mareaState.set(state);
}

/** Returns control to the event-driven derivation — call this from any
 * real interaction (recording, sending a question) so a chip/demo choice
 * doesn't freeze the water forever. */
export function releaseMareaManualOverride(): void {
  mareaManualOverride.set(false);
  stopAutoDemo();
}

function advanceMareaState(): void {
  const current = get(mareaState);
  const idx = ORDER.indexOf(current);
  setMareaState(ORDER[(idx + 1) % ORDER.length], { manual: true });
}

let autoDemoTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleNextAutoDemoTick(): void {
  const current = get(mareaState);
  autoDemoTimer = setTimeout(() => {
    advanceMareaState();
    if (get(mareaAutoDemo)) scheduleNextAutoDemoTick();
  }, AUTO_DEMO_DURATIONS_MS[current]);
}

export function toggleAutoDemo(): void {
  const next = !get(mareaAutoDemo);
  mareaAutoDemo.set(next);
  if (next) {
    mareaManualOverride.set(true);
    scheduleNextAutoDemoTick();
  } else {
    stopAutoDemo();
  }
}

function stopAutoDemo(): void {
  mareaAutoDemo.set(false);
  if (autoDemoTimer !== null) {
    clearTimeout(autoDemoTimer);
    autoDemoTimer = null;
  }
}

export interface MareaDeriveInput {
  recording: boolean;
  isStreaming: boolean;
  hasActiveThinkingStep: boolean;
  hasPendingInteraction: boolean;
  ttsPlaying: boolean;
}

/** The real, event-driven mapping from app state to a MAREA visual state.
 * "respond" covers both the spoken/streamed answer AND the data-request
 * modal — per the design handoff's own production-vs-prototype note, the
 * modal is not a separate visual state, just something that can be
 * showing *while* in "respond". */
export function deriveMareaState(input: MareaDeriveInput): MareaVisualState {
  if (input.recording) return 'listen';
  if (input.hasPendingInteraction) return 'respond';
  if (input.isStreaming) return input.hasActiveThinkingStep ? 'think' : 'respond';
  if (input.ttsPlaying) return 'respond';
  return 'idle';
}
