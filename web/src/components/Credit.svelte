<script lang="ts">
  import Icon from "./Icon.svelte";
  // "Crafted with ♥ by Bibhas": where "Powered by" used to be (sidebar foot, sign-in panel).
  // `inherit` takes the surrounding text colour (on the coloured sign-in panel).
  let { class: cls = "", inherit = false }: { class?: string; inherit?: boolean } = $props();
</script>

<span class="credit {cls}" class:is-inherit={inherit}>
  Crafted with
  <Icon name="heart" class="heart" size={13} label="love" />
  by Bibhas
</span>

<style>
  .credit { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--faint-foreground, var(--muted-foreground)); white-space: nowrap; }
  .credit.is-inherit { color: inherit; font-size: inherit; }
  .heart { fill: #e5484d; flex: none; animation: beat 2.4s ease-in-out infinite; transform-origin: center; }
  @keyframes beat { 0%, 60%, 100% { transform: scale(1); } 30% { transform: scale(1.18); } }
  @media (prefers-reduced-motion: reduce) { .heart { animation: none; } }
  @media print { .credit { display: none; } }
</style>
