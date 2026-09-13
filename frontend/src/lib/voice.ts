/**
 * Microphone recording, live audio level, wake-word detection, and STT —
 * ported from static/voice/app.js. onLevel gives MAREA's water shader
 * (Fase 5) a real audio-driven pulse instead of the synthetic sine wave
 * the design prototype uses.
 */
import { apiFetch } from './api';

export function getAudioMimeType(): string {
  const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg'];
  return types.find((t) => MediaRecorder.isTypeSupported(t)) ?? 'audio/webm';
}

export class Recorder {
  private mediaRecorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private stream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;

  get isRecording(): boolean {
    return this.mediaRecorder?.state === 'recording';
  }

  async start(onLevel?: (level: number) => void): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.chunks = [];
    this.mediaRecorder = new MediaRecorder(this.stream, { mimeType: getAudioMimeType() });
    this.mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.chunks.push(e.data);
    };
    this.mediaRecorder.start(100);
    if (onLevel) this.watchLevel(this.stream, onLevel);
  }

  /** Stop and return the recorded audio, or null if nothing was captured. */
  stop(): Promise<Blob | null> {
    return new Promise((resolve) => {
      if (!this.mediaRecorder || this.mediaRecorder.state !== 'recording') {
        resolve(null);
        return;
      }
      const mimeType = getAudioMimeType();
      this.mediaRecorder.onstop = () => {
        this.stream?.getTracks().forEach((t) => t.stop());
        void this.audioCtx?.close();
        resolve(this.chunks.length > 0 ? new Blob(this.chunks, { type: mimeType }) : null);
      };
      this.mediaRecorder.stop();
    });
  }

  cancel(): void {
    if (this.mediaRecorder?.state === 'recording') {
      this.chunks = [];
      this.mediaRecorder.onstop = () => {
        this.stream?.getTracks().forEach((t) => t.stop());
        void this.audioCtx?.close();
      };
      this.mediaRecorder.stop();
    }
  }

  private watchLevel(stream: MediaStream, onLevel: (level: number) => void): void {
    const AudioContextCtor =
      window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.audioCtx = new AudioContextCtor();
    const analyser = this.audioCtx.createAnalyser();
    analyser.fftSize = 256;
    this.audioCtx.createMediaStreamSource(stream).connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);

    const tick = (): void => {
      if (this.mediaRecorder?.state !== 'recording') return;
      analyser.getByteTimeDomainData(data);
      let sumSquares = 0;
      for (const sample of data) sumSquares += (sample - 128) ** 2;
      const level = Math.min(1, Math.sqrt(sumSquares / data.length) / 40);
      onLevel(level);
      requestAnimationFrame(tick);
    };
    tick();
  }
}

export async function transcribe(apiKey: string, audio: Blob): Promise<string> {
  const ext = audio.type.includes('ogg') ? 'ogg' : 'webm';
  const formData = new FormData();
  formData.append('file', audio, `recording.${ext}`);
  const resp = await apiFetch(apiKey, '/voice/transcribe', { method: 'POST', body: formData });
  const data = (await resp.json()) as { transcript?: string };
  return data.transcript?.trim() ?? '';
}

const WAKE_PHRASES = ['hey brain', 'secondbrain', 'second brain', 'oye brain', 'hey secondbrain'];

/** Minimal shape of the non-standard Web Speech API this needs. */
interface SpeechRecognitionLike extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: { length: number; [i: number]: { [i: number]: { transcript: string } } } }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

export class WakeWordListener {
  private recognition: SpeechRecognitionLike | null = null;
  private enabled = false;

  get isSupported(): boolean {
    const w = window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown };
    return Boolean(w.SpeechRecognition ?? w.webkitSpeechRecognition);
  }

  start(onWake: () => void): void {
    const w = window as unknown as {
      SpeechRecognition?: new () => SpeechRecognitionLike;
      webkitSpeechRecognition?: new () => SpeechRecognitionLike;
    };
    const SR = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!SR) return;

    this.enabled = true;
    const recognition = new SR();
    this.recognition = recognition;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'es-AR';
    recognition.onresult = (event) => {
      const last = event.results[event.results.length - 1];
      const transcript = last[0].transcript.toLowerCase().trim();
      if (WAKE_PHRASES.some((phrase) => transcript.includes(phrase))) onWake();
    };
    recognition.onend = () => {
      // Checking the instance flag (not a nulled reference) closes the
      // restart race static/voice/app.js had: stop() flips this before any
      // pending restart timeout fires, even if `this.recognition` was
      // already nulled out from under this closure.
      if (this.enabled) {
        setTimeout(() => {
          try {
            recognition.start();
          } catch {
            /* already running */
          }
        }, 500);
      }
    };
    try {
      recognition.start();
    } catch {
      /* already running */
    }
  }

  stop(): void {
    this.enabled = false;
    try {
      this.recognition?.stop();
    } catch {
      /* not running */
    }
    this.recognition = null;
  }
}
