<script lang="ts">
  /**
   * One UIField, rendered by its `kind` — the widget registry the plan
   * calls for. An unrecognized kind renders a "not supported" fallback,
   * NEVER a passthrough — this file is the other half of the "no markup"
   * security property (app/api/schemas/ui_protocol.py's module docstring
   * enforces the mechanical half; this is where a model-authored string
   * only ever becomes a text node, never `{@html}` or a markdown render).
   */
  import type { UIField } from '../lib/types';

  export let field: UIField;
  // Bound by the parent (InteractionModal) via bind:value — shape depends
  // on `field.kind`: string (single_select/entity_pick/text/datetime),
  // string[] (multi_select), boolean (confirm).
  export let value: unknown;

  function toggleMultiSelectOption(optionId: string): void {
    const current: string[] = Array.isArray(value) ? value : [];
    value = current.includes(optionId)
      ? current.filter((v) => v !== optionId)
      : [...current, optionId];
  }

  // Audit finding: the label's `for` only ever matched a real element's
  // `id` for text/datetime — every chip-based kind had a dangling
  // `for={field.key}` AND a dangling `aria-labelledby={field.key}` (no
  // element anywhere carried that id), so a screen reader got no
  // accessible name for the group at all. The label now always carries
  // its own id; chip-based kinds reference it via aria-labelledby, and
  // only the kinds with a real matching input still use `for`.
  const labelId = `${field.key}-label`;
  const isTextLikeField = field.kind === 'text' || field.kind === 'datetime';
</script>

<div class="field">
  <label class="field-label" id={labelId} for={isTextLikeField ? field.key : undefined}>
    {field.label}{field.required ? ' *' : ''}
  </label>
  {#if field.help}<p class="help">{field.help}</p>{/if}

  {#if field.kind === 'single_select' || field.kind === 'entity_pick'}
    <div class="chips" role="radiogroup" aria-labelledby={labelId}>
      {#each field.options ?? [] as opt (opt.id)}
        <button
          type="button"
          class="chip"
          class:active={value === opt.id}
          role="radio"
          aria-checked={value === opt.id}
          on:click={() => (value = opt.id)}
        >
          {opt.label}
        </button>
      {/each}
      {#if field.allow_none}
        <button type="button" class="chip" class:active={value === null} on:click={() => (value = null)}>
          {field.none_label ?? 'Ninguno'}
        </button>
      {/if}
    </div>

  {:else if field.kind === 'multi_select'}
    <div class="chips" role="group" aria-labelledby={labelId}>
      {#each field.options ?? [] as opt (opt.id)}
        {@const selected = Array.isArray(value) && value.includes(opt.id)}
        <button
          type="button"
          class="chip"
          class:active={selected}
          aria-pressed={selected}
          on:click={() => toggleMultiSelectOption(opt.id)}
        >
          {opt.label}
        </button>
      {/each}
    </div>

  {:else if field.kind === 'confirm'}
    <div class="chips" role="group" aria-labelledby={labelId}>
      <button type="button" class="chip" class:active={value === true} on:click={() => (value = true)}>
        {field.affirm_label ?? 'Sí'}
      </button>
      <button type="button" class="chip" class:active={value === false} on:click={() => (value = false)}>
        {field.deny_label ?? 'No'}
      </button>
    </div>

  {:else if field.kind === 'text'}
    {#if field.multiline}
      <textarea
        id={field.key}
        bind:value
        maxlength={field.max_length}
        placeholder={field.placeholder}
      ></textarea>
    {:else}
      <input
        id={field.key}
        type="text"
        bind:value
        maxlength={field.max_length}
        placeholder={field.placeholder}
      />
    {/if}

  {:else if field.kind === 'datetime'}
    <!-- Svelte forbids a dynamic `type` on a two-way-bound input, hence
         three branches instead of one input with a computed type. -->
    {#if field.mode === 'date'}
      <input id={field.key} type="date" bind:value min={field.min_iso} max={field.max_iso} />
    {:else if field.mode === 'time'}
      <input id={field.key} type="time" bind:value min={field.min_iso} max={field.max_iso} />
    {:else}
      <input id={field.key} type="datetime-local" bind:value min={field.min_iso} max={field.max_iso} />
    {/if}

  {:else}
    <p class="unsupported">Este tipo de campo no está soportado todavía.</p>
  {/if}
</div>

<style>
  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .field-label {
    font-size: 0.8rem;
    color: var(--color-text);
    font-weight: 500;
  }
  .help {
    margin: 0;
    font-size: 0.72rem;
    color: rgba(190, 225, 255, 0.65);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 44px;
    padding: 7px 16px;
    border-radius: 999px;
    border: 1px solid rgba(120, 200, 255, 0.28);
    background: rgba(8, 28, 56, 0.5);
    color: rgba(205, 238, 255, 0.85);
    font-size: 0.78rem;
    font-weight: 500;
    cursor: pointer;
    transition: border-color 0.15s ease, background-color 0.15s ease, transform 0.15s ease, filter 0.15s ease;
  }
  .chip:hover:not(.active) {
    border-color: rgba(120, 200, 255, 0.5);
    background: rgba(8, 28, 56, 0.75);
    transform: translateY(-1px);
  }
  .chip.active {
    background: var(--color-accent);
    color: var(--color-accent-ink);
    box-shadow: 0 0 18px rgba(84, 224, 255, 0.4);
  }
  .chip.active:hover {
    filter: brightness(1.08);
  }
  .chip:focus-visible,
  input:focus-visible,
  textarea:focus-visible {
    outline: 2px solid var(--color-focus);
    outline-offset: 2px;
  }
  input,
  textarea {
    min-height: 44px;
    padding: 10px 14px;
    border-radius: 10px;
    border: 1px solid rgba(120, 200, 255, 0.3);
    background: rgba(4, 16, 34, 0.6);
    color: var(--color-text);
    font-size: 0.85rem;
    font-family: inherit;
  }
  textarea {
    min-height: 70px;
    resize: vertical;
  }
  .unsupported {
    margin: 0;
    font-size: 0.78rem;
    color: rgba(255, 150, 150, 0.85);
    font-style: italic;
  }
</style>
