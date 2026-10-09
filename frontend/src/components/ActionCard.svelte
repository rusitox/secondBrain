<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte';
  import { apiKey, showToast } from '../lib/stores';
  import {
    approveAction,
    fetchProposedAction,
    rejectAction,
    type ProposedActionDetail,
  } from '../lib/interactions';

  export let actionId: string;

  const dispatch = createEventDispatcher<{ resolved: void }>();

  // Client-side echo of a status change THIS card instance just caused —
  // separate from detail.status (the source of truth fetched on load),
  // which may already reflect a non-"proposed" state for reasons that had
  // nothing to do with this render at all: the SSE emission that surfaces
  // an action_id fires for ANY status (see _extract_proposed_action_id's
  // docstring) since an idempotent re-proposal of an in-flight action
  // returns its current status, not "proposed" — a card opened from that
  // event must never show Aprobar/Rechazar for an action someone (or a
  // prior turn) already approved/rejected/executed.
  let detail: ProposedActionDetail | null = null;
  let loadError = '';
  let busy = false;
  let resolution: 'approved' | 'rejected' | null = null;
  // Gate on a second explicit click for RIESGO ALTO — approving one of
  // these (an email that actually gets sent, etc.) was previously a single
  // click, same as a low-risk action, with no extra friction at the one
  // checkpoint this product's whole "ask-human-last" trust model leans on.
  let confirmingHighRisk = false;

  const STATUS_LABELS: Record<string, string> = {
    approved: 'ACCIÓN APROBADA — EN CURSO',
    executing: 'ACCIÓN EJECUTÁNDOSE',
    executed: 'ACCIÓN EJECUTADA',
    rejected: 'ACCIÓN RECHAZADA',
    expired: 'PROPUESTA VENCIDA',
    failed: 'ACCIÓN FALLIDA',
  };

  $: isActionable = resolution === null && detail?.status === 'proposed';
  $: readOnlyLabel = resolution === 'approved'
    ? 'ACCIÓN APROBADA'
    : resolution === 'rejected'
      ? 'ACCIÓN RECHAZADA'
      : detail
        ? STATUS_LABELS[detail.status]
        : undefined;

  onMount(async () => {
    try {
      detail = await fetchProposedAction($apiKey, actionId);
    } catch {
      loadError = 'No se pudo cargar esta propuesta.';
    }
  });

  async function approve(): Promise<void> {
    if (!detail || busy) return;
    if (detail.risk === 'high' && !confirmingHighRisk) {
      confirmingHighRisk = true;
      return;
    }
    busy = true;
    try {
      await approveAction($apiKey, actionId, detail.payload_sha256);
      resolution = 'approved';
    } catch (err) {
      showToast(err instanceof Error && err.message ? err.message : 'No se pudo aprobar la acción');
      console.error(err);
    } finally {
      busy = false;
      confirmingHighRisk = false;
    }
  }

  async function reject(): Promise<void> {
    if (busy) return;
    confirmingHighRisk = false;
    busy = true;
    try {
      await rejectAction($apiKey, actionId);
      resolution = 'rejected';
    } catch (err) {
      showToast(err instanceof Error && err.message ? err.message : 'No se pudo rechazar la acción');
      console.error(err);
    } finally {
      busy = false;
    }
  }

  function cancelHighRiskConfirm(): void {
    confirmingHighRisk = false;
  }

  function close(): void {
    dispatch('resolved');
  }
</script>

<div class="card">
  {#if loadError}
    <p class="error">{loadError}</p>
    <button class="ghost" on:click={close}>Cerrar</button>
  {:else if !detail}
    <p class="loading">Cargando…</p>
  {:else}
    <div class="header-row">
      <span class="kicker" class:good={isActionable || resolution === 'approved'}>
        {isActionable ? 'PROPUESTA · LISTA PARA REVISAR' : readOnlyLabel}
      </span>
      {#if detail.risk === 'high'}<span class="risk-badge">RIESGO ALTO</span>{/if}
    </div>

    {#if detail.artifact.kind === 'email_draft'}
      <div class="email">
        <div class="email-meta">
          Para: {detail.artifact.to.map((a) => a.name ?? a.address).join(', ')}
          · Asunto: {detail.artifact.subject}
        </div>
        {#each detail.artifact.body_paragraphs as p, i (i)}
          <p>{p}</p>
        {/each}
        {#if detail.artifact.footnote_token === 'drafted_by_assistant'}
          <div class="footnote">
            Redactado por MAREA. Revisalo con atención: lo que ves acá es exactamente lo que se va a enviar si
            aprobás.
          </div>
        {/if}
      </div>
    {:else}
      <div class="key-values">
        <h3>{detail.artifact.title}</h3>
        {#each detail.artifact.rows as row (row.label)}
          <div class="kv-row">
            <span class="kv-label">{row.label}</span>
            <span class="kv-value tone-{row.tone}">{row.value}</span>
          </div>
        {/each}
      </div>
    {/if}

    {#if detail.status === 'failed' && detail.error}
      <p class="error">{detail.error}</p>
    {/if}

    <div class="actions" aria-live="polite">
      {#if isActionable}
        {#if confirmingHighRisk}
          <span class="confirm-hint">¿Confirmás? Esto no se puede deshacer.</span>
          <button class="ghost" on:click={cancelHighRiskConfirm} disabled={busy}>Cancelar</button>
          <button class="primary danger" on:click={approve} disabled={busy}>
            {busy ? 'Procesando…' : 'Confirmar y aprobar ✓'}
          </button>
        {:else}
          <button class="ghost" on:click={reject} disabled={busy}>Rechazar</button>
          <button class="primary" on:click={approve} disabled={busy}>
            {busy ? 'Procesando…' : 'Aprobar ✓'}
          </button>
        {/if}
      {:else}
        <button class="ghost" on:click={close}>Cerrar</button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .card {
    width: 100%;
    max-width: 600px;
    background: rgba(9, 26, 50, 0.6);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(120, 200, 255, 0.22);
    border-radius: 18px;
    padding: 22px 26px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .header-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .kicker {
    font-size: var(--text-floor-size);
    letter-spacing: 0.2em;
    color: var(--color-label);
  }
  .kicker.good {
    color: var(--color-success);
  }
  .risk-badge {
    font-size: var(--text-floor-size);
    letter-spacing: 0.1em;
    padding: 3px 8px;
    border-radius: 999px;
    background: rgba(255, 107, 107, 0.18);
    color: #ff8a8a;
    border: 1px solid rgba(255, 107, 107, 0.35);
  }
  .email {
    background: rgba(4, 16, 34, 0.55);
    border-radius: 12px;
    padding: 16px 18px;
    font-size: 14.5px;
    line-height: 1.6;
    color: var(--color-text);
  }
  .email-meta {
    font-size: 11px;
    color: rgba(190, 225, 255, 0.7);
    margin-bottom: 10px;
  }
  .email p {
    margin: 0 0 10px;
  }
  .footnote {
    font-size: var(--text-floor-size);
    color: rgba(190, 225, 255, 0.55);
  }
  .key-values h3 {
    margin: 0 0 10px;
    font-size: 13px;
    font-weight: 500;
    color: var(--color-text);
  }
  .kv-row {
    display: flex;
    justify-content: space-between;
    padding: 6px 0;
    border-bottom: 1px solid rgba(120, 200, 255, 0.1);
    font-size: 13px;
  }
  .kv-label {
    color: rgba(190, 225, 255, 0.8);
  }
  .kv-value.tone-good {
    color: var(--color-success);
  }
  .kv-value.tone-warn {
    color: #f5c451;
  }
  .actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 10px;
  }
  .confirm-hint {
    font-size: 12px;
    color: var(--color-danger-text);
    margin-right: auto;
  }
  .primary.danger {
    background: #ff8a8a;
    color: #2f0808;
    box-shadow: 0 0 18px rgba(255, 107, 107, 0.4);
  }
  .primary,
  .ghost {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 44px;
    transition: filter 0.15s ease, border-color 0.15s ease, background-color 0.15s ease, transform 0.15s ease;
  }
  .primary {
    padding: 10px 20px;
    border-radius: 10px;
    border: none;
    background: var(--color-success);
    color: var(--color-success-ink);
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 0 18px rgba(110, 242, 197, 0.4);
  }
  .primary:hover:not(:disabled) {
    filter: brightness(1.08);
  }
  .primary:disabled {
    opacity: 0.6;
    cursor: default;
    box-shadow: none;
  }
  .ghost {
    padding: 10px 16px;
    border-radius: 10px;
    border: 1px solid rgba(120, 200, 255, 0.28);
    background: transparent;
    color: rgba(205, 238, 255, 0.85);
    cursor: pointer;
  }
  .ghost:hover:not(:disabled) {
    border-color: rgba(120, 200, 255, 0.5);
    background: rgba(8, 28, 56, 0.4);
    transform: translateY(-1px);
  }
  .ghost:focus-visible,
  .primary:focus-visible {
    outline: 2px solid var(--color-focus);
    outline-offset: 2px;
  }
  .loading,
  .error {
    margin: 0;
    font-size: 0.85rem;
    color: rgba(224, 245, 255, 0.75);
  }
  .error {
    color: var(--color-danger-text);
  }
</style>
