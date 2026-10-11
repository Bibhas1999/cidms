<script lang="ts">
  // "Crafted with ♥ by Bibhas": where "Powered by" used to be (sidebar foot, sign-in panel).
  // `inherit` takes the surrounding text colour (on the coloured sign-in panel).
  let { class: cls = "", inherit = false }: { class?: string; inherit?: boolean } = $props();
</script>

<span class="credit {cls}" class:is-inherit={inherit}>
  Crafted with
  <svg class="heart" viewBox="0 0 24 24" width="13" height="13" role="img" aria-label="love">
    <path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.7 4.5c2.1 0 3.6 1.1 5.3 3 1.7-1.9 3.2-3 5.3-3 3.7 0 5.8 3.9 4.3 7.3C19.5 16.4 12 21 12 21z" />
  </svg>
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
