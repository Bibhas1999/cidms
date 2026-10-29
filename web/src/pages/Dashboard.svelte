<script lang="ts">
  import DateRange from "../components/DateRange.svelte";
  import DigitalClock from "../components/DigitalClock.svelte";
  import KpiCard from "../components/charts/KpiCard.svelte";
  import Icon from "../components/Icon.svelte";
  import InfoTip from "../components/InfoTip.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import PlatformHome from "./platform/PlatformHome.svelte";
  import TrendChart from "../components/TrendChart.svelte";
  import { untrack } from "svelte";
  import { get } from "../lib/api";
  import { confirmDialog } from "../lib/confirm.svelte";
  import { BILL_STATUS, paymentState, type BillPage } from "../lib/bill-types";
  import { rangeLabel, thisMonth } from "../lib/dates";
  import { count, date, dateTime, rupees, rupeesShort } from "../lib/format";
  import { navigate, router, setQuery } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { tooltip } from "../lib/tooltip";
  import type { DeskSummary, Overview } from "../lib/types";

  const first = (session.me?.full_name ?? "").split(" ")[0];
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  // Everyone sees the totals (bills, total amount, collected, dues). Only the owner and the centre admin
  // (analytics.view) get the analytics: the trend, departments, doctors and the comparison with the period before.
  // Read once: who you are doesn't change while the page is open, and the loads below must not re-run when the
  // session object is refreshed by a reply (that made them repeat without end).
  const platform = session.isPlatform;
  const business = !platform && session.can("analytics.view");

  // ---------- one period for the whole page, kept in the address (?from=&to=) ----------
  // Nothing in the address = this month (the 1st to today); ?from=all = all time.
  const period = thisMonth();
  const allPicked = $derived(router.query.get("from") === "all");
  const from = $derived(allPicked ? "" : router.query.get("from") ?? period.from);
  const to = $derived(allPicked ? "" : router.query.get("to") ?? (router.query.has("from") ? "" : period.to));
  const allTime = $derived(!from && !to);
  const label = $derived(rangeLabel(from, to));
  const words = $derived(allTime ? "all time" : /^[A-Z][a-z]/.test(label) && !/^\d/.test(label) ? label.toLowerCase() : label);
  const oneDay = $derived(!!from && from === to);
  const setRange = (f: string, t: string) =>
    setQuery(!f && !t ? { from: "all", to: null } : f === period.from && t === period.to ? { from: null, to: null } : { from: f, to: t });
  // Links to the lists keep this period (lists open on this month by default, so "all time" is said explicitly).
  const bq = $derived(allTime ? "&from=all" : `${from ? `&from=${from}` : ""}${to ? `&to=${to}` : ""}`);

  let data = $state<Overview | null>(null);
  let loading = $state(false);
  let failed = $state("");
  $effect(() => {
    if (!business) return;
    const ctrl = new AbortController();
    const q = { from: from || undefined, to: to || undefined };
    untrack(() => {
      loading = true;
      failed = "";
      get<Overview>("/api/summary/overview", q, ctrl.signal)
        .then((d) => (data = d))
        .catch((e) => { if (e.name !== "AbortError") failed = e.message; })
        .finally(() => { if (!ctrl.signal.aborted) loading = false; });
    });
    return () => ctrl.abort();
  });

  // ---------- everyone else: collected and dues for the period ----------
  let desk = $state<DeskSummary | null>(null);
  $effect(() => {
    if (business || platform) return;
    const ctrl = new AbortController();
    const q = { from: from || undefined, to: to || undefined };
    untrack(() => {
      loading = true;
      failed = "";
      get<DeskSummary>("/api/summary/desk", q, ctrl.signal)
        .then((d) => (desk = d))
        .catch((e) => { if (e.name !== "AbortError") failed = e.message; })
        .finally(() => { if (!ctrl.signal.aborted) loading = false; });
    });
    return () => ctrl.abort();
  });

  // ---------- the bills card, first on the page: the period's bills, with search and payment ----------
  let payment = $state<"" | "due" | "paid" | "part" | "unpaid">("");
  let search = $state("");
  let searchText = $state("");
  let bills = $state<BillPage | null>(null);
  let billsLoading = $state(false);

  $effect(() => {
    if (platform) return;
    const ctrl = new AbortController();
    const q = { from: from || undefined, to: to || undefined, search, size: 10, payment: payment || undefined };
    untrack(() => {
      billsLoading = true;
      get<BillPage>("/api/bills", q, ctrl.signal)
        .then((d) => (bills = d)).catch(() => {}).finally(() => { if (!ctrl.signal.aborted) billsLoading = false; });
    });
    return () => ctrl.abort();
  });

  // Searching while the payment filter is on: ask once per search, as in the Sandhata Registry. (The period at the
  // top is the page's, not a filter of this table, so it's left alone.)
  let timer: ReturnType<typeof setTimeout>;
  let asked = false;
  const onSearch = () => {
    clearTimeout(timer);
    if (!searchText.trim()) asked = false;
    timer = setTimeout(async () => {
      const value = searchText.trim();
      const names = payment ? ["Payment"] : []; // the period at the top isn't a table filter
      if (value && !asked && names.length) {
        asked = true;
        const clear = await confirmDialog({
          title: "Filters are applied",
          message: `You have ${names.length === 1 ? "a filter" : `${names.length} filters`} applied (${names.join(", ")}). Search all bills, or only the ones that match these filters?`,
          confirmLabel: "Clear filters and search all", cancelLabel: "Search within filters",
        });
        if (clear) payment = "";
      }
      search = value;
    }, 300);
  };
  const allHref = $derived(`/bills?${bq.slice(1)}${payment ? `&payment=${payment}` : ""}${search ? `&search=${encodeURIComponent(search)}` : ""}`);
  const timeOf = (iso: string) => new Intl.DateTimeFormat("en-IN", { timeStyle: "short", timeZone: "Asia/Kolkata" }).format(new Date(iso));

  const MODES: Record<string, string> = { cash: "Cash", upi: "UPI", card: "Card", bank: "Bank", other: "Other" };
  const change = (now: string | number, before: string | number) => {
    const n = Number(now), b = Number(before);
    return b ? Math.round(((n - b) / b) * 100) : null;
  };
  const billedDelta = $derived(data && !data.all_time ? change(data.period.billed, data.previous.billed) : null);
  const collectedDelta = $derived(data && !data.all_time ? change(data.period.collected_total, data.previous.collected_total) : null);
  const vs = $derived(data ? (data.days === 1 ? "vs the day before" : `vs prev. ${count(data.days)} days`) : "");
  const trendWords = $derived(data && data.trend.length
    ? `${date(data.trend[0].day)} to ${date(data.trend[data.trend.length - 1].day)}` : "this period");
  const deptMax = $derived(Math.max(1, ...(data?.departments ?? []).map((d) => Number(d.amount))));
  const docMax = $derived(Math.max(1, ...(data?.doctors ?? []).map((d) => d.bills)));
  // The header names the dates themselves: "1 Oct 2026 – 11 Oct 2026" (all time: from the first bill, once known).
  const dates = $derived(from && to ? (from === to ? date(from) : `${date(from)} – ${date(to)}`)
    : data ? `${date(data.date_from)} – ${date(data.date_to)}` : "All time");
  const span = $derived(data ? (data.date_from === data.date_to ? date(data.date_from) : `${date(data.date_from)} – ${date(data.date_to)}`) : "");
</script>

<PageHeader eyebrow="Overview" title="{greeting}, {first}"
            description={session.isPlatform ? "Cloud Integrated Diagnostic Management System · platform administration" : `${session.workspace?.name ?? ""} · ${dates}`}>
  {#snippet actions()}
    <DigitalClock />
    {#if !session.isPlatform}<DateRange id="dash" {from} {to} anyLabel="All time" compact onchange={setRange} />{/if}
    {#if business}<a class="btn btn-outline" href="/analytics?{bq.slice(1) || 'from=all'}"><Icon name="barChart" /> Open analytics</a>{/if}
  {/snippet}
</PageHeader>

{#if session.isPlatform}
  <PlatformHome />
{:else}
  {#if failed}
    <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div><div class="alert-title">Couldn't load the figures</div>{failed}</div></div>
  {/if}

  {#if business}
    <div class="grid-4 kpis" aria-busy={loading}>
      <KpiCard icon="receipt" href="/bills?{bq.slice(1)}" label="Total bills" loading={!data}
               tip="Bills made in this period, by bill date, not counting cancelled ones."
               value={data ? count(data.period.bills) : ""} note={data ? `${count(data.period.patients)} patients` : ""} />
      <KpiCard icon="rupee" href="/bills?{bq.slice(1)}" label="Total billed amount" loading={!data}
               tip="What this period's bills came to after discounts. Cancelled bills are left out. The arrow compares the same number of days just before."
               value={data ? rupees(data.period.billed, { paise: false }) : ""}
               note={data && Number(data.period.discounts) ? `${rupeesShort(data.period.discounts)} discount` : ""}
               delta={billedDelta} deltaWords={vs} />
      <KpiCard icon="wallet" tone="green" label="Collected" loading={!data}
               tip="Money received in this period, refunds taken off. Includes dues paid on older bills, so it can be more than the total amount."
               value={data ? rupees(data.period.collected_total, { paise: false }) : ""} delta={collectedDelta} deltaWords={vs}>
        {#if data}{#each Object.entries(data.period.collected) as [mode, amount] (mode)}<span>{MODES[mode] ?? mode} <strong class="tabular">{rupeesShort(amount)}</strong></span>{:else}<span>Nothing collected</span>{/each}{/if}
      </KpiCard>
      <KpiCard icon="alert" tone="orange" href={allTime ? "/dues?from=all" : `/bills?payment=due${bq}`} label="Dues" loading={!data}
               tip={allTime ? "Everything still owed, on bills of any date." : "Still owed on this period's bills. The note gives everything owed on bills of any date."}
               value={data ? rupees(allTime ? data.outstanding_dues : data.period.due_on_bills, { paise: false }) : ""}
               note={data ? (allTime ? `${count(data.dues_count)} bills` : `${rupeesShort(data.outstanding_dues)} owed overall`) : ""} />
    </div>
  {/if}

  {#if !business}
    <div class="grid-4 kpis" aria-busy={loading}>
      <KpiCard icon="receipt" href="/bills?{bq.slice(1)}" label="Total bills" loading={!desk}
               tip="Bills made in this period, by bill date, not counting cancelled ones." value={desk ? count(desk.bills) : ""} />
      <KpiCard icon="rupee" href="/bills?{bq.slice(1)}" label="Total billed amount" loading={!desk}
               tip="What this period's bills came to, after discounts. Cancelled bills are left out." value={desk ? rupees(desk.billed, { paise: false }) : ""} />
      <KpiCard icon="wallet" tone="green" label="Collected" loading={!desk}
               tip="Money received in this period, refunds taken off. Includes dues paid against older bills."
               value={desk ? rupees(desk.collected_total, { paise: false }) : ""}>
        {#if desk}
          {#each Object.entries(desk.collected) as [mode, amount] (mode)}<span>{MODES[mode] ?? mode} <strong class="tabular">{rupeesShort(amount)}</strong></span>{:else}<span>Nothing collected</span>{/each}
          {#if !desk.all_time && Number(desk.dues_collected)}<span>· {rupeesShort(desk.dues_collected)} of it on older bills</span>{/if}
          {#if Number(desk.refunds)}<span>· {rupeesShort(desk.refunds)} refunded</span>{/if}
        {/if}
      </KpiCard>
      <KpiCard icon="alert" tone="orange" label="Dues" loading={!desk}
               href={allTime ? (session.can("payments.collect") ? "/dues" : "/bills?payment=due") : `/bills?payment=due${bq}`}
               tip={allTime ? "Everything still owed, on bills of any date." : "Still owed on this period's bills. The note gives everything owed, any date."}
               value={desk ? rupees(allTime ? desk.outstanding_dues : desk.due_on_bills, { paise: false }) : ""}
               note={desk ? (allTime ? `${count(desk.dues_count)} bills with money due` : `${count(desk.due_bills)} bills · ${rupees(desk.outstanding_dues, { paise: false })} owed overall`) : ""} />
    </div>
  {/if}

  <div class="grid-3 items-start">
    <!-- Bills first: the period's bills, filterable in place -->
    <section class="card full-row" aria-labelledby="bills-title">
      <div class="card-header">
        <div><h2 class="card-title" id="bills-title">Bills · {label}<InfoTip about="Bills" text={business ? "The period's bills, newest first. Billed is what they came to after discounts (cancelled bills left out); due is what's still owed on them." : "The period's bills, newest first, with what's still owed on them."} /></h2>
          <p class="card-description">{bills ? `${count(bills.total)} bills${bills.sums.billed !== null ? ` · ${rupees(bills.sums.billed, { paise: false })} billed` : ""} · ${rupees(bills.sums.due, { paise: false })} due` : "Loading…"}</p></div>
        <a class="btn btn-ghost btn-sm" href={allHref}>View all <Icon name="arrowRight" size="sm" /></a>
      </div>
      <div class="bills-filters">
        <div class="input-group"><Icon name="search" />
          <input class="input" type="search" placeholder="Patient, mobile or bill no." aria-label="Search bills" bind:value={searchText} oninput={onSearch} /></div>
        <select class="select" aria-label="Payment" bind:value={payment}>
          <option value="">All payments</option><option value="due">With dues</option><option value="paid">Fully paid</option>
          <option value="part">Part paid</option><option value="unpaid">Unpaid</option>
        </select>
      </div>
      <div class="table-wrap" aria-busy={billsLoading}>
        <table class="table" style="min-width: 0">
          <thead><tr><th>Bill</th><th>Patient</th><th class="hide-sm">Referred by</th><th class="num">Total</th><th class="num">Due</th><th class="hide-sm">Payment</th><th class="num"><span class="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {#each bills?.items ?? [] as b (b.id)}
              {@const pay = paymentState(b)}
              <tr class="is-clickable" onclick={(e) => { if (!(e.target as Element).closest("a")) navigate(`/bills/${b.id}`); }}>
                <td><a class="cell-title mono nowrap" href="/bills/{b.id}">{b.invoice_no}</a><div class="cell-sub" use:tooltip={dateTime(b.created_at)}>{oneDay ? timeOf(b.created_at) : date(b.bill_date)}</div></td>
                <td><div class="cell-title">{b.patient_name}</div><div class="cell-sub tabular">{b.patient_mobile || "—"}</div></td>
                <td class="text-sm hide-sm">{b.referring_doctor_name || "Self"}</td>
                <td class="num money">{rupees(b.total)}</td>
                <td class="num money {Number(b.due) > 0 ? 'money-due' : 'text-muted'}">{rupees(b.due)}</td>
                <td class="hide-sm">{#if b.status !== "confirmed"}<span class="badge {BILL_STATUS[b.status][0]}">{BILL_STATUS[b.status][1]}</span>{:else}<span class="badge {pay[0]}">{pay[1]}</span>{/if}</td>
                <td class="num nowrap">
                  <a class="btn btn-ghost btn-icon btn-sm" href="/bills/{b.id}/print" target="_blank" rel="noopener" aria-label="Print {b.invoice_no}" use:tooltip={"Print"}><Icon name="printer" size="sm" /></a>
                  {#if Number(b.due) > 0 && b.status !== "cancelled" && session.can("payments.collect")}
                    <a class="btn btn-ghost btn-icon btn-sm" href="/bills/{b.id}?collect=1" aria-label="Collect due on {b.invoice_no}" use:tooltip={"Collect due"}><Icon name="wallet" size="sm" /></a>
                  {/if}
                </td>
              </tr>
            {:else}
              <tr><td colspan="7"><div class="empty"><Icon name="receipt" />{billsLoading ? "Loading…" : search || payment ? "No bills match these filters." : allTime ? "No bills yet." : `No bills for ${words}.`}</div></td></tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if bills && bills.total > bills.items.length}
        <div class="card-footer" style="justify-content: center"><a class="link-button" href={allHref}>See all {count(bills.total)} bills</a></div>
      {/if}
    </section>

  </div>

  {#if business && data}
    <div class="grid-3 items-start">
      <section class="card span-2" aria-labelledby="trend-title">
        <div class="card-header"><div><h2 class="card-title" id="trend-title">Billing and collection<InfoTip about="Billing and collection" text="Billed by bill date against money received by the date it came in, day by day (month by month for long periods)." /></h2>
          <p class="card-description">{data.trend_unit === "month" ? "By month" : "By day"}, {trendWords}. Collected includes dues paid against older bills.</p></div></div>
        <div class="card-content"><TrendChart points={data.trend} unit={data.trend_unit === "month" ? "month" : "day"} period={trendWords} /></div>
      </section>
      <section class="card" aria-labelledby="dept-title">
        <div class="card-header"><div><h2 class="card-title" id="dept-title">By department<InfoTip about="By department" text="What each department's tests came to on the period's bills, before any discount on the bill, and how many bills had them." /></h2><p class="card-description">Tests billed · {words}.</p></div></div>
        <div class="card-content">
          {#if data.departments.length}
            <ul class="bar-list">
              {#each data.departments as d (d.name)}
                <li><div class="bar-head"><span class="name">{d.name}</span><span class="value">{rupeesShort(d.amount)} · {count(d.bills)}</span></div>
                  <div class="progress" aria-hidden="true"><div class="progress-bar" style="width: {(Number(d.amount) / deptMax) * 100}%"></div></div></li>
              {/each}
            </ul>
          {:else}<div class="empty"><Icon name="inbox" />Nothing billed for {words}.</div>{/if}
        </div>
      </section>
    </div>

    <div class="grid-2 items-start">
      <section class="card" aria-labelledby="doc-title">
        <div class="card-header"><div><h2 class="card-title" id="doc-title">Top referrers<InfoTip about="Top referrers" text="Doctors and hospitals that referred the most bills in the period, with what those bills came to." /></h2><p class="card-description">Bills referred · {words}.</p></div>
          <a class="btn btn-ghost btn-sm" href="/doctors">View all <Icon name="arrowRight" size="sm" /></a></div>
        <div class="card-content">
          {#if data.doctors.length}
            <ul class="bar-list">
              {#each data.doctors as d (d.name)}
                <li><div class="bar-head"><span class="name">{d.name}</span><span class="value">{count(d.bills)} bills · {rupeesShort(d.amount)}</span></div>
                  <div class="progress" aria-hidden="true"><div class="progress-bar" style="width: {(d.bills / docMax) * 100}%"></div></div></li>
              {/each}
            </ul>
          {:else}<div class="empty"><Icon name="stethoscope" />No referred bills for {words}.</div>{/if}
        </div>
      </section>
      <section class="card" aria-labelledby="dues-title">
        <div class="card-header"><div><h2 class="card-title" id="dues-title">Dues to chase<InfoTip about="Dues to chase" text="The six oldest bills that still have money owed, whatever the period above." /></h2><p class="card-description">The oldest bills with money still due, any date.</p></div>
          <a class="btn btn-ghost btn-sm" href="/dues">View all <Icon name="arrowRight" size="sm" /></a></div>
        <div class="table-wrap">
          <table class="table" style="min-width: 0">
            <thead><tr><th>Bill</th><th>Patient</th><th class="num">Due</th></tr></thead>
            <tbody>
              {#each data.oldest_dues as b (b.id)}
                <tr class="is-clickable" onclick={(e) => { if (!(e.target as Element).closest("a")) navigate(`/bills/${b.id}`); }}>
                  <td><a class="cell-title mono nowrap" href="/bills/{b.id}">{b.invoice_no}</a><div class="cell-sub">{date(b.bill_date)}</div></td>
                  <td><div class="cell-title">{b.patient_name}</div><div class="cell-sub">{b.patient_mobile || "—"}</div></td>
                  <td class="num money money-due">{rupees(b.due)}</td>
                </tr>
              {:else}
                <tr><td colspan="3"><div class="empty"><Icon name="check" />No dues. Everything is paid.</div></td></tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  {/if}
{/if}

<style>
  .bills-filters { display: grid; grid-template-columns: minmax(0, 1fr) 170px; gap: 10px; padding: 14px 20px; border-bottom: 1px solid var(--border); }
  .full-row { grid-column: 1 / -1; }
  /* the cards: one line for the label, the figure, then the notes (the change on its own line when they don't fit) */
  .kpis :global(.kpi-note) { display: flex; flex-wrap: wrap; gap: 2px 10px; align-items: center; }
  .kpis :global(.stat-delta) { white-space: nowrap; }
  @media (max-width: 760px) {
    .bills-filters { grid-template-columns: 1fr; padding: 12px 16px; }
    .hide-sm { display: none; }
    .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 10px; }
  }
</style>
