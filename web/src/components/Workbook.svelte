<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";
  import InfoTip from "./InfoTip.svelte";

  // A page laid out like an Excel window: title bar (with actions), ribbon (filters), formula bar (name box +
  // what the sheet shows), the sheet itself, sheet tabs along the bottom and a status bar with key figures.
  //   <Workbook title="Dues" file="Supreme Health Care" sheets={[{ key: "0", label: "Summary" }, …]} active="0"
  //             onsheet={(k) => …} nameBox="Summary" formula="Bills still owing · 12 bills" {figures}>
  //     {#snippet actions()}…{/snippet} {#snippet ribbon()}…{/snippet}
  //     <Spreadsheet … />
  //   </Workbook>
  let { title, file = "", sheets = [], active = "", onsheet, nameBox = "", formula = "", about = "", figures = [], hint = "",
        status = "Ready", actions, ribbon, children }: {
    title: string; file?: string; sheets?: { key: string; label: string; hint?: string }[]; active?: string;
    onsheet?: (key: string) => void; nameBox?: string; formula?: string; about?: string;
    figures?: { label: string; value: string }[]; hint?: string; status?: string;
    actions?: Snippet; ribbon?: Snippet; children?: Snippet;
  } = $props();
</script>

<div class="workbook">
  <header class="wb-title">
    <span class="wb-app"><Icon name="sheet" size={18} /></span>
    <h1>{title}{#if file}<span class="wb-file">&nbsp;— {file}</span>{/if}</h1>
    {#if actions}<div class="wb-actions no-print">{@render actions()}</div>{/if}
  </header>

  {#if ribbon}<div class="wb-ribbon no-print" role="toolbar" aria-label="Filters">{@render ribbon()}</div>{/if}

  <div class="wb-formula">
    <span class="namebox" title="The sheet on screen">{nameBox}</span>
    <span class="fx" aria-hidden="true">fx</span>
    <span class="formula">{formula}</span>
    {#if about}<InfoTip text={about} about={title} />{/if}
  </div>

  <div class="wb-grid">{@render children?.()}</div>

  {#if sheets.length}
    <nav class="wb-tabs no-print" aria-label="Sheets">
      {#each sheets as s (s.key)}
        <button type="button" class="tab" class:is-active={s.key === active} aria-current={s.key === active ? "page" : undefined}
                title={s.hint} onclick={() => onsheet?.(s.key)}>{s.label}</button>
      {/each}
    </nav>
  {/if}

  <footer class="wb-status">
    <span class="st-state">{status}</span>
    {#if figures.length}
      <dl class="st-figures" aria-live="polite">{#each figures as f (f.label)}<div><dt>{f.label}</dt><dd>{f.value}</dd></div>{/each}</dl>
    {/if}
    {#if hint}<span class="st-hint no-print">{hint}</span>{/if}
  </footer>
</div>

<style>
  .workbook { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
    background: var(--card); box-shadow: var(--shadow-sm, 0 1px 2px rgb(0 0 0 / .06)); min-width: 0; }

  .wb-title { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--brand-navy, #0b2f6b); color: #fff; }
  .wb-app { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 6px; background: rgb(255 255 255 / .14); flex: none; }
  .wb-title h1 { margin: 0; color: #fff; font: 650 15px/1.2 var(--font-sans); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0; }
  .wb-file { font-weight: 400; color: rgb(255 255 255 / .78); }
  .wb-actions { display: flex; gap: 6px; align-items: center; }
  .wb-actions :global(.btn) { height: 32px; background: rgb(255 255 255 / .12); border-color: rgb(255 255 255 / .25); color: #fff; }
  .wb-actions :global(.btn:hover:not(:disabled)) { background: rgb(255 255 255 / .22); }

  .wb-ribbon { display: flex; align-items: stretch; flex-wrap: wrap; padding: 6px 8px 4px; background: var(--muted); border-bottom: 1px solid var(--border); }
  .wb-ribbon :global(.rb-group) { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 2px 12px; border-right: 1px solid var(--border); }
  .wb-ribbon :global(.rb-group:last-child) { border-right: 0; }
  .wb-ribbon :global(.rb-body) { display: flex; align-items: center; gap: 6px; min-height: 34px; }
  .wb-ribbon :global(.rb-label) { font-size: 11px; color: var(--muted-foreground); letter-spacing: .02em; }
  .wb-ribbon :global(.date-filter > .select) { width: 170px; min-width: 0; }

  .wb-formula { display: flex; align-items: center; height: 32px; border-bottom: 1px solid var(--border); background: var(--card); font-size: 13px; }
  .namebox { width: 170px; flex: none; height: 100%; display: flex; align-items: center; padding: 0 10px; border-right: 1px solid var(--border);
    font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .fx { padding: 0 10px; font: italic 600 13px Georgia, serif; color: var(--muted-foreground); border-right: 1px solid var(--border); height: 100%; display: flex; align-items: center; }
  .formula { flex: 1; min-width: 0; padding: 0 10px; color: var(--muted-foreground); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .wb-formula :global(button) { margin-right: 8px; }

  /* Empty cells fill the window below and beside the data, as in Excel. */
  .wb-grid { min-width: 0; min-height: calc(100vh - 318px); background-color: var(--card);
    background-image: linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px);
    background-size: 110px 25px; background-position: -1px -1px; }
  .wb-grid :global(.jss_content), .wb-grid :global(.jexcel_content) { border: 0 !important; border-radius: 0 !important; }
  .wb-grid :global(.wb-empty) { display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 260px; color: var(--muted-foreground); }

  .wb-tabs { display: flex; align-items: flex-end; gap: 1px; padding: 0 8px; overflow-x: auto; background: var(--muted); border-top: 1px solid var(--border); scrollbar-width: thin; }
  .tab { flex: none; padding: 6px 14px 7px; border: 1px solid transparent; border-top: 0; border-radius: 0 0 7px 7px; background: transparent;
    color: var(--muted-foreground); font: 500 12.5px var(--font-sans); white-space: nowrap; cursor: pointer; }
  .tab:hover { color: var(--foreground); background: color-mix(in srgb, var(--card) 60%, transparent); }
  .tab.is-active { background: var(--card); border-color: var(--border); color: var(--primary-text); font-weight: 650; box-shadow: inset 0 -2px 0 var(--primary); margin-top: -1px; }

  .wb-status { display: flex; align-items: center; gap: 6px 18px; flex-wrap: wrap; min-height: 28px; padding: 4px 12px; background: var(--primary); color: #fff; font-size: 12px; }
  .st-state { font-weight: 600; }
  .st-figures { display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 0; }
  .st-figures div { display: flex; gap: 5px; }
  .st-figures dt { opacity: .8; }
  .st-figures dd { margin: 0; font-weight: 650; font-variant-numeric: tabular-nums; }
  .st-hint { margin-left: auto; opacity: .8; }

  @media (max-width: 760px) {
    .wb-ribbon { flex-direction: column; align-items: stretch; }
    .wb-ribbon :global(.rb-group) { border-right: 0; border-bottom: 1px solid var(--border); align-items: stretch; padding: 6px 4px; }
    .wb-ribbon :global(.date-filter > .select) { width: 100%; }
    .namebox { width: 110px; }
    .st-hint { display: none; }
  }
  @media print {
    .workbook { border: 0; box-shadow: none; }
    .wb-title, .wb-formula, .wb-status { display: none; }
  }
</style>
