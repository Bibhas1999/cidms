<script lang="ts">
  import type { Snippet } from "svelte";

  // A row of controls inside a card (above a list, at the top of a tab): things on the left (`children`) and
  // actions pushed to the right (`end`). It wraps on narrow screens; on phones the end actions go full width.
  //   <Toolbar>{#snippet end()}<Button variant="primary" size="sm" icon="plus">Add a department</Button>{/snippet}</Toolbar>
  let { children, end, class: cls = "" }: { children?: Snippet; end?: Snippet; class?: string } = $props();
</script>

<div class="ui-toolbar {cls}">
  {#if children}<div class="ui-toolbar-start">{@render children()}</div>{/if}
  {#if end}<div class="ui-toolbar-end">{@render end()}</div>{/if}
</div>

<style>
  .ui-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 14px 16px 0; }
  .ui-toolbar-start { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; flex: 1 1 auto; min-width: 0; }
  .ui-toolbar-end { display: flex; align-items: center; gap: 8px; margin-left: auto; }
  @media (max-width: 640px) {
    .ui-toolbar { padding: 12px 12px 0; }
    .ui-toolbar-end { flex: 1 1 100%; margin-left: 0; }
    .ui-toolbar-end > :global(*) { flex: 1 1 0; }
  }
</style>
