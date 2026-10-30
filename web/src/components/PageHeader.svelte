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

<style src="./styles/PageHeader.css"></style>
