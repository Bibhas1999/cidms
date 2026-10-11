<script lang="ts">
  import type { Snippet } from "svelte";
  import InfoTip from "./InfoTip.svelte";

  // A card: an optional header (title, one line of description, an ⓘ tip, actions on the right), the
  // content, and an optional footer.
  //   <Card title="Bills" description="…" tip="…">{#snippet actions()}…{/snippet} … {#snippet footer()}…{/snippet}</Card>
  // `flush` drops the content padding, for a DataTable or FilterBar placed straight in the card (they bring
  // their own spacing, and the table sits inset in its own rounded box).
  let { title = "", description = "", tip = "", id = "", tag = "section", flush = false, class: cls = "", header, actions, children, footer }: {
    title?: string; description?: string; tip?: string; id?: string; tag?: "section" | "div" | "aside" | "article";
    flush?: boolean; class?: string; header?: Snippet; actions?: Snippet; children?: Snippet; footer?: Snippet;
  } = $props();
  const uid = $props.id();
  const titleId = $derived(id ? `${id}-title` : `${uid}-title`);
</script>

<svelte:element this={tag} class="card {cls}" {id} aria-labelledby={title ? titleId : undefined}>
  {#if header}
    {@render header()}
  {:else if title || actions}
    <div class="card-header">
      <div class="grow">
        {#if title}<h2 class="card-title" id={titleId}>{title}{#if tip}<span class="card-tip"><InfoTip text={tip} about={title} /></span>{/if}</h2>{/if}
        {#if description}<p class="card-description">{description}</p>{/if}
      </div>
      {#if actions}<div class="card-actions">{@render actions()}</div>{/if}
    </div>
  {/if}
  {#if children}
    {#if flush}{@render children()}{:else}<div class="card-content">{@render children()}</div>{/if}
  {/if}
  {#if footer}<div class="card-footer">{@render footer()}</div>{/if}
</svelte:element>

<style>
  .card-tip { margin-left: 4px; }
  .card-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex: none; }
  @media (max-width: 640px) {
    .card-actions { flex: 1 1 100%; }
  }
</style>
