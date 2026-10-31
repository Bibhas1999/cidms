<script lang="ts">
  import type { Snippet } from "svelte";
  import { confirmDialog } from "../lib/confirm.svelte";
  import { router, setQuery } from "../lib/router.svelte";
  import { tooltip } from "../lib/tooltip";
  import Icon from "./Icon.svelte";

  // The bar above every list: a search box, the filters used most (inline), a "Filters" button opening the
  // rest (with a count of those in use) and "Clear all". Every filter lives in the address (?search=&status=…),
  // so a filtered list can be shared, bookmarked and survives a reload; changing one goes back to page 1.
  //
  //   <FilterBar placeholder="Patient, mobile or bill number…" moreKeys={["status", ["min_total", "max_total"]]}>
  //     {#snippet inline()}<select …onchange={(e) => setQuery({ payment: e.currentTarget.value, page: null })}>…{/snippet}
  //     {#snippet more()}<Field …>…</Field>{/snippet}          (laid out two per row; one per row on phones)
  //     {#snippet actions()}<ExportMenu … />{/snippet}
  //   </FilterBar>
  // moreKeys   the address keys set inside the pop-up; a group (["from","to"]) counts once
  // inlineKeys the keys of the inline filters (for Clear all)
  // On phones the bar stacks and the pop-up opens as a sheet from the bottom of the screen.
  //
  // Searching while filters are on (as in the Sandhata Registry): when typing pauses, a dialog names the filters in
  // use and asks "Clear filters and search all" or "Search within filters" — once per search.
  // labels       names for the address keys in that message ({ department_id: "Department" }); others are tidied keys
  // alsoApplied  filters in effect that aren't in the address (e.g. the default "This month")
  // clearValues  what "clear" sets as well (e.g. { from: "all" } where no dates means this month)
  // notFilters   keys that aren't filters (e.g. "sort")
  let { search = true, searchKey = "search", placeholder = "Search…", searchLabel = "Search", searchTip = "", inline, more,
        moreKeys = [], inlineKeys = [], actions, onclear, moreTitle = "Filters", labels = {}, alsoApplied = [], clearValues = {},
        notFilters = ["sort"], noun = "results" }: {
    search?: boolean; searchKey?: string; placeholder?: string; searchLabel?: string; searchTip?: string;
    inline?: Snippet; more?: Snippet; moreKeys?: (string | string[])[]; inlineKeys?: string[]; actions?: Snippet;
    onclear?: () => void; moreTitle?: string; labels?: Record<string, string>; alsoApplied?: string[];
    clearValues?: Record<string, string | null>; notFilters?: string[];
    /** What the list holds, for the question: "Search all bills, or only…". */
    noun?: string;
  } = $props();

  const uid = $props.id();
  const q = $derived(router.query);
  const current = $derived(q.get(searchKey) ?? "");
  let text = $state("");
  let typed = "<initial>"; // forces the first sync below
  // Follow the address when it changes from outside (Clear all, back button).
  $effect(() => { if (current !== typed.trim()) { text = current; typed = current; } });

  const flat = (keys: (string | string[])[]) => keys.flatMap((k) => (Array.isArray(k) ? k : [k]));
  const tidy = (k: string) => { const t = k.replace(/_id$/, "").replace(/_/g, " "); return t.charAt(0).toUpperCase() + t.slice(1); };
  const filterKeys = $derived([...inlineKeys, ...moreKeys].filter((k) => !flat([k]).some((x) => notFilters.includes(x))));
  /** The filters in effect: a group (["from","to"]) counts once. `keys` is missing for an alsoApplied entry
      (e.g. the default "This month"), which isn't a specific address key to clear, so its chip has no ×. */
  const formatValue = (key: string, value: string) => {
    const v = value.trim();
    if (!v) return "";
    if (v === "true") return "Yes";
    if (v === "false") return "No";
    if (key === "from" || key === "to") {
      const d = new Date(v);
      return Number.isNaN(d.getTime()) ? v.replace(/_/g, " ") : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
    }
    if (["min_total", "max_total"].includes(key)) return v;
    return v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  };
  const appliedFilters = $derived<{ label: string; value?: string; keys?: string[] }[]>([
    ...alsoApplied.map((label): { label: string; value?: string; keys?: string[] } => ({ label })),
    ...filterKeys.filter((k) => flat([k]).some((x) => q.get(x)))
      .map((k) => {
        const keys = flat([k]);
        const label = labels[keys[0]] ?? tidy(keys[0]);
        const values = keys.map((key) => q.get(key)).filter((v): v is string => Boolean(v));
        const value = values.length === 1 ? formatValue(keys[0], values[0])
          : values.length > 1 ? `${formatValue(keys[0], values[0])} to ${formatValue(keys[1], values[1])}` : undefined;
        return { label, value, keys };
      }),
  ].filter((v, i, all) => all.findIndex((o) => o.label === v.label && (o as { value?: string }).value === (v as { value?: string }).value) === i));
  /** Just the names, for the "Search all X, or only…" dialog below. */
  const applied = $derived(appliedFilters.map((f) => f.label));

  function removeFilter(f: { keys?: string[] }) {
    if (f.keys) setQuery({ ...Object.fromEntries(f.keys.map((k) => [k, null])), page: null });
  }

  let timer: ReturnType<typeof setTimeout>;
  let asked = false; // once per search; emptying the box resets it
  function onSearch() {
    clearTimeout(timer);
    typed = text;
    if (!text.trim()) asked = false;
    timer = setTimeout(async () => {
      const value = text.trim();
      if (value && !asked && applied.length) {
        asked = true;
        const names = applied;
        const clear = await confirmDialog({
          title: "Filters are applied",
          message: `You have ${names.length === 1 ? "a filter" : `${names.length} filters`} applied (${names.join(", ")}). Search all ${noun}, or only the ones that match these filters?`,
          confirmLabel: "Clear filters and search all", cancelLabel: "Search within filters",
        });
        if (clear) {
          setQuery({ ...Object.fromEntries(flat(filterKeys).map((k) => [k, null])), ...clearValues, [searchKey]: text.trim(), page: null });
          onclear?.();
          return;
        }
      }
      setQuery({ [searchKey]: text.trim(), page: null });
    }, 300);
  }
  const moreCount = $derived(moreKeys.filter((k) => (Array.isArray(k) ? k : [k]).some((x) => q.get(x))).length);
  const allKeys = $derived([...(search ? [searchKey] : []), ...inlineKeys, ...flat(moreKeys)]);
  const anyActive = $derived(allKeys.some((k) => q.get(k)));

  function clearAll() {
    clearTimeout(timer);
    text = "";
    typed = "";
    setQuery(Object.fromEntries([...allKeys, "page"].map((k) => [k, null])));
    onclear?.();
  }

  // ---------- the pop-up ----------
  let open = $state(false);
  let panel = $state<HTMLElement>();
  let button = $state<HTMLButtonElement>();

  $effect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!panel?.contains(t) && !button?.contains(t) && !(t as Element).closest?.(".row-menu, .ui-tooltip")) open = false;
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { open = false; button?.focus(); } };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", key);
    queueMicrotask(() => panel?.querySelector<HTMLElement>("input, select, button:not(.fp-close)")?.focus());
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", key); };
  });
</script>

<div class="filter-bar fb">
  <div class="fb-row">
    {#if search}
      <div class="input-group fb-search">
        <Icon name="search" />
        <label class="sr-only" for="{uid}-search">{searchLabel}</label>
        <input id="{uid}-search" class="input" type="search" {placeholder} bind:value={text} oninput={onSearch} use:tooltip={searchTip} />
      </div>
    {/if}
    {#if inline}<div class="fb-inline">{@render inline()}</div>{/if}
    <div class="fb-end">
      {#if more}
        <div class="fb-anchor">
          <button bind:this={button} type="button" use:tooltip={moreCount ? `${moreCount} more filter${moreCount > 1 ? "s" : ""} in use` : "More ways to narrow the list"} class="btn btn-outline fb-more" class:is-active={moreCount > 0} aria-expanded={open}
                  aria-controls="{uid}-panel" onclick={() => (open = !open)}>
            <Icon name="filter" size="sm" /> Filters
            {#if moreCount}<span class="filter-count" aria-label="{moreCount} in use">{moreCount}</span>{/if}
          </button>
          {#if open}
            <div class="fb-backdrop" aria-hidden="true"></div>
            <div class="fb-panel" id="{uid}-panel" role="dialog" aria-modal="true" aria-label={moreTitle} bind:this={panel}>
              <div class="fp-head">
                <h2 class="fp-title">{moreTitle}</h2>
                <button type="button" class="btn btn-ghost btn-icon btn-sm fp-close" aria-label="Close filters" use:tooltip={"Close (Esc)"} onclick={() => (open = false)}><Icon name="x" size="sm" /></button>
              </div>
              <div class="fp-body">{@render more()}</div>
              <div class="fp-foot">
                <button type="button" class="btn btn-ghost" onclick={clearAll} disabled={!anyActive}>Clear all</button>
                <button type="button" class="btn btn-primary" onclick={() => (open = false)}>Done</button>
              </div>
            </div>
          {/if}
        </div>
      {/if}
      {#if anyActive}<button type="button" class="btn btn-ghost fb-clear" onclick={clearAll}><Icon name="x" size="sm" /> Clear all</button>{/if}
      {#if actions}<div class="fb-actions">{@render actions()}</div>{/if}
    </div>
  </div>
  {#if appliedFilters.length}
    <div class="fb-chips" role="list" aria-label="Filters applied">
      {#each appliedFilters as f (f.label + (f.value ?? "") + (f.keys ?? []).join("-"))}
        <span class="fb-chip" role="listitem">
          {f.label}{#if f.value}: {f.value}{/if}
          {#if f.keys}
            <button type="button" class="fb-chip-x" aria-label="Remove the {f.label} filter" onclick={() => removeFilter(f)}><Icon name="x" size="sm" /></button>
          {/if}
        </span>
      {/each}
    </div>
  {/if}
</div>

<style src="./styles/FilterBar.css"></style>
