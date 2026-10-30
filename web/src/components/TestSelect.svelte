<script lang="ts">
  import { get } from "../lib/api";
  import { InfiniteList } from "../lib/infinite.svelte";
  import { searchCachedTests, withOffline } from "../lib/offline.svelte";
  import type { LabTest } from "../lib/bill-types";
  import { rupees } from "../lib/format";
  import type { Page } from "../lib/types";
  import Icon from "./Icon.svelte";

  // "Test name" on the bill: click the box and a short list drops down (typing narrows it), with a tick-box
  // on each test. Ticking puts the test on the bill at once and unticking takes it off; the list stays open
  // and the box keeps focus, so several tests go in quickly. `selected` = ids already on the bill.
  let { selected, ontoggle, id = "test-select" }: {
    selected: Set<string>; ontoggle: (test: LabTest, on: boolean) => void; id?: string;
  } = $props();
  let inputEl = $state<HTMLInputElement>();

  let query = $state("");
  let open = $state(false);
  // The list loads 30 tests at a time and fetches more as you scroll to its bottom.
  // Offline (lib/offline), from this computer's copy of the catalogue.
  const search = withOffline<LabTest>((q, page, size, signal) => get<Page<LabTest>>("/api/tests", { search: q, active: true, page, size }, signal),
                                      searchCachedTests);
  const list = new InfiniteList<LabTest>((page, size, signal) => search(query.trim(), page, size, signal), 30);
  const tests = $derived(list.items);
  const loading = $derived(list.loading);
  let active = $state(0);
  let root = $state<HTMLElement>();

  $effect(() => {
    if (!open) return;
    const q = query.trim();
    const t = setTimeout(() => { list.reset(); active = 0; }, q ? 150 : 0);
    return () => clearTimeout(t);
  });

  function onscroll(e: Event) {
    const el = e.currentTarget as HTMLElement;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 60) list.more();
  }

  // Close on a click outside the box and its list.
  $effect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!root?.contains(e.target as Node)) open = false; };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  });

  const isPicked = (t: LabTest) => selected.has(t.id);
  function toggle(t: LabTest) {
    const adding = !isPicked(t);
    ontoggle(t, adding);
    if (adding) query = "";  // ready for the next search; the list stays open
    queueMicrotask(() => inputEl?.focus());
  }

  function onkey(e: KeyboardEvent) {
    if (!open) { if (e.key === "ArrowDown") open = true; return; }
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(tests.length - 1, active + 1); if (active >= tests.length - 3) list.more(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); }
    else if (e.key === "Enter" || e.key === " ") { if (tests[active] && (e.key === "Enter" || e.ctrlKey)) { e.preventDefault(); toggle(tests[active]); } }
    else if (e.key === "Escape") { e.stopPropagation(); open = false; }
  }
</script>

<div class="ts" bind:this={root}>
  <div class="input-group">
    <Icon name="search" />
    <input {id} class="input" type="text" role="combobox" autocomplete="off" aria-expanded={open} aria-controls="{id}-list"
           placeholder={selected.size ? "Add more tests…" : "Select or search tests…"}
           bind:value={query} bind:this={inputEl} onkeydown={onkey} onfocus={() => (open = true)} onclick={() => (open = true)} oninput={() => (open = true)} />
  </div>

  {#if open}
    <div class="ts-pop">
      <ul class="ts-list" id="{id}-list" role="listbox" aria-multiselectable="true" aria-label="Tests" {onscroll}>
        {#each tests as t, i (t.id)}
          {@const on = isPicked(t)}
          <li role="option" aria-selected={on}>
            <label class="ts-row" class:is-on={on} class:is-active={i === active} onmouseenter={() => (active = i)}>
              <input class="checkbox" type="checkbox" checked={on} onchange={() => toggle(t)} />
              <span class="ts-name">{t.name}</span>
              <span class="ts-dept">{t.department.name}</span>
              <span class="ts-price money">{rupees(t.price)}</span>
            </label>
          </li>
        {:else}
          <li class="ts-empty">{loading ? "Searching…" : "No tests match."}</li>
        {/each}
        {#if tests.length && loading}<li class="ts-empty">Loading more…</li>{/if}
      </ul>
      <div class="ts-foot">
        <span>{selected.size} on the bill · Enter ticks the highlighted test</span>
        <button type="button" class="btn btn-primary btn-sm" onclick={() => { open = false; query = ""; }}>Done</button>
      </div>
    </div>
  {/if}

</div>

<style src="./styles/TestSelect.css"></style>
