<script lang="ts">
  import { toast } from '../lib/stores';
</script>

{#if $toast}
  <div class="toast">{$toast.message}</div>
{/if}

<style>
  .toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(8, 28, 56, 0.9);
    border: 1px solid rgba(120, 190, 255, 0.3);
    color: #eaf6ff;
    padding: 10px 18px;
    border-radius: 999px;
    font-size: 0.85rem;
    z-index: 1000;
  }
</style>
