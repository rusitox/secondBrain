<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { AgentStreamError, askQuestion } from '../lib/agent';
  import { clearApiKey, saveSessionId } from '../lib/api';
  import { resetDashboardCache } from '../lib/dashboard';
  import {
    deriveMareaState,
    mareaAutoDemo,
    mareaManualOverride,
    mareaState,
    releaseMareaManualOverride,
    setMareaState,
    toggleAutoDemo,
  } from '../lib/marea-state';
  import {
    apiKey,
    autoPlay,
    isStreaming,
    messages,
    resetChatState,
    sessionId,
    showToast,
    thinkingSteps,
    ttsVoice,
    wakeEnabled,
  } from '../lib/stores';
  import { TTSPlayer } from '../lib/tts';
  import { Recorder, transcribe, WakeWordListener } from '../lib/voice';
  import ActionCard from './ActionCard.svelte';
  import Dashboard from './Dashboard.svelte';
  import InteractionModal from './InteractionModal.svelte';
  import SystemsHeader from './SystemsHeader.svelte';
  import WaterCanvas from './WaterCanvas.svelte';
  import type { MareaVisualState } from '../lib/water-engine';

  const VOICES = ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'];
  const STATE_CHIPS: { state: MareaVisualState; label: string }[] = [
    { state: 'idle', label: 'Reposo' },
    { state: 'listen', label: 'Escucha' },
    { state: 'think', label: 'Pensando' },
    { state: 'respond', label: 'Respuesta' },
    { state: 'panel', label: 'Panel' },
  ];

  // State chips + the AUTO demo cycle are a QA/debug tool (per
  // marea-state.ts's own docstring) for previewing every MAREA visual
  // state on demand — not a real end-user control, since the real state
  // already derives automatically from what's actually happening. Hidden
  // from the normal UI; reachable via ?debug in the URL for whoever needs
  // to eyeball a specific state again.
  const debugMode = typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('debug');

  let question = '';
  let audioLevel = 0;
  let ttsLevel = 0;
  let ttsPlaying = false;
  let recording = false;
  let processing = false;
  let chatEl: HTMLElement | undefined;
  // Design item 1 — chat is a dismissible deck over the water, not a
  // co-equal layout column: closed by default, opened by the toolbar icon
  // or automatically the moment the user asks something (so a typed
  // question's answer is never invisible), and closable at any time.
  let chatDeckOpen = false;

  // Only the first is actually rendered as a modal (see the template) —
  // Strands' one-snapshot-per-session limitation (strands_orchestrator.py's
  // _finalize_turn) means multiple simultaneous interrupts from one turn
  // aren't independently resumable yet, so answering more than one at a
  // time isn't reliable regardless of what the UI offers.
  let pendingInteractionIds: string[] = [];
  // Unlike interactions, propose_action never interrupts the turn, so more
  // than one really can be genuinely independent and open at once.
  let proposedActionIds: string[] = [];

  const recorder = new Recorder();
  const wakeWord = new WakeWordListener();
  const tts = new TTSPlayer(
    () => $apiKey,
    () => $ttsVoice,
    // Drives the shader's audio-reactive pulse — noisy on purpose, tracks
    // the instant amplitude including natural pauses in speech.
    (level) => {
      ttsLevel = level;
    },
    // Drives MAREA's visual state — "is a TTS turn in progress", not
    // "is there sound RIGHT NOW". A pause between sentences or within one
    // must not drop the state back to idle mid-answer.
    (active) => {
      ttsPlaying = active;
    },
  );

  // Event-driven MAREA visual state — the real production path (see
  // lib/marea-state.ts's module docstring). Suspended while a chip or the
  // debug auto-demo has manual control.
  $: if (!$mareaManualOverride) {
    setMareaState(
      deriveMareaState({
        recording,
        isStreaming: $isStreaming,
        hasActiveThinkingStep: $thinkingSteps.some((s) => s.status === 'active'),
        hasPendingInteraction: pendingInteractionIds.length > 0 || proposedActionIds.length > 0,
        ttsPlaying,
      }),
    );
  }
  $: liveLevel = recording ? audioLevel : ttsLevel;

  function scrollToBottom(): void {
    requestAnimationFrame(() => {
      chatEl?.scrollTo({ top: chatEl.scrollHeight });
    });
  }

  $: if ($messages) scrollToBottom();

  onMount(() => {
    if ($wakeEnabled) wakeWord.start(handleWake);
  });

  onDestroy(() => {
    wakeWord.stop();
    tts.stop();
  });

  function handleWake(): void {
    if (!$isStreaming && !recording) {
      showToast('Wake word detectado');
      void startRecording();
    }
  }

  async function startRecording(): Promise<void> {
    if ($isStreaming) return;
    releaseMareaManualOverride();
    try {
      await recorder.start((level) => {
        audioLevel = level;
      });
      recording = true;
    } catch {
      showToast('No se pudo acceder al micrófono');
    }
  }

  async function stopRecording(): Promise<void> {
    recording = false;
    processing = true;
    const blob = await recorder.stop();
    processing = false;
    if (!blob) return;
    try {
      const transcript = await transcribe($apiKey, blob);
      if (transcript) {
        question = transcript;
        await send();
      } else {
        showToast('No se detectó audio. Intentá de nuevo.');
      }
    } catch {
      showToast('Error al transcribir el audio');
    }
  }

  // Design item 2 — push-to-talk replaces the footer mic toggle: recording
  // runs only while the control is actively pressed/held, not start/stop
  // on separate clicks. pointerdown/up (not click) so it also works for
  // touch and mouse the same way, and pointerleave/pointercancel stop a
  // press that drags off the control or gets interrupted (e.g. a system
  // gesture) instead of leaving the mic stuck open.
  function handlePushToTalkStart(): void {
    if (recording || processing || $isStreaming) return;
    // Must happen synchronously in this gesture handler, not later inside
    // the async TTS pipeline — some browsers only allow the AudioContext
    // used for gapless playback to start/resume within the same task as a
    // real user gesture (see TTSPlayer.unlock's docstring).
    tts.unlock();
    void startRecording();
  }

  function handlePushToTalkEnd(): void {
    if (recording) void stopRecording();
  }

  async function send(): Promise<void> {
    const text = question.trim();
    if (!text || $isStreaming) return;
    // Same reasoning as handlePushToTalkStart — synchronous, before any
    // await, so the "Enviar" click also counts as the gesture that's
    // allowed to start/resume the AudioContext on stricter browsers.
    tts.unlock();
    question = '';
    releaseMareaManualOverride();

    messages.update((m) => [...m, { id: crypto.randomUUID(), role: 'user', text }]);
    isStreaming.set(true);
    chatDeckOpen = true;
    tts.stop();

    try {
      const result = await askQuestion($apiKey, text, $sessionId, tts, $autoPlay);
      sessionId.set(result.sessionId);
      saveSessionId(result.sessionId);
      pendingInteractionIds = result.awaiting;
      addProposedActionIds(result.proposedActionIds);
    } catch (err) {
      if (err instanceof AgentStreamError) addProposedActionIds(err.partial.proposedActionIds);
      showToast(err instanceof Error && err.message ? err.message : 'Error al procesar la consulta');
      console.error(err);
    } finally {
      isStreaming.set(false);
    }
  }

  function addProposedActionIds(ids: string[]): void {
    if (ids.length === 0) return;
    proposedActionIds = [...new Set([...proposedActionIds, ...ids])];
  }

  function handleInteractionResolved(
    e: CustomEvent<{ awaiting: string[]; proposedActionIds: string[] }>,
  ): void {
    releaseMareaManualOverride();
    pendingInteractionIds = e.detail.awaiting;
    addProposedActionIds(e.detail.proposedActionIds);
  }

  function handleInteractionDismissed(id: string): void {
    pendingInteractionIds = pendingInteractionIds.filter((x) => x !== id);
  }

  function handleActionResolved(id: string): void {
    releaseMareaManualOverride();
    proposedActionIds = proposedActionIds.filter((x) => x !== id);
  }

  function handleKeydown(e: KeyboardEvent): void {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  function logout(): void {
    clearApiKey();
    apiKey.set('');
    wakeWord.stop();
    tts.stop();
    // Stores are module-level — without this, a different user logging in
    // on the same machine would still see the previous user's chat
    // history and reuse their session_id (a real privacy leak for a
    // personal-assistant app).
    resetChatState();
    resetDashboardCache();
    pendingInteractionIds = [];
    proposedActionIds = [];
    releaseMareaManualOverride();
    mareaState.set('idle');
  }

  function toggleWake(): void {
    const next = !$wakeEnabled;
    wakeEnabled.set(next);
    if (next) wakeWord.start(handleWake);
    else wakeWord.stop();
  }

  function pickStateChip(state: MareaVisualState): void {
    setMareaState(state, { manual: true });
  }
</script>

<div class="layout">
  <WaterCanvas {liveLevel} {chatDeckOpen} />

  <SystemsHeader state={$mareaState} />

  <div class="toolbar">
    <button class:active={chatDeckOpen} on:click={() => (chatDeckOpen = !chatDeckOpen)} title="Mostrar/ocultar chat">
      💬 chat
    </button>
    <button class:active={$autoPlay} on:click={() => autoPlay.set(!$autoPlay)}>▶ auto TTS</button>
    <button class:active={$wakeEnabled} on:click={toggleWake} disabled={!wakeWord.isSupported}>
      👂 wake
    </button>
    <select bind:value={$ttsVoice}>
      {#each VOICES as v (v)}
        <option value={v}>{v}</option>
      {/each}
    </select>
    <button on:click={logout}>Salir</button>
  </div>

  {#if $mareaState === 'panel'}
    <Dashboard />
  {:else}
    <div class="body">
      <!-- Design item 2, take 2 — a solid button drawn on top of the water
           always looked wrong once the sphere started morphing/moving
           underneath it (design feedback). Instead: the water itself is
           the press-and-hold surface (same "tap sobre el agua" precedent
           as the state-advance gesture), so there's no competing static
           shape drawn over a constantly-changing one — and a small fixed
           status pill (not centered on the sphere) carries the icon/hint/
           level glow, the way push-to-talk affordances work in Discord/
           Slack rather than as a floating button on the visualization. -->
      <button
        class="push-to-talk-surface"
        disabled={processing || $isStreaming}
        on:pointerdown={handlePushToTalkStart}
        on:pointerup={handlePushToTalkEnd}
        on:pointerleave={handlePushToTalkEnd}
        on:pointercancel={handlePushToTalkEnd}
        aria-label={recording ? 'Soltá para enviar' : 'Mantené para hablar'}
      ></button>

      <div class="ptt-hint" class:recording style:--level={recording ? audioLevel : 0}>
        <span class="ptt-indicator" class:recording>
          <span class="ptt-indicator-dot"></span>
        </span>
        <span>{recording ? 'soltá para enviar' : 'mantené para hablar'}</span>
      </div>

      {#if $thinkingSteps.length > 0}
        <aside class="thinking">
          <h2>Proceso de pensamiento</h2>
          {#each $thinkingSteps as step (step.id)}
            <div class="step">
              {#if step.category}<span class="badge {step.category}">{step.category}</span>{/if}
              <span class="label">{step.label ?? step.id}</span>
              <span class="status {step.status}">
                {step.status === 'active' ? '●' : step.status === 'done' ? '✓' : '✗'}
              </span>
            </div>
          {/each}
        </aside>
      {/if}

      <aside class="chat-deck" class:open={chatDeckOpen}>
        <div class="deck-header">
          <span>MAREA · CHAT</span>
          <button class="deck-close" on:click={() => (chatDeckOpen = false)} title="Cerrar chat">✕</button>
        </div>

        <main bind:this={chatEl} class="chat">
          {#each $messages as m (m.id)}
            <div class="msg {m.role}">
              <div class="role">{m.role === 'user' ? 'Vos' : 'MAREA'}</div>
              <div class="bubble">{m.text || '…'}</div>
            </div>
          {/each}
        </main>
      </aside>
    </div>
  {/if}

  {#if proposedActionIds.length > 0}
    <div class="action-cards">
      {#each proposedActionIds as id (id)}
        <ActionCard actionId={id} on:resolved={() => handleActionResolved(id)} />
      {/each}
    </div>
  {/if}

  {#if pendingInteractionIds[0]}
    <InteractionModal
      interactionId={pendingInteractionIds[0]}
      {tts}
      on:resolved={handleInteractionResolved}
      on:dismissed={() => handleInteractionDismissed(pendingInteractionIds[0])}
    />
  {/if}

  {#if debugMode}
    <div class="state-chips">
      {#each STATE_CHIPS as chip (chip.state)}
        <button class:active={$mareaState === chip.state} on:click={() => pickStateChip(chip.state)}>
          {chip.label}
        </button>
      {/each}
      <button class:active={$mareaAutoDemo} on:click={toggleAutoDemo} title="Modo debug: ciclo automático">
        ▶ AUTO
      </button>
    </div>
  {/if}

  <footer>
    <textarea
      bind:value={question}
      on:keydown={handleKeydown}
      placeholder="Preguntale a MAREA…"
      disabled={$isStreaming}
    ></textarea>
    <button class="send" on:click={send} disabled={$isStreaming || !question.trim()}>Enviar</button>
  </footer>
</div>

<style>
  .layout {
    position: relative;
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
    background: radial-gradient(1100px 760px at 50% 44%, #0b1c36 0%, #060d1c 55%, #030710 100%);
  }

  .toolbar {
    position: relative;
    z-index: 2;
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    align-items: center;
    padding: 8px 32px 0;
  }
  .toolbar button,
  .toolbar select {
    padding: 5px 10px;
    border-radius: 999px;
    border: 1px solid rgba(120, 200, 255, 0.28);
    background: rgba(8, 28, 56, 0.5);
    color: rgba(205, 238, 255, 0.85);
    font-size: 0.7rem;
    cursor: pointer;
  }
  .toolbar button.active {
    background: #54e0ff;
    color: #052540;
  }

  .state-chips {
    position: relative;
    z-index: 2;
    display: flex;
    justify-content: center;
    gap: 8px;
    padding: 8px 0;
  }
  .state-chips button {
    padding: 7px 14px;
    border-radius: 999px;
    border: 1px solid rgba(120, 200, 255, 0.28);
    background: rgba(8, 28, 56, 0.5);
    color: rgba(205, 238, 255, 0.85);
    font-size: 0.7rem;
    font-weight: 500;
    cursor: pointer;
  }
  .state-chips button.active {
    background: #54e0ff;
    color: #052540;
    box-shadow: 0 0 18px rgba(84, 224, 255, 0.45);
  }

  /* Reinstates the old .body's role: a flex:1 positioning context between
     the toolbar and the footer/state-chips, so the push-to-talk button and
     chat-deck below (both position:absolute) are confined to this middle
     area instead of overlapping the toolbar/footer, and the footer stays
     pinned to the bottom exactly like it did with a real .chat filling
     this space directly. */
  .body {
    position: relative;
    z-index: 1;
    flex: 1;
    overflow: hidden;
  }

  /* Design item 2, take 2 — the water itself is the press-and-hold
     surface: an invisible full-stage hit target, z-index'd BELOW the side
     panels (.thinking/.chat-deck, z-index 2) so their own controls (close
     button, scrolling, text selection) still take priority over it where
     they overlap, but ABOVE the water canvas (which is pointer-events:none
     anyway) so it actually receives the press. No visible chrome at all —
     drawing any static shape here always looks wrong against a sphere
     that's constantly morphing/moving underneath it. */
  .push-to-talk-surface {
    position: absolute;
    inset: 0;
    z-index: 1;
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    cursor: pointer;
    -webkit-user-select: none;
    user-select: none;
    touch-action: none;
  }
  .push-to-talk-surface:disabled {
    cursor: default;
  }

  /* The actual visible affordance — a small fixed pill, not centered on
     the sphere, so it never competes with or has to track the water's own
     shape/position. Purely informational (clicks pass through to the
     press-and-hold surface beneath it). */
  .ptt-hint {
    position: absolute;
    left: 50%;
    bottom: 26px;
    z-index: 3;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    border-radius: 999px;
    background: rgba(8, 28, 56, 0.55);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(120, 200, 255, 0.24);
    color: rgba(220, 245, 255, 0.8);
    font-size: 0.68rem;
    letter-spacing: 0.06em;
    pointer-events: none;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
    box-shadow: 0 0 calc(6px + var(--level, 0) * 26px) rgba(84, 224, 255, calc(0.1 + var(--level, 0) * 0.3));
  }
  .ptt-hint.recording {
    border-color: rgba(255, 90, 90, 0.55);
    box-shadow: 0 0 calc(6px + var(--level, 0) * 26px) rgba(255, 90, 90, calc(0.15 + var(--level, 0) * 0.35));
  }

  /* Record-indicator glyph (ring + dot) — chosen over a mic emoji/icon
     font so it reads as a real UI affordance instead of decoration, and
     doesn't depend on any icon set. */
  .ptt-indicator {
    position: relative;
    width: 14px;
    height: 14px;
    flex-shrink: 0;
  }
  .ptt-indicator::before {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: 999px;
    border: 1.5px solid rgba(127, 224, 255, 0.9);
    transition: border-color 0.15s ease;
  }
  .ptt-indicator-dot {
    position: absolute;
    inset: 3px;
    border-radius: 999px;
    background: rgba(127, 224, 255, 0.9);
    transition: background 0.15s ease;
  }
  .ptt-indicator.recording::before {
    border-color: rgba(255, 110, 110, 0.9);
  }
  .ptt-indicator.recording .ptt-indicator-dot {
    background: rgba(255, 90, 90, 0.9);
    animation: ptt-pulse 1s ease-in-out infinite;
  }
  @keyframes ptt-pulse {
    0%, 100% {
      opacity: 1;
      transform: scale(1);
    }
    50% {
      opacity: 0.55;
      transform: scale(0.8);
    }
  }

  /* Design item 1 — the chat is a dismissible deck docked to the right,
     not a layout column competing with the water for space. Closed by
     default (translated fully off-screen and non-interactive), it slides
     in without ever covering the whole viewport. */
  .chat-deck {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 2;
    /* Must never overlap .thinking (260px + border) when both are open —
     * previously min(420px, 92vw) could still exceed the remaining space
     * on a narrower window, e.g. 92vw already fits under a ~700px window
     * while 260px + 420px doesn't. Reserve room for it unconditionally. */
    width: min(420px, calc(100vw - 300px));
    display: flex;
    flex-direction: column;
    background: rgba(6, 18, 36, 0.72);
    backdrop-filter: blur(16px);
    border-left: 1px solid rgba(120, 200, 255, 0.2);
    transform: translateX(100%);
    transition: transform 0.28s ease;
    pointer-events: none;
  }
  .chat-deck.open {
    transform: translateX(0);
    pointer-events: auto;
  }
  .deck-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px;
    font-size: 0.65rem;
    letter-spacing: 0.2em;
    color: #6fc9ff;
    border-bottom: 1px solid rgba(120, 200, 255, 0.14);
    flex-shrink: 0;
  }
  .deck-close {
    background: none;
    border: none;
    color: rgba(220, 245, 255, 0.7);
    font-size: 0.85rem;
    cursor: pointer;
    padding: 2px 6px;
  }

  /* Always visible (unlike the chat transcript deck) — this is a live
     status readout of what the agent is doing right now, not conversation
     history to dismiss/recall at will. Independent left-side panel so
     hiding the chat deck never hides agent activity along with it. */
  .thinking {
    position: absolute;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 2;
    width: 260px;
    padding: 18px 20px;
    background: rgba(9, 26, 50, 0.5);
    backdrop-filter: blur(14px);
    border-right: 1px solid rgba(120, 200, 255, 0.18);
    overflow-y: auto;
  }
  .thinking h2 {
    font-size: 0.65rem;
    letter-spacing: 0.25em;
    color: #6fc9ff;
    margin: 0 0 12px;
    font-weight: 400;
  }
  .step {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
    border-bottom: 1px solid rgba(120, 200, 255, 0.08);
    font-size: 0.75rem;
  }
  .badge {
    font-size: 0.6rem;
    letter-spacing: 0.1em;
    padding: 2px 6px;
    border-radius: 5px;
    flex-shrink: 0;
  }
  .badge.AGENTE {
    background: rgba(84, 224, 255, 0.16);
    color: #54e0ff;
  }
  .badge.HERRAMIENTA {
    background: rgba(140, 160, 255, 0.16);
    color: #9fb0ff;
  }
  .badge.SISTEMA {
    background: rgba(110, 242, 197, 0.14);
    color: #6ef2c5;
  }
  .badge.RAZONAMIENTO {
    background: rgba(255, 255, 255, 0.09);
    color: rgba(220, 240, 255, 0.8);
  }
  .label {
    flex: 1;
    color: #dceeff;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .status.done {
    color: #6ef2c5;
  }
  .status.active {
    color: #54e0ff;
  }
  .status.error {
    color: #ff6b6b;
  }

  .chat {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .msg .role {
    font-size: 0.7rem;
    color: rgba(190, 225, 255, 0.6);
    margin-bottom: 4px;
  }
  .msg .bubble {
    background: rgba(9, 26, 50, 0.52);
    border: 1px solid rgba(120, 200, 255, 0.14);
    border-radius: 12px;
    padding: 10px 14px;
    max-width: 640px;
    white-space: pre-wrap;
  }
  .msg.user .bubble {
    background: rgba(84, 224, 255, 0.1);
  }

  .action-cards {
    position: fixed;
    top: 118px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 25;
    width: calc(100% - 64px);
    max-width: 620px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  footer {
    position: relative;
    z-index: 2;
    display: flex;
    align-items: flex-end;
    gap: 10px;
    padding: 16px 24px;
    background: rgba(9, 26, 50, 0.4);
    backdrop-filter: blur(10px);
    border-top: 1px solid rgba(120, 190, 255, 0.14);
  }
  textarea {
    flex: 1;
    resize: none;
    min-height: 40px;
    max-height: 120px;
    padding: 10px 14px;
    border-radius: 12px;
    border: 1px solid rgba(120, 200, 255, 0.2);
    background: rgba(4, 16, 34, 0.6);
    color: #eaf6ff;
    font-size: 0.9rem;
    font-family: inherit;
  }
  .send {
    padding: 10px 18px;
    border-radius: 12px;
    border: none;
    background: #54e0ff;
    color: #052540;
    font-weight: 600;
    cursor: pointer;
    flex-shrink: 0;
  }
  .send:disabled {
    opacity: 0.5;
    cursor: default;
  }
</style>
