<script lang="ts">
  import { onDestroy, onMount, tick as svelteTick } from 'svelte';
  import { mareaState } from '../lib/marea-state';
  import { thinkingSteps } from '../lib/stores';
  import type { ThinkingCategory } from '../lib/types';
  import { WaterEngine } from '../lib/water-engine';

  // Real-time amplitude (0..1) from the mic while listening or TTS while
  // responding — see water-engine.ts's module docstring for how this
  // replaces the design prototype's synthetic sine-wave pulse.
  export let liveLevel = 0;
  // Orbital labels are positioned from the sphere's own screen-space ball
  // coordinates, with no awareness of the chat deck docked over the right
  // side of the screen — a label whose ball happens to orbit there was
  // rendering right under the deck, unreadable. Hidden instead of
  // repositioned when this is true (see updateLabelPositions).
  export let chatDeckOpen = false;

  let canvasEl: HTMLCanvasElement;
  let engine: WaterEngine | undefined;
  let raf = 0;
  let resizeObserver: ResizeObserver | undefined;
  const t0 = performance.now();
  let cssWidth = 0;
  let cssHeight = 0;

  $: engine?.setLiveLevel(liveLevel);
  $: engine?.setState($mareaState);

  // Design item 7 — floating labels anchored to the orbiting satellite
  // balls while "thinking" (e.g. "● AGENTE · search_memory"). Dynamic,
  // not the design mockup's hardcoded "CORREO/SLACK/ASANA": whatever
  // tools/agents/systems are ACTUALLY active right now, same philosophy
  // as the rest of MAREA's header/dashboard. RAZONAMIENTO is excluded —
  // it's the model's own reasoning trace, not an external agent/tool/
  // system this visual is meant to represent as "orbiting" the core.
  // Capped at 7 (there are only 7 satellite balls, index 1-7; index 0 is
  // the core).
  const ABBR: Record<ThinkingCategory, string> = {
    AGENTE: 'AG',
    HERRAMIENTA: 'HERR',
    SISTEMA: 'SYS',
    RAZONAMIENTO: '',
  };
  const DOT_COLOR: Record<ThinkingCategory, string> = {
    AGENTE: '#54e0ff',
    HERRAMIENTA: '#9fb0ff',
    SISTEMA: '#6ef2c5',
    RAZONAMIENTO: 'transparent',
  };

  $: activeAgentLabels = $mareaState === 'think'
    ? $thinkingSteps
        .filter((s) => s.status === 'active' && s.category && s.category !== 'RAZONAMIENTO')
        .slice(0, 7)
    : [];

  let labelEls: (HTMLDivElement | null)[] = [];

  onMount(() => {
    engine = new WaterEngine(canvasEl);

    resizeObserver = new ResizeObserver(() => {
      const rect = canvasEl.getBoundingClientRect();
      cssWidth = rect.width;
      cssHeight = rect.height;
      engine?.resize(rect.width, rect.height);
    });
    resizeObserver.observe(canvasEl);
    const initial = canvasEl.getBoundingClientRect();
    cssWidth = initial.width;
    cssHeight = initial.height;
    engine.resize(initial.width, initial.height);
    engine.setState($mareaState);

    const tick = (): void => {
      const t = (performance.now() - t0) / 1000;
      try {
        engine?.draw(t);
      } catch (e) {
        // A WebGL error here (e.g. context loss) must not silently kill
        // the loop forever with no trace — log and keep rescheduling.
        console.error('MAREA water draw() failed', e);
      }
      updateLabelPositions();
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  });

  // Direct DOM writes (not Svelte reactivity) for per-frame label
  // positioning — same reasoning as the water shader itself: this runs
  // up to 60x/second, and re-running a full reactive/diffing pass on N
  // small elements every frame is unnecessary overhead versus a plain
  // style.transform/opacity write, mirroring how the design prototype's
  // own vanilla-JS driver anchored its labels.
  function updateLabelPositions(): void {
    if (!engine || activeAgentLabels.length === 0) return;
    const positions = engine.getBallScreenPositions(cssWidth, cssHeight);
    const opacity = engine.getLabelOpacity();
    // Read once per tick, only while relevant — cheap (a single layout
    // read), and always correct even if the deck's CSS width formula
    // changes later, unlike duplicating that formula here.
    const deckLeftEdge = chatDeckOpen
      ? (document.querySelector('.chat-deck')?.getBoundingClientRect().left ?? Infinity)
      : Infinity;
    for (let i = 0; i < activeAgentLabels.length; i++) {
      const el = labelEls[i];
      if (!el) continue;
      const ball = positions[i + 1]; // ball 0 is the core, satellites start at 1
      if (!ball) continue;
      const labelX = ball.screenX + 16;
      // Hidden, not clamped/repositioned — moving it sideways just
      // relocates the overlap onto whatever else is there, with no
      // guarantee of a gap to land in.
      const hiddenByDeck = labelX > deckLeftEdge - 12;
      el.style.transform = `translate(${labelX}px, ${ball.screenY - 7}px)`;
      el.style.opacity = hiddenByDeck ? '0' : String(opacity);
    }
  }

  // A newly-appeared label needs its bind:this ref before the next tick
  // can position it — otherwise it flashes at (0,0) for one frame.
  $: if (activeAgentLabels) {
    void svelteTick().then(updateLabelPositions);
  }

  onDestroy(() => {
    cancelAnimationFrame(raf);
    resizeObserver?.disconnect();
    engine?.dispose();
  });
</script>

<canvas bind:this={canvasEl} class="water"></canvas>

{#each activeAgentLabels as step, i (step.id)}
  <div class="orbital-label" bind:this={labelEls[i]}>
    <span class="dot" style:background={DOT_COLOR[step.category ?? 'HERRAMIENTA']}></span>
    {ABBR[step.category ?? 'HERRAMIENTA']} · {step.label ?? step.id}
  </div>
{/each}

<style>
  .water {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
    pointer-events: none;
  }

  .orbital-label {
    position: absolute;
    top: 0;
    left: 0;
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 10px;
    letter-spacing: 0.16em;
    color: #bfe9ff;
    white-space: nowrap;
    pointer-events: none;
    opacity: 0;
    will-change: transform, opacity;
  }
  .orbital-label .dot {
    width: 5px;
    height: 5px;
    border-radius: 999px;
    flex-shrink: 0;
  }
</style>
