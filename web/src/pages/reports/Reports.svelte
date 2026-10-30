<script lang="ts">
  import DateRange from "../../components/DateRange.svelte";
  import ExportMenu from "../../components/ExportMenu.svelte";
  import Icon from "../../components/Icon.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import Spreadsheet from "../../components/Spreadsheet.svelte";
  import { get } from "../../lib/api";
  import { rangeLabel, todayISO } from "../../lib/dates";
  import { count, date, dateTime, rupees } from "../../lib/format";
  import { navigate, router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { notifyError } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";

  // Billing reports. One page, three steps: pick the question, set the filters, read (or download/print)
  // the table. /reports/<name>?from=&to=&group=&mode=&department_id= — filters live in the address, and
  // Excel, PDF and Print all use exactly what's on screen.
  let { params = {} }: { params?: Record<string, string> } = $props();

  type Kind = "text" | "money" | "int" | "date" | "datetime" | "percent";
  interface Meta { name: string; group: "money" | "work"; title: string; question: string; description: string; filters: string[] }
  interface Column { key: string; label: string; kind: Kind }
  interface Summary { label: string; value: string | number; kind: Kind }
  interface Report {
    name: string; title: string; subtitle: string; columns: Column[];
    rows: Record<string, string | number | null>[]; totals: Record<string, string | number | null> | null; summary: Summary[];
  }
  interface Department { id: string; name: string }

  const ICON: Record<string, string> = {
    collection: "wallet", payments: "receipt", dues: "clock", discounts: "tag",
    tests: "flask", departments: "layers", "referring-doctors": "stethoscope", staff: "users",
  };
  // What each report counts and which date it goes by, for the ⓘ beside the table title.
  const ABOUT: Record<string, string> = {
    collection: "Bills, billed and discounts go by the bill's date; money goes by the day it was received, so Net collected includes dues paid on older bills. Net collected = payments − refunds. Cancelled bills never count.",
    payments: "Every payment and refund received in these dates, whatever the bill's date. Refunds show as negative amounts.",
    dues: "Bills that still have money owed today, oldest first. Age is days since the bill's date. Dates, if chosen, narrow by bill date.",
    discounts: "Bills dated in the range that were given a discount. % is the discount as a share of the bill before discount.",
    tests: "Tests on bills dated in the range, counted by quantity. Amount is the price before any bill discount.",
    departments: "Tests, bills and amount per department. A bill with tests from two departments counts in both rows.",
    "referring-doctors": "Bills per referring doctor; bills without a doctor count as Self. Billed is after discount.",
    staff: "Bills each person made (by bill date), and money each person took (by the day received).",
  };
  const FIGURE: Record<string, string> = {
    Bills: "Bills dated in the range, not counting cancelled bills.",
    Billed: "Bill totals after discount; cancelled bills left out.",
    "Net collected": "Payments received minus refunds given in these dates, whatever the bill's date.",
    "Dues collected": "Payments taken on bills dated before the day they were paid.",
    "Bills with dues": "Bills with money still owed today.",
    "Total due": "Everything still owed on those bills today.",
    "Net received": "Payments minus refunds in these dates.",
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

  const name = $derived(params.name || (catalogue.some((r) => r.name === "collection") ? "collection" : catalogue[0]?.name ?? "collection"));
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

  /** Moving to another report keeps the dates. */
  function linkFor(r: Meta): string {
    const qs = new URLSearchParams();
    for (const k of ["from", "to"]) { const v = q.get(k); if (v !== null) qs.set(k, v); }
    const s = qs.toString();
    return `/reports/${r.name}${s ? `?${s}` : ""}`;
  }
  const setRange = (a: string, b: string) => setQuery(!a && !b ? { from: "all", to: null } : { from: a, to: b });

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
  // The whole workbook uses the same dates (and grouping) as the sheet on screen.
  const bookQuery = $derived({ from: allTime ? undefined : from, to: allTime ? undefined : to, all: allTime || undefined, group });
  const openRow = (row: Record<string, unknown>) => { if (typeof row.id === "string") navigate(`/bills/${row.id}`); };
  const periodWords = $derived(usesDates ? (allTime ? (optionalDates ? "Any date" : "All time") : rangeLabel(from, to)) : "");
  const printedAt = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" }).format(new Date());
</script>

<PageHeader eyebrow="Billing" title="Billing reports">
  {#snippet actions()}
    {#if meta}
      <button class="btn btn-outline" type="button" disabled={!report || loading} onclick={() => window.print()}><Icon name="printer" /> Print</button>
      <ExportMenu path="/api/reports/{meta.name}" kind="report" {query} label="Download" disabled={!report || loading}
                  workbook={{ path: "/api/reports/workbook.xlsx", query: bookQuery,
                              about: "One Excel file with a sheet for each report — Collection, Dues, Payments and the rest — for these dates. Dues always lists every bill still owing." }} />
    {/if}
  {/snippet}
</PageHeader>

<!-- one bar: which report, and its filters -->
<section class="card bar no-print" aria-label="Report and filters">
  {#if meta && usesDates}<DateRange id="rep" {from} {to} anyLabel={optionalDates ? "Any date" : "All time"} compact onchange={setRange} />{/if}
  {#if f.includes("group")}
    <div class="segmented" role="radiogroup" aria-label="One row per">
      <span class="seg-label">One row per</span>
      {#each GROUP_BY as g (g.id)}
        <button type="button" role="radio" aria-checked={group === g.id} class:is-on={group === g.id}
                onclick={() => setQuery({ group: g.id === "day" ? null : g.id })}>{g.label}</button>
      {/each}
    </div>
  {/if}
  {#if f.includes("mode")}
    <label class="sr-only" for="rep-mode">Payment mode</label>
    <select id="rep-mode" class="select" value={mode} onchange={(e) => setQuery({ mode: e.currentTarget.value || null })}>
      <option value="">All payment modes</option>
      {#each MODES as m (m.id)}<option value={m.id}>{m.label}</option>{/each}
    </select>
  {/if}
  {#if f.includes("department")}
    <label class="sr-only" for="rep-dept">Department</label>
    <select id="rep-dept" class="select" value={departmentId} onchange={(e) => setQuery({ department_id: e.currentTarget.value || null })}>
      <option value="">All departments</option>
      {#each departments as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
    </select>
  {/if}
  {#if filtered}<button class="btn btn-ghost" type="button" onclick={() => setQuery({ mode: null, department_id: null })}><Icon name="x" size="sm" /> Clear</button>{/if}
</section>

{#if meta}
  <!-- one tab per report -->
  <nav class="sheet-tabs no-print" aria-label="Sheets">
    {#each catalogue as r (r.name)}
      <a class="sheet-tab" class:is-active={r.name === name} href={linkFor(r)} aria-current={r.name === name ? "page" : undefined}
         use:tooltip={{ text: r.question, placement: "bottom" }}>{r.title}</a>
    {/each}
  </nav>

  <div class="print-head" aria-hidden="true">
    <strong>{session.workspace?.name}</strong> · {meta.title}{periodWords ? ` · ${periodWords}` : ""} · printed {printedAt}
  </div>

  {#if loadError}
    <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{loadError} <button class="link-button" onclick={() => reload++}>Try again</button></div></div>
  {:else}
    <section class="card sheet-card" aria-labelledby="rep-title" aria-busy={loading}>
      <div class="sheet-head">
        <div class="sheet-title">
          <h2 class="card-title title-row" id="rep-title">{meta.title}{#if ABOUT[meta.name]}<InfoTip text={ABOUT[meta.name]} about={meta.title} />{/if}</h2>
          <span class="text-sm text-muted">{report && report.name === meta.name ? report.subtitle : meta.description}</span>
        </div>
        {#if report && report.name === meta.name && report.summary.length}
          <dl class="figures" aria-live="polite">
            {#each report.summary as s (s.label)}
              <div><dt>{s.label}{#if FIGURE[s.label]}<InfoTip text={FIGURE[s.label]} about={s.label} />{/if}</dt><dd class:money={s.kind === "money"}>{show(s.value, s.kind)}</dd></div>
            {/each}
          </dl>
        {/if}
      </div>
      {#if report && report.name === meta.name}
        {#if report.rows.length}
          {#key `${report.name}|${report.subtitle}|${report.rows.length}`}
            <Spreadsheet label={meta.title} columns={report.columns} rows={report.rows} totals={report.totals}
                         height="calc(100vh - 330px)" onopen={openRow} />
          {/key}
          <p class="sheet-hint no-print">Click a heading to sort · type in the row under the headings to filter · select cells and press Ctrl+C to copy into Excel{report.rows.some((r) => typeof r.id === "string") ? " · double-click a row to open the bill" : ""}.</p>
        {:else}
          <div class="empty"><Icon name="inbox" />Nothing for these filters.</div>
        {/if}
      {:else}
        <div class="empty" aria-busy="true">Loading…</div>
      {/if}
    </section>
  {/if}
{:else if catalogue.length}
  <div class="card"><div class="empty"><Icon name="lock" />This report isn't available to you.</div></div>
{/if}

<style src="./styles/Reports.css"></style>
