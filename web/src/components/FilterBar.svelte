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
  /** The filters in effect, by name: a group (["from","to"]) counts once. */
  const applied = $derived([
    ...alsoApplied,
    ...filterKeys.filter((k) => flat([k]).some((x) => q.get(x))).map((k) => { const first = flat([k])[0]; return labels[first] ?? tidy(first); }),
  ].filter((v, i, all) => all.indexOf(v) === i));

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
</div>

<style>
  .fb { padding: 14px 16px 0; }
  .fb-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
  .fb-search { flex: 1 1 240px; min-width: 200px; max-width: 420px; }
  .fb-inline { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; min-width: 0; }
  .fb-inline :global(.select) { width: auto; min-width: 150px; max-width: 220px; }
  .fb-end { display: flex; align-items: center; gap: 8px; margin-left: auto; }
  .fb-anchor { position: relative; }
  .fb-more { gap: 8px; }
  .fb-more.is-active { border-color: var(--primary-text); color: var(--primary-text); }
  .fb-actions { display: flex; gap: 8px; }
  .fb-backdrop { position: fixed; inset: 0; z-index: 59; background: rgb(10 22 46 / .45); animation: fb-fade .15s ease-out; }
  .fb-panel { position: fixed; z-index: 60; left: 50%; top: 50%; transform: translate(-50%, -50%); width: min(600px, calc(100vw - 32px));
    background: var(--popover); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow-lg);
    display: flex; flex-direction: column; max-height: min(680px, calc(100dvh - 48px)); animation: fb-pop .16s ease-out; }
  .fp-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 12px 10px 16px; border-bottom: 1px solid var(--border); }
  .fp-title { font-size: 15px; font-weight: 600; }
  .fp-body { padding: 16px; overflow-y: auto; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 16px; align-content: start; }
  .fp-body > :global(.span-all) { grid-column: 1 / -1; }
  .fp-foot { display: flex; justify-content: space-between; gap: 10px; padding: 12px 16px; border-top: 1px solid var(--border); }

  @media (max-width: 900px) {
    .fb-search { max-width: none; }
  }
  @media (max-width: 640px) {
    .fb { padding: 12px 12px 0; }
    .fb-search { flex: 1 1 100%; min-width: 0; }
    .fb-inline { flex: 1 1 100%; display: grid; grid-template-columns: minmax(0, 1fr); }
    .fb-inline :global(.select), .fb-inline :global(.date-filter), .fb-inline :global(.date-filter > .select) { width: 100% !important; max-width: none !important; min-width: 0 !important; }
    .fb-inline :global(.date-filter) { display: grid !important; grid-template-columns: minmax(0, 1fr); }
    .fb-inline :global(.check-row) { grid-column: 1 / -1; }
    .fb-inline :global(.date-filter) { grid-column: 1 / -1; }
    .fb-end { flex: 1 1 100%; margin-left: 0; flex-wrap: wrap; }
    .fb-anchor { flex: 1 1 0; }
    .fb-more { width: 100%; }
    .fb-clear { flex: 1 1 0; }
    .fb-actions { flex: 1 1 0; }
    .fb-actions > :global(*) { flex: 1 1 0; }
    .fb-actions :global(.btn) { width: 100%; }
    .fb-panel { position: fixed; left: 0; right: 0; bottom: 0; top: auto; transform: none; width: 100%; max-height: 88dvh; border-radius: 16px 16px 0 0;
      padding-bottom: env(safe-area-inset-bottom); animation: fb-up .18s ease-out; }
    .fp-body { grid-template-columns: minmax(0, 1fr); }
    .fp-foot .btn { flex: 1 1 0; height: 44px; }
  }
  @keyframes fb-up { from { transform: translateY(24px); opacity: .6; } to { transform: none; opacity: 1; } }
  @keyframes fb-pop { from { opacity: 0; transform: translate(-50%, -48%) scale(.98); } to { opacity: 1; transform: translate(-50%, -50%); } }
  @keyframes fb-fade { from { opacity: 0; } to { opacity: 1; } }
  @media (prefers-reduced-motion: reduce) { .fb-panel, .fb-backdrop { animation: none; } }
</style>
