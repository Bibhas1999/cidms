<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "../Icon.svelte";
  import InfoTip from "../InfoTip.svelte";

  // A card for one chart: title, a line of description, an ⓘ tip explaining the figure, the legend, a
  // "Show as table" switch (every chart has a table view), and loading / error / empty states.
  //   <ChartCard title="Billed and collected" tip="…" table={{ columns, rows }} empty={!points.length}>
  //     {#snippet legend()}…{/snippet}  <LineChart … />
  //   </ChartCard>
  export interface TableData { columns: { label: string; num?: boolean }[]; rows: (string | number)[][]; caption?: string }

  let { title, description = "", tip = "", loading = false, error = "", empty = false, emptyText = "Nothing to show for these filters.",
        emptyIcon = "barChart", table = null, class: extra = "", legend, actions, children }: {
    title: string; description?: string; tip?: string; loading?: boolean; error?: string; empty?: boolean; emptyText?: string; emptyIcon?: string;
    table?: TableData | null; class?: string; legend?: Snippet; actions?: Snippet; children: Snippet;
  } = $props();

  const uid = $props.id();
  let showTable = $state(false);
</script>

<section class="card chart-card {extra}" aria-labelledby="{uid}-title" aria-busy={loading}>
  <div class="card-header">
    <div style="min-width: 0">
      <div class="chart-title-row"><h2 class="card-title" id="{uid}-title">{title}</h2>{#if tip}<InfoTip text={tip} about={title} />{/if}</div>
      {#if description}<p class="card-description">{description}</p>{/if}
    </div>
    {#if actions || (table && !empty && !error)}
      <div class="chart-card-actions">
        {#if actions}{@render actions()}{/if}
        {#if table && !empty && !error}
          <button class="link-button text-sm" type="button" aria-pressed={showTable} onclick={() => (showTable = !showTable)}>
            {showTable ? "Show chart" : "Show as table"}
          </button>
        {/if}
      </div>
    {/if}
  </div>
  <div class="card-content">
    {#if error}
      <div class="empty"><Icon name="alert" />Couldn't load this chart. {error}</div>
    {:else if loading && empty}
      <div class="chart-skeleton" aria-label="Loading"></div>
    {:else if empty}
      <div class="empty"><Icon name={emptyIcon} />{emptyText}</div>
    {:else}
      {#if legend && !showTable}<div class="chart-legend" aria-hidden="true">{@render legend()}</div>{/if}
      {#if showTable && table}
        <div class="table-wrap chart-table">
          <table class="table">
            <caption class="sr-only">{table.caption ?? title}</caption>
            <thead><tr>{#each table.columns as c, i (i)}<th class={c.num ? "num" : ""}>{c.label}</th>{/each}</tr></thead>
            <tbody>
              {#each table.rows as r, i (i)}
                <tr>{#each r as cell, j (j)}<td class={table.columns[j]?.num ? "num tabular" : ""}>{cell}</td>{/each}</tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else}
        {@render children()}
      {/if}
    {/if}
  </div>
</section>
