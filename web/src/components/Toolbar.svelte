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

<style src="./styles/Toolbar.css"></style>
