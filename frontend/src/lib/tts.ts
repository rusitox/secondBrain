/**
 * TTS playback pipeline — gapless: every fetched fragment is decoded into
 * an AudioBuffer and scheduled back-to-back on ONE shared AudioContext
 * (via AudioBufferSourceNode.start(exactTime)), instead of queuing
 * separate <audio> elements. Playing discrete <audio> elements in
 * sequence has its own per-element startup latency that shows up as an
 * audible gap between fragments no matter how well the next fetch is
 * prefetched — scheduling buffers on a single audio clock is the standard
 * way to eliminate that entirely. It also collapses the audio graph to
 * ONE persistent AudioContext + AnalyserNode (shared by every fragment)
 * instead of a fresh createMediaElementSource dance per utterance, which
 * both simplifies the level-monitoring loop and removes the failure mode
 * where a freshly-created/auto-suspended AudioContext silently drops all
 * audio routed through it with no error at all (a real bug this app hit).
 *
 * Cancellation still uses a monotonic generation counter: stopping
 * (barge-in, a new question, or an explicit stop) increments it, and
 * every in-flight fetch checks its own captured generation against the
 * current one before doing anything user-visible.
 */
import { apiFetch } from './api';

function stripMarkdown(text: string): string {
  return text
    .replace(/#{1,6}\s+/g, '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\*(.*?)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^[-*+]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .trim();
}

type AudioContextCtor = typeof AudioContext;

export class TTSPlayer {
  private generation = 0;
  private queue: Promise<ArrayBuffer | null>[] = [];
  private draining = false;
  private audioCtx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  // Audio-clock cursor (in this.audioCtx's own time base) for the next
  // scheduled fragment — always advanced to the previous fragment's exact
  // end, which is what makes back-to-back playback gapless.
  private nextStartTime = 0;
  private activeSources = new Set<AudioBufferSourceNode>();
  private levelRafId: number | null = null;
  // Count of fragments enqueued but not yet finished (played, cancelled,
  // or failed) — drives onActiveChange. Deliberately NOT derived from the
  // live analyser level (onLevel): a real speech pause, or the moment
  // between one fragment ending and the next one's decode finishing,
  // drops the level to 0 for an instant even though the turn is still
  // very much "speaking". MAREA's visual state must not flicker to idle
  // during that gap.
  private activeCount = 0;

  constructor(
    private getApiKey: () => string,
    private getVoice: () => string,
    // Real audio-driven pulse for the water shader's "respond" state — the
    // design prototype simulates this with a sine wave; onLevel gives it
    // the actual playing audio's amplitude instead. Optional: TTS still
    // works with no water canvas listening.
    private onLevel?: (level: number) => void,
    // Whether this player has any fragment enqueued, playing, or pending
    // fetch/decode — for driving "is MAREA speaking" independently of the
    // noisy, instant-by-instant audio level (see activeCount above).
    private onActiveChange?: (active: boolean) => void,
  ) {}

  /** Create/resume the AudioContext — call this SYNCHRONOUSLY from inside a
   * real user-gesture handler (pointerdown on push-to-talk, click on
   * "Enviar"), before any `await`. Some browsers (notably Safari/WebKit)
   * only allow an AudioContext to start/resume when that happens within
   * the same task as the gesture itself — by the time enqueue() runs, a
   * whole network round trip (STT, agent streaming) has already elapsed,
   * which is too late for those browsers even though `resume()` is also
   * called defensively in ensureContext() on every use. Safe to call any
   * time, including if a context already exists — it's a no-op resume(). */
  unlock(): void {
    this.ensureContext();
  }

  /** Queue a fragment for pipelined, gapless playback (used while a reply streams in). */
  enqueue(text: string): void {
    const gen = this.generation;
    this.markActive();
    this.queue.push(this.fetchBytes(text, gen));
    void this.drain();
  }

  private markActive(): void {
    this.activeCount++;
    if (this.activeCount === 1) this.onActiveChange?.(true);
  }

  private markUtteranceDone(): void {
    this.activeCount = Math.max(0, this.activeCount - 1);
    if (this.activeCount === 0) this.onActiveChange?.(false);
  }

  /** Fetch-and-play a single utterance immediately (the "▶ reproducir" button). */
  async playOnce(text: string): Promise<void> {
    const gen = this.generation;
    const bytes = await this.fetchBytes(text, gen);
    if (!bytes || gen !== this.generation) return;
    const ctx = this.ensureContext();
    let audioBuffer: AudioBuffer;
    try {
      audioBuffer = await ctx.decodeAudioData(bytes);
    } catch (err) {
      console.error('MAREA TTS: decodeAudioData failed', err);
      return;
    }
    if (gen !== this.generation) return;
    await this.playBufferNow(audioBuffer);
  }

  /** Cancel everything in-flight, queued, or scheduled/playing. */
  stop(): void {
    this.generation++;
    this.queue = [];
    const wasActive = this.activeCount > 0;
    this.activeCount = 0;
    for (const source of this.activeSources) {
      try {
        source.stop();
      } catch {
        // Already stopped/ended — nothing to do.
      }
    }
    this.activeSources.clear();
    this.nextStartTime = 0;
    this.stopLevelLoop();
    if (wasActive) this.onActiveChange?.(false);
  }

  private async fetchBytes(text: string, gen: number): Promise<ArrayBuffer | null> {
    const clean = stripMarkdown(text);
    if (!clean.trim()) return null;
    try {
      const resp = await apiFetch(this.getApiKey(), '/voice/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: clean, voice: this.getVoice() }),
      });
      if (gen !== this.generation) return null;
      const buf = await resp.arrayBuffer();
      if (gen !== this.generation) return null;
      return buf;
    } catch {
      return null;
    }
  }

  private ensureContext(): AudioContext {
    if (!this.audioCtx) {
      const Ctor =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext: AudioContextCtor }).webkitAudioContext;
      this.audioCtx = new Ctor();
    }
    if (!this.analyser) {
      this.analyser = this.audioCtx.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.connect(this.audioCtx.destination);
    }
    // A freshly-created (or browser-auto-suspended, e.g. after
    // backgrounding the tab) AudioContext starts/goes "suspended",
    // silently dropping all audio scheduled on it — nothing throws or
    // errors, it just never reaches the speakers. Resuming defensively
    // before every use is the standard fix (a safe no-op if already running).
    void this.audioCtx.resume();
    return this.audioCtx;
  }

  /** Decode fetched fragments as they arrive and schedule them back-to-back
   * — only the fetch+decode is awaited here (fast), not playback itself,
   * so the queue keeps pipelining exactly like before this rewrite. */
  private async drain(): Promise<void> {
    if (this.draining) return;
    this.draining = true;

    while (this.queue.length > 0) {
      const bytesPromise = this.queue.shift();
      if (!bytesPromise) continue;
      const gen = this.generation;
      const bytes = await bytesPromise;
      if (!bytes || gen !== this.generation) {
        this.markUtteranceDone();
        continue;
      }

      let audioBuffer: AudioBuffer;
      try {
        const ctx = this.ensureContext();
        audioBuffer = await ctx.decodeAudioData(bytes);
      } catch (err) {
        console.error('MAREA TTS: decodeAudioData failed', err);
        this.markUtteranceDone();
        continue;
      }
      if (gen !== this.generation) {
        this.markUtteranceDone();
        continue;
      }

      this.scheduleBuffer(audioBuffer, gen);
    }

    this.draining = false;
  }

  /** Schedule one decoded fragment to start exactly where the previous one
   * ends (or now, if nothing is queued) — the actual gapless mechanism.
   * Fire-and-forget: does not block drain()'s loop on playback finishing. */
  private scheduleBuffer(audioBuffer: AudioBuffer, gen: number): void {
    const ctx = this.ensureContext();
    if (ctx.state !== 'running') {
      // Should be rare after unlock()'s synchronous resume() — if this
      // still fires, the browser is refusing to resume outside a gesture
      // even via unlock(), and audio will be silent despite everything
      // else succeeding (fetch, decode, schedule all report no error).
      console.warn('MAREA TTS: AudioContext state is', ctx.state, '— audio may not be audible');
    }
    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    if (this.analyser) source.connect(this.analyser);

    const startAt = Math.max(ctx.currentTime, this.nextStartTime);
    this.nextStartTime = startAt + audioBuffer.duration;

    this.activeSources.add(source);
    this.startLevelLoop();
    source.onended = () => {
      this.activeSources.delete(source);
      // A stale onended from a generation stop() already tore down must
      // not double-decrement activeCount — stop() already zeroed it.
      if (gen === this.generation) this.markUtteranceDone();
    };
    source.start(startAt);
  }

  /** Used only by playOnce() — schedules immediately and awaits its own end. */
  private playBufferNow(audioBuffer: AudioBuffer): Promise<void> {
    const ctx = this.ensureContext();
    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    if (this.analyser) source.connect(this.analyser);
    this.activeSources.add(source);
    this.startLevelLoop();
    return new Promise((resolve) => {
      source.onended = () => {
        this.activeSources.delete(source);
        resolve();
      };
      source.start(ctx.currentTime);
    });
  }

  /** One continuous level-monitoring loop shared by every scheduled
   * fragment — replaces the old per-utterance watch/cleanup dance, since
   * every fragment now flows through the same persistent analyser. Starts
   * itself on demand and stops itself once nothing is playing/scheduled. */
  private startLevelLoop(): void {
    if (this.levelRafId !== null || !this.onLevel || !this.analyser) return;
    const analyser = this.analyser;
    const data = new Uint8Array(analyser.frequencyBinCount);
    const tick = (): void => {
      analyser.getByteTimeDomainData(data);
      let sumSquares = 0;
      for (const sample of data) sumSquares += (sample - 128) ** 2;
      const level = Math.min(1, Math.sqrt(sumSquares / data.length) / 40);
      this.onLevel?.(level);
      if (this.activeSources.size > 0) {
        this.levelRafId = requestAnimationFrame(tick);
      } else {
        this.levelRafId = null;
        this.onLevel?.(0);
      }
    };
    this.levelRafId = requestAnimationFrame(tick);
  }

  private stopLevelLoop(): void {
    if (this.levelRafId !== null) {
      cancelAnimationFrame(this.levelRafId);
      this.levelRafId = null;
    }
    this.onLevel?.(0);
  }
}
