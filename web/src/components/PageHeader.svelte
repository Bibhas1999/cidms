<script lang="ts">
  import type { Snippet } from "svelte";
  import InfoTip from "./InfoTip.svelte";

  // Every page starts the same way: a small section label, the title (with an optional ⓘ tip), one line on
  // what the page is for, and the page's main actions on the right. `compact` is for a page shown inside
  // another (a section of Settings): a smaller heading, no section label.
  // On phones the actions drop under the title and wrap; the primary action (.btn-primary) goes full width.
  let { eyebrow, title, description = "", tip = "", actions, compact = false }: {
    eyebrow: string; title: string; description?: string; tip?: string; actions?: Snippet; compact?: boolean;
  } = $props();
</script>

{#if compact}
  <div class="page-header page-header-compact">
    <div class="ph-text"><h2 class="ph-compact-title">{title}{#if tip}<InfoTip text={tip} about={title} />{/if}</h2>
      {#if description}<p class="text-sm text-muted ph-compact-desc">{description}</p>{/if}</div>
    {#if actions}<div class="page-actions">{@render actions()}</div>{/if}
  </div>
{:else}
  <div class="page-header">
    <div class="ph-text">
      <span class="eyebrow">{eyebrow}</span>
      <h1 class="page-title">{title}{#if tip}<InfoTip text={tip} about={title} />{/if}</h1>
      {#if description}<p class="page-description">{description}</p>{/if}
    </div>
    {#if actions}<div class="page-actions">{@render actions()}</div>{/if}
  </div>
{/if}

<style>
  .ph-text { min-width: 0; flex: 1 1 320px; }
  .ph-compact-title { font-size: 18px; }
  .ph-compact-desc { margin-top: 4px; }
  .page-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .page-title :global(.tip), .ph-compact-title :global(.tip) { margin-left: 4px; }
  @media (max-width: 640px) {
    .page-actions { width: 100%; }
    .page-actions > :global(.btn) { flex: 1 1 auto; }
    .page-actions > :global(.btn-primary) { flex: 1 1 100%; height: 44px; }
    .page-description { font-size: 13.5px; }
  }
</style>
