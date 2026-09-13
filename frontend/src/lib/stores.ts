import { writable } from 'svelte/store';
import { loadConfig, saveAutoPlay, saveSessionId, saveTtsVoice, saveWakeEnabled } from './api';
import type { ThinkingEvent } from './types';

const initial = loadConfig();

export const apiKey = writable<string>(initial.apiKey);
export const sessionId = writable<string>(initial.sessionId);

export const autoPlay = writable<boolean>(initial.autoPlay);
autoPlay.subscribe((v) => saveAutoPlay(v));

export const wakeEnabled = writable<boolean>(initial.wakeEnabled);
wakeEnabled.subscribe((v) => saveWakeEnabled(v));

export const ttsVoice = writable<string>(initial.ttsVoice);
ttsVoice.subscribe((v) => saveTtsVoice(v));

export const isStreaming = writable<boolean>(false);

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
}

export const messages = writable<ChatMessage[]>([]);

/** Live "thinking process" rows for the turn currently in flight — cleared
 * at the start of each new question. Keyed by id so a "done"/"error"
 * status update for the same id replaces its row in place. */
export const thinkingSteps = writable<ThinkingEvent[]>([]);

export function upsertThinkingStep(event: ThinkingEvent): void {
  thinkingSteps.update((steps) => {
    const idx = steps.findIndex((s) => s.id === event.id);
    if (idx === -1) return [...steps, event];
    const next = steps.slice();
    const prev = next[idx];
    // The reasoning row's "active" emissions each carry only the new delta
    // (see ThinkingEvent's docstring in app/api/schemas/stream.py) — every
    // other row (tool calls) sends one complete label once, and any row's
    // terminal "done"/"error" emission carries its own full text. Appending
    // is only correct for id="reasoning" while both the previous and new
    // emission are "active"; anything else replaces.
    const isReasoningDelta =
      event.id === 'reasoning' && event.status === 'active' && prev.status === 'active';
    const label = isReasoningDelta ? (prev.label ?? '') + (event.label ?? '') : (event.label ?? prev.label);
    next[idx] = { ...prev, ...event, label };
    return next;
  });
}

/** Reset per-conversation UI state — call on logout so a different user
 * logging in on the same machine never sees the previous user's chat
 * history, session, or in-flight thinking steps. */
export function resetChatState(): void {
  messages.set([]);
  thinkingSteps.set([]);
  const fresh = crypto.randomUUID();
  sessionId.set(fresh);
  saveSessionId(fresh); // otherwise the old user's id survives in localStorage until the next turn completes
}

export interface ToastState {
  message: string;
  id: number;
}

export const toast = writable<ToastState | null>(null);
let toastCounter = 0;

export function showToast(message: string, durationMs = 2800): void {
  const id = ++toastCounter;
  toast.set({ message, id });
  setTimeout(() => {
    toast.update((current) => (current?.id === id ? null : current));
  }, durationMs);
}
