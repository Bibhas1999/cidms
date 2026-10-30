<script lang="ts" generics="T">
  import type { Snippet } from "svelte";
  import { InfiniteList } from "../lib/infinite.svelte";
  import Icon from "./Icon.svelte";

  // A search box with a list of matches (WAI-ARIA combobox): type to search, ↑/↓ to move, Enter to pick,
  // Esc to close. `search` loads the matches; or `searchPage` loads them a page at a time, with more
  // fetched as the list is scrolled (long lists). `onpick` receives the chosen one.
  let { id, label, placeholder = "", search, searchPage, onpick, option, value = $bindable(""), icon = "search", minChars = 1,
        emptyText = "No matches.", onadd, addLabel = "", autofocus = false, inputEl = $bindable() }: {
    id: string; label: string; placeholder?: string; search?: (q: string, signal: AbortSignal) => Promise<T[]>;
    searchPage?: (q: string, page: number, size: number, signal: AbortSignal) => Promise<{ items: T[]; total: number }>;
    onpick: (item: T) => void; option: Snippet<[T]>; value?: string; icon?: string; minChars?: number; emptyText?: string;
    /** No matches: offer to add what was typed right there, instead of making them go find a separate button.
     *  `addLabel` is what it's added as (e.g. "a new patient"), shown as `Add "x" as a new patient`; both are
     *  needed for the row to show. */
    onadd?: (text: string) => void; addLabel?: string;
    autofocus?: boolean; inputEl?: HTMLInputElement;
  } = $props();

  let plain = $state<T[]>([]);
  const list = new InfiniteList<T>((page, size, signal) =>
    searchPage ? searchPage(value.trim(), page, size, signal) : Promise.resolve({ items: [], total: 0 }), 20, (x: any) => x.id);
  const paged = $derived(searchPage ? list : null);
  const items = $derived(paged ? paged.items : plain);
  let open = $state(false);
  let active = $state(0);
  let loading = $state(false);
  let ctrl: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout>;

  function run(q: string) {
    clearTimeout(timer);
    ctrl?.abort();
    if (q.trim().length < minChars) { plain = []; open = false; return; }
    if (paged) {
      timer = setTimeout(() => { paged.reset(); active = 0; open = true; }, 180);
      return;
    }
    timer = setTimeout(async () => {
      ctrl = new AbortController();
      loading = true;
      try {
        plain = await search!(q.trim(), ctrl.signal);
        active = 0;
        open = true;
      } catch (e) {
        if ((e as Error).name !== "AbortError") { plain = []; open = false; }
      } finally {
        loading = false;
      }
    }, 180);
  }

  function pick(item: T) {
    open = false;
    plain = [];
    onpick(item);
  }

  function onkey(e: KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); if (!open && items.length) open = true; else active = Math.min(items.length - 1, active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); }
    else if (e.key === "Enter") { if (open && items[active]) { e.preventDefault(); pick(items[active]); } }
    else if (e.key === "Escape") { if (open) { e.stopPropagation(); open = false; } }
  }
</script>

<div class="field combo">
  <label class="label" for={id}>{label}</label>
  <div class="input-group">
    <Icon name={icon} />
    <!-- svelte-ignore a11y_autofocus -->
    <input {id} class="input" type="text" role="combobox" autocomplete="off" {placeholder} {autofocus} bind:value bind:this={inputEl}
           aria-expanded={open} aria-controls="{id}-list" aria-autocomplete="list"
           aria-activedescendant={open && items[active] ? `${id}-opt-${active}` : undefined}
           oninput={() => run(value)} onkeydown={onkey} onfocus={() => { if (items.length) open = true; }}
           onblur={() => setTimeout(() => (open = false), 150)} />
    {#if loading || paged?.loading}<span class="combo-spin" aria-hidden="true"></span>{/if}
  </div>
  {#if open}
    <ul class="combo-list" id="{id}-list" role="listbox" aria-label={label}
        onscroll={(e) => { const el = e.currentTarget; if (paged && el.scrollTop + el.clientHeight >= el.scrollHeight - 60) paged.more(); }}>
      {#each items as item, i (i)}
        <li id="{id}-opt-{i}" role="option" aria-selected={i === active} class:is-active={i === active}
            onmousedown={(e) => { e.preventDefault(); pick(item); }} onmouseenter={() => (active = i)}>{@render option(item)}</li>
      {:else}
        <li class="combo-empty" role="option" aria-selected="false" aria-disabled="true">{emptyText}</li>
        {#if onadd && addLabel && value.trim()}
          <li class="combo-add" role="option" aria-selected="false" onmousedown={(e) => { e.preventDefault(); open = false; onadd(value.trim()); }}>
            <Icon name="plus" size="sm" /> Add "{value.trim()}" as {addLabel}
          </li>
        {/if}
      {/each}
    </ul>
  {/if}
</div>

<style src="./styles/Combobox.css"></style>
