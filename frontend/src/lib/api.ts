/**
 * Auth + config persistence, ported from static/voice/app.js. Same-origin
 * assumption (API_BASE = '') — the built app is served by the FastAPI app
 * itself at /marea, exactly like /voice-ui.
 */

const API_BASE = '';

const STORAGE_KEY = 'sb_api_key';
const SESSION_KEY = 'sb_session_id';
const AUTOPLAY_KEY = 'sb_autoplay';
const WAKE_KEY = 'sb_wake';
const VOICE_KEY = 'sb_tts_voice';

export interface Config {
  apiKey: string;
  sessionId: string;
  autoPlay: boolean;
  wakeEnabled: boolean;
  ttsVoice: string;
}

export function loadConfig(): Config {
  return {
    apiKey: localStorage.getItem(STORAGE_KEY) ?? '',
    sessionId: localStorage.getItem(SESSION_KEY) ?? crypto.randomUUID(),
    autoPlay: localStorage.getItem(AUTOPLAY_KEY) !== 'false',
    wakeEnabled: localStorage.getItem(WAKE_KEY) === 'true',
    ttsVoice: localStorage.getItem(VOICE_KEY) ?? 'nova',
  };
}

export function saveApiKey(apiKey: string): void {
  localStorage.setItem(STORAGE_KEY, apiKey);
}

export function clearApiKey(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function saveSessionId(sessionId: string): void {
  localStorage.setItem(SESSION_KEY, sessionId);
}

export function saveAutoPlay(value: boolean): void {
  localStorage.setItem(AUTOPLAY_KEY, String(value));
}

export function saveWakeEnabled(value: boolean): void {
  localStorage.setItem(WAKE_KEY, String(value));
}

export function saveTtsVoice(value: string): void {
  localStorage.setItem(VOICE_KEY, value);
}

export interface LoginResult {
  api_key: string;
  user_name?: string;
}

export async function login(email: string, password: string): Promise<LoginResult | null> {
  try {
    const resp = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!resp.ok) return null;
    return (await resp.json()) as LoginResult;
  } catch {
    return null;
  }
}

/** Authenticated fetch — throws with the server's `detail` message on failure. */
export async function apiFetch(apiKey: string, path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${apiKey}`);
  const resp = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}) as { detail?: string });
    throw new Error(detail.detail ?? `HTTP ${resp.status}`);
  }
  return resp;
}
