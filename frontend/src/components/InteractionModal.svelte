<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte';
  import { AgentStreamError, answerInteraction } from '../lib/agent';
  import { apiKey, autoPlay, isStreaming, sessionId, showToast } from '../lib/stores';
  import { fetchInteraction, type InteractionDetail } from '../lib/interactions';
  import type { TTSPlayer } from '../lib/tts';
  import DynamicField from './DynamicField.svelte';

  export let interactionId: string;
  export let tts: TTSPlayer;

  const dispatch = createEventDispatcher<{
    resolved: { awaiting: string[]; proposedActionIds: string[] };
    dismissed: void;
  }>();

  // The kicker's copy lives client-side, localized — never model-authored
  // (app/api/schemas/ui_protocol.py's module docstring, point 3).
  const KICKER_LABELS: Record<string, string> = {
    needs_datum: 'LA IA NECESITA UN DATO TUYO',
    confirm_knowledge: 'CONFIRMÁ ESTE DATO',
    disambiguate: 'AYUDANOS A DESAMBIGUAR',
    review_draft: 'REVISÁ EL BORRADOR',
  };

  let detail: InteractionDetail | null = null;
  let loadError = '';
  let submitting = false;
  let answers: Record<string, unknown> = {};
  let formEl: HTMLFormElement | undefined;

  onMount(async () => {
    try {
      detail = await fetchInteraction($apiKey, interactionId);
      if (detail.status === 'open') {
        const initial: Record<string, unknown> = {};
        for (const f of detail.spec.fields) {
          if (f.kind === 'single_select' && f.default !== undefined) initial[f.key] = f.default;
          else if (f.kind === 'multi_select') initial[f.key] = [];
          else if (f.kind === 'text' || f.kind === 'datetime') initial[f.key] = '';
          // confirm/single_select-without-default/entity_pick all start
          // undefined, not '' — '' is a value a select/entity_pick field
          // can never validly hold (it's never a member of `option_ids`),
          // so an untouched optional one would fail validation on submit
          // even though nothing was required. undefined serializes out of
          // the request body entirely (JSON.stringify drops it), which is
          // exactly how the backend already expects "left unanswered" to
          // look for a non-required field.
          else initial[f.key] = undefined;
        }
        answers = initial;
      }
      // Focus the first interactive control for keyboard users.
      requestAnimationFrame(() => {
        formEl?.querySelector<HTMLElement>('button, input, textarea')?.focus();
      });
    } catch {
      loadError = 'No se pudo cargar esta pregunta.';
    }
  });

  function missingRequiredField(): string | null {
    if (!detail) return null;
    for (const f of detail.spec.fields) {
      if (!f.required) continue;
      const v = answers[f.key];
      const empty =
        v === undefined ||
        v === '' ||
        (f.kind === 'multi_select' && Array.isArray(v) && v.length === 0);
      if (empty) return f.label;
    }
    return null;
  }

  async function submit(): Promise<void> {
    if (!detail || submitting || $isStreaming) return;
    const missing = missingRequiredField();
    if (missing) {
      showToast(`Falta completar: ${missing}`);
      return;
    }
    submitting = true;
    try {
      const result = await answerInteraction(
        $apiKey, interactionId, answers, $sessionId, tts, $autoPlay,
      );
      dispatch('resolved', { awaiting: result.awaiting, proposedActionIds: result.proposedActionIds });
    } catch (err) {
      if (err instanceof AgentStreamError) {
        // The claim already succeeded (this only throws mid-stream, after
        // the answer was durably recorded server-side) — the interaction
        // itself is resolved even though the resumed turn then failed, so
        // still surface whatever it managed to propose before failing.
        dispatch('resolved', { awaiting: [], proposedActionIds: err.partial.proposedActionIds });
      }
      showToast(err instanceof Error && err.message ? err.message : 'No se pudo enviar la respuesta');
      console.error(err);
    } finally {
      submitting = false;
    }
  }

  function dismiss(): void {
    dispatch('dismissed');
  }

  function handleKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape' && detail?.spec.allow_dismiss) dismiss();
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<div class="overlay">
  <div class="modal">
    {#if loadError}
      <p class="error">{loadError}</p>
      <button class="ghost" on:click={dismiss}>Cerrar</button>
    {:else if !detail}
      <p class="loading">Cargando…</p>
    {:else if detail.status !== 'open'}
      <p class="loading">Esta pregunta ya fue respondida.</p>
      <button class="ghost" on:click={dismiss}>Cerrar</button>
    {:else}
      <span class="kicker">{KICKER_LABELS[detail.spec.kicker] ?? detail.spec.kicker}</span>
      <p class="prompt">
        {#each detail.spec.prompt as span, i (i)}
          <span class:entity={span.emphasis === 'entity'}>{span.text}</span>
        {/each}
      </p>

      <form bind:this={formEl} on:submit|preventDefault={submit} class="fields">
        {#each detail.spec.fields as field (field.key)}
          <DynamicField {field} bind:value={answers[field.key]} />
        {/each}

        <div class="actions">
          {#if detail.spec.allow_dismiss}
            <button type="button" class="ghost" on:click={dismiss} disabled={submitting}>Más tarde</button>
          {/if}
          <button type="submit" class="primary" disabled={submitting || $isStreaming}>
            {submitting ? 'Enviando…' : detail.spec.submit_label}
          </button>
        </div>
      </form>
    {/if}
  </div>
</div>

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 30;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 118px;
    background: rgba(3, 7, 16, 0.35);
  }
  .modal {
    width: 600px;
    max-width: calc(100vw - 48px);
    max-height: calc(100vh - 160px);
    overflow-y: auto;
    background: rgba(9, 26, 50, 0.9);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(120, 200, 255, 0.22);
    border-radius: 18px;
    padding: 26px 32px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .kicker {
    font-size: 10px;
    letter-spacing: 0.2em;
    color: #6fc9ff;
  }
  .prompt {
    margin: 0;
    font-size: 19px;
    line-height: 1.5;
    color: #eaf6ff;
  }
  .prompt .entity {
    color: #7fe3ff;
    font-weight: 600;
  }
  .fields {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    margin-top: 4px;
  }
  .primary {
    padding: 10px 20px;
    border-radius: 10px;
    border: none;
    background: #54e0ff;
    color: #052540;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 0 18px rgba(84, 224, 255, 0.4);
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
  .ghost:focus-visible,
  .primary:focus-visible {
    outline: 2px solid #7fe3ff;
    outline-offset: 2px;
  }
  .loading,
  .error {
    margin: 0;
    font-size: 0.85rem;
    color: rgba(224, 245, 255, 0.75);
  }
  .error {
    color: #ff9696;
  }
</style>
