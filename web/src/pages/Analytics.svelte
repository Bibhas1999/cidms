<script lang="ts">
  import BarChart from "../components/charts/BarChart.svelte";
  import ChartCard from "../components/charts/ChartCard.svelte";
  import Heatmap from "../components/charts/Heatmap.svelte";
  import KpiCard from "../components/charts/KpiCard.svelte";
  import LineChart from "../components/charts/LineChart.svelte";
  import Sparkline from "../components/charts/Sparkline.svelte";
  import DateRange from "../components/DateRange.svelte";
  import Icon from "../components/Icon.svelte";
  import InfoTip from "../components/InfoTip.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import { get } from "../lib/api";
  import { exact, full, hourLabel, MODE_COLORS, MODE_LABELS, MODE_ORDER, num, short, type Series, type Unit } from "../lib/chart";
  import { rangeLabel, thisMonth } from "../lib/dates";
  import { count, date, rupees } from "../lib/format";
  import { router, setQuery } from "../lib/router.svelte";
  import { tooltip } from "../lib/tooltip";

  // Analytics for the owner and the centre admin (analytics.view): every figure for a period, narrowed by
  // department, referring doctor and who billed, plus a live view of today that refreshes itself.
  // Each section is its own request, so the page fills in as answers arrive.

  /* eslint-disable @typescript-eslint/no-explicit-any */
  type Data = Record<string, any>;

  // ---------- filters, kept in the address ----------
  const year = thisMonth(); // the default period: this month
  const q = $derived(router.query);
  const allPicked = $derived(q.get("from") === "all");
  const from = $derived(allPicked ? "" : q.get("from") ?? year.from);
  const to = $derived(allPicked ? "" : q.get("to") ?? (q.has("from") ? "" : year.to));
  const dept = $derived(q.get("department") ?? "");
  const doctor = $derived(q.get("doctor") ?? "");
  const by = $derived(q.get("by") ?? "");
  const label = $derived(rangeLabel(from, to));
  const filtered = $derived(!!(dept || doctor || by));
  const setRange = (f: string, t: string) =>
    setQuery(!f && !t ? { from: "all", to: null } : f === year.from && t === year.to ? { from: null, to: null } : { from: f, to: t });

  let options = $state<{ departments: { id: string; name: string }[]; doctors: { id: string; name: string }[]; billers: { id: string; name: string }[] }>(
    { departments: [], doctors: [], billers: [] });
  $effect(() => { get<typeof options>("/api/analytics/options").then((o) => (options = o)).catch(() => {}); });

  // ---------- the period's sections, loaded side by side ----------
  const SECTIONS = ["summary", "trend", "heatmap", "departments", "tests", "doctors", "patients", "dues", "staff", "pipeline"] as const;
  let data = $state<Data>({});
  let errors = $state<Record<string, string>>({});
  let loading = $state(false);

  $effect(() => {
    const params = { from: from || undefined, to: to || undefined, department_id: dept || undefined, doctor: doctor || undefined, created_by: by || undefined };
    const ctrl = new AbortController();
    loading = true;
    errors = {};
    let left = SECTIONS.length;
    for (const s of SECTIONS) {
      get<Data>(`/api/analytics/${s}`, params, ctrl.signal)
        .then((d) => (data[s] = d))
        .catch((e) => { if (e.name !== "AbortError") errors[s] = e.message; })
        .finally(() => { if (!ctrl.signal.aborted && --left === 0) loading = false; });
    }
    return () => ctrl.abort();
  });

  const s = $derived(data.summary);
  const unit = $derived<Unit>(data.trend?.unit ?? "day");
  const per = $derived(unit === "month" ? "By month" : unit === "week" ? "By week" : "By day");
  const span = $derived(s ? (s.date_from === s.date_to ? date(s.date_from) : `${date(s.date_from)} – ${date(s.date_to)}`) : "");
  const change = (now: unknown, before: unknown) => { const n = num(now as string), b = num(before as string); return b ? Math.round(((n - b) / b) * 100) : null; };
  const vs = $derived(s && !s.all_time ? `vs the ${s.days === 1 ? "day" : `${count(s.days)} days`} before` : "");

  // ---------- chart data ----------
  const points = $derived<Data[]>(data.trend?.points ?? []);
  const keys = $derived(points.map((p) => p.key as string));
  const col = (field: string) => points.map((p) => num(p[field]));
  const billedCollected = $derived<Series[]>([
    { key: "billed", label: "Billed", color: "var(--chart-1)", values: col("billed") },
    { key: "collected", label: "Collected", color: "var(--chart-2)", values: col("collected") },
  ]);
  const modesSeen = $derived(MODE_ORDER.filter((m) => points.some((p) => num(p.by_mode?.[m]) !== 0)));
  const byMode = $derived<Series[]>(modesSeen.map((m) => ({ key: m, label: MODE_LABELS[m], color: MODE_COLORS[m], values: points.map((p) => Math.max(0, num(p.by_mode?.[m]))) })));
  const trendEmpty = $derived(!points.some((p) => num(p.billed) || num(p.collected)));
  const timeTable = (cols: { label: string; field: string; fmt: "money" | "count" | "percent" }[]) => ({
    columns: [{ label: unit === "month" ? "Month" : unit === "week" ? "Week" : "Day" }, ...cols.map((c) => ({ label: c.label, num: true }))],
    rows: [...points].reverse().map((p) => [full(p.key, unit), ...cols.map((c) => exact(p[c.field] === null ? null : num(p[c.field]), c.fmt))]),
  });

  const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const heat = $derived.by(() => {
    const cells: Data[] = data.heatmap?.cells ?? [];
    const hours = cells.map((c) => c.hour as number);
    const lo = Math.min(8, ...hours), hi = Math.max(20, ...hours);
    const cols = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
    const values = WEEKDAYS.map((_, d) => cols.map((h) => cells.find((c) => c.weekday === d + 1 && c.hour === h)?.bills ?? 0));
    return { cols, values, empty: !cells.length };
  });

  const depts = $derived<Data[]>(data.departments?.rows ?? []);
  const topRevenue = $derived<Data[]>(data.tests?.by_revenue ?? []);
  const topCount = $derived<Data[]>(data.tests?.by_count ?? []);
  const doctors = $derived<Data[]>(data.doctors?.rows ?? []);
  const patientPoints = $derived<Data[]>(data.patients?.points ?? []);
  const ages = $derived<Data[]>(data.patients?.ages ?? []);
  const GENDERS = [{ key: "female", label: "Female", color: "var(--chart-1)" }, { key: "male", label: "Male", color: "var(--chart-2)" }, { key: "other", label: "Other", color: "var(--chart-3)" }];
  const gendersSeen = $derived(GENDERS.filter((g) => ages.some((a) => a[g.key] > 0)));
  const dues = $derived<Data[]>(data.dues?.rows ?? []);
  const staff = $derived<Data[]>(data.staff?.rows ?? []);
  const stages = $derived<Data[]>(data.pipeline?.stages ?? []);
  const STAGE: Record<string, string> = { billed: "Billed", scanned: "Scanned / sample taken", reported: "Reported", delivered: "Delivered" };
  const cancelEmpty = $derived(!points.some((p) => p.cancelled || num(p.refunds)));

  // ---------- live: today, refreshed every 20 seconds while the tab is visible ----------
  const LIVE_EVERY = 20_000;
  let live = $state<Data | null>(null);
  let liveError = $state("");
  let liveAt = $state<Date | null>(null);
  let paused = $state(typeof document !== "undefined" && document.hidden);
  let liveTimer: ReturnType<typeof setTimeout> | undefined;

  async function refreshLive() {
    clearTimeout(liveTimer);
    try {
      live = await get<Data>("/api/analytics/live");
      liveAt = new Date();
      liveError = "";
    } catch (e) {
      liveError = (e as Error).message;
    }
    if (!document.hidden) liveTimer = setTimeout(refreshLive, LIVE_EVERY);
  }

  $effect(() => {
    refreshLive();
    const onVisible = () => {
      paused = document.hidden;
      if (document.hidden) clearTimeout(liveTimer);
      else refreshLive();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearTimeout(liveTimer); document.removeEventListener("visibilitychange", onVisible); };
  });

  const clock = (d: Date) => new Intl.DateTimeFormat("en-IN", { timeStyle: "medium", timeZone: "Asia/Kolkata" }).format(d);
  const timeOf = (iso: string) => new Intl.DateTimeFormat("en-IN", { timeStyle: "short", timeZone: "Asia/Kolkata" }).format(new Date(iso));
  const liveHours = $derived.by(() => {
    const hours: Data[] = live?.hours ?? [];
    const busy = hours.filter((h) => h.today || h.average);
    const lo = Math.min(8, ...busy.map((h) => h.hour)), hi = Math.max(20, ...busy.map((h) => h.hour));
    return hours.filter((h) => h.hour >= lo && h.hour <= hi);
  });
  const nowHour = $derived(live ? Number(String(live.as_of).slice(11, 13)) : 24);
</script>

<PageHeader eyebrow="Business" title="Analytics"
            description="Turnover, collection, patients, doctors and staff · {label}{span && label !== span ? ` (${span})` : ''}. Only the owner and admins see this page." />

<!-- ---------- live ---------- -->
<section class="card live-card" aria-labelledby="live-title">
  <div class="card-header">
    <div>
      <div class="chart-title-row"><h2 class="card-title" id="live-title">Today, live</h2>
        <InfoTip about="Today, live" text="The whole centre today, whatever the filters below. It refreshes by itself every 20 seconds while this tab is open, and pauses when you switch away." /></div>
      <p class="card-description">{live ? `${live.weekday}, ${date(live.day)}` : "Loading…"}</p>
    </div>
    <div class="live-status" role="status" aria-live="polite">
      <span class="live-dot {paused || liveError ? 'is-paused' : 'is-on'}" aria-hidden="true"></span>
      {#if liveError}Couldn't refresh · retrying{:else if paused}Paused{:else}Live{/if}{#if liveAt} · updated {clock(liveAt)}{/if}
      <button class="btn btn-ghost btn-icon btn-sm" type="button" aria-label="Refresh now" use:tooltip={"Refresh now"} onclick={refreshLive}><Icon name="refresh" size="sm" /></button>
    </div>
  </div>
  <div class="card-content stack">
    <div class="live-kpis">
      <div class="kpi"><span class="kpi-label">Bills<InfoTip about="Bills today" text="Bills made today, cancelled ones left out, and how many different patients they were for." /></span><span class="kpi-value">{live ? count(live.bills) : "—"}</span><span class="kpi-note">{live ? `${count(live.patients)} patients` : ""}</span></div>
      <div class="kpi"><span class="kpi-label">Billed<InfoTip about="Billed today" text="What today's bills came to after discounts, and how much of that is still owed." /></span><span class="kpi-value">{live ? rupees(live.billed, { paise: false }) : "—"}</span><span class="kpi-note">{live ? `${rupees(live.due_on_bills, { paise: false })} still due` : ""}</span></div>
      <div class="kpi"><span class="kpi-label">Collected<InfoTip about="Collected today" text="Money received today, refunds taken off. Includes dues paid today against older bills." /></span>
        <span class="kpi-value">{live ? rupees(live.collected, { paise: false }) : "—"}</span>
        <span class="kpi-note">{#if live}{#each Object.entries(live.collected_by_mode) as [m, v] (m)}<span>{MODE_LABELS[m] ?? m} {short(num(v as string), "money")}</span>{/each}{/if}</span></div>
      <div class="kpi"><span class="kpi-label">Older dues collected<InfoTip about="Older dues collected" text="Paid today against bills made before today. It's part of Collected." /></span><span class="kpi-value">{live ? rupees(live.dues_collected, { paise: false }) : "—"}</span></div>
      <div class="kpi"><span class="kpi-label">Tests waiting<InfoTip about="Tests waiting" text="Tests on today's bills still to be scanned or sampled, or waiting for the report." /></span><span class="kpi-value">{live ? count(live.waiting.billed + live.waiting.scanned) : "—"}</span>
        <span class="kpi-note">{live ? `${count(live.waiting.billed)} to scan · ${count(live.waiting.scanned)} to report` : ""}</span></div>
    </div>
    <div class="live-grid">
      <div class="stack-sm" style="min-width: 0">
        <div class="chart-toolbar live-head">
          <div class="chart-title-row"><h3 class="text-sm font-semibold" style="margin: 0">Bills by hour</h3>
            <InfoTip about="Bills by hour" text={`Bills made in each hour today, against the average for a ${live?.weekday ?? "day like today"} over the last eight weeks (counting only days the centre billed${live ? `: ${live.compared_days}` : ""}).`} /></div>
          <div class="chart-legend" aria-hidden="true">
            <span><span class="swatch" style="background: var(--chart-1)"></span>Today</span>
            <span><span class="swatch is-dashed" style="color: var(--chart-2)"></span>Average {live?.weekday ?? ""}</span>
          </div>
        </div>
        {#if live}
          <LineChart keys={liveHours.map((h) => String(h.hour))} unit="hour" fmt="count" height={200} min={4} dashed={["average"]}
                     label="Bills by hour today against the average for the same weekday"
                     series={[{ key: "today", label: "Today", color: "var(--chart-1)", values: liveHours.map((h) => (h.hour <= nowHour ? h.today : null)) },
                              { key: "average", label: "Average", color: "var(--chart-2)", values: liveHours.map((h) => h.average) }]} />
        {:else}<div class="chart-skeleton"></div>{/if}
      </div>
      <div class="stack-sm" style="min-width: 0">
        <div class="chart-toolbar live-head"><div class="chart-title-row"><h3 class="text-sm font-semibold" style="margin: 0">Latest bills</h3><InfoTip about="Latest bills" text="The twelve most recent bills, any date, newest first. Open one to see it." /></div></div>
        <ul class="feed" aria-label="Latest bills">
          {#each live?.recent ?? [] as b (b.id)}
            <li>
              <a href="/bills/{b.id}" class="feed-main">
                <span class="cell-title">{b.patient_name}</span>
                <span class="cell-sub"><span class="mono">{b.invoice_no}</span> · {timeOf(b.created_at)} · {b.created_by_name || "—"}</span>
              </a>
              <span class="feed-money"><strong class="money">{rupees(b.total, { paise: false })}</strong>
                {#if b.status === "cancelled"}<span class="badge badge-plain">Cancelled</span>{:else if num(b.due) > 0}<span class="text-sm money-due">{rupees(b.due, { paise: false })} due</span>{:else}<span class="text-sm text-muted">Paid</span>{/if}</span>
            </li>
          {:else}
            <li class="empty" style="padding: 20px"><Icon name="receipt" />{live ? "No bills yet." : "Loading…"}</li>
          {/each}
        </ul>
      </div>
    </div>
  </div>
</section>

<!-- ---------- the period at a glance ---------- -->
<!-- ---------- the period: its title and filters in one bar (they don't change "Today, live" above) ---------- -->
<section class="card period-bar" aria-labelledby="period-title">
  <div class="period-head">
    <h2 class="period-title" id="period-title">{label}</h2>
    <p class="period-sub">{span && label !== span ? span : allPicked ? "Since the first bill" : ""}{#if filtered} · filtered{/if}</p>
  </div>
  <div class="period-filters" role="group" aria-label="Filters for the figures below">
    <DateRange id="an" {from} {to} anyLabel="All time" compact onchange={setRange} />
    <label class="sr-only" for="an-dept">Department</label>
    <select id="an-dept" class="select" value={dept} onchange={(e) => setQuery({ department: e.currentTarget.value || null })}>
      <option value="">All departments</option>
      {#each options.departments as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
    </select>
    <label class="sr-only" for="an-doc">Referring doctor</label>
    <select id="an-doc" class="select" value={doctor} onchange={(e) => setQuery({ doctor: e.currentTarget.value || null })}>
      <option value="">All referrers</option>
      <option value="self">Self-referred</option>
      {#each options.doctors as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
    </select>
    <label class="sr-only" for="an-by">Billed by</label>
    <select id="an-by" class="select" value={by} onchange={(e) => setQuery({ by: e.currentTarget.value || null })}>
      <option value="">Billed by anyone</option>
      {#each options.billers as b (b.id)}<option value={b.id}>{b.name}</option>{/each}
    </select>
    {#if filtered}<button class="btn btn-ghost" type="button" onclick={() => setQuery({ department: null, doctor: null, by: null })}><Icon name="x" size="sm" /> Clear</button>{/if}
  </div>
</section>
<div class="kpi-grid" aria-busy={loading}>
  <KpiCard label="Billed" tip="What the period's bills came to after discounts, by bill date. Cancelled bills are left out." loading={!s}
           value={s ? rupees(s.billed, { paise: false }) : ""} note={s ? `${count(s.bills)} bills · ${count(s.tests)} tests` : ""}
           delta={s && !s.all_time ? change(s.billed, s.previous.billed) : null} deltaWords={vs} />
  <KpiCard label="Collected" tip="Money received in the period, refunds taken off. Includes dues paid against older bills, so it can be more than what was billed." loading={!s}
           value={s ? rupees(s.collected, { paise: false }) : ""} delta={s && !s.all_time ? change(s.collected, s.previous.collected) : null}>
    {#if s}{#each Object.entries(s.collected_by_mode) as [m, v] (m)}<span>{MODE_LABELS[m] ?? m} {short(num(v as string), "money")}</span>{/each}{/if}
  </KpiCard>
  <KpiCard label="Average bill" tip="Billed divided by the number of bills." loading={!s} value={s ? rupees(s.average_bill, { paise: false }) : ""}
           note={s ? `${count(s.patients)} patients` : ""} />
  <KpiCard label="Collection efficiency" tip="Of what the period's bills came to, the share already paid on them. 100% means nothing is owed on these bills." loading={!s}
           value={s ? (s.efficiency_pct === null ? "—" : `${s.efficiency_pct}%`) : ""} note={s ? `${rupees(s.due_on_bills, { paise: false })} still due on them` : ""} />
  <KpiCard label="Discounts" tip="Discounts given on the period's bills, and as a share of what they came to before discount." loading={!s}
           value={s ? rupees(s.discounts, { paise: false }) : ""} note={s && s.discount_pct !== null ? `${s.discount_pct}% of the bills before discount` : ""} />
  <KpiCard label="Dues outstanding" tip="Everything still owed today, on bills of any date (the department, doctor and billed-by filters apply)." loading={!s} href="/dues"
           value={s ? rupees(s.outstanding_dues, { paise: false }) : ""} note={s ? `${count(s.dues_count)} bills` : ""} />
  <KpiCard label="Older dues collected" tip="Paid in the period against bills dated before it." loading={!s}
           value={s ? rupees(s.dues_collected, { paise: false }) : ""} />
  <KpiCard label="Cancellations & refunds" tip="Bills cancelled in the period (their value before discount), and money given back." loading={!s}
           value={s ? `${count(s.cancelled)} · ${rupees(s.refunds, { paise: false })}` : ""} note={s ? `${rupees(s.cancelled_amount, { paise: false })} cancelled · refunds` : ""} />
</div>

<!-- ---------- money over time ---------- -->
<div class="grid-3">
  <ChartCard class="span-2" title="Billed and collected" description="{per} · {label}"
             tip="Billed is by bill date; collected is by the date the money came in, so it includes dues paid against older bills."
             loading={!data.trend} error={errors.trend} empty={trendEmpty} emptyText="No bills or payments for these filters."
             table={timeTable([{ label: "Billed", field: "billed", fmt: "money" }, { label: "Collected", field: "collected", fmt: "money" }])}>
    {#snippet legend()}<span><span class="swatch" style="background: var(--chart-1)"></span>Billed</span><span><span class="swatch" style="background: var(--chart-2)"></span>Collected</span>{/snippet}
    <LineChart {keys} {unit} series={billedCollected} label="Billed and collected, {per.toLowerCase()}" />
  </ChartCard>
  <ChartCard title="Collection by mode" description="{per} · refunds taken off" tip="Money received each period, split by how it was paid."
             loading={!data.trend} error={errors.trend} empty={!byMode.length} emptyText="No payments for these filters."
             table={{ columns: [{ label: "Period" }, ...byMode.map((m) => ({ label: m.label, num: true }))], rows: [...keys].reverse().map((k) => { const i = keys.indexOf(k); return [full(k, unit), ...byMode.map((m) => exact(m.values[i], "money"))]; }) }}>
    {#snippet legend()}{#each byMode as m (m.key)}<span><span class="swatch is-block" style="background: {m.color}"></span>{m.label}</span>{/each}{/snippet}
    <BarChart {keys} {unit} series={byMode} mode="stacked" label="Collection by payment mode, {per.toLowerCase()}" />
  </ChartCard>
</div>

<div class="grid-2">
  <ChartCard title="Bills" description="{per} · number of bills" loading={!data.trend} error={errors.trend} empty={!points.some((p) => p.bills)}
             tip="How many bills were made (cancelled ones left out)." table={timeTable([{ label: "Bills", field: "bills", fmt: "count" }])}>
    <BarChart {keys} {unit} fmt="count" series={[{ key: "bills", label: "Bills", color: "var(--chart-1)", values: col("bills") }]} label="Bills, {per.toLowerCase()}" />
  </ChartCard>
  <ChartCard title="Average bill value" description="{per} · billed ÷ bills" loading={!data.trend} error={errors.trend} empty={!points.some((p) => p.bills)}
             tip="What a bill came to on average, after discounts." table={timeTable([{ label: "Average bill", field: "average_bill", fmt: "money" }])}>
    <LineChart {keys} {unit} endLabels={false} series={[{ key: "avg", label: "Average bill", color: "var(--chart-1)", values: points.map((p) => (p.bills ? num(p.average_bill) : null)) }]} label="Average bill value, {per.toLowerCase()}" />
  </ChartCard>
</div>

<div class="grid-3">
  <ChartCard title="Collection efficiency" description="{per} · share of each period's bills already paid" loading={!data.trend} error={errors.trend}
             empty={!points.some((p) => p.efficiency_pct !== null)}
             tip="For the bills made in each period: paid so far ÷ what they came to. Older periods climb as dues are paid."
             table={timeTable([{ label: "Paid of billed", field: "efficiency_pct", fmt: "percent" }])}>
    <LineChart {keys} {unit} fmt="percent" endLabels={false} series={[{ key: "eff", label: "Paid of billed", color: "var(--chart-1)", values: points.map((p) => p.efficiency_pct) }]} label="Collection efficiency, {per.toLowerCase()}" />
  </ChartCard>
  <ChartCard title="Discounts given" description="{per} · amount" loading={!data.trend} error={errors.trend}
             empty={!points.some((p) => num(p.discounts))} emptyText="No discounts for these filters."
             tip="Discounts given on the bills made in each period, in rupees."
             table={timeTable([{ label: "Discounts", field: "discounts", fmt: "money" }, { label: "Share of bills", field: "discount_pct", fmt: "percent" }])}>
    <BarChart {keys} {unit} series={[{ key: "disc", label: "Discounts", color: "var(--chart-2)", values: col("discounts") }]} label="Discounts given, {per.toLowerCase()}" />
  </ChartCard>
  <ChartCard title="Discount share" description="{per} · discount ÷ bills before discount" loading={!data.trend} error={errors.trend}
             empty={!points.some((p) => num(p.discounts))} emptyText="No discounts for these filters."
             tip="How much of what the bills came to before discount was given away: discount ÷ (bill total before discount)."
             table={timeTable([{ label: "Share of bills", field: "discount_pct", fmt: "percent" }])}>
    <LineChart {keys} {unit} fmt="percent" endLabels={false} series={[{ key: "pct", label: "Share of bills", color: "var(--chart-1)", values: points.map((p) => p.discount_pct) }]} label="Discount as a share of bills, {per.toLowerCase()}" />
  </ChartCard>
</div>

<!-- ---------- when, what and who ---------- -->
<div class="grid-3">
  <ChartCard class="span-2" title="Busiest days and hours" description="Bills by weekday and hour of the day · {label}" loading={!data.heatmap} error={errors.heatmap}
             empty={heat.empty} tip="Darker cells had more bills. Hours are the centre's clock (India time)."
             table={{ columns: [{ label: "Day" }, ...heat.cols.map((h) => ({ label: hourLabel(h), num: true }))], rows: WEEKDAYS.map((d, i) => [d, ...heat.values[i]]) }}>
    <Heatmap rows={WEEKDAYS} cols={heat.cols.map((h) => hourLabel(h))} values={heat.values} unitWord="bills" label="Bills by weekday and hour" />
  </ChartCard>
  <ChartCard title="Department revenue" description="Tests billed, before bill discounts" loading={!data.departments} error={errors.departments} empty={!depts.length}
             tip="What each department's tests came to on the period's bills, before any discount on the bill."
             table={{ columns: [{ label: "Department" }, { label: "Revenue", num: true }, { label: "Tests", num: true }, { label: "Bills", num: true }], rows: depts.map((d) => [d.name, exact(num(d.amount), "money"), count(d.tests), count(d.bills)]) }}>
    <BarChart horizontal keys={depts.map((d) => d.name)} series={[{ key: "amt", label: "Revenue", color: "var(--chart-1)", values: depts.map((d) => num(d.amount)) }]} label="Revenue by department" />
  </ChartCard>
</div>

<div class="grid-2">
  <ChartCard title="Top tests by revenue" description="The ten that brought in the most" loading={!data.tests} error={errors.tests} empty={!topRevenue.length}
             tip="What each test brought in on the period's bills, before any discount on the bill."
             table={{ columns: [{ label: "Test" }, { label: "Department" }, { label: "Revenue", num: true }, { label: "Times", num: true }], rows: topRevenue.map((t) => [t.name, t.department, exact(num(t.amount), "money"), count(t.count)]) }}>
    <BarChart horizontal keys={topRevenue.map((t, i) => `${i}`)} names={topRevenue.map((t) => t.name)} series={[{ key: "amt", label: "Revenue", color: "var(--chart-1)", values: topRevenue.map((t) => num(t.amount)) }]} label="Top tests by revenue" />
  </ChartCard>
  <ChartCard title="Top tests by count" description="The ten done most often" loading={!data.tests} error={errors.tests} empty={!topCount.length}
             tip="How many times each test was billed in the period (quantity counted), with what it brought in before bill discounts."
             table={{ columns: [{ label: "Test" }, { label: "Department" }, { label: "Times", num: true }, { label: "Revenue", num: true }], rows: topCount.map((t) => [t.name, t.department, count(t.count), exact(num(t.amount), "money")]) }}>
    <BarChart horizontal fmt="count" keys={topCount.map((t, i) => `${i}`)} names={topCount.map((t) => t.name)} series={[{ key: "n", label: "Times billed", color: "var(--chart-2)", values: topCount.map((t) => t.count) }]} label="Top tests by count" />
  </ChartCard>
</div>

<div class="grid-2">
  <ChartCard title="Top referring doctors" description={data.doctors ? `${count(data.doctors.referred.bills)} referred bills from ${count(data.doctors.referred.doctors)} doctors · ${count(data.doctors.self_referred.bills)} self-referred` : ""}
             loading={!data.doctors} error={errors.doctors} empty={!doctors.length} emptyIcon="stethoscope" emptyText="No referred bills for these filters."
             tip="By bills referred. The line shows each doctor's bills {per.toLowerCase()} over the period."
             table={{ columns: [{ label: "Doctor" }, { label: "Bills", num: true }, { label: "Revenue", num: true }], rows: doctors.map((d) => [d.name, count(d.bills), exact(num(d.amount), "money")]) }}>
    <ul class="doc-list">
      {#each doctors as d (d.id)}
        <li>
          <span class="doc-name">{d.name}</span>
          <Sparkline values={d.trend} label="{d.name}: bills {per.toLowerCase()}, from {d.trend[0]} to {d.trend[d.trend.length - 1]}" />
          <span class="doc-fig"><strong class="tabular">{count(d.bills)}</strong> <span class="text-muted">bills</span></span>
          <span class="doc-fig money">{short(num(d.amount), "money")}</span>
        </li>
      {/each}
    </ul>
  </ChartCard>
  <ChartCard title="Staff performance" description="Bills made and money taken, by person" loading={!data.staff} error={errors.staff} empty={!staff.length}
             tip="Billed: the bills each person made (after discounts). Collected: money each person received in the period, refunds taken off."
             table={{ columns: [{ label: "Person" }, { label: "Bills", num: true }, { label: "Billed", num: true }, { label: "Average", num: true }, { label: "Discounts", num: true }, { label: "Collected", num: true }],
                      rows: staff.map((p) => [p.name, count(p.bills), exact(num(p.billed), "money"), exact(num(p.average_bill), "money"), exact(num(p.discounts), "money"), exact(num(p.collected), "money")]) }}>
    {#snippet legend()}<span><span class="swatch is-block" style="background: var(--chart-1)"></span>Billed</span><span><span class="swatch is-block" style="background: var(--chart-2)"></span>Collected</span>{/snippet}
    <BarChart horizontal keys={staff.map((p, i) => `${i}`)} names={staff.map((p) => `${p.name} · ${count(p.bills)} ${p.bills === 1 ? "bill" : "bills"}`)}
              series={[{ key: "billed", label: "Billed", color: "var(--chart-1)", values: staff.map((p) => num(p.billed)) },
                       { key: "collected", label: "Collected", color: "var(--chart-2)", values: staff.map((p) => num(p.collected)) }]} label="Billed and collected by person" />
  </ChartCard>
</div>

<!-- ---------- patients ---------- -->
<div class="grid-2">
  <ChartCard title="New and returning patients" description={data.patients ? `${per} · over the whole period ${count(data.patients.new)} new, ${count(data.patients.returning)} who'd been before` : per} loading={!data.patients} error={errors.patients}
             empty={!patientPoints.some((p) => p.new || p.returning)}
             tip="Each bar counts patients billed in that week or month. New: their first bill ever is in it. Returning: they'd been billed in an earlier week or month. The totals above use the whole period instead."
             table={{ columns: [{ label: "Period" }, { label: "New", num: true }, { label: "Returning", num: true }], rows: [...patientPoints].reverse().map((p) => [full(p.key, unit), count(p.new), count(p.returning)]) }}>
    {#snippet legend()}<span><span class="swatch is-block" style="background: var(--chart-1)"></span>New</span><span><span class="swatch is-block" style="background: var(--chart-2)"></span>Returning</span>{/snippet}
    <BarChart keys={patientPoints.map((p) => p.key)} {unit} fmt="count" mode="stacked" label="New and returning patients, {per.toLowerCase()}"
              series={[{ key: "new", label: "New", color: "var(--chart-1)", values: patientPoints.map((p) => p.new) },
                       { key: "returning", label: "Returning", color: "var(--chart-2)", values: patientPoints.map((p) => p.returning) }]} />
  </ChartCard>
  <ChartCard title="Patients by age and gender" description="Visits in the period, age as written on the bill" loading={!data.patients} error={errors.patients}
             empty={!ages.some((a) => a.female || a.male || a.other)} tip="Each bill counts once. Babies under a year are in 0–12."
             table={{ columns: [{ label: "Age" }, ...GENDERS.map((g) => ({ label: g.label, num: true }))], rows: ages.map((a) => [a.band, ...GENDERS.map((g) => count(a[g.key]))]) }}>
    {#snippet legend()}{#each gendersSeen as g (g.key)}<span><span class="swatch is-block" style="background: {g.color}"></span>{g.label}</span>{/each}{/snippet}
    <BarChart horizontal fmt="count" mode="stacked" keys={ages.map((a) => a.band)} label="Visits by age band and gender"
              series={gendersSeen.map((g) => ({ ...g, values: ages.map((a) => a[g.key]) }))} />
  </ChartCard>
</div>

<!-- ---------- dues, cancellations and the lab ---------- -->
<div class="grid-3">
  <ChartCard title="Dues by age" description={data.dues ? `${rupees(data.dues.total, { paise: false })} owed on ${count(data.dues.bills)} bills, today` : ""}
             loading={!data.dues} error={errors.dues} empty={!dues.some((d) => d.bills)} emptyIcon="check" emptyText="Nothing is owed."
             tip="Everything still owed today, by how long ago the bill was made. Dates don't narrow this; the other filters do."
             table={{ columns: [{ label: "Owed for" }, { label: "Bills", num: true }, { label: "Amount", num: true }], rows: dues.map((d) => [d.bucket, count(d.bills), exact(num(d.amount), "money")]) }}>
    <BarChart horizontal keys={dues.map((d) => d.bucket)} series={[{ key: "amt", label: "Owed", color: "var(--chart-2)", values: dues.map((d) => num(d.amount)) }]} label="Dues by how long they have been owed" />
  </ChartCard>
  <ChartCard title="Cancellations and refunds" description="{per} · value of cancelled bills, and money given back" loading={!data.trend} error={errors.trend}
             empty={cancelEmpty} emptyIcon="check" emptyText="No cancellations or refunds for these filters."
             tip="Cancelled: bills cancelled in each period, at their value before discount. Refunds: money given back, by date."
             table={timeTable([{ label: "Cancelled bills", field: "cancelled", fmt: "count" }, { label: "Cancelled value", field: "cancelled_amount", fmt: "money" }, { label: "Refunds", field: "refunds", fmt: "money" }])}>
    {#snippet legend()}<span><span class="swatch is-block" style="background: var(--chart-1)"></span>Cancelled value</span><span><span class="swatch is-block" style="background: var(--chart-2)"></span>Refunds</span>{/snippet}
    <BarChart {keys} {unit} label="Cancellations and refunds, {per.toLowerCase()}"
              series={[{ key: "c", label: "Cancelled value", color: "var(--chart-1)", values: col("cancelled_amount") }, { key: "r", label: "Refunds", color: "var(--chart-2)", values: col("refunds") }]} />
  </ChartCard>
  <ChartCard title="Test pipeline" description={data.pipeline ? `${count(data.pipeline.total)} tests on the period's bills` : ""} loading={!data.pipeline} error={errors.pipeline}
             empty={!data.pipeline?.total} emptyIcon="clipboard"
             tip="How many of the period's tests have reached each stage, and the average time from billing to the stage they're at now."
             table={{ columns: [{ label: "Stage" }, { label: "Reached", num: true }, { label: "There now", num: true }, { label: "Average time", num: true }], rows: stages.map((st) => [STAGE[st.stage], count(st.reached), count(st.now), st.avg_hours === null ? "—" : exact(st.avg_hours, "hours")]) }}>
    <BarChart horizontal fmt="count" keys={stages.map((st) => st.stage)} names={stages.map((st) => `${STAGE[st.stage]}${st.avg_hours !== null ? ` · avg ${exact(st.avg_hours, "hours")}` : ""}`)}
              series={[{ key: "reached", label: "Reached", color: "var(--chart-1)", values: stages.map((st) => st.reached) }]} label="Tests reaching each stage" />
  </ChartCard>
</div>

<style>
  /* The period bar: title on the left, the filters on the right in one row; stays in view while scrolling. */
  .period-bar { position: sticky; top: calc(var(--topbar-height, 56px) + 8px); z-index: 5; display: flex; align-items: center;
    justify-content: space-between; gap: 12px 20px; flex-wrap: wrap; padding: 12px 16px; margin-top: 4px; }
  .period-head { min-width: 0; }
  .period-title { margin: 0; font-size: 16px; font-weight: 650; letter-spacing: -0.01em; line-height: 1.3; }
  .period-sub { margin: 2px 0 0; font-size: 12.5px; color: var(--muted-foreground); }
  .period-sub:empty { display: none; }
  .period-filters { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; margin-left: auto; }
  .period-filters > .select { width: 180px; min-width: 0; flex: none; }
  .period-filters :global(.date-filter) { gap: 10px; flex-wrap: nowrap; }
  .period-filters :global(.date-filter > .select) { width: 180px; min-width: 0; }
  .period-filters :global(.date-range) { flex-wrap: nowrap; }
  .period-filters :global(.date-field .input) { width: 150px; }
  .live-status { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted-foreground); white-space: nowrap; }
  .live-kpis { display: grid; gap: 16px; grid-template-columns: repeat(5, minmax(0, 1fr)); }
  .live-grid { display: grid; gap: 24px; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); align-items: start; }
  .live-head { min-height: 28px; }
  .feed { list-style: none; margin: 0; padding: 0; max-height: 260px; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius-sm); }
  .feed li { display: flex; justify-content: space-between; gap: 12px; padding: 8px 12px; border-bottom: 1px solid var(--border); }
  .feed li:last-child { border-bottom: 0; }
  .feed-main { display: flex; flex-direction: column; min-width: 0; color: inherit; text-decoration: none; }
  .feed-main:hover .cell-title { text-decoration: underline; }
  .feed-main .cell-title, .feed-main .cell-sub { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .feed-money { display: flex; flex-direction: column; align-items: flex-end; flex: none; }
  .doc-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  .doc-list li { display: grid; grid-template-columns: minmax(0, 1fr) 96px 80px 64px; gap: 12px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13.5px; }
  .doc-list li:last-child { border-bottom: 0; }
  .doc-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .doc-fig { text-align: right; white-space: nowrap; }
  @media (max-width: 1100px) { .live-kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
  @media (max-width: 900px) { .live-grid { grid-template-columns: 1fr; } }
  @media (max-width: 760px) {
    .period-bar { position: static; }
    .period-filters { display: grid; grid-template-columns: 1fr 1fr; width: 100%; margin-left: 0; }
    .period-filters > .select, .period-filters :global(.date-filter > .select) { width: 100%; }
    .period-filters :global(.date-filter) { grid-column: 1 / -1; flex-wrap: wrap; }
    .period-filters :global(.date-filter > .select), .period-filters :global(.date-range) { flex: 1 1 100%; }
    .period-filters :global(.date-field) { flex: 1 1 0; }
    .period-filters :global(.date-field .input) { width: 100%; }
    .period-filters > .select:last-of-type:nth-of-type(odd) { grid-column: 1 / -1; }
    .live-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .card-header:has(.live-status) { flex-wrap: wrap; }
    .doc-list li { grid-template-columns: minmax(0, 1fr) 64px 56px; }
    .doc-list li :global(svg) { display: none; }
  }
</style>
