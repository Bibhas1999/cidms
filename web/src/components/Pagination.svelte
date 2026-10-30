<script lang="ts">
  import { tooltip } from "../lib/tooltip";
  import { count } from "../lib/format";
  import { setQuery } from "../lib/router.svelte";
  import Icon from "./Icon.svelte";

  // The registry's pagination footer: "Showing 1–25 of 4,801", page numbers with gaps, previous / next.
  // Pages are fetched from the server one at a time (LIMIT/OFFSET there); "Rows per page" sets ?size=.
  let { page, size, total, onchange, sizes = [10, 25, 50, 100] }: {
    page: number; size: number; total: number; onchange: (page: number) => void; sizes?: number[];
  } = $props();
  const uid = $props.id();

  const pages = $derived(Math.max(1, Math.ceil(total / size)));
  const from = $derived(total === 0 ? 0 : (page - 1) * size + 1);
  const to = $derived(Math.min(page * size, total));
  // 1 … 4 5 [6] 7 8 … 20
  const list = $derived.by(() => {
    const out: (number | "gap")[] = [];
    for (let p = 1; p <= pages; p++) {
      if (p === 1 || p === pages || Math.abs(p - page) <= 1) out.push(p);
      else if (out[out.length - 1] !== "gap") out.push("gap");
    }
    return out;
  });
</script>

<nav class="pager card-footer" aria-label="Pages">
  <p class="pager-summary text-sm text-muted">Showing <strong>{count(from)}–{count(to)}</strong> of <strong>{count(total)}</strong></p>
  <div class="pagination">
    <button class="btn btn-ghost btn-sm page-step" class:is-disabled={page <= 1} disabled={page <= 1} use:tooltip={"Previous page"} onclick={() => onchange(page - 1)}>
      <Icon name="chevronRight" size="sm" class="flip" /><span>Previous</span></button>
    <ul class="page-list">
      {#each list as p, i (i)}
        {#if p === "gap"}<li class="page-gap" aria-hidden="true">…</li>
        {:else}<li><button class="page-num btn-ghost" class:is-current={p === page} aria-current={p === page ? "page" : undefined}
                         aria-label="Page {p}" onclick={() => onchange(p)} style="cursor:pointer; background-color: {p === page ? '' : 'transparent'}">{p}</button></li>{/if}
      {/each}
    </ul>
    <button class="btn btn-ghost btn-sm page-step" class:is-disabled={page >= pages} disabled={page >= pages} use:tooltip={"Next page"} onclick={() => onchange(page + 1)}>
      <span>Next</span><Icon name="chevronRight" size="sm" /></button>
  </div>
  <div class="pager-size">
    <label class="text-sm text-muted" for="{uid}-size">Rows per page</label>
    <select id="{uid}-size" class="select select-sm" value={size} onchange={(e) => setQuery({ size: e.currentTarget.value, page: null })}>
      {#each [...new Set([...sizes, size])].sort((a, b) => a - b) as n (n)}<option value={n}>{n}</option>{/each}
    </select>
  </div>
</nav>

<style src="./styles/Pagination.css"></style>
