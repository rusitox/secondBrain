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
  /* Design tokens — the recurring values that were previously copy-pasted
     as literal hex/rgba across every component's own <style> block (8
     files, per the audit). Only values that were genuinely identical
     across files are promoted here; a value used once stays local. */
  :global(:root) {
    --color-bg-deep: #030710;
    --color-bg-mid: #060d1c;
    --color-bg-soft: #0b1c36;
    --gradient-base: radial-gradient(
      1100px 760px at 50% 44%,
      var(--color-bg-soft) 0%,
      var(--color-bg-mid) 55%,
      var(--color-bg-deep) 100%
    );
    --color-text: #eaf6ff;
    --color-text-dim: rgba(190, 225, 255, 0.6);
    --color-accent: #54e0ff;
    --color-accent-ink: #052540;
    --color-accent-soft: #9fd8ff;
    --color-label: #6fc9ff;
    --color-success: #6ef2c5;
    --color-success-ink: #04301f;
    --color-danger-strong: #ff6b6b;
    --color-danger-text: #ff9696;
    --color-border: rgba(120, 200, 255, 0.28);
    --color-focus: #7fe3ff;
    /* The detector's own functional-text floor. Was copy-pasted as 9px,
       10px, 10.5px, 0.6rem, 0.65rem, and 0.68rem across 6 files (the audit
       that caught the live violations flagged this repetition) — one
       value now, so nothing can drift under it again by accident. */
    --text-floor-size: 11px;
  }

  :global(html, body) {
    margin: 0;
    height: 100%;
    background: var(--color-bg-deep);
    color: var(--color-text);
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
