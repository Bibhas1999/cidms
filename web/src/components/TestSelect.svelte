<script lang="ts">
  import { get } from "../lib/api";
  import type { LabTest } from "../lib/bill-types";
  import { rupees } from "../lib/format";
  import type { Page } from "../lib/types";
  import Icon from "./Icon.svelte";

  // "Test name" on the bill: type to search, and a short list pops up with a tick-box on each test, so
  // several can be picked before pressing Add. Picked tests show as chips under the box.
  let { picked = $bindable([]), exclude = new Set<string>(), id = "test-select" }: {
    picked?: LabTest[]; exclude?: Set<string>; id?: string;
  } = $props();

  let query = $state("");
  let open = $state(false);
  let tests = $state<LabTest[]>([]);
  let loading = $state(false);
  let active = $state(0);
  let root = $state<HTMLElement>();

  $effect(() => {
    const q = query.trim();
    if (!q) { tests = []; open = false; return; }
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      loading = true;
      get<Page<LabTest>>("/api/tests", { search: q, active: true, size: 30 }, ctrl.signal)
        .then((r) => { tests = r.items; active = 0; open = true; })
        .catch(() => {}).finally(() => (loading = false));
    }, 150);
    return () => { clearTimeout(t); ctrl.abort(); };
  });

  // Close on a click outside the box and its list.
  $effect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!root?.contains(e.target as Node)) open = false; };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  });

  const isPicked = (t: LabTest) => picked.some((p) => p.id === t.id);
  function toggle(t: LabTest) {
    picked = isPicked(t) ? picked.filter((p) => p.id !== t.id) : [...picked, t];
  }

  function onkey(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(tests.length - 1, active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); }
    else if (e.key === "Enter" || e.key === " ") { if (tests[active] && (e.key === "Enter" || e.ctrlKey)) { e.preventDefault(); toggle(tests[active]); } }
    else if (e.key === "Escape") { e.stopPropagation(); open = false; }
  }
</script>

<div class="ts" bind:this={root}>
  <div class="input-group">
    <Icon name="search" />
    <input {id} class="input" type="text" role="combobox" autocomplete="off" aria-expanded={open} aria-controls="{id}-list"
           placeholder={picked.length ? "Type to add more tests…" : "Type to search tests…"}
           bind:value={query} onkeydown={onkey} onfocus={() => { if (query.trim() && tests.length) open = true; }} />
  </div>

  {#if open}
    <div class="ts-pop">
      <ul class="ts-list" id="{id}-list" role="listbox" aria-multiselectable="true" aria-label="Tests">
        {#each tests as t, i (t.id)}
          {@const on = isPicked(t)}
          <li role="option" aria-selected={on}>
            <label class="ts-row" class:is-on={on} class:is-active={i === active} onmouseenter={() => (active = i)}>
              <input class="checkbox" type="checkbox" checked={on} onchange={() => toggle(t)} />
              <span class="ts-name">{t.name}</span>
              <span class="ts-dept">{t.department.name}{#if exclude.has(t.id)} · on bill{/if}</span>
              <span class="ts-price money">{rupees(t.price)}</span>
            </label>
          </li>
        {:else}
          <li class="ts-empty">{loading ? "Searching…" : "No tests match."}</li>
        {/each}
      </ul>
      <div class="ts-foot">
        <span>{picked.length} selected · Enter ticks the highlighted test</span>
        <button type="button" class="link-button" onclick={() => { open = false; query = ""; }}>Done</button>
      </div>
    </div>
  {/if}

  {#if picked.length}
    <div class="ts-chips">
      {#each picked as t (t.id)}
        <span class="ts-chip">{t.name}<button type="button" aria-label="Remove {t.name}" onclick={() => toggle(t)}><Icon name="x" size="sm" /></button></span>
      {/each}
    </div>
  {/if}
</div>

<style>
  .ts { position: relative; }
  .ts-pop { position: absolute; z-index: 50; left: 0; right: 0; top: 42px; min-width: 380px; background: var(--popover);
    border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-lg); overflow: hidden; }
  .ts-list { list-style: none; margin: 0; padding: 4px; max-height: 216px; overflow-y: auto; }
  .ts-row { display: flex; align-items: center; gap: 8px; height: 34px; padding: 0 8px; border-radius: var(--radius-sm); cursor: pointer; font-size: 13px; }
  .ts-row.is-active { background: var(--muted); }
  .ts-row.is-on { background: var(--accent); }
  .ts-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
  .ts-dept { flex: none; font-size: 11.5px; color: var(--muted-foreground); }
  .ts-price { flex: none; width: 82px; text-align: right; font-weight: 600; }
  .ts-empty { padding: 10px; font-size: 13px; color: var(--muted-foreground); }
  .ts-foot { display: flex; justify-content: space-between; align-items: center; padding: 4px 10px; border-top: 1px solid var(--border);
    font-size: 12px; color: var(--muted-foreground); }
  .ts-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .ts-chip { display: inline-flex; align-items: center; gap: 4px; height: 26px; padding: 0 4px 0 10px; border-radius: 999px;
    background: var(--accent); color: var(--accent-foreground); font-size: 12px; font-weight: 600; }
  .ts-chip button { display: grid; place-items: center; width: 20px; height: 20px; border: 0; border-radius: 50%; background: none; color: inherit; cursor: pointer; }
  .ts-chip button:hover { background: color-mix(in srgb, var(--primary-text) 15%, transparent); }
</style>
