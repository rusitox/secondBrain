<script lang="ts">
  import { login, saveApiKey } from '../lib/api';
  import { apiKey } from '../lib/stores';

  let email = '';
  let password = '';
  let error = '';
  let loading = false;

  async function handleSubmit(): Promise<void> {
    if (!email || !password) return;
    loading = true;
    error = '';
    const result = await login(email, password);
    loading = false;
    if (result) {
      saveApiKey(result.api_key);
      apiKey.set(result.api_key);
      password = '';
    } else {
      error = 'Credenciales incorrectas.';
      password = '';
    }
  }
</script>

<div class="overlay">
  <form on:submit|preventDefault={handleSubmit}>
    <h1>MAREA</h1>
    <input type="email" placeholder="Correo electrónico" bind:value={email} autocomplete="username" />
    <input type="password" placeholder="Contraseña" bind:value={password} autocomplete="current-password" />
    {#if error}
      <p class="error" role="alert">{error}</p>
    {/if}
    <button type="submit" disabled={loading}>{loading ? 'Entrando…' : 'Entrar'}</button>
  </form>
</div>

<style>
  .overlay {
    position: fixed;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--gradient-base);
  }
  form {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    width: 280px;
  }
  h1 {
    text-align: center;
    letter-spacing: 0.3em;
    font-size: 1rem;
    color: var(--color-accent-soft);
    margin-bottom: 1rem;
    font-weight: 400;
  }
  input,
  button {
    min-height: 44px;
    padding: 0.6rem 0.8rem;
    border-radius: 10px;
    border: 1px solid rgba(120, 190, 255, 0.25);
    background: rgba(4, 16, 34, 0.6);
    color: var(--color-text);
    font-size: 0.9rem;
  }
  /* The detector measured the browser's default placeholder color here at
     4.0:1 against this background — under the 4.5:1 WCAG AA floor. */
  input::placeholder {
    color: rgba(159, 216, 255, 0.72);
  }
  input:focus-visible,
  button:focus-visible {
    outline: 2px solid var(--color-focus);
    outline-offset: 2px;
  }
  button {
    background: var(--color-accent);
    color: var(--color-accent-ink);
    font-weight: 600;
    border: none;
    cursor: pointer;
    transition: filter 0.15s ease;
  }
  button:hover:not(:disabled) {
    filter: brightness(1.08);
  }
  button:disabled {
    opacity: 0.6;
    cursor: default;
  }
  .error {
    color: var(--color-danger-strong);
    font-size: 0.85rem;
    margin: 0;
  }
</style>
