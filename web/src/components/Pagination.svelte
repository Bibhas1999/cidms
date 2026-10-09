<script lang="ts">
  let { page, size, total, onchange }: { page: number; size: number; total: number; onchange: (page: number) => void } = $props();

  const pages = $derived(Math.max(1, Math.ceil(total / size)));
  const from = $derived(total === 0 ? 0 : (page - 1) * size + 1);
  const to = $derived(Math.min(page * size, total));
</script>

<nav class="pager" aria-label="Pages">
  <span class="muted">{from}–{to} of {total.toLocaleString("en-IN")}</span>
  <button class="btn small" disabled={page <= 1} onclick={() => onchange(page - 1)}>Previous</button>
  <span aria-current="page">Page {page} of {pages}</span>
  <button class="btn small" disabled={page >= pages} onclick={() => onchange(page + 1)}>Next</button>
</nav>

<style>
  .pager { display: flex; align-items: center; justify-content: flex-end; gap: 10px; padding: 12px; flex-wrap: wrap; }
  .muted { margin-right: auto; }
</style>
