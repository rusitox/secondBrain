/**
 * Orchestrates one agent turn — either a fresh question (POST /agent/
 * stream) or an answer resuming a paused one (POST /interactions/{id}/
 * answer) — through the same typed SSE stream (sse.ts) and event handling,
 * so the two entry points genuinely are "one streaming code path" rather
 * than two copies that drift.
 */
import { streamPost } from './sse';
import { messages, upsertThinkingStep } from './stores';
import type { TTSPlayer } from './tts';
import type { DoneEvent, StreamEvent } from './types';

// Bundling ~2-3 sentences per TTS call instead of one gives OpenAI's
// synthesis actual sentence-to-sentence context to work with — a lone
// sentence sent in isolation has nowhere to carry natural prosody from/to,
// which is a real contributor to the "robotic" quality on top of the
// inter-fragment playback gap (see tts.ts's gapless scheduling rewrite).
const TTS_MIN_CHUNK_CHARS = 160;
// Hard ceiling regardless of sentence boundaries or chunk size — the
// safety valve that guarantees the buffer empties no matter what (see
// flushTTS's markdown-guard comment for why this must never be blocked).
const TTS_MAX_CHUNK_CHARS = 320;

/** True when `text` ends mid-markdown-marker — an odd number of `**` bold
 * delimiters, an odd number of standalone `*` (italic) markers once bold
 * pairs AND leading list-item markers ("* item") are stripped out, or an
 * odd number of backticks. Streamed answers routinely have a `**bold**`
 * span or a code span straddle two token chunks; flushing the first half
 * to TTS leaves a literal, spoken-aloud asterisk or backtick in the other
 * half once stripMarkdown runs on it per-fragment. Not exhaustive markdown
 * parsing — just enough to tell "wait for the closing marker" from "this
 * fragment is clean". List markers are stripped before counting single
 * stars because a bullet list with an odd number of items (extremely
 * common) would otherwise read as a permanently-unclosed italic span. */
function hasUnbalancedMarkdown(text: string): boolean {
  const boldMarkerCount = (text.match(/\*\*/g) ?? []).length;
  if (boldMarkerCount % 2 !== 0) return true;
  const withoutBoldPairs = text.replace(/\*\*/g, '');
  const withoutListMarkers = withoutBoldPairs.replace(/^[ \t]*\*[ \t]+/gm, '');
  const remainingStars = (withoutListMarkers.match(/\*/g) ?? []).length;
  if (remainingStars % 2 !== 0) return true;
  const backtickCount = (text.match(/`/g) ?? []).length;
  return backtickCount % 2 !== 0;
}

export interface AgentTurnResult {
  answer: string;
  sessionId: string;
  stopReason: string;
  awaiting: string[];
  proposedActionIds: string[];
}

/** Thrown when the stream ends with an "error" event. Carries whatever the
 * turn had already produced up to that point — in particular
 * proposedActionIds, since propose_action commits its row independently of
 * the rest of the turn succeeding (app/services/agent/strands_tools.py): a
 * turn that proposes an action and then hits an unrelated failure later
 * must not silently drop the client's only way to learn that action_id
 * exists (it would otherwise just sit unseen until its 24h expiry). */
export class AgentStreamError extends Error {
  constructor(
    message: string,
    public readonly partial: Pick<AgentTurnResult, 'proposedActionIds' | 'sessionId'>,
  ) {
    super(message);
    this.name = 'AgentStreamError';
  }
}

async function consumeStream(
  stream: AsyncGenerator<StreamEvent>,
  assistantId: string,
  tts: TTSPlayer,
  autoPlay: boolean,
  initialSessionId: string,
): Promise<AgentTurnResult> {
  let fullAnswer = '';
  let sentenceBuf = '';
  let ttsStreamed = false;
  let resolvedSessionId = initialSessionId;
  let doneEvent: DoneEvent | null = null;
  const proposedActionIds: string[] = [];

  const flushTTS = (force = false): void => {
    if (!sentenceBuf.trim()) return;
    // A digit-preceded '.'/'?'/'!' is a decimal point ("$3.5M", "28.5%"),
    // not a sentence boundary — don't flush there.
    const sentenceEnded = /(?<!\d)[.?!]\s*$/.test(sentenceBuf);
    const readyOnSentenceEnd = sentenceEnded && sentenceBuf.length >= TTS_MIN_CHUNK_CHARS;
    const tooLong = sentenceBuf.length > TTS_MAX_CHUNK_CHARS;
    if (!force && !readyOnSentenceEnd && !tooLong) return;
    // Wait for the closing marker rather than sending a fragment with a
    // dangling markdown delimiter — but ONLY when a sentence boundary is
    // what triggered this flush. The length fallback exists specifically
    // to guarantee the buffer empties no matter what; letting the markdown
    // guard override it let an unresolved imbalance (e.g. a bullet list
    // with an odd item count, which never "closes") grow the buffer
    // without limit until it exceeded /voice/speak's 4096-char limit and
    // failed outright — silencing the whole turn's audio.
    if (!force && sentenceEnded && !tooLong && hasUnbalancedMarkdown(sentenceBuf)) return;
    const text = sentenceBuf.trim();
    sentenceBuf = '';
    if (autoPlay) {
      ttsStreamed = true;
      tts.enqueue(text);
    }
  };

  for await (const evt of stream) {
    switch (evt.event) {
      case 'session':
        resolvedSessionId = evt.data.session_id;
        break;
      case 'thinking':
        upsertThinkingStep(evt.data);
        break;
      case 'token':
        fullAnswer += evt.data.text;
        sentenceBuf += evt.data.text;
        flushTTS();
        updateAssistantMessage(assistantId, fullAnswer);
        break;
      case 'tool_result':
        // The matching "thinking" event (same id) already carries status —
        // nothing else to render here.
        break;
      case 'action_proposed':
        proposedActionIds.push(evt.data.id);
        break;
      case 'done':
        doneEvent = evt.data;
        resolvedSessionId = evt.data.session_id || resolvedSessionId;
        flushTTS(true);
        break;
      case 'error':
        throw new AgentStreamError(evt.data.detail || 'Agent error', {
          proposedActionIds, sessionId: resolvedSessionId,
        });
    }
  }

  if (!ttsStreamed && autoPlay && fullAnswer) {
    tts.enqueue(fullAnswer);
  }

  return {
    answer: fullAnswer,
    sessionId: resolvedSessionId,
    stopReason: doneEvent?.stop_reason ?? 'end_turn',
    awaiting: doneEvent?.awaiting ?? [],
    proposedActionIds,
  };
}

function updateAssistantMessage(id: string, text: string): void {
  messages.update((list) => list.map((m) => (m.id === id ? { ...m, text } : m)));
}

function startAssistantMessage(): string {
  const id = crypto.randomUUID();
  messages.update((m) => [...m, { id, role: 'assistant', text: '' }]);
  return id;
}

export async function askQuestion(
  apiKey: string,
  question: string,
  sessionId: string,
  tts: TTSPlayer,
  autoPlay: boolean,
): Promise<AgentTurnResult> {
  const assistantId = startAssistantMessage();
  const stream = await streamPost('/agent/stream', apiKey, { question, session_id: sessionId });
  return consumeStream(stream, assistantId, tts, autoPlay, sessionId);
}

export async function answerInteraction(
  apiKey: string,
  interactionId: string,
  answer: Record<string, unknown>,
  sessionId: string,
  tts: TTSPlayer,
  autoPlay: boolean,
): Promise<AgentTurnResult> {
  const assistantId = startAssistantMessage();
  const stream = await streamPost(`/interactions/${interactionId}/answer`, apiKey, { answer });
  return consumeStream(stream, assistantId, tts, autoPlay, sessionId);
}
