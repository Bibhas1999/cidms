<script lang="ts">
  import { tooltip } from "../lib/tooltip";
  import { toasts, type NotifyKind } from "../lib/toast.svelte";
  import Icon from "./Icon.svelte";

  const ICON: Record<NotifyKind, string> = { success: "check", error: "alert", warning: "alert", info: "info", progress: "clock" };
  const errors = $derived(toasts.items.filter((t) => t.kind === "error"));
  const others = $derived(toasts.items.filter((t) => t.kind !== "error"));
</script>

{#snippet card(t: (typeof toasts.items)[number])}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div class="toast is-{t.kind}" class:is-leaving={t.leaving} role="group" aria-label={t.title || t.message}
       onmouseenter={() => toasts.pause(t.id)} onmouseleave={() => toasts.resume(t.id)}
       onfocusin={() => toasts.pause(t.id)} onfocusout={() => toasts.resume(t.id)}
       onkeydown={(e) => { if (e.key === "Escape") { e.stopPropagation(); toasts.dismiss(t.id); } }}>
    {#if t.kind === "progress"}<span class="toast-spinner" aria-hidden="true"></span>{:else}<Icon name={ICON[t.kind]} />{/if}
    <div class="toast-text">
      {#if t.title}<div class="toast-title">{t.title}</div>{/if}
      <div>{t.message}</div>
      {#if t.detail}<div class="toast-detail">{t.detail}</div>{/if}
      {#if t.action}{@const act = t.action}
        <button type="button" class="btn btn-sm toast-action" onclick={() => { toasts.dismiss(t.id); act.run(); }}>{act.label}</button>
      {/if}
    </div>
    <button type="button" class="toast-close" aria-label="Dismiss notification" use:tooltip={"Dismiss"} onclick={() => toasts.dismiss(t.id)}><Icon name="x" size="sm" /></button>
  </div>
{/snippet}

<!-- Errors are announced at once (assertive); everything else politely. Styles: styles/globals.css (.toast). -->
<div class="toast-region">
  <div class="toast-stack" role="alert" aria-live="assertive">{#each errors as t (t.id)}{@render card(t)}{/each}</div>
  <div class="toast-stack" role="status" aria-live="polite">{#each others as t (t.id)}{@render card(t)}{/each}</div>
</div>

<style>
  .toast-action { margin-top: 8px; height: 30px; padding: 0 12px; font-weight: 600; }
</style>
