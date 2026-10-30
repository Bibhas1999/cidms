<script lang="ts" module>
  import type { Snippet } from "svelte";

  // One column of a DataTable.
  export interface Column<T> {
    key: string;
    label: string;
    /** Draw the cell yourself (a snippet taking the row), or give `value` for plain text. */
    cell?: Snippet<[T]>;
    value?: (row: T) => string | number | null | undefined;
    align?: "left" | "right" | "center";
    /** Makes the header a sort button; the value sent to `onsort` (descending is "-" + sortKey). */
    sortKey?: string;
    /** An ⓘ tip beside the header, for a figure that needs explaining. */
    tip?: string;
    width?: string;
    nowrap?: boolean;
    class?: string;
    /** Hide on tablets and small laptops (shown on wide screens and, as a field, in phone cards unless mobile is "hide"). */
    optional?: boolean;
    /**
     * Where the cell goes when the table becomes cards on phones:
     *  "title" the bold top line · "sub" a quiet line under it · "end" the right of the top line (an amount or a badge)
     *  "field" a "Label  value" line (the default) · "hide" not shown on phones
     */
    mobile?: "title" | "sub" | "end" | "field" | "hide";
  }
</script>

<script lang="ts" generics="T">
  import { navigate, setQuery } from "../lib/router.svelte";
  import EmptyState from "./EmptyState.svelte";
  import Icon from "./Icon.svelte";
  import InfoTip from "./InfoTip.svelte";
  import Pagination from "./Pagination.svelte";
  import IconButton from "./IconButton.svelte";
  import RowMenu, { type RowAction } from "./RowMenu.svelte";

  // The app's table. Every list uses it, so lists look and behave the same everywhere:
  //  - sits inset in its card, in its own rounded box; the header stays in view while the box scrolls
  //  - loading skeleton rows the first time, then the old rows stay (dimmed) while the next page loads
  //  - an empty state, an error with "Try again"
  //  - the ⋮ menu (RowMenu) at the end of each row, from `actions(row)`
  //  - rows that open something: `rowHref(row)` (the address) or `onrowclick(row)`; clicks on links, buttons
  //    and selected text inside the row keep their own meaning
  //  - optional sorting (sortKey on columns + sort/onsort) and selection (selectable + bind:selected)
  //  - server-side pages: pass `page` = { page, size, total } for the Pagination footer (?page= & ?size=)
  //  - phones (< 640px): every row becomes a stacked card (see Column.mobile), with its ⋮ menu top right
  //
  //   <DataTable label="Bills" {columns} rows={data?.items ?? []} loading={!data} {error} onretry={load}
  //              rowHref={(b) => `/bills/${b.id}`} actions={actionsFor} page={data} empty={{ icon: "receipt", title: "No bills yet." }} />
  let { columns, rows, label, rowKey = (r: T) => String((r as { id?: unknown }).id), loading = false, error = "", onretry,
        empty = { title: "Nothing here yet." }, emptySlot, actions, actionsLabel, actionsInline = false, minWidth, rowHref, onrowclick, rowClass,
        selectable = false, selected = $bindable([]), sort = "", onsort, page, onpage, foot, footAlways = false, maxHeight = "", skeletonRows = 5 }: {
    columns: Column<T>[];
    rows: T[];
    /** What the table lists, for screen readers ("Bills"). */
    label: string;
    rowKey?: (row: T) => string;
    loading?: boolean;
    error?: string;
    onretry?: () => void;
    empty?: { icon?: string; title: string; text?: string };
    emptySlot?: Snippet;
    actions?: (row: T) => RowAction[];
    actionsLabel?: (row: T) => string;
    /** Show each action as its own icon button (e.g. one trash button) instead of the ⋮ menu. */
    actionsInline?: boolean;
    /** Narrowest the table may get before it scrolls inside its card (default 680 px; 0 for small tables). */
    minWidth?: number;
    rowHref?: (row: T) => string;
    onrowclick?: (row: T) => void;
    rowClass?: (row: T) => string;
    selectable?: boolean;
    selected?: string[];
    sort?: string;
    onsort?: (sort: string) => void;
    page?: { page: number; size: number; total: number } | null;
    onpage?: (page: number) => void;
    foot?: Snippet;
    /** Show `foot` even with no rows yet (e.g. totals a form keeps building toward from zero). */
    footAlways?: boolean;
    /** Limit the height (e.g. "60vh") so the box scrolls with the header kept in view. */
    maxHeight?: string;
    skeletonRows?: number;
  } = $props();

  const clickable = $derived(!!(rowHref || onrowclick));
  const hasActions = $derived(!!actions);
  const span = $derived(columns.length + (hasActions ? 1 : 0) + (selectable ? 1 : 0));
  const keys = $derived(rows.map(rowKey));
  const allOn = $derived(keys.length > 0 && keys.every((k) => selected.includes(k)));
  const someOn = $derived(!allOn && keys.some((k) => selected.includes(k)));

  function open(e: MouseEvent, row: T) {
    if (!clickable) return;
    const t = e.target as Element;
    if (t.closest("a, button, input, select, textarea, label, [role='menu']") || window.getSelection()?.toString()) return;
    if (rowHref) {
      const href = rowHref(row);
      if (e.ctrlKey || e.metaKey) window.open(href, "_blank", "noopener");
      else navigate(href);
    } else onrowclick?.(row);
  }

  function toggleAll(on: boolean) {
    selected = on ? [...new Set([...selected, ...keys])] : selected.filter((k) => !keys.includes(k));
  }
  function toggleOne(k: string, on: boolean) {
    selected = on ? [...selected, k] : selected.filter((x) => x !== k);
  }

  function sortBy(c: Column<T>) {
    if (!c.sortKey || !onsort) return;
    onsort(sort === c.sortKey ? `-${c.sortKey}` : c.sortKey);
  }
  const ariaSort = (c: Column<T>) =>
    !c.sortKey ? undefined : sort === c.sortKey ? "ascending" : sort === `-${c.sortKey}` ? "descending" : "none";

  const cellClass = (c: Column<T>) =>
    [c.align === "right" ? "num" : c.align === "center" ? "text-center" : "", c.nowrap ? "nowrap" : "", c.optional ? "dt-optional" : "",
     `m-${c.mobile ?? "field"}`, c.class ?? ""].filter(Boolean).join(" ");
</script>

{#if error}
  <div class="card-content dt-error"><div class="alert alert-destructive" role="alert"><Icon name="alert" />
    <div>{error}{#if onretry} <button class="link-button" type="button" onclick={onretry}>Try again</button>{/if}</div></div></div>
{:else}
  <div class="table-wrap dt-wrap" class:has-max={!!maxHeight} style={maxHeight ? `--dt-max-h: ${maxHeight}` : undefined}
       aria-busy={loading || undefined}>
    <table class="table dt-table" class:is-loading={loading && rows.length > 0} class:has-select={selectable} aria-label={label}
           style={minWidth !== undefined ? `min-width: ${minWidth}px` : undefined}>
      <thead>
        <tr>
          {#if selectable}
            <th class="dt-select"><input class="checkbox" type="checkbox" aria-label="Select all on this page" checked={allOn}
                                         indeterminate={someOn} onchange={(e) => toggleAll(e.currentTarget.checked)} /></th>
          {/if}
          {#each columns as c (c.key)}
            <th class={cellClass(c)} style={c.width ? `width: ${c.width}` : undefined} aria-sort={ariaSort(c)} scope="col">
              {#if c.sortKey && onsort}
                <button type="button" class="sort-link dt-sort" onclick={() => sortBy(c)}>{c.label}
                  <span class="sort-icon" aria-hidden="true">{sort === c.sortKey ? "▲" : sort === `-${c.sortKey}` ? "▼" : "↕"}</span></button>
              {:else}{c.label}{/if}
              {#if c.tip}<InfoTip text={c.tip} about={c.label} />{/if}
            </th>
          {/each}
          {#if hasActions}<th class="num dt-actions" scope="col"><span class="sr-only">Actions</span></th>{/if}
        </tr>
      </thead>
      <tbody>
        {#if loading && rows.length === 0}
          {#each { length: skeletonRows } as _, i (i)}
            <tr class="dt-skeleton" aria-hidden="true">
              {#if selectable}<td class="dt-select"></td>{/if}
              {#each columns as c, j (c.key)}<td class={cellClass(c)} style={c.width ? `width: ${c.width}` : undefined}><span class="skeleton" style="width: {j === 0 ? 70 : 45 + ((i * 7 + j * 13) % 40)}%"></span></td>{/each}
              {#if hasActions}<td class="dt-actions m-actions"></td>{/if}
            </tr>
          {/each}
        {:else}
          {#each rows as row, i (keys[i])}
            {@const k = keys[i]}
            {@const acts = actions ? actions(row) : []}
            <tr class="{rowClass?.(row) ?? ''}" class:is-clickable={clickable} class:is-selected={selectable && selected.includes(k)}
                onclick={(e) => open(e, row)}>
              {#if selectable}
                <td class="dt-select"><input class="checkbox" type="checkbox" aria-label="Select row" checked={selected.includes(k)}
                                             onchange={(e) => toggleOne(k, e.currentTarget.checked)} /></td>
              {/if}
              {#each columns as c (c.key)}
                <td class={cellClass(c)} data-label={c.label} style={c.width ? `width: ${c.width}` : undefined}>
                  {#if c.cell}{@render c.cell(row)}{:else}{c.value?.(row) ?? ""}{/if}
                </td>
              {/each}
              {#if hasActions}
                <td class="num dt-actions m-actions">
                  {#if acts.length && actionsInline}
                    {#each acts as a (a.label)}
                      <IconButton icon={a.icon ?? "x"} label={a.label} size="sm" variant={a.tone === "danger" ? "ghost-destructive" : "ghost"}
                                  href={a.href ?? ""} onclick={(e) => { e.stopPropagation(); a.onclick?.(); }} />
                    {/each}
                  {:else if acts.length}<RowMenu actions={acts} label={actionsLabel?.(row) ?? "Actions"} />{/if}
                </td>
              {/if}
            </tr>
          {:else}
            <tr class="dt-empty"><td colspan={span}>
              {#if emptySlot}{@render emptySlot()}{:else}<EmptyState icon={empty.icon} title={empty.title} text={empty.text} />{/if}
            </td></tr>
          {/each}
        {/if}
      </tbody>
      {#if foot && (rows.length || footAlways)}<tfoot>{@render foot()}</tfoot>{/if}
    </table>
  </div>
  {#if page && page.total > 0}
    <Pagination page={page.page} size={page.size} total={page.total} onchange={(p) => (onpage ? onpage(p) : setQuery({ page: p }, { replace: false }))} />
  {/if}
{/if}

<style src="./styles/DataTable.css"></style>
