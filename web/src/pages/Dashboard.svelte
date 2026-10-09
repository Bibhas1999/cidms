<script lang="ts">
  import Icon from "../components/Icon.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import TrendChart from "../components/TrendChart.svelte";
  import { get } from "../lib/api";
  import { BILL_STATUS, paymentState, type BillPage } from "../lib/bill-types";
  import { count, date, dateTime, rupees, rupeesShort } from "../lib/format";
  import { navigate } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import type { Overview } from "../lib/types";

  const first = (session.me?.full_name ?? "").split(" ")[0];
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const todayText = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata" }).format(new Date());

  // Owners and accounts see the business figures; everyone sees the bills.
  const business = !session.isPlatform && session.can("business_reports.view");

  let data = $state<Overview | null>(null);
  let failed = $state("");
  $effect(() => {
    if (!business) return;
    const ctrl = new AbortController();
    get<Overview>("/api/summary/overview", undefined, ctrl.signal).then((d) => (data = d)).catch((e) => { if (e.name !== "AbortError") failed = e.message; });
    return () => ctrl.abort();
  });

  // ---------- the bills card, first on the page, with its own filters ----------
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  const shift = (iso: string, days: number) => { const d = new Date(`${iso}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); };
  const RANGES: Record<string, [string, string, string]> = {
    today: ["Today", today, today],
    yesterday: ["Yesterday", shift(today, -1), shift(today, -1)],
    "7d": ["Last 7 days", shift(today, -6), today],
    month: ["This month", today.slice(0, 8) + "01", today],
  };
  let range = $state("today");
  let payment = $state<"" | "due" | "paid">("");
  let search = $state("");
  let searchText = $state("");
  let bills = $state<BillPage | null>(null);
  let billsLoading = $state(false);

  $effect(() => {
    if (session.isPlatform) return;
    const [, from, to] = RANGES[range];
    const ctrl = new AbortController();
    billsLoading = true;
    get<BillPage>("/api/bills", { from, to, search, size: 10, due: payment === "due" || undefined, paid: payment === "paid" || undefined }, ctrl.signal)
      .then((d) => (bills = d)).catch(() => {}).finally(() => (billsLoading = false));
    return () => ctrl.abort();
  });

  let timer: ReturnType<typeof setTimeout>;
  const onSearch = () => { clearTimeout(timer); timer = setTimeout(() => (search = searchText.trim()), 300); };
  const allHref = $derived(`/bills?from=${RANGES[range][1]}&to=${RANGES[range][2]}${payment === "due" ? "&due=true" : ""}${search ? `&search=${encodeURIComponent(search)}` : ""}`);
  const timeOf = (iso: string) => new Intl.DateTimeFormat("en-IN", { timeStyle: "short", timeZone: "Asia/Kolkata" }).format(new Date(iso));

  const MODES: Record<string, string> = { cash: "Cash", upi: "UPI", card: "Card", bank: "Bank", other: "Other" };
  const delta = $derived.by(() => {
    if (!data) return null;
    const t = Number(data.today.billed), y = Number(data.yesterday_billed);
    return y ? Math.round(((t - y) / y) * 100) : null;
  });
  const deptMax = $derived(Math.max(1, ...(data?.departments ?? []).map((d) => Number(d.amount))));
  const docMax = $derived(Math.max(1, ...(data?.doctors ?? []).map((d) => d.bills)));
</script>

<PageHeader eyebrow="Overview" title="{greeting}, {first}" description="{session.workspace?.name} · {todayText}">
  {#snippet actions()}
    {#if session.can("payments.collect")}<a class="btn btn-outline" href="/dues"><Icon name="wallet" /> Collect a due</a>{/if}
    {#if session.can("billing.create")}<a class="btn btn-primary" href="/bills/new"><Icon name="plus" /> New bill</a>{/if}
  {/snippet}
</PageHeader>

{#if session.isPlatform}
  <div class="quick-actions">
    {#if session.can("platform.clients.view")}<a class="quick-action" href="/clients"><span class="qa-icon"><Icon name="building" /></span><span>Clients<small>Centres, plans and status</small></span></a>{/if}
    <a class="quick-action" href="/settings"><span class="qa-icon"><Icon name="settings" /></span><span>Settings<small>Platform staff and activity</small></span></a>
  </div>
{:else}
  {#if failed}
    <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div><div class="alert-title">Couldn't load the figures</div>{failed}</div></div>
  {/if}

  {#if business}
    <div class="grid-4" aria-busy={!data}>
      <a class="card stat" href="/bills?from={today}&to={today}">
        <span class="stat-icon"><Icon name="receipt" /></span>
        <span class="stat-label">Billed today</span>
        <span class="stat-value money">{data ? rupees(data.today.billed, { paise: false }) : "—"}</span>
        <span class="stat-note">{data ? `${count(data.today.bills)} bills` : "…"}
          {#if delta !== null}<span class="stat-delta {delta >= 0 ? 'is-up' : 'is-down'}"><Icon name={delta >= 0 ? "trendUp" : "trendDown"} size="sm" />{Math.abs(delta)}% vs yesterday</span>{/if}
        </span>
      </a>
      <div class="card stat">
        <span class="stat-icon is-green"><Icon name="wallet" /></span>
        <span class="stat-label">Collected today</span>
        <span class="stat-value money">{data ? rupees(data.today.collected_total, { paise: false }) : "—"}</span>
        <span class="stat-split">
          {#if data}{#each Object.entries(data.today.collected) as [mode, amount] (mode)}<span>{MODES[mode] ?? mode} <strong>{rupeesShort(amount)}</strong></span>{:else}<span>Nothing yet</span>{/each}{/if}
        </span>
      </div>
      <a class="card stat" href="/dues">
        <span class="stat-icon is-orange"><Icon name="alert" /></span>
        <span class="stat-label">Dues outstanding</span>
        <span class="stat-value money">{data ? rupees(data.today.outstanding_dues, { paise: false }) : "—"}</span>
        <span class="stat-note">{data ? `${count(data.dues_count)} bills · ${rupees(data.today.dues_collected, { paise: false })} collected today` : "…"}</span>
      </a>
      <a class="card stat" href="/worklist">
        <span class="stat-icon"><Icon name="clipboard" /></span>
        <span class="stat-label">Tests waiting</span>
        <span class="stat-value">{data ? count(data.pending_tests.billed + data.pending_tests.scanned) : "—"}</span>
        <span class="stat-note">{data ? `${count(data.pending_tests.billed)} to scan · ${count(data.pending_tests.scanned)} to report` : "…"}</span>
      </a>
    </div>
  {/if}

  <div class="grid-3 items-start">
    <!-- Bills first: what the desk did today, filterable in place -->
    <section class="card {business ? 'span-2' : 'span-3'}" aria-labelledby="bills-title">
      <div class="card-header">
        <div><h2 class="card-title" id="bills-title">Bills</h2>
          <p class="card-description">{bills ? `${count(bills.total)} bills · ${rupees(bills.sums.billed, { paise: false })} billed · ${rupees(bills.sums.due, { paise: false })} due` : "Loading…"}</p></div>
        <a class="btn btn-ghost btn-sm" href={allHref}>View all <Icon name="arrowRight" size="sm" /></a>
      </div>
      <div class="bills-filters">
        <div class="input-group"><Icon name="search" />
          <input class="input" type="search" placeholder="Patient, mobile or bill no." aria-label="Search bills" bind:value={searchText} oninput={onSearch} /></div>
        <select class="select" aria-label="When" bind:value={range}>{#each Object.entries(RANGES) as [k, [label]] (k)}<option value={k}>{label}</option>{/each}</select>
        <select class="select" aria-label="Payment" bind:value={payment}><option value="">All payments</option><option value="due">With dues</option><option value="paid">Fully paid</option></select>
      </div>
      <div class="table-wrap" aria-busy={billsLoading}>
        <table class="table" style="min-width: 0">
          <thead><tr><th>Bill</th><th>Patient</th><th>Referred by</th><th class="num">Total</th><th class="num">Due</th><th>Payment</th><th class="num"><span class="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {#each bills?.items ?? [] as b (b.id)}
              {@const pay = paymentState(b)}
              <tr class="is-clickable" onclick={(e) => { if (!(e.target as Element).closest("a")) navigate(`/bills/${b.id}`); }}>
                <td><a class="cell-title mono nowrap" href="/bills/{b.id}">{b.invoice_no}</a><div class="cell-sub" title={dateTime(b.created_at)}>{range === "today" ? timeOf(b.created_at) : date(b.bill_date)}</div></td>
                <td><div class="cell-title">{b.patient_name}</div><div class="cell-sub tabular">{b.patient_mobile || "—"}</div></td>
                <td class="text-sm">{b.referring_doctor_name || "Self"}</td>
                <td class="num money">{rupees(b.total)}</td>
                <td class="num money {Number(b.due) > 0 ? 'money-due' : 'text-muted'}">{rupees(b.due)}</td>
                <td>{#if b.status !== "confirmed"}<span class="badge {BILL_STATUS[b.status][0]}">{BILL_STATUS[b.status][1]}</span>{:else}<span class="badge {pay[0]}">{pay[1]}</span>{/if}</td>
                <td class="num nowrap">
                  <a class="btn btn-ghost btn-icon btn-sm" href="/bills/{b.id}/print" target="_blank" rel="noopener" aria-label="Print {b.invoice_no}" title="Print"><Icon name="printer" size="sm" /></a>
                  {#if Number(b.due) > 0 && b.status !== "cancelled" && session.can("payments.collect")}
                    <a class="btn btn-ghost btn-icon btn-sm" href="/bills/{b.id}?collect=1" aria-label="Collect due on {b.invoice_no}" title="Collect due"><Icon name="wallet" size="sm" /></a>
                  {/if}
                </td>
              </tr>
            {:else}
              <tr><td colspan="7"><div class="empty"><Icon name="receipt" />{billsLoading ? "Loading…" : search || payment ? "No bills match these filters." : `No bills ${RANGES[range][0].toLowerCase()}.`}</div></td></tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if bills && bills.total > bills.items.length}
        <div class="card-footer" style="justify-content: center"><a class="link-button" href={allHref}>See all {count(bills.total)} bills</a></div>
      {/if}
    </section>

    {#if business && data}
      <section class="card" aria-labelledby="month-title">
        <div class="card-header"><div><h2 class="card-title" id="month-title">This month</h2><p class="card-description">From the 1st to today.</p></div></div>
        <div class="card-content">
          <dl class="month">
            <div><dt>Billed</dt><dd class="money">{rupees(data.month_billed, { paise: false })}</dd></div>
            <div><dt>Collected</dt><dd class="money">{rupees(data.month_collected, { paise: false })}</dd></div>
            <div><dt>Bills</dt><dd>{count(data.month_bills)}{#if data.month_bills}<span class="text-sm text-muted">&nbsp;· average {rupees(Number(data.month_billed) / data.month_bills, { paise: false })}</span>{/if}</dd></div>
            <div><dt>Discounts given</dt><dd class="money">{rupees(data.month_discounts, { paise: false })}</dd></div>
          </dl>
        </div>
      </section>
    {/if}
  </div>

  {#if business && data}
    <div class="grid-3 items-start">
      <section class="card span-2" aria-labelledby="trend-title">
        <div class="card-header"><div><h2 class="card-title" id="trend-title">Billing and collection</h2>
          <p class="card-description">Last 30 days. Collected includes dues paid against older bills.</p></div></div>
        <div class="card-content"><TrendChart points={data.trend} /></div>
      </section>
      <section class="card" aria-labelledby="dept-title">
        <div class="card-header"><div><h2 class="card-title" id="dept-title">By department</h2><p class="card-description">Tests billed this month.</p></div></div>
        <div class="card-content">
          {#if data.departments.length}
            <ul class="bar-list">
              {#each data.departments as d (d.name)}
                <li><div class="bar-head"><span class="name">{d.name}</span><span class="value">{rupeesShort(d.amount)} · {count(d.bills)}</span></div>
                  <div class="progress" aria-hidden="true"><div class="progress-bar" style="width: {(Number(d.amount) / deptMax) * 100}%"></div></div></li>
              {/each}
            </ul>
          {:else}<div class="empty"><Icon name="inbox" />Nothing billed this month yet.</div>{/if}
        </div>
      </section>
    </div>

    <div class="grid-2 items-start">
      <section class="card" aria-labelledby="doc-title">
        <div class="card-header"><div><h2 class="card-title" id="doc-title">Top referring doctors</h2><p class="card-description">Bills referred this month.</p></div>
          <a class="btn btn-ghost btn-sm" href="/doctors">View all <Icon name="arrowRight" size="sm" /></a></div>
        <div class="card-content">
          {#if data.doctors.length}
            <ul class="bar-list">
              {#each data.doctors as d (d.name)}
                <li><div class="bar-head"><span class="name">{d.name}</span><span class="value">{count(d.bills)} bills · {rupeesShort(d.amount)}</span></div>
                  <div class="progress" aria-hidden="true"><div class="progress-bar" style="width: {(d.bills / docMax) * 100}%"></div></div></li>
              {/each}
            </ul>
          {:else}<div class="empty"><Icon name="stethoscope" />No referred bills this month yet.</div>{/if}
        </div>
      </section>
      <section class="card" aria-labelledby="dues-title">
        <div class="card-header"><div><h2 class="card-title" id="dues-title">Dues to chase</h2><p class="card-description">The oldest bills with money still due.</p></div>
          <a class="btn btn-ghost btn-sm" href="/dues">View all <Icon name="arrowRight" size="sm" /></a></div>
        <div class="table-wrap">
          <table class="table" style="min-width: 0">
            <thead><tr><th>Bill</th><th>Patient</th><th class="num">Due</th></tr></thead>
            <tbody>
              {#each data.oldest_dues as b (b.id)}
                <tr class="is-clickable" onclick={() => navigate(`/bills/${b.id}`)}>
                  <td><span class="cell-title mono nowrap">{b.invoice_no}</span><div class="cell-sub">{date(b.bill_date)}</div></td>
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
  .bills-filters { display: grid; grid-template-columns: minmax(0, 1fr) 160px 160px; gap: 10px; padding: 14px 20px; border-bottom: 1px solid var(--border); }
  .month { display: grid; gap: 16px; margin: 0; }
  .month dt { font-size: 13px; color: var(--muted-foreground); }
  .month dd { margin: 2px 0 0; font-size: 20px; font-weight: 650; letter-spacing: -0.02em; }
  @media (max-width: 760px) { .bills-filters { grid-template-columns: 1fr; } }
</style>
