<script lang="ts">
  import DateRange from "../../components/DateRange.svelte";
  import ExportMenu from "../../components/ExportMenu.svelte";
  import Icon from "../../components/Icon.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import Spreadsheet from "../../components/Spreadsheet.svelte";
  import { get } from "../../lib/api";
  import { rangeLabel, todayISO } from "../../lib/dates";
  import { count, date, dateTime, rupees } from "../../lib/format";
  import { navigate, router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { notifyError } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";

  // Billing reports, laid out like an Excel workbook: a title bar, a ribbon with the filters, a formula bar
  // (name box + what the sheet shows), the sheet itself, sheet tabs along the bottom (one per report; the Bills
  // report opens into Summary + one tab per referring doctor) and a status bar with the key figures.
  // /reports/<name>?from=&to=&group=&mode=&department_id=&sheet= — everything lives in the address, and
  // Excel, PDF and Print use exactly what's on screen.
  let { params = {} }: { params?: Record<string, string> } = $props();

  type Kind = "text" | "money" | "int" | "date" | "datetime" | "percent";
  interface Meta { name: string; group: "money" | "work"; title: string; question: string; description: string; filters: string[] }
  interface Column { key: string; label: string; kind: Kind }
  interface Summary { label: string; value: string | number; kind: Kind }
  interface Sheet {
    name: string; title: string; subtitle: string; columns: Column[];
    rows: Record<string, string | number | null>[]; totals: Record<string, string | number | null> | null; summary: Summary[];
  }
  interface Report extends Sheet { sheets?: Sheet[] }
  interface Department { id: string; name: string }

  // What each report counts and which date it goes by, for the ⓘ in the formula bar.
  const ABOUT: Record<string, string> = {
    bills: "Every bill dated in the range. Summary: one row per referring doctor (bills without one count as Self); each doctor's sheet lists their bills. Cancelled bills are listed but not added up.",
    collection: "Bills, billed and discounts go by the bill's date; money goes by the day it was received, so Net collected includes dues paid on older bills. Net collected = payments − refunds. Cancelled bills never count.",
    payments: "Every payment and refund received in these dates, whatever the bill's date. Refunds show as negative amounts.",
    dues: "Bills that still have money owed today, oldest first. Age is days since the bill's date. Dates, if chosen, narrow by bill date.",
    discounts: "Bills dated in the range that were given a discount. % is the discount as a share of the bill before discount.",
    tests: "Tests on bills dated in the range, counted by quantity. Amount is the price before any bill discount.",
    departments: "Tests, bills and amount per department. A bill with tests from two departments counts in both rows.",
    "referring-doctors": "Bills per referring doctor; bills without a doctor count as Self. Billed is after discount.",
    staff: "Bills each person made (by bill date), and money each person took (by the day received).",
  };
  const GROUP_BY = [{ id: "day", label: "Day" }, { id: "week", label: "Week" }, { id: "month", label: "Month" }, { id: "year", label: "Year" }];
  const MODES = [{ id: "cash", label: "Cash" }, { id: "upi", label: "UPI" }, { id: "card", label: "Card" }, { id: "bank", label: "Bank" }, { id: "other", label: "Other" }];

  let catalogue = $state<Meta[]>([]);
  let departments = $state<Department[]>([]);
  let report = $state<Report | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);

  const today = todayISO();
  const monthStart = today.slice(0, 8) + "01";

  const name = $derived(params.name || (catalogue.some((r) => r.name === "bills") ? "bills" : catalogue[0]?.name ?? "bills"));
  const meta = $derived(catalogue.find((r) => r.name === name));
  const q = $derived(router.query);
  const f = $derived(meta?.filters ?? []);
  const usesDates = $derived(f.includes("range") || f.includes("range_optional"));
  const optionalDates = $derived(f.includes("range_optional"));
  // "all" = every date. Otherwise this month by default, for every report.
  const allTime = $derived(q.get("from") === "all");
  const from = $derived(allTime ? "" : q.get("from") ?? monthStart);
  const to = $derived(allTime ? "" : q.get("to") ?? today);
  const group = $derived(GROUP_BY.some((g) => g.id === q.get("group")) ? q.get("group")! : "day");
  const mode = $derived(q.get("mode") ?? "");
  const departmentId = $derived(q.get("department_id") ?? "");

  const query = $derived({
    from: usesDates && !allTime ? from : undefined,
    to: usesDates && !allTime ? to : undefined,
    all: usesDates && allTime && !optionalDates ? true : undefined,
    group: f.includes("group") ? group : undefined,
    mode: f.includes("mode") ? mode || undefined : undefined,
    department_id: f.includes("department") ? departmentId || undefined : undefined,
  });
  const filtered = $derived(!!(query.mode || query.department_id));

  $effect(() => {
    get<Meta[]>("/api/reports").then((c) => (catalogue = c)).catch((e) => { loadError = e.message; });
    get<Department[]>("/api/departments").then((d) => (departments = d)).catch((e) => notifyError(e));
  });

  $effect(() => {
    if (!meta) return;
    const ctrl = new AbortController();
    const want = { ...query };
    void reload;
    loading = true;
    get<Report>(`/api/reports/${meta.name}`, want, ctrl.signal)
      .then((r) => { report = r; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") { loadError = e.message; report = null; } })
      .finally(() => { if (!ctrl.signal.aborted) loading = false; });
    return () => ctrl.abort();
  });

  // ---------- sheets ----------
  const ready = $derived(!!report && !!meta && report.name === meta.name);
  const subSheets = $derived(ready ? report!.sheets ?? [] : []);
  const sheetIndex = $derived(Math.min(Math.max(0, Number(q.get("sheet") ?? 0) || 0), subSheets.length));
  // The sheet on screen: the report itself (or the Summary of a workbook report), or one of its sheets.
  const active = $derived<Sheet | null>(ready ? (sheetIndex > 0 ? subSheets[sheetIndex - 1] : report) : null);
  const activeName = $derived(!meta ? "" : sheetIndex > 0 && active ? active.title : subSheets.length ? "Summary" : meta.title);

  /** Moving to another report keeps the dates. */
  function linkFor(r: Meta): string {
    const qs = new URLSearchParams();
    for (const k of ["from", "to"]) { const v = q.get(k); if (v !== null) qs.set(k, v); }
    const s = qs.toString();
    return `/reports/${r.name}${s ? `?${s}` : ""}`;
  }
  const setRange = (a: string, b: string) => setQuery(!a && !b ? { from: "all", to: null, sheet: null } : { from: a, to: b, sheet: null });
  const openSheet = (i: number) => setQuery({ sheet: i ? String(i) : null });

  function show(value: string | number | null | undefined, kind: Kind): string {
    if (value === null || value === undefined || value === "") return kind === "text" ? "—" : "";
    switch (kind) {
      case "money": return rupees(value);
      case "int": return count(Number(value));
      case "percent": return `${Number(value).toFixed(2)}%`;
      case "date": return date(String(value));
      case "datetime": return dateTime(String(value));
      default: return String(value);
    }
  }
  // Double-click: a doctor on the Summary opens their sheet; a bill opens the bill.
  function openRow(row: Record<string, unknown>) {
    if (subSheets.length && sheetIndex === 0 && typeof row.doctor === "string") {
      const i = subSheets.findIndex((s) => s.title === row.doctor);
      if (i >= 0) { openSheet(i + 1); return; }
    }
    if (typeof row.id === "string") navigate(`/bills/${row.id}`);
  }
  // The whole workbook uses the same dates (and grouping) as the sheet on screen.
  const bookQuery = $derived({ from: allTime ? undefined : from, to: allTime ? undefined : to, all: allTime || undefined, group });
  const periodWords = $derived(usesDates ? (allTime ? (optionalDates ? "Any date" : "All time") : rangeLabel(from, to)) : "");
  const printedAt = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" }).format(new Date());
  const figures = $derived(ready ? report!.summary : []);
  const opensBills = $derived(!!active?.rows.some((r) => typeof r.id === "string"));
</script>

<div class="workbook" aria-busy={loading}>
  <!-- title bar -->
  <header class="wb-title">
    <span class="wb-app"><Icon name="sheet" size={18} /></span>
    <h1>Billing reports<span class="wb-file">{session.workspace?.name ? ` — ${session.workspace.name}` : ""}{periodWords ? ` · ${periodWords}` : ""}</span></h1>
    {#if meta}
      <div class="wb-actions no-print">
        <button class="btn btn-sm wb-btn" type="button" disabled={!ready || loading} onclick={() => window.print()}><Icon name="printer" size="sm" /> Print</button>
        <ExportMenu path="/api/reports/{meta.name}" kind="report" {query} label="Download" disabled={!ready || loading}
                    workbook={{ path: "/api/reports/workbook.xlsx", query: bookQuery,
                                about: "One Excel file with a sheet for each report — Bills, Collection, Dues, Payments and the rest — for these dates." }} />
      </div>
    {/if}
  </header>

  <!-- ribbon: the filters, grouped like Excel's ribbon -->
  <div class="wb-ribbon no-print" role="toolbar" aria-label="Filters">
    {#if meta && usesDates}
      <div class="rb-group"><div class="rb-body"><DateRange id="rep" {from} {to} anyLabel={optionalDates ? "Any date" : "All time"} compact onchange={setRange} /></div><span class="rb-label">Dates</span></div>
    {/if}
    {#if f.includes("group")}
      <div class="rb-group">
        <div class="rb-body segmented" role="radiogroup" aria-label="One row per">
          {#each GROUP_BY as g (g.id)}
            <button type="button" role="radio" aria-checked={group === g.id} class:is-on={group === g.id}
                    onclick={() => setQuery({ group: g.id === "day" ? null : g.id })}>{g.label}</button>
          {/each}
        </div>
        <span class="rb-label">One row per</span>
      </div>
    {/if}
    {#if f.includes("mode")}
      <div class="rb-group">
        <div class="rb-body"><label class="sr-only" for="rep-mode">Payment mode</label>
          <select id="rep-mode" class="select select-sm" value={mode} onchange={(e) => setQuery({ mode: e.currentTarget.value || null })}>
            <option value="">All payment modes</option>
            {#each MODES as m (m.id)}<option value={m.id}>{m.label}</option>{/each}
          </select></div>
        <span class="rb-label">Payment mode</span>
      </div>
    {/if}
    {#if f.includes("department")}
      <div class="rb-group">
        <div class="rb-body"><label class="sr-only" for="rep-dept">Department</label>
          <select id="rep-dept" class="select select-sm" value={departmentId} onchange={(e) => setQuery({ department_id: e.currentTarget.value || null })}>
            <option value="">All departments</option>
            {#each departments as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
          </select></div>
        <span class="rb-label">Department</span>
      </div>
    {/if}
    {#if filtered}<button class="btn btn-ghost btn-sm" type="button" onclick={() => setQuery({ mode: null, department_id: null })}><Icon name="x" size="sm" /> Clear</button>{/if}
  </div>

  <!-- formula bar: name box + what this sheet shows -->
  {#if meta}
    <div class="wb-formula">
      <span class="namebox" title="The sheet on screen">{activeName}</span>
      <span class="fx" aria-hidden="true">fx</span>
      <span class="formula">{active ? active.subtitle : meta.description}</span>
      {#if ABOUT[meta.name]}<InfoTip text={ABOUT[meta.name]} about={meta.title} />{/if}
    </div>
  {/if}

  <div class="print-head" aria-hidden="true">
    <strong>{session.workspace?.name}</strong> · {meta?.title}{sheetIndex > 0 ? ` · ${activeName}` : ""}{periodWords ? ` · ${periodWords}` : ""} · printed {printedAt}
  </div>

  <!-- the sheet -->
  <div class="wb-grid">
    {#if loadError}
      <div class="wb-empty" role="alert"><Icon name="alert" />{loadError} <button class="link-button" onclick={() => reload++}>Try again</button></div>
    {:else if !catalogue.length || (meta && !active)}
      <div class="wb-empty" aria-busy="true">Loading…</div>
    {:else if !meta}
      <div class="wb-empty"><Icon name="lock" />This report isn't available to you.</div>
    {:else if active && active.rows.length}
      {#key `${report?.name}|${report?.subtitle}|${sheetIndex}|${active.rows.length}`}
        <Spreadsheet label={activeName} columns={active.columns} rows={active.rows} totals={active.totals}
                     height="calc(100vh - 318px)" onopen={openRow} />
      {/key}
    {:else}
      <div class="wb-empty"><Icon name="inbox" />Nothing for these filters.</div>
    {/if}
  </div>

  <!-- sheet tabs, along the bottom as in Excel -->
  {#if catalogue.length}
    <nav class="wb-tabs no-print" aria-label="Sheets">
      {#each catalogue as r (r.name)}
        {@const on = r.name === name}
        <a class="tab" class:is-active={on && sheetIndex === 0} class:is-open={on} href={linkFor(r)} aria-current={on && sheetIndex === 0 ? "page" : undefined}
           use:tooltip={{ text: r.question, placement: "top" }}>{r.title}{#if on && subSheets.length}<span class="tab-sub">&nbsp;· Summary</span>{/if}</a>
        {#if on && subSheets.length}
          {#each subSheets as s, i (s.title)}
            <button type="button" class="tab tab-child" class:is-active={sheetIndex === i + 1} aria-current={sheetIndex === i + 1 ? "page" : undefined}
                    onclick={() => openSheet(i + 1)}>{s.title}</button>
          {/each}
          <span class="tab-gap" aria-hidden="true"></span>
        {/if}
      {/each}
    </nav>
  {/if}

  <!-- status bar -->
  <footer class="wb-status">
    <span class="st-state">{loading ? "Calculating…" : loadError ? "Error" : "Ready"}</span>
    {#if figures.length}
      <dl class="st-figures" aria-live="polite">
        {#each figures as s (s.label)}<div><dt>{s.label}</dt><dd>{show(s.value, s.kind)}</dd></div>{/each}
      </dl>
    {/if}
    <span class="st-hint no-print">Sort: click a heading · Filter: the row under the headings · Copy: select, Ctrl+C{opensBills ? " · Double-click a bill to open it" : subSheets.length && sheetIndex === 0 ? " · Double-click a doctor for their sheet" : ""}</span>
  </footer>
</div>

<style>
  /* An Excel window in the app's colours: title bar, ribbon, formula bar, grid, sheet tabs, status bar. */
  .workbook { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
    background: var(--card); box-shadow: var(--shadow-sm, 0 1px 2px rgb(0 0 0 / .06)); min-width: 0; }

  .wb-title { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--brand-navy, #0b2f6b); color: #fff; }
  .wb-app { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 6px; background: rgb(255 255 255 / .14); flex: none; }
  .wb-title h1 { margin: 0; color: #fff; font: 650 15px/1.2 var(--font-sans); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0; }
  .wb-file { font-weight: 400; color: rgb(255 255 255 / .78); }
  .wb-actions { display: flex; gap: 6px; align-items: center; }
  .wb-actions :global(.btn) { height: 32px; background: rgb(255 255 255 / .12); border-color: rgb(255 255 255 / .25); color: #fff; }
  .wb-actions :global(.btn:hover:not(:disabled)) { background: rgb(255 255 255 / .22); }

  .wb-ribbon { display: flex; align-items: stretch; flex-wrap: wrap; gap: 0; padding: 6px 8px 4px; background: var(--muted); border-bottom: 1px solid var(--border); }
  .rb-group { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 2px 12px; border-right: 1px solid var(--border); }
  .rb-group:last-of-type { border-right: 0; }
  .rb-body { display: flex; align-items: center; min-height: 34px; }
  .rb-label { font-size: 11px; color: var(--muted-foreground); letter-spacing: .02em; }
  .wb-ribbon > .btn { align-self: center; margin-left: 8px; }
  .wb-ribbon .select { width: 180px; }
  .wb-ribbon :global(.date-filter > .select) { width: 170px; min-width: 0; }
  .segmented { display: inline-flex; align-items: center; height: 32px; padding: 2px; gap: 2px; border: 1px solid var(--input); border-radius: 7px; background: var(--background); }
  .segmented button { height: 26px; padding: 0 11px; border: 0; border-radius: 5px; background: none; color: var(--foreground); font: 500 12.5px var(--font-sans); cursor: pointer; }
  .segmented button:hover { background: var(--muted); }
  .segmented button.is-on { background: var(--primary); color: #fff; }

  .wb-formula { display: flex; align-items: center; gap: 0; height: 32px; border-bottom: 1px solid var(--border); background: var(--card); font-size: 13px; }
  .namebox { width: 160px; flex: none; height: 100%; display: flex; align-items: center; padding: 0 10px; border-right: 1px solid var(--border);
    font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .fx { padding: 0 10px; font: italic 600 13px Georgia, serif; color: var(--muted-foreground); border-right: 1px solid var(--border); height: 100%; display: flex; align-items: center; }
  .formula { flex: 1; min-width: 0; padding: 0 10px; color: var(--muted-foreground); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .wb-formula :global(button) { margin-right: 8px; }

  /* Empty cells fill the window below and beside the data, as in Excel. */
  .wb-grid { min-width: 0; min-height: calc(100vh - 318px); background-color: var(--card);
    background-image: linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px);
    background-size: 110px 25px; background-position: -1px -1px; }
  /* the sheet fills the window: no rounded card of its own */
  .wb-grid :global(.jss_content), .wb-grid :global(.jexcel_content) { border: 0 !important; border-radius: 0 !important; }
  .wb-empty { display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 260px; color: var(--muted-foreground);
    background-image: linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px);
    background-size: 96px 24px; background-position: -1px -1px; }
  .wb-empty :global(.link-button) { margin-left: 6px; }

  .wb-tabs { display: flex; align-items: flex-end; gap: 1px; padding: 0 8px; overflow-x: auto; background: var(--muted); border-top: 1px solid var(--border); scrollbar-width: thin; }
  .tab { flex: none; padding: 6px 14px 7px; border: 1px solid transparent; border-top: 0; border-radius: 0 0 7px 7px; background: transparent;
    color: var(--muted-foreground); font: 500 12.5px var(--font-sans); text-decoration: none !important; white-space: nowrap; cursor: pointer; }
  .tab:hover { color: var(--foreground); background: color-mix(in srgb, var(--card) 60%, transparent); }
  .tab.is-open { color: var(--foreground); }
  .tab.is-active { background: var(--card); border-color: var(--border); color: var(--primary-text); font-weight: 650; box-shadow: inset 0 -2px 0 var(--primary); margin-top: -1px; }
  .tab-sub { font-weight: 400; color: var(--muted-foreground); }
  .tab-child { font-size: 12px; padding-inline: 11px; }
  .tab-gap { flex: none; width: 1px; height: 18px; margin: 0 6px 6px; background: var(--border); }

  .wb-status { display: flex; align-items: center; gap: 6px 18px; flex-wrap: wrap; min-height: 28px; padding: 4px 12px; background: var(--primary); color: #fff; font-size: 12px; }
  .st-state { font-weight: 600; }
  .st-figures { display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 0; }
  .st-figures div { display: flex; gap: 5px; }
  .st-figures dt { opacity: .8; }
  .st-figures dd { margin: 0; font-weight: 650; font-variant-numeric: tabular-nums; }
  .st-hint { margin-left: auto; opacity: .8; }
  .print-head { display: none; }

  @media (max-width: 760px) {
    .wb-ribbon { flex-direction: column; align-items: stretch; }
    .rb-group { border-right: 0; border-bottom: 1px solid var(--border); align-items: stretch; padding: 6px 4px; }
    .wb-ribbon .select, .wb-ribbon :global(.date-filter > .select) { width: 100%; }
    .namebox { width: 110px; }
    .st-hint { display: none; }
  }
  @media print {
    .workbook { border: 0; box-shadow: none; }
    .wb-title, .wb-formula, .wb-status { display: none; }
    .print-head { display: block; margin-bottom: 10px; font-size: 12px; }
  }
</style>
