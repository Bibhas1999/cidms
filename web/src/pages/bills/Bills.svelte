<script lang="ts">
  import DateRange from "../../components/DateRange.svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import Pagination from "../../components/Pagination.svelte";
  import { get } from "../../lib/api";
  import { BILL_STATUS, paymentState, type BillPage } from "../../lib/bill-types";
  import { count, date, dateTime, rupees } from "../../lib/format";
  import { navigate, router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";

  // All bills, or (mode "dues") only bills with money still owed, oldest first in the eyes of whoever chases them.
  let { mode = "all" }: { mode?: "all" | "dues"; params?: Record<string, string> } = $props();
  const dues = $derived(mode === "dues");

  const SIZE = $derived(Math.min(100, Number(router.query.get("size")) || 25));
  const q = $derived(router.query);
  const page = $derived(Number(q.get("page") ?? 1) || 1);
  const search = $derived(q.get("search") ?? "");
  const from = $derived(q.get("from") ?? "");
  const to = $derived(q.get("to") ?? "");
  const status = $derived(q.get("status") ?? "");
  const dueOnly = $derived(dues || q.get("due") === "true");

  let data = $state<BillPage | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let searchText = $state(router.query.get("search") ?? "");

  $effect(() => {
    const ctrl = new AbortController();
    loading = true;
    get<BillPage>("/api/bills", { page, size: SIZE, search, from, to, status, due: dueOnly || undefined, sort: dues ? "oldest" : undefined }, ctrl.signal)
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  let timer: ReturnType<typeof setTimeout>;
  const onSearch = () => { clearTimeout(timer); timer = setTimeout(() => setQuery({ search: searchText.trim(), page: null }), 300); };

  const filtered = $derived(!!(search || from || to || status || (!dues && dueOnly)));
</script>

<PageHeader eyebrow="Front desk" title={dues ? "Dues" : "Bills"}
            description={dues ? "Bills with money still owed. Open one to collect what's due; every instalment is kept." : "Every bill, newest first. Search by patient, mobile or bill number."}>
  {#snippet actions()}
    {#if session.can("billing.create")}<a class="btn btn-primary" href="/bills/new"><Icon name="plus" /> New bill</a>{/if}
  {/snippet}
</PageHeader>

<section class="card">
  <div class="toolbar">
    <div class="input-group">
      <Icon name="search" />
      <label class="sr-only" for="bill-search">Search bills</label>
      <input id="bill-search" class="input" type="search" placeholder="Patient name, mobile or bill number…" bind:value={searchText} oninput={onSearch} />
    </div>
    {#if !dues}
      <label class="sr-only" for="bill-status">Status</label>
      <select id="bill-status" class="select" value={status} onchange={(e) => setQuery({ status: e.currentTarget.value, page: null })}>
        <option value="">All statuses</option><option value="confirmed">Confirmed</option><option value="on_hold">On hold</option><option value="cancelled">Cancelled</option>
      </select>
      <label class="check-row"><input class="checkbox" type="checkbox" checked={dueOnly} onchange={(e) => setQuery({ due: e.currentTarget.checked ? "true" : null, page: null })} /> Only with dues</label>
    {/if}
  </div>
  <div class="toolbar" style="padding-top: 10px">
    <DateRange from={from} to={to} id="bills" onchange={(f, t) => setQuery({ from: f, to: t, page: null })} />
    {#if filtered}<button class="link-button" onclick={() => { searchText = ""; setQuery({ search: null, from: null, to: null, status: null, due: null, page: null }); }}><Icon name="x" size="sm" /> Clear filters</button>{/if}
  </div>

  {#if loadError}
    <div class="card-content"><div class="alert alert-destructive" role="alert"><Icon name="alert" />{loadError}</div></div>
  {:else if data}
    <div class="card-content row-wrap" style="padding-top: 12px; padding-bottom: 12px; gap: 20px">
      <span class="text-sm"><strong>{count(data.total)}</strong> <span class="text-muted">bills</span></span>
      {#if !dues}<span class="text-sm"><span class="text-muted">Billed</span> <strong class="money">{rupees(data.sums.billed)}</strong></span>{/if}
      <span class="text-sm"><span class="text-muted">Still due</span> <strong class="money money-due">{rupees(data.sums.due)}</strong></span>
      {#if !dues}<span class="text-xs text-faint">Cancelled bills aren't counted in these totals.</span>{/if}
    </div>
    <div class="table-wrap" aria-busy={loading}>
      <table class="table">
        <thead>
          <tr><th>Bill</th><th>Patient</th><th>Referred by</th><th class="num">Total</th><th class="num">Paid</th><th class="num">Due</th><th>Payment</th>{#if !dues}<th>Status</th>{/if}<th class="num">Actions</th></tr>
        </thead>
        <tbody>
          {#each data.items as b (b.id)}
            {@const pay = paymentState(b)}
            <tr class="is-clickable" onclick={(e) => { if (!(e.target as Element).closest("a")) navigate(`/bills/${b.id}`); }}>
              <td><a class="cell-title mono nowrap" href="/bills/{b.id}">{b.invoice_no}</a><div class="cell-sub">{date(b.bill_date)}{#if b.legacy_no} · old #{b.legacy_no}{/if}</div></td>
              <td><div class="cell-title">{b.patient_name}</div><div class="cell-sub tabular">{b.patient_mobile || "—"}</div></td>
              <td class="text-sm">{b.referring_doctor_name || "Self"}</td>
              <td class="num money">{rupees(b.total)}</td>
              <td class="num money">{rupees(b.paid)}</td>
              <td class="num money {Number(b.due) > 0 ? 'money-due' : ''}">{rupees(b.due)}</td>
              <td><span class="badge {pay[0]}">{pay[1]}</span></td>
              {#if !dues}<td>{#if b.status !== "confirmed"}<span class="badge {BILL_STATUS[b.status][0]}">{BILL_STATUS[b.status][1]}</span>{:else}<span class="text-xs text-muted" title={dateTime(b.created_at)}>by {b.created_by_name || "—"}</span>{/if}</td>{/if}
              <td class="num nowrap">
                <a class="btn btn-ghost btn-icon btn-sm" href="/bills/{b.id}" aria-label="View {b.invoice_no}" title="View"><Icon name="eye" size="sm" /></a>
                <a class="btn btn-ghost btn-icon btn-sm" href="/bills/{b.id}/print" target="_blank" rel="noopener" aria-label="Print {b.invoice_no}" title="Print"><Icon name="printer" size="sm" /></a>
                {#if Number(b.due) > 0 && b.status !== "cancelled" && session.can("payments.collect")}
                  <a class="btn btn-ghost btn-icon btn-sm" href="/bills/{b.id}?collect=1" aria-label="Collect due on {b.invoice_no}" title="Collect due"><Icon name="wallet" size="sm" /></a>
                {/if}
                {#if b.status !== "cancelled" && session.can("billing.edit")}
                  <a class="btn btn-ghost btn-icon btn-sm" href="/bills/{b.id}?edit=1" aria-label="Change tests on {b.invoice_no}" title="Change tests"><Icon name="edit" size="sm" /></a>
                {/if}
              </td>
            </tr>
          {:else}
            <tr><td colspan="9"><div class="empty"><Icon name={dues ? "wallet" : "receipt"} />
              {filtered ? "No bills match these filters." : dues ? "No dues. Everything is paid." : "No bills yet."}</div></td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if data.total > 0}<Pagination page={data.page} size={data.size} total={data.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />{/if}
  {:else}
    <div class="empty" aria-busy="true">Loading…</div>
  {/if}
</section>
