<script lang="ts">
  import { onMount } from 'svelte';
  import { apiKey } from '../lib/stores';
  import { consolidatePendingItems, fetchBriefing, type BriefingData } from '../lib/dashboard';
  import { sourceLabel } from '../lib/systems';

  let data: BriefingData | null = null;
  let loadError = '';
  let refreshing = false;

  async function load(forceRefresh = false): Promise<void> {
    loadError = '';
    try {
      data = await fetchBriefing($apiKey, forceRefresh);
    } catch {
      loadError = 'No se pudo cargar el resumen.';
    }
  }

  async function refresh(): Promise<void> {
    refreshing = true;
    await load(true);
    refreshing = false;
  }

  onMount(() => void load());

  $: pendingItems = data ? consolidatePendingItems(data.pending_commitments, data.overdue_commitments) : [];
  $: overdueIds = data ? new Set(data.overdue_commitments.map((c) => c.id)) : new Set<string>();
</script>

<div class="dashboard">
  <div class="dashboard-header">
    <span class="hint">LA ESFERA CEDIÓ EL CENTRO — DECÍ «VOLVÉ» PARA RETOMAR</span>
    <button class="refresh" on:click={refresh} disabled={refreshing}>
      {refreshing ? 'Actualizando…' : '↻ Actualizar'}
    </button>
  </div>

  {#if loadError}
    <p class="error">{loadError}</p>
  {:else if !data}
    <p class="loading">Cargando…</p>
  {:else}
    <div class="grid">
      {#if data.agenda.length > 0}
        <div class="card">
          <h3>AGENDA · {data.agenda.length} hoy</h3>
          {#each data.agenda.slice(0, 6) as ev (ev.timestamp + ev.subject)}
            <div class="row">
              <span class="title">{ev.subject || 'Sin título'}</span>
              <span class="secondary">{ev.local_time ?? ev.timestamp}{ev.organizer ? ` · ${ev.organizer}` : ''}</span>
            </div>
          {/each}
        </div>
      {/if}

      {#if pendingItems.length > 0}
        <div class="card">
          <h3>TUS PENDIENTES · {pendingItems.length}</h3>
          <p class="card-subtitle">
            Compromisos que son tuyos, consolidados de todas tus fuentes conectadas
            (Outlook, Slack, Fathom, Teams).
          </p>
          {#each pendingItems as c (c.id)}
            <div class="row">
              <span class="title">{c.commitment_text}</span>
              <span class="secondary" class:overdue={overdueIds.has(c.id)}>
                {#if c.source?.platform}vía {sourceLabel(c.source.platform)} · {/if}{c.due_date ? new Date(c.due_date).toLocaleDateString() : 'sin fecha'}
                {overdueIds.has(c.id) ? ' · vencido' : ''}
              </span>
            </div>
          {/each}
        </div>
      {/if}

      {#if data.agenda.length === 0 && pendingItems.length === 0}
        <p class="empty">Sin agenda ni compromisos pendientes por ahora.</p>
      {/if}
    </div>
  {/if}
</div>

<style>
  .dashboard {
    padding: 98px 44px 32px;
    position: relative;
    z-index: 1;
  }
  .dashboard-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
  }
  .hint {
    font-size: 11px;
    letter-spacing: 0.14em;
    color: rgba(190, 225, 255, 0.6);
  }
  .refresh {
    padding: 5px 12px;
    border-radius: 999px;
    border: 1px solid rgba(120, 200, 255, 0.28);
    background: rgba(8, 28, 56, 0.5);
    color: rgba(205, 238, 255, 0.85);
    font-size: 0.7rem;
    cursor: pointer;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 20px;
  }
  .card {
    background: rgba(9, 26, 50, 0.52);
    backdrop-filter: blur(14px);
    border: 1px solid rgba(120, 200, 255, 0.18);
    border-radius: 16px;
    padding: 20px 22px;
  }
  .card h3 {
    margin: 0 0 12px;
    font-size: 13px;
    letter-spacing: 0.08em;
    color: #6fc9ff;
    font-weight: 500;
  }
  .card-subtitle {
    margin: -6px 0 14px;
    font-size: 11.5px;
    line-height: 1.4;
    color: rgba(190, 225, 255, 0.6);
  }
  .row {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 0;
    border-bottom: 1px solid rgba(120, 200, 255, 0.1);
  }
  .row:last-child {
    border-bottom: none;
  }
  .title {
    font-size: 13px;
    font-weight: 500;
    color: #eaf6ff;
  }
  .secondary {
    font-size: 12px;
    color: rgba(190, 225, 255, 0.8);
  }
  .secondary.overdue {
    color: #ff9696;
  }
  .loading,
  .error,
  .empty {
    font-size: 0.85rem;
    color: rgba(224, 245, 255, 0.75);
  }
  .error {
    color: #ff9696;
  }
</style>
