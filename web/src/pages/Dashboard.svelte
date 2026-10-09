<script lang="ts">
  import Icon from "../components/Icon.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import TrendChart from "../components/TrendChart.svelte";
  import { get } from "../lib/api";
  import { count, date, rupees, rupeesShort } from "../lib/format";
  import { session } from "../lib/session.svelte";
  import type { BillSummary, Overview, Page } from "../lib/types";

  const first = (session.me?.full_name ?? "").split(" ")[0];
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const todayText = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata" }).format(new Date());

  // Owners and accounts see the business; everyone else sees what the front desk needs.
  const business = !session.isPlatform && session.can("business_reports.view");

  let data = $state<Overview | null>(null);
  let recent = $state<BillSummary[] | null>(null);
  let failed = $state("");

  $effect(() => {
    const ctrl = new AbortController();
    if (business) get<Overview>("/api/summary/overview", undefined, ctrl.signal).then((d) => (data = d)).catch((e) => { if (e.name !== "AbortError") failed = e.message; });
    else if (!session.isPlatform) get<Page<BillSummary>>("/api/bills", { size: 10 }, ctrl.signal).then((d) => (recent = d.items)).catch((e) => { if (e.name !== "AbortError") failed = e.message; });
    return () => ctrl.abort();
  });

  const MODES: Record<string, string> = { cash: "Cash", upi: "UPI", card: "Card", bank: "Bank", other: "Other" };
  const delta = $derived.by(() => {
    if (!data) return null;
    const t = Number(data.today.billed), y = Number(data.yesterday_billed);
    if (!y) return null;
    return Math.round(((t - y) / y) * 100);
  });
  const deptMax = $derived(Math.max(1, ...(data?.departments ?? []).map((d) => Number(d.amount))));
  const docMax = $derived(Math.max(1, ...(data?.doctors ?? []).map((d) => d.bills)));
  const STATUS: Record<string, [string, string]> = { confirmed: ["badge-success", "Confirmed"], on_hold: ["badge-warning", "On hold"], cancelled: ["badge-destructive", "Cancelled"] };
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
    {#if session.can("platform.staff.manage")}<a class="quick-action" href="/staff"><span class="qa-icon"><Icon name="shield" /></span><span>Platform staff<small>Who runs the platform</small></span></a>{/if}
    {#if session.can("platform.activity.view")}<a class="quick-action" href="/activity"><span class="qa-icon"><Icon name="activity" /></span><span>Activity log<small>Sign-ins and changes</small></span></a>{/if}
  </div>
{:else if failed}
  <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div><div class="alert-title">Couldn't load the dashboard</div>{failed}</div></div>
{:else if business && !data}
  <div class="grid-4" aria-busy="true">{#each [1, 2, 3, 4] as i (i)}<div class="card stat"><span class="stat-label">Loading…</span><span class="stat-value">&nbsp;</span></div>{/each}</div>
{:else if business && data}
  {#if data.dues_count}
    <div class="card"><div class="card-content row-between">
      <div class="row"><span class="timeline-dot is-warning"><Icon name="wallet" size="sm" /></span>
        <div><div class="font-semibold">{count(data.dues_count)} bills have money still due: {rupees(data.today.outstanding_dues)}</div>
          <div class="text-sm text-muted">Oldest first, so the longest-waiting dues are chased first.</div></div></div>
      <a class="btn btn-primary btn-sm" href="/dues">Open dues</a>
    </div></div>
  {/if}

  <div class="grid-4">
    <a class="card stat is-navy" href="/bills?from={data.today.day}&to={data.today.day}">
      <span class="stat-label">Billed today</span>
      <span class="stat-value money">{rupees(data.today.billed, { paise: false })}</span>
      <span class="stat-note">{count(data.today.bills)} bills
        {#if delta !== null}· <span class="stat-delta {delta >= 0 ? 'is-up' : 'is-down'}"><Icon name={delta >= 0 ? "trendUp" : "trendDown"} size="sm" />{Math.abs(delta)}% vs yesterday</span>{/if}
      </span>
    </a>
    <div class="card stat is-teal">
      <span class="stat-label">Collected today</span>
      <span class="stat-value money">{rupees(data.today.collected_total, { paise: false })}</span>
      <span class="stat-split">
        {#each Object.entries(data.today.collected) as [mode, amount] (mode)}<span>{MODES[mode] ?? mode} <strong>{rupeesShort(amount)}</strong></span>{:else}<span>Nothing yet</span>{/each}
      </span>
    </div>
    <a class="card stat is-warning" href="/dues">
      <span class="stat-label">Dues outstanding</span>
      <span class="stat-value money">{rupees(data.today.outstanding_dues, { paise: false })}</span>
      <span class="stat-note">{count(data.dues_count)} bills · {rupees(data.today.dues_collected, { paise: false })} collected today</span>
    </a>
    <a class="card stat" href="/worklist">
      <span class="stat-label">Tests waiting</span>
      <span class="stat-value">{count(data.pending_tests.billed + data.pending_tests.scanned)}</span>
      <span class="stat-note">{count(data.pending_tests.billed)} to scan · {count(data.pending_tests.scanned)} to report (last 7 days)</span>
    </a>
  </div>

  <div class="grid-3 items-start">
    <section class="card span-2" aria-labelledby="trend-title">
      <div class="card-header"><div><h2 class="card-title" id="trend-title">Billing and collection</h2>
        <p class="card-description">Last 30 days. Collected includes dues paid against older bills.</p></div></div>
      <div class="card-content"><TrendChart points={data.trend} /></div>
    </section>
    <section class="card" aria-labelledby="month-title">
      <div class="card-header"><div><h2 class="card-title" id="month-title">This month</h2>
        <p class="card-description">From the 1st to today.</p></div></div>
      <div class="card-content">
        <dl class="dl" style="grid-template-columns: 1fr">
          <div><dt>Billed</dt><dd class="text-lg font-semibold money">{rupees(data.month_billed)}</dd></div>
          <div><dt>Collected</dt><dd class="text-lg font-semibold money">{rupees(data.month_collected)}</dd></div>
          <div><dt>Bills</dt><dd>{count(data.month_bills)}{#if data.month_bills}&nbsp;· average {rupees(Number(data.month_billed) / data.month_bills, { paise: false })}{/if}</dd></div>
          <div><dt>Discounts given</dt><dd class="money">{rupees(data.month_discounts)}</dd></div>
        </dl>
      </div>
    </section>
  </div>

  <div class="grid-2 items-start">
    <section class="card" aria-labelledby="dept-title">
      <div class="card-header"><div><h2 class="card-title" id="dept-title">By department</h2>
        <p class="card-description">Tests billed this month.</p></div></div>
      <div class="card-content">
        {#if data.departments.length}
          <ul class="bar-list">
            {#each data.departments as d (d.name)}
              <li>
                <div class="bar-head"><span class="name">{d.name}</span><span class="value">{rupees(d.amount, { paise: false })} · {count(d.bills)} bills</span></div>
                <div class="progress" aria-hidden="true"><div class="progress-bar" style="width: {(Number(d.amount) / deptMax) * 100}%"></div></div>
              </li>
            {/each}
          </ul>
        {:else}<div class="empty"><Icon name="inbox" />Nothing billed this month yet.</div>{/if}
      </div>
    </section>
    <section class="card" aria-labelledby="doc-title">
      <div class="card-header"><div><h2 class="card-title" id="doc-title">Top referring doctors</h2>
        <p class="card-description">Bills referred this month.</p></div>
        <a class="btn btn-ghost btn-sm" href="/doctors">View all</a></div>
      <div class="card-content">
        {#if data.doctors.length}
          <ul class="bar-list">
            {#each data.doctors as d (d.name)}
              <li>
                <div class="bar-head"><span class="name">{d.name}</span><span class="value">{count(d.bills)} bills · {rupees(d.amount, { paise: false })}</span></div>
                <div class="progress" aria-hidden="true"><div class="progress-bar" style="width: {(d.bills / docMax) * 100}%"></div></div>
              </li>
            {/each}
          </ul>
        {:else}<div class="empty"><Icon name="stethoscope" />No referred bills this month yet.</div>{/if}
      </div>
    </section>
  </div>

  <div class="grid-2 items-start">
    {@render billTable("Dues to chase", "The oldest bills with money still due.", data.oldest_dues, true, "/dues")}
    {@render billTable("Recent bills", "The latest bills from the front desk.", data.recent_bills, false, "/bills")}
  </div>
{:else if recent}
  <div class="quick-actions">
    {#if session.can("billing.create")}<a class="quick-action" href="/bills/new"><span class="qa-icon"><Icon name="filePlus" /></span><span>New bill<small>Bill a patient's tests</small></span></a>{/if}
    <a class="quick-action" href="/patients"><span class="qa-icon"><Icon name="search" /></span><span>Find a patient<small>By name, mobile or number</small></span></a>
    {#if session.can("payments.collect")}<a class="quick-action" href="/dues"><span class="qa-icon"><Icon name="wallet" /></span><span>Collect a due<small>Money still owed</small></span></a>{/if}
    <a class="quick-action" href="/worklist"><span class="qa-icon"><Icon name="clipboard" /></span><span>Worklist<small>Tests waiting</small></span></a>
  </div>
  {@render billTable("Recent bills", "The latest bills.", recent, false, "/bills")}
{/if}

{#snippet billTable(title: string, description: string, rows: BillSummary[], dueOnly: boolean, href: string)}
  <section class="card">
    <div class="card-header"><div><h2 class="card-title">{title}</h2><p class="card-description">{description}</p></div>
      <a class="btn btn-ghost btn-sm" {href}>View all</a></div>
    <div class="card-flush">
      {#if rows.length}
        <div class="table-wrap"><table class="table" style="min-width: 0">
          <thead><tr><th>Bill</th><th>Patient</th><th class="num">{dueOnly ? "Due" : "Total"}</th>{#if !dueOnly}<th>Status</th>{/if}</tr></thead>
          <tbody>
            {#each rows as b (b.id)}
              <tr>
                <td><a href="/bills/{b.id}" class="cell-title mono nowrap">{b.invoice_no}</a><div class="cell-sub">{date(b.bill_date)}</div></td>
                <td><div class="cell-title">{b.patient_name}</div><div class="cell-sub">{b.patient_mobile || "—"}</div></td>
                <td class="num money {dueOnly ? 'money-due' : ''}">{rupees(dueOnly ? b.due : b.total)}</td>
                {#if !dueOnly}<td><span class="badge {STATUS[b.status][0]}">{STATUS[b.status][1]}</span></td>{/if}
              </tr>
            {/each}
          </tbody>
        </table></div>
      {:else}<div class="empty"><Icon name="inbox" />{dueOnly ? "No dues. Everything is paid." : "No bills yet."}</div>{/if}
    </div>
  </section>
{/snippet}
