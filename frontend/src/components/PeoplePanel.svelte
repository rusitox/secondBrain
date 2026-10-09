<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte';
  import { apiKey } from '../lib/stores';
  import { claimTypeLabel, fetchPeople, fetchPersonProfile, sortClaimTypes } from '../lib/people';
  import type { PersonProfile, PersonSummary } from '../lib/types';

  const dispatch = createEventDispatcher<{ close: void }>();

  let people: PersonSummary[] = [];
  let loadError = '';
  let loading = true;

  // Keyed by entity_id — lets more than one card stay expanded at once,
  // and remembers a fetched profile across collapse/re-expand instead of
  // re-fetching every click.
  let profiles: Record<string, PersonProfile> = {};
  let profileErrors: Record<string, string> = {};
  let expanded: Record<string, boolean> = {};
  let loadingProfile: Record<string, boolean> = {};

  async function load(): Promise<void> {
    loadError = '';
    try {
      const result = await fetchPeople($apiKey);
      people = result.people;
    } catch (err) {
      loadError = err instanceof Error && err.message ? err.message : 'No se pudieron cargar las personas.';
    } finally {
      loading = false;
    }
  }

  onMount(() => void load());

  async function toggle(entityId: string): Promise<void> {
    expanded[entityId] = !expanded[entityId];
    expanded = { ...expanded };
    if (!expanded[entityId] || profiles[entityId] || loadingProfile[entityId]) return;

    // Clear any error from a previous failed attempt on this same card —
    // otherwise a successful retry still shows the stale error, since the
    // template checks profileErrors before profiles.
    if (profileErrors[entityId]) {
      const { [entityId]: _removed, ...rest } = profileErrors;
      profileErrors = rest;
    }

    loadingProfile = { ...loadingProfile, [entityId]: true };
    try {
      profiles[entityId] = await fetchPersonProfile($apiKey, entityId);
      profiles = { ...profiles };
    } catch (err) {
      profileErrors[entityId] =
        err instanceof Error && err.message ? err.message : 'No se pudo cargar el perfil.';
      profileErrors = { ...profileErrors };
    } finally {
      loadingProfile = { ...loadingProfile, [entityId]: false };
    }
  }
</script>

<div class="people">
  <div class="people-header">
    <span class="hint">PERSONAS — rol, vínculo, forma de comunicarse y de llegar a acuerdos</span>
    <button class="close" on:click={() => dispatch('close')} title="Cerrar">✕</button>
  </div>

  {#if loading}
    <p class="loading">Cargando…</p>
  {:else if loadError}
    <p class="error">{loadError}</p>
  {:else if people.length === 0}
    <p class="empty">
      Todavía no hay personas en la base de conocimiento. Se van sumando a medida que los agentes de
      cada fuente procesan tus documentos.
    </p>
  {:else}
    <div class="list">
      {#each people as person (person.entity_id)}
        <div class="card">
          <button class="card-header" on:click={() => toggle(person.entity_id)}>
            <div class="identity">
              <span class="name">{person.canonical_name}</span>
              {#if person.role}<span class="role">{person.role}</span>{/if}
            </div>
            <span class="confidence" title="Confianza del grafo de conocimiento">
              {Math.round(person.confidence * 100)}%
            </span>
          </button>

          {#if expanded[person.entity_id]}
            <div class="detail">
              {#if loadingProfile[person.entity_id]}
                <p class="loading">Cargando perfil…</p>
              {:else if profileErrors[person.entity_id]}
                <p class="error">{profileErrors[person.entity_id]}</p>
              {:else if profiles[person.entity_id]}
                {@const profile = profiles[person.entity_id]}
                {#each sortClaimTypes(Object.keys(profile.claims_by_type)) as claimType (claimType)}
                  <div class="group">
                    <h4>{claimTypeLabel(claimType)}</h4>
                    {#each profile.claims_by_type[claimType] as claim, i (i)}
                      <p class="claim">{claim.claim_text}</p>
                    {/each}
                  </div>
                {/each}
                {#if profile.related_entities.length > 0}
                  <div class="group">
                    <h4>Relacionado con</h4>
                    {#each profile.related_entities as rel (rel.entity_id)}
                      <p class="claim">{rel.canonical_name ?? rel.entity_id} · {rel.relation_type}</p>
                    {/each}
                  </div>
                {/if}
                {#if Object.keys(profile.claims_by_type).length === 0 && profile.related_entities.length === 0}
                  <p class="empty">Todavía no hay información adicional sobre esta persona.</p>
                {/if}
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .people {
    padding: 98px 44px 32px;
    position: relative;
    z-index: 1;
    height: 100%;
    overflow-y: auto;
    box-sizing: border-box;
  }
  .people-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
  }
  .hint {
    font-size: 11px;
    letter-spacing: 0.1em;
    color: rgba(190, 225, 255, 0.6);
  }
  .close {
    padding: 5px 10px;
    border-radius: 999px;
    border: 1px solid rgba(120, 200, 255, 0.28);
    background: rgba(8, 28, 56, 0.5);
    color: rgba(205, 238, 255, 0.85);
    font-size: 0.8rem;
    cursor: pointer;
  }
  .list {
    display: flex;
    flex-direction: column;
    gap: 12px;
    max-width: 640px;
  }
  .card {
    background: rgba(9, 26, 50, 0.52);
    backdrop-filter: blur(14px);
    border: 1px solid rgba(120, 200, 255, 0.18);
    border-radius: 16px;
    overflow: hidden;
  }
  .card-header {
    width: 100%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
  }
  .identity {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .name {
    font-size: 14px;
    font-weight: 500;
    color: #eaf6ff;
  }
  .role {
    font-size: 12px;
    color: rgba(190, 225, 255, 0.75);
  }
  .confidence {
    font-size: 11px;
    color: #6fc9ff;
    flex-shrink: 0;
  }
  .detail {
    padding: 0 20px 18px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .group h4 {
    margin: 0 0 6px;
    font-size: 11px;
    letter-spacing: 0.08em;
    color: #6fc9ff;
    font-weight: 500;
    text-transform: uppercase;
  }
  .claim {
    margin: 0 0 4px;
    font-size: 12.5px;
    line-height: 1.5;
    color: rgba(224, 245, 255, 0.85);
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
