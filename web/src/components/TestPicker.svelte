<script lang="ts">
  import { get } from "../lib/api";
  import type { LabTest } from "../lib/bill-types";
  import { rupees } from "../lib/format";
  import type { Page } from "../lib/types";
  import Icon from "./Icon.svelte";

  // Pick several tests at once: search and/or a department, then tick as many as needed. Ticking adds the
  // test to the bill straight away; unticking takes it off. `selected` = ids on the bill; `locked` = ids that
  // can't be taken off (already scanned or reported).
  let { selected, locked = new Set<string>(), ontoggle, onaddmany }: {
    selected: Set<string>; locked?: Set<string>;
    ontoggle: (test: LabTest, on: boolean) => void; onaddmany: (tests: LabTest[]) => void;
  } = $props();

  interface Department { id: string; name: string; is_active: boolean }
  let departments = $state<Department[]>([]);
  let department = $state("");
  let search = $state("");
  let tests = $state<LabTest[]>([]);
  let total = $state(0);
  let loading = $state(false);
  let searchEl = $state<HTMLInputElement>();

  $effect(() => {
    get<Department[]>("/api/departments").then((d) => (departments = d.filter((x) => x.is_active))).catch(() => {});
  });

  let timer: ReturnType<typeof setTimeout>;
  $effect(() => {
    const q = search.trim(), dep = department;
    clearTimeout(timer);
    const ctrl = new AbortController();
    timer = setTimeout(() => {
      loading = true;
      get<Page<LabTest>>("/api/tests", { search: q, department_id: dep, active: true, size: 100 }, ctrl.signal)
        .then((r) => { tests = r.items; total = r.total; })
        .catch(() => {})
        .finally(() => (loading = false));
    }, q ? 180 : 0);
    return () => { clearTimeout(timer); ctrl.abort(); };
  });

  const shownNotSelected = $derived(tests.filter((t) => !selected.has(t.id)));

  function onkey(e: KeyboardEvent) {
    // Enter ticks the first test that isn't on the bill yet, so typing + Enter stays quick.
    if (e.key === "Enter") {
      e.preventDefault();
      const first = shownNotSelected[0];
      if (first) { ontoggle(first, true); search = ""; }
    }
  }

  export function focus() { searchEl?.focus(); }
</script>

<div class="picker">
  <div class="picker-bar">
    <div class="input-group grow">
      <Icon name="search" />
      <label class="sr-only" for="tp-search">Search tests</label>
      <input id="tp-search" class="input" type="search" placeholder="Search tests by name or code… (Enter adds the first)" autocomplete="off"
             bind:value={search} bind:this={searchEl} onkeydown={onkey} />
    </div>
    <label class="sr-only" for="tp-dept">Department</label>
    <select id="tp-dept" class="select" style="width: auto; min-width: 170px" bind:value={department}>
      <option value="">All departments</option>
      {#each departments as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
    </select>
  </div>

  <div class="picker-head">
    <span class="text-sm text-muted">{loading ? "Searching…" : `${total} ${total === 1 ? "test" : "tests"}${total > tests.length ? `, showing the first ${tests.length}: search to narrow` : ""}`}</span>
    {#if shownNotSelected.length > 1 && (search.trim() || department)}
      <button class="link-button" type="button" onclick={() => onaddmany(shownNotSelected)}><Icon name="plus" size="sm" /> Add all {shownNotSelected.length} shown</button>
    {/if}
  </div>

  <ul class="picker-list" role="listbox" aria-label="Tests" aria-multiselectable="true">
    {#each tests as t (t.id)}
      {@const on = selected.has(t.id)}
      {@const fixed = locked.has(t.id)}
      <li role="option" aria-selected={on}>
        <label class="picker-row" class:is-on={on} class:is-locked={fixed}>
          <input class="checkbox" type="checkbox" checked={on} disabled={fixed} onchange={(e) => ontoggle(t, e.currentTarget.checked)} />
          <span class="grow">
            <span class="font-semibold">{t.name}</span>{#if t.code} <span class="text-xs text-muted mono">{t.code}</span>{/if}
            <span class="sub">{t.department.name}{#if t.test_type} · {t.test_type.name}{/if}{#if fixed} · already started{/if}</span>
          </span>
          <span class="money font-semibold">{rupees(t.price)}</span>
        </label>
      </li>
    {:else}
      <li class="empty" style="padding: 24px">{loading ? "Loading…" : "No tests match."}</li>
    {/each}
  </ul>
</div>

<style src="./styles/TestPicker.css"></style>
