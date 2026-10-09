<script lang="ts">
  import { toasts } from "../lib/toast.svelte";
</script>

<!-- Polite for confirmations, assertive for errors, so screen readers announce failures at once. -->
<div class="toasts" aria-live="polite">
  {#each toasts.items as t (t.id)}
    <div class="toast {t.kind}" role={t.kind === "error" ? "alert" : "status"}>
      <div class="grow">
        <div>{t.message}</div>
        {#if t.detail}<div class="detail mono">{t.detail}</div>{/if}
      </div>
      <button class="close" aria-label="Dismiss" onclick={() => toasts.dismiss(t.id)}>×</button>
    </div>
  {/each}
</div>

<style>
  .toasts { position: fixed; right: 16px; bottom: 16px; display: grid; gap: 8px; z-index: 100; max-width: min(420px, calc(100vw - 32px)); }
  .toast { display: flex; gap: 10px; align-items: flex-start; padding: 12px 14px; border-radius: var(--radius); background: var(--surface);
    border: 1px solid var(--border); border-left: 4px solid var(--success); box-shadow: var(--shadow); }
  .toast.error { border-left-color: var(--danger); }
  .toast.info { border-left-color: var(--brand); }
  .detail { color: var(--text-2); margin-top: 2px; font-size: 12px; }
  .close { border: 0; background: none; color: var(--text-2); font-size: 18px; line-height: 1; cursor: pointer; padding: 0 2px; }
</style>
