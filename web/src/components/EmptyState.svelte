<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";

  // What a list shows when it has nothing: an icon, one line saying why, optionally a hint and an action.
  //   <EmptyState icon="receipt" title="No bills match these filters." text="Try a longer date range.">
  //     {#snippet action()}<Button onclick={clear}>Clear filters</Button>{/snippet}</EmptyState>
  let { icon = "inbox", title, text = "", compact = false, action }: {
    icon?: string; title: string; text?: string; compact?: boolean; action?: Snippet;
  } = $props();
</script>

<div class="empty empty-state" class:is-compact={compact}>
  <Icon name={icon} />
  <div class="font-semibold empty-title">{title}</div>
  {#if text}<div class="text-sm">{text}</div>{/if}
  {#if action}<div class="empty-state-action">{@render action()}</div>{/if}
</div>

<style>
  .empty-title { color: var(--foreground); }
  .is-compact { padding: 20px 16px; }
  .empty-state-action { margin-top: 8px; }
</style>
