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
    <input type="email" placeholder="Email" bind:value={email} autocomplete="username" />
    <input type="password" placeholder="Contraseña" bind:value={password} autocomplete="current-password" />
    {#if error}
      <p class="error">{error}</p>
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
    background: radial-gradient(1100px 760px at 50% 44%, #0b1c36 0%, #060d1c 55%, #030710 100%);
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
    color: #9fd8ff;
    margin-bottom: 1rem;
    font-weight: 400;
  }
  input,
  button {
    padding: 0.6rem 0.8rem;
    border-radius: 10px;
    border: 1px solid rgba(120, 190, 255, 0.25);
    background: rgba(4, 16, 34, 0.6);
    color: #eaf6ff;
    font-size: 0.9rem;
  }
  button {
    background: #54e0ff;
    color: #052540;
    font-weight: 600;
    border: none;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.6;
    cursor: default;
  }
  .error {
    color: #ff6b6b;
    font-size: 0.85rem;
    margin: 0;
  }
</style>
