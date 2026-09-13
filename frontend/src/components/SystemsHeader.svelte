<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { apiKey } from '../lib/stores';
  import { fetchSystemsStatus, sourceLabel } from '../lib/systems';
  import type { SystemStatusItem } from '../lib/types';
  import type { MareaVisualState } from '../lib/water-engine';

  export let state: MareaVisualState = 'idle';

  const STATE_LABELS: Record<MareaVisualState, string> = {
    idle: 'EN REPOSO',
    listen: 'ESCUCHANDO',
    think: 'PROCESANDO',
    respond: 'RESPONDIENDO',
    panel: 'SISTEMAS ACTIVOS',
  };

  const HEALTH_COLOR: Record<string, string> = {
    ok: '#6ef2c5',
    stale: '#f5c451',
    error: '#ff5c6c',
    disabled: 'rgba(210,240,255,.3)',
    external: '#9fb0ff',
  };

  const POLL_MS = 20000;

  let systems: SystemStatusItem[] = [];
  let openDetail: string | null = null;
  let pollTimer: ReturnType<typeof setInterval> | undefined;

  async function refresh(): Promise<void> {
    if (!$apiKey) return;
    try {
      const status = await fetchSystemsStatus($apiKey);
      systems = status.systems;
    } catch {
      // The header degrades to "no systems shown" rather than surfacing an
      // error toast for a background poll — the chat itself still works.
    }
  }

  onMount(() => {
    void refresh();
    pollTimer = setInterval(() => void refresh(), POLL_MS);
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  function toggleDetail(source: string): void {
    openDetail = openDetail === source ? null : source;
  }
</script>

<div class="header">
  <div class="left">
    <span class="wordmark">MAREA · 01</span>
    <div class="status-row">
      <span class="dot pulse"></span>
      <span class="label">{STATE_LABELS[state]}</span>
    </div>
  </div>

  <div class="right">
    <span class="kicker">NÚCLEO CONECTADO A</span>
    {#if systems.length === 0}
      <span class="empty">Sin sistemas conectados</span>
    {:else}
      <div class="systems">
        {#each systems as sys (sys.source)}
          <div class="system">
            <button
              class="chip"
              on:click={() => toggleDetail(sys.source)}
              title={sys.detail ?? sys.health}
            >
              <span class="light" style:background={HEALTH_COLOR[sys.health]}></span>
              {sourceLabel(sys.source)}
            </button>
            {#if openDetail === sys.source}
              <div class="detail">
                <div><strong>{sourceLabel(sys.source)}</strong> — {sys.health}</div>
                {#if sys.detail}<div>{sys.detail}</div>{/if}
                {#if sys.pending_documents > 0}
                  <div>{sys.pending_documents} documentos pendientes</div>
                {/if}
                {#if sys.last_sync_at}<div>Última sync: {new Date(sys.last_sync_at).toLocaleString()}</div>{/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>

<style>
  .header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 28px 32px 0;
    position: relative;
    z-index: 2;
  }
  .left {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .wordmark {
    font-family: 'Michroma', monospace;
    font-size: 13px;
    letter-spacing: 0.3em;
    color: #9fd8ff;
  }
  .status-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: #54e0ff;
    box-shadow: 0 0 8px rgba(84, 224, 255, 0.8);
  }
  .dot.pulse {
    animation: pulse 2s infinite;
  }
  .label {
    font-size: 11px;
    letter-spacing: 0.22em;
    color: rgba(210, 240, 255, 0.78);
  }

  .right {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
    text-align: right;
  }
  .kicker {
    font-size: 10px;
    letter-spacing: 0.2em;
    color: rgba(160, 210, 255, 0.6);
  }
  .empty {
    font-size: 12px;
    color: rgba(224, 245, 255, 0.5);
  }
  .systems {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 6px;
    max-width: 420px;
  }
  .system {
    position: relative;
  }
  .chip {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid rgba(120, 200, 255, 0.2);
    background: rgba(8, 28, 56, 0.5);
    color: rgba(224, 245, 255, 0.85);
    font-size: 11px;
    cursor: pointer;
  }
  .light {
    width: 7px;
    height: 7px;
    border-radius: 999px;
    flex-shrink: 0;
  }
  .detail {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    width: 240px;
    padding: 10px 12px;
    background: rgba(9, 26, 50, 0.92);
    backdrop-filter: blur(14px);
    border: 1px solid rgba(120, 200, 255, 0.2);
    border-radius: 10px;
    font-size: 11px;
    line-height: 1.5;
    color: rgba(224, 245, 255, 0.85);
    text-align: left;
    z-index: 10;
  }

  @keyframes pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.4;
    }
  }
</style>
