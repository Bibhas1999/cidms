<script lang="ts" generics="T">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";

  // A search box with a list of matches (WAI-ARIA combobox): type to search, ↑/↓ to move, Enter to pick,
  // Esc to close. `search` loads the matches; `onpick` receives the chosen one.
  let { id, label, placeholder = "", search, onpick, option, value = $bindable(""), icon = "search", minChars = 1,
        emptyText = "No matches.", autofocus = false, inputEl = $bindable() }: {
    id: string; label: string; placeholder?: string; search: (q: string, signal: AbortSignal) => Promise<T[]>;
    onpick: (item: T) => void; option: Snippet<[T]>; value?: string; icon?: string; minChars?: number; emptyText?: string;
    autofocus?: boolean; inputEl?: HTMLInputElement;
  } = $props();

  let items = $state<T[]>([]);
  let open = $state(false);
  let active = $state(0);
  let loading = $state(false);
  let ctrl: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout>;

  function run(q: string) {
    clearTimeout(timer);
    ctrl?.abort();
    if (q.trim().length < minChars) { items = []; open = false; return; }
    timer = setTimeout(async () => {
      ctrl = new AbortController();
      loading = true;
      try {
        items = await search(q.trim(), ctrl.signal);
        active = 0;
        open = true;
      } catch (e) {
        if ((e as Error).name !== "AbortError") { items = []; open = false; }
      } finally {
        loading = false;
      }
    }, 180);
  }

  function pick(item: T) {
    open = false;
    items = [];
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
    {#if loading}<span class="combo-spin" aria-hidden="true"></span>{/if}
  </div>
  {#if open}
    <ul class="combo-list" id="{id}-list" role="listbox" aria-label={label}>
      {#each items as item, i (i)}
        <li id="{id}-opt-{i}" role="option" aria-selected={i === active} class:is-active={i === active}
            onmousedown={(e) => { e.preventDefault(); pick(item); }} onmouseenter={() => (active = i)}>{@render option(item)}</li>
      {:else}
        <li class="combo-empty" role="option" aria-selected="false" aria-disabled="true">{emptyText}</li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .combo { position: relative; }
  .combo-list { position: absolute; z-index: 40; left: 0; right: 0; top: 100%; margin: 4px 0 0; padding: 4px; list-style: none; max-height: 320px; overflow-y: auto;
    background: var(--popover); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-lg); }
  .combo-list li { padding: 8px 10px; border-radius: var(--radius-sm); cursor: pointer; }
  .combo-list li.is-active { background: var(--accent); }
  .combo-empty { color: var(--muted-foreground); cursor: default !important; }
  .combo-spin { position: absolute; right: 12px; top: 50%; width: 14px; height: 14px; margin-top: -7px; border-radius: 50%;
    border: 2px solid var(--border); border-top-color: var(--primary); animation: combo-spin .7s linear infinite; }
  @keyframes combo-spin { to { transform: rotate(360deg); } }
</style>
