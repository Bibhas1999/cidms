<script lang="ts">
  import type { Snippet } from "svelte";

  // Every page starts the same way, as in the Sandhata Registry: a small section label, the title,
  // one line on what the page is for, and the page's main actions on the right. `compact` is for a page
  // shown inside another (a section of Settings): a smaller heading, no section label.
  let { eyebrow, title, description = "", actions, compact = false }: {
    eyebrow: string; title: string; description?: string; actions?: Snippet; compact?: boolean;
  } = $props();
</script>

{#if compact}
  <div class="row-between">
    <div><h2 style="font-size: 18px">{title}</h2>{#if description}<p class="text-sm text-muted" style="margin-top: 4px">{description}</p>{/if}</div>
    {#if actions}<div class="row-wrap">{@render actions()}</div>{/if}
  </div>
{:else}
  <div class="page-header">
    <div>
      <span class="eyebrow">{eyebrow}</span>
      <h1 class="page-title">{title}</h1>
      {#if description}<p class="page-description">{description}</p>{/if}
    </div>
    {#if actions}<div class="row-wrap">{@render actions()}</div>{/if}
  </div>
{/if}
