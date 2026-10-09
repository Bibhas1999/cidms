<script lang="ts">
  import { toasts, type NotifyKind } from "../lib/toast.svelte";

  const ICON: Record<NotifyKind, string> = {
    success: "M5 12.5l4.5 4.5L19 7.5",
    error: "M12 8v5M12 16.5v.01M10.3 3.9 2.6 17.3A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.7L13.7 3.9a2 2 0 0 0-3.4 0z",
    warning: "M12 8v5M12 16.5v.01M10.3 3.9 2.6 17.3A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.7L13.7 3.9a2 2 0 0 0-3.4 0z",
    info: "M12 11v5M12 8v.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
    progress: "",
  };

  const errors = $derived(toasts.items.filter((t) => t.kind === "error"));
  const others = $derived(toasts.items.filter((t) => t.kind !== "error"));
</script>

{#snippet card(t: (typeof toasts.items)[number])}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div class="toast is-{t.kind}" class:leaving={t.leaving} tabindex="-1"
       role="group" aria-label={t.title || t.message}
       onmouseenter={() => toasts.pause(t.id)} onmouseleave={() => toasts.resume(t.id)}
       onfocusin={() => toasts.pause(t.id)} onfocusout={() => toasts.resume(t.id)}
       onkeydown={(e) => { if (e.key === "Escape") { e.stopPropagation(); toasts.dismiss(t.id); } }}>
    {#if t.kind === "progress"}
      <span class="spinner" aria-hidden="true"></span>
    {:else}
      <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d={ICON[t.kind]} /></svg>
    {/if}
    <div class="text">
      {#if t.title}<div class="title">{t.title}</div>{/if}
      <div>{t.message}</div>
      {#if t.detail}<div class="detail mono">{t.detail}</div>{/if}
    </div>
    <button type="button" class="close" aria-label="Dismiss notification" onclick={() => toasts.dismiss(t.id)}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
    </button>
  </div>
{/snippet}

<!-- Two live regions: errors are announced at once, everything else politely. -->
<div class="region">
  <div class="stack" role="alert" aria-live="assertive">{#each errors as t (t.id)}{@render card(t)}{/each}</div>
  <div class="stack" role="status" aria-live="polite">{#each others as t (t.id)}{@render card(t)}{/each}</div>
</div>

<style>
  .region { position: fixed; right: 16px; bottom: 16px; z-index: 1000; display: grid; gap: 8px; width: min(420px, calc(100vw - 32px)); pointer-events: none; }
  .stack { display: grid; gap: 8px; }
  .toast { pointer-events: auto; display: flex; gap: 12px; align-items: flex-start; padding: 12px 12px 12px 14px; border-radius: 10px;
    background: var(--surface); color: var(--text); border: 1px solid var(--border); box-shadow: 0 10px 30px -8px rgb(16 24 40 / 28%);
    animation: enter .18s ease-out; transition: opacity .15s, transform .15s; outline: none; }
  .toast:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
  .leaving { opacity: 0; transform: translateY(6px); }
  .icon { width: 20px; height: 20px; flex: none; margin-top: 1px; fill: none; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
  .is-success { border-left: 4px solid var(--success); } .is-success .icon { stroke: var(--success); }
  .is-error { border-left: 4px solid var(--danger); } .is-error .icon { stroke: var(--danger); }
  .is-warning { border-left: 4px solid var(--warning); } .is-warning .icon { stroke: var(--warning); }
  .is-info, .is-progress { border-left: 4px solid var(--brand); } .is-info .icon { stroke: var(--brand); }
  .text { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .title { font-weight: 650; margin-bottom: 2px; }
  .detail { color: var(--text-2); font-size: 12px; margin-top: 4px; }
  .close { flex: none; display: grid; place-items: center; width: 28px; height: 28px; border: 0; border-radius: 6px; background: none; cursor: pointer; color: var(--text-2); }
  .close:hover { background: var(--surface-2); }
  .close svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; }
  .spinner { width: 18px; height: 18px; flex: none; margin-top: 2px; border-radius: 50%; border: 2px solid var(--border); border-top-color: var(--brand); animation: spin .7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes enter { from { opacity: 0; transform: translateY(8px); } }
  @media (prefers-reduced-motion: reduce) { .toast, .spinner { animation: none; transition: none; } }
</style>
