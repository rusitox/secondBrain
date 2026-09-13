<script lang="ts">
  import { apiKey } from './lib/stores';
  import AuthOverlay from './components/AuthOverlay.svelte';
  import ChatView from './components/ChatView.svelte';
  import Toast from './components/Toast.svelte';
</script>

{#if $apiKey}
  <ChatView />
{:else}
  <AuthOverlay />
{/if}

<Toast />

<style>
  :global(html, body) {
    margin: 0;
    height: 100%;
    background: #030710;
    color: #eaf6ff;
    font-family:
      -apple-system,
      BlinkMacSystemFont,
      'Segoe UI',
      sans-serif;
  }

  :global(#app) {
    height: 100%;
  }

  :global(*) {
    box-sizing: border-box;
  }
</style>
