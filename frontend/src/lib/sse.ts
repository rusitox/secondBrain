/**
 * Server-Sent Events client — hand-parsed via fetch() + ReadableStream
 * instead of EventSource, because EventSource cannot send an Authorization
 * header and this API requires a Bearer token. One implementation serves
 * both /agent/stream and /interactions/{id}/answer (app/api/schemas/
 * stream.py's EVENT_SCHEMAS is the single vocabulary both endpoints share),
 * so the frontend has exactly one streaming code path regardless of
 * whether a turn started fresh or resumed from an interrupt.
 *
 * Fixes a real bug from static/voice/app.js: there, `evtName` was declared
 * inside the per-chunk read loop, so an `event:` line arriving at the very
 * end of one network chunk had its name silently discarded if the
 * matching `data:` line arrived in the next chunk — a real, if rare, way
 * to drop events under normal network chunking. Declaring it once for the
 * whole stream (and resetting only after each completed event) fixes that.
 */
import type { StreamEvent } from './types';

export async function* parseSSE(response: Response): AsyncGenerator<StreamEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let evtName = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() ?? '';

    for (const line of lines) {
      if (line.startsWith('event:')) {
        evtName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        const raw = line.slice(5).trim();
        let payload: unknown;
        try {
          payload = JSON.parse(raw);
        } catch {
          continue;
        }
        if (evtName) {
          yield { event: evtName, data: payload } as StreamEvent;
        }
        evtName = '';
      }
      // A blank line is the SSE frame terminator — nothing to do beyond
      // what the data: branch above already did.
    }
  }
}

/** POST `body` to `path` and stream the typed SSE response. */
export async function streamPost(
  path: string,
  apiKey: string,
  body: unknown,
): Promise<AsyncGenerator<StreamEvent>> {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}) as { detail?: string });
    throw new Error(detail.detail ?? `HTTP ${resp.status}`);
  }
  return parseSSE(resp);
}
