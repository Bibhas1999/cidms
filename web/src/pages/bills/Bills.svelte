<script lang="ts">
  import Combobox from "../../components/Combobox.svelte";
  import DataTable, { type Column } from "../../components/DataTable.svelte";
  import DateRange from "../../components/DateRange.svelte";
  import ExportMenu from "../../components/ExportMenu.svelte";
  import FilterBar from "../../components/FilterBar.svelte";
  import Icon from "../../components/Icon.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import type { RowAction } from "../../components/RowMenu.svelte";
  import StatCard from "../../components/StatCard.svelte";
  import StatusBadge from "../../components/StatusBadge.svelte";
  import { get } from "../../lib/api";
  import { PAYMENT_MODES, type BillPage, type Doctor, type LabTest } from "../../lib/bill-types";
  import { rangeLabel, thisMonth } from "../../lib/dates";
  import { count, dateTime, longDate, rupees, timeOf } from "../../lib/format";
  import { formatPhone } from "../../lib/phone";
  import { navigate, router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { tooltip } from "../../lib/tooltip";
  import type { BillSummary, Department, Page, Staff } from "../../lib/types";

  // All bills, or (at /dues) only bills with money still owed, oldest first for whoever chases them.
  // Every filter is in the address (FilterBar), so a filtered list can be shared and survives a reload.
  const dues = $derived(router.path === "/dues");

  const q = $derived(router.query);
  // Dues isn't paginated (see dueGroups below) - every due bill is fetched (100 at a time, the server's own
  // cap), not just the first page, so a doctor's bills are never silently cut off.
  const PAGE_SIZE = 100;
  const SIZE = $derived(dues ? PAGE_SIZE : Math.min(100, Number(q.get("size")) || 25));
  const page = $derived(Number(q.get("page") ?? 1) || 1);
  // Nothing in the address = this month (owner's default everywhere); ?from=all = every date.
  const month = thisMonth();
  const allPicked = $derived(q.get("from") === "all");
  const from = $derived(allPicked ? "" : q.get("from") ?? month.from);
  const to = $derived(allPicked ? "" : q.get("to") ?? (q.has("from") ? "" : month.to));
  const setDates = (f: string, t: string) =>
    set(!f && !t ? { from: "all", to: null } : f === month.from && t === month.to ? { from: null, to: null } : { from: f, to: t });
  // Older links used ?due=true for "only with dues".
  const payment = $derived(dues ? "due" : q.get("payment") ?? (q.get("due") === "true" ? "due" : ""));
  const sort = $derived(q.get("sort") ?? (dues ? "oldest" : "newest"));

  /** The filters as the server takes them (the same for the list and the export). */
  const filters = $derived({
    search: q.get("search") ?? "", from, to, status: q.get("status") ?? "", payment, mode: q.get("mode") ?? "",
    doctor_id: q.get("doctor_id") ?? "", self_referred: q.get("self_referred") === "true" || undefined,
    department_id: q.get("department_id") ?? "", test_id: q.get("test_id") ?? "", created_by: q.get("created_by") ?? "",
    min_total: q.get("min_total") ?? "", max_total: q.get("max_total") ?? "", discount: q.get("discount") ?? "",
    report: q.get("report") ?? "", sort,
  });

  let data = $state<BillPage | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);

  $effect(() => {
    const ctrl = new AbortController();
    const query = { ...filters, page, size: SIZE };
    const isDues = dues;
    reload;
    loading = true;
    (async () => {
      if (!isDues) return get<BillPage>("/api/bills", query, ctrl.signal);
      // Every page, not just the first: a doctor's bills must never split across an unfetched page.
      let p = 1, first: BillPage | null = null, items: BillPage["items"] = [];
      for (;;) {
        const d = await get<BillPage>("/api/bills", { ...query, page: p, size: PAGE_SIZE }, ctrl.signal);
        first ??= d;
        items = items.concat(d.items);
        if (items.length >= d.total || !d.items.length) break;
        p += 1;
      }
      return { ...first!, items, page: 1, size: items.length };
    })()
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  // The four cards follow the date range in the header only, not the table's search or filters. (On Dues the
  // page itself is "bills with money owed", so that stays.)
  let cards = $state<BillPage | null>(null);
  $effect(() => {
    const ctrl = new AbortController();
    const query = { from, to, payment: dues ? "due" : undefined, page: 1, size: 1 };
    void reload;
    get<BillPage>("/api/bills", query, ctrl.signal).then((d) => (cards = d)).catch(() => {});
    return () => ctrl.abort();
  });

  // Lists for the Filters pop-up.
  let departments = $state<Department[]>([]);
  $effect(() => { get<Department[]>("/api/departments").then((d) => (departments = d)).catch(() => {}); });
  const canSeeStaff = $derived(session.can("staff.manage"));
  const searchDoctors = (s: string, p: number, size: number, signal: AbortSignal) => get<Page<Doctor>>("/api/doctors", { search: s, page: p, size }, signal);
  const searchTests = (s: string, p: number, size: number, signal: AbortSignal) => get<Page<LabTest>>("/api/tests", { search: s, page: p, size }, signal);
  const searchStaff = (s: string, p: number, size: number, signal: AbortSignal) => get<Page<Staff>>("/api/staff", { search: s, page: p, size, active: undefined }, signal);
  let doctorText = $state("");
  let testText = $state("");
  let staffText = $state("");

  const set = (values: Record<string, string | null>) => setQuery({ ...values, page: null });
  // The bill-total range, checked as soon as either box changes: no list can match "at least 5000, at most 500".
  const rangeProblem = $derived.by(() => {
    const lo = q.get("min_total"), hi = q.get("max_total");
    if ((lo && Number(lo) < 0) || (hi && Number(hi) < 0)) return "Enter amounts of 0 or more.";
    return lo && hi && Number(lo) > Number(hi) ? "The lowest total can't be more than the highest." : "";
  });

  // Names as people write them: "PIU KOLEY" -> "Piu Koley".
  const nice = (n: string) => n.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());

  function actionsFor(b: BillSummary): RowAction[] {
    const live = b.status !== "cancelled";
    // Dues: just the one thing this page is for, nothing else to choose from.
    if (dues) {
      return live && Number(b.due) > 0 && session.can("payments.collect")
        ? [{ label: "Collect due", icon: "wallet", href: `/bills/${b.id}?collect=1`, hint: `${rupees(b.due)} still to pay` }] : [];
    }
    return [
      { label: "View bill", icon: "eye", href: `/bills/${b.id}` },
      { label: "Print", icon: "printer", href: `/bills/${b.id}/print`, newTab: true, hint: "Opens the printable bill in a new tab" },
      ...(live && Number(b.due) > 0 && session.can("payments.collect") ? [{ label: "Collect due", icon: "wallet", href: `/bills/${b.id}?collect=1`, hint: `${rupees(b.due)} still to pay` }] : []),
      ...(live && b.status === "on_hold" && Number(b.due) > 0 && session.can("billing.edit")
        ? [{ label: "Change tests", icon: "edit", href: `/bills/${b.id}?edit=1` }] : []),
      { label: "Patient's details", icon: "user", href: `/patients/${b.patient_id}` },
    ];
  }

  const moreKeys = $derived<(string | string[])[]>([
    ...(dues ? [] : ["status"]), "mode", ["doctor_id", "doctor"], "self_referred", "department_id", ["test_id", "test"],
    ["created_by", "by"], ["min_total", "max_total"], "discount", "report", ...(dues ? [] : ["sort"]),
  ]);
  // The table's own filters (the dates at the top are the page's period, not a table filter).
  const filtered = $derived(moreKeys.flat().some((k) => q.get(k)) || !!(q.get("search") || (!dues && payment)));

  // Dues, grouped by referring doctor and sorted by who owes the most, so whoever's chasing dues can work
  // through doctors most worth calling first (bills without a doctor fall under "Self"). Not paginated like
  // the rest of the list - dues lists are small enough to show in one go, and a doctor's bills shouldn't
  // split across pages.
  interface DoctorDues { name: string; bills: BillSummary[]; total: number }
  const dueGroups = $derived<DoctorDues[]>(
    !dues ? [] : Object.values(
      (data?.items ?? []).reduce<Record<string, DoctorDues>>((acc, b) => {
        const name = b.referring_doctor_name ? nice(b.referring_doctor_name) : "Self";
        (acc[name] ??= { name, bills: [], total: 0 }).bills.push(b);
        acc[name].total += Number(b.due);
        return acc;
      }, {}),
    ).sort((a, b) => b.total - a.total),
  );
  // One doctor at a time, picked from the tab strip - the default is whoever owes the most.
  const activeDoctor = $derived(q.get("doctor_tab") || dueGroups[0]?.name || "");
  const activeGroup = $derived(dueGroups.find((g) => g.name === activeDoctor) ?? dueGroups[0]);

  // The active doctor's bills, revealed a batch at a time as the page scrolls, rather than every row of a
  // long list rendered (and painted) at once. Resets to one batch whenever the doctor tab changes.
  const DUE_BATCH = 50;
  let shown = $state(DUE_BATCH);
  $effect(() => { activeGroup; shown = DUE_BATCH; });
  const visibleBills = $derived(activeGroup?.bills.slice(0, shown) ?? []);
  const hasMore = $derived(shown < (activeGroup?.bills.length ?? 0));
  function moreSentinel(node: HTMLElement) {
    const io = new IntersectionObserver((entries) => { if (entries[0].isIntersecting) shown += DUE_BATCH; }, { rootMargin: "400px" });
    io.observe(node);
    return { destroy: () => io.disconnect() };
  }
</script>

{#snippet billCell(b: BillSummary)}
  <a class="cell-title mono nowrap" href="/bills/{b.id}">{b.invoice_no}</a><div class="cell-sub nowrap">{longDate(b.bill_date)} {timeOf(b.created_at)}</div>
{/snippet}
{#snippet patientCell(b: BillSummary)}
  <div class="cell-title">{b.patient_name}</div><div class="cell-sub tabular">{formatPhone(b.patient_mobile) || "—"}</div>
{/snippet}
{#snippet doctorCell(b: BillSummary)}<span class="text-sm">{b.referring_doctor_name ? nice(b.referring_doctor_name) : "Self"}</span>{/snippet}
{#snippet totalCell(b: BillSummary)}<span class="money">{rupees(b.total)}</span>{/snippet}
{#snippet paidCell(b: BillSummary)}<span class="money">{rupees(b.paid)}</span>{/snippet}
{#snippet dueCell(b: BillSummary)}<span class="money" class:money-due={Number(b.due) > 0}>{rupees(b.due)}</span>{/snippet}
{#snippet payCell(b: BillSummary)}<StatusBadge bill={b} />{/snippet}
{#snippet byCell(b: BillSummary)}<span class="nowrap text-sm" use:tooltip={`Billed ${dateTime(b.created_at)}`}>{b.created_by_name ? nice(b.created_by_name) : "—"}</span>{/snippet}

<PageHeader eyebrow="Front Desk" title={dues ? "Dues" : "Bills"}
            description={dues ? "Bills with money still owed, oldest first. Open one to collect what's due; every instalment is kept." : "Every bill, newest first. Search by patient, mobile or bill number."}>
  {#snippet actions()}
    <DateRange {from} {to} id="bills" anyLabel="All time" compact onchange={setDates} />
  {/snippet}
</PageHeader>

{#if dues}
  <!-- Dues: just the two figures that matter here -->
  <div class="stat-row" aria-live="polite">
    <StatCard label="Total bills with dues" value={cards ? count(cards.total) : "—"} loading={!cards} icon="receipt" note={rangeLabel(from, to)}
              tip="How many bills in these dates still have money owed (the table's search and filters don't change this card)." />
    <StatCard label="Total dues" value={cards ? rupees(cards.sums.due) : "—"} loading={!cards} icon="alert" tone="red" valueClass="money-due"
              tip="Money still owed on the bills in these dates: their totals less what's been paid (refunds add back)." />
  </div>
{:else}
  <!-- Four figures: total bills, total billed amount, collected, dues -->
  <div class="stat-row" aria-live="polite">
    <StatCard label="Total bills" value={cards ? count(cards.total) : "—"} loading={!cards} icon="receipt"
              note={rangeLabel(from, to)} tip="How many bills fall in the dates chosen at the top (the table's search and filters don't change these cards). Cancelled bills are included in this count." />
    <StatCard label="Total billed amount" value={cards ? rupees(cards.sums.billed ?? 0) : "—"} loading={!cards} icon="rupee"
              tip="What the bills in these dates came to, after discounts. Cancelled bills aren't counted." />
    <StatCard label="Collected" value={cards ? rupees(cards.sums.paid) : "—"} loading={!cards} icon="wallet" tone="green"
              tip="What has been paid on the bills in these dates, refunds taken off. Cancelled bills aren't counted." />
    <StatCard label="Dues" value={cards ? rupees(cards.sums.due) : "—"} loading={!cards} icon="alert" tone="red" valueClass="money-due"
              tip="Money still owed on the bills in these dates: their totals less what's been paid (refunds add back). Cancelled bills aren't counted." />
  </div>
{/if}

<section class="card" aria-label={dues ? "Dues" : "Bills"}>
  <FilterBar placeholder="Patient name, mobile or bill number…" searchLabel="Search bills" {moreKeys} noun={dues ? "dues" : "bills"}
             labels={{ from: "Dates", status: "Status", payment: "Payment", due: "Payment", mode: "Paid by", doctor_id: "Referred by",
                       self_referred: "Self-referred", department_id: "Department", test_id: "Test", created_by: "Billed by",
                       min_total: "Bill total", discount: "Discount", report: "Reports" }}
             inlineKeys={dues ? [] : ["payment", "due"]} onclear={() => { doctorText = ""; testText = ""; staffText = ""; }}>
    {#snippet inline()}
      {#if !dues}
        <label class="sr-only" for="bill-payment">Payment</label>
        <select id="bill-payment" class="select" value={payment} onchange={(e) => set({ payment: e.currentTarget.value, due: null })}>
          <option value="">Any payment</option><option value="due">Has dues</option><option value="unpaid">Unpaid</option>
          <option value="part">Part paid</option><option value="paid">Paid in full</option>
        </select>
      {/if}
    {/snippet}
    {#snippet more()}
      {#if !dues}
        <div class="field">
          <label class="label" for="f-status">Bill status</label>
          <select id="f-status" class="select" value={q.get("status") ?? ""} onchange={(e) => set({ status: e.currentTarget.value })}>
            <option value="">Any status</option><option value="confirmed">Confirmed</option><option value="on_hold">On hold</option><option value="cancelled">Cancelled</option>
          </select>
        </div>
      {/if}
      <div class="field">
        <div class="label-row"><label class="label" for="f-mode">Paid by</label><InfoTip about="Paid by" text="Bills with at least one payment taken this way." /></div>
        <select id="f-mode" class="select" value={q.get("mode") ?? ""} onchange={(e) => set({ mode: e.currentTarget.value })}>
          <option value="">Any way</option>{#each PAYMENT_MODES as [v, l] (v)}<option value={v}>{l}</option>{/each}
        </select>
      </div>
      <div class="field span-all">
        {#if q.get("doctor_id")}
          <span class="label">Referred by</span>
          <div class="chip"><Icon name="stethoscope" size="sm" /><span class="grow truncate">{q.get("doctor") || "Chosen doctor"}</span>
            <button type="button" class="btn btn-ghost btn-icon btn-sm" aria-label="Remove the doctor filter" use:tooltip={"Remove this filter"} onclick={() => { doctorText = ""; set({ doctor_id: null, doctor: null }); }}><Icon name="x" size="sm" /></button></div>
        {:else}
          <Combobox id="f-doctor" label="Referred by" placeholder="Search doctors…" icon="stethoscope" searchPage={searchDoctors} bind:value={doctorText}
                    onpick={(d) => set({ doctor_id: d.id, doctor: d.name, self_referred: null })}>
            {#snippet option(d)}<span class="font-semibold">{d.name}</span>{#if d.qualification} <span class="text-xs text-muted">{d.qualification}</span>{/if}{/snippet}
          </Combobox>
        {/if}
        <label class="check-row"><input class="checkbox" type="checkbox" checked={q.get("self_referred") === "true"}
               onchange={(e) => set({ self_referred: e.currentTarget.checked ? "true" : null, doctor_id: null, doctor: null })} /> Only self-referred (no doctor)</label>
      </div>
      <div class="field">
        <label class="label" for="f-dept">Department</label>
        <select id="f-dept" class="select" value={q.get("department_id") ?? ""} onchange={(e) => set({ department_id: e.currentTarget.value })}>
          <option value="">Any department</option>{#each departments as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
        </select>
      </div>
      <div class="field">
        {#if q.get("test_id")}
          <span class="label">Test</span>
          <div class="chip"><Icon name="flask" size="sm" /><span class="grow truncate">{q.get("test") || "Chosen test"}</span>
            <button type="button" class="btn btn-ghost btn-icon btn-sm" aria-label="Remove the test filter" use:tooltip={"Remove this filter"} onclick={() => { testText = ""; set({ test_id: null, test: null }); }}><Icon name="x" size="sm" /></button></div>
        {:else}
          <Combobox id="f-test" label="Test" placeholder="Search tests…" icon="flask" searchPage={searchTests} bind:value={testText}
                    onpick={(t) => set({ test_id: t.id, test: t.name })}>
            {#snippet option(t)}<span class="font-semibold">{t.name}</span> <span class="text-xs text-muted">{t.department.name}</span>{/snippet}
          </Combobox>
        {/if}
      </div>
      {#if canSeeStaff}
        <div class="field">
          {#if q.get("created_by")}
            <span class="label">Billed by</span>
            <div class="chip"><Icon name="user" size="sm" /><span class="grow truncate">{q.get("by") || "Chosen person"}</span>
              <button type="button" class="btn btn-ghost btn-icon btn-sm" aria-label="Remove the billed-by filter" use:tooltip={"Remove this filter"} onclick={() => { staffText = ""; set({ created_by: null, by: null }); }}><Icon name="x" size="sm" /></button></div>
          {:else}
            <Combobox id="f-staff" label="Billed by" placeholder="Search staff…" icon="user" searchPage={searchStaff} bind:value={staffText}
                      onpick={(s) => set({ created_by: s.id, by: s.full_name })}>
              {#snippet option(s)}<span class="font-semibold">{s.full_name}</span> <span class="text-xs text-muted">{s.email}</span>{/snippet}
            </Combobox>
          {/if}
        </div>
      {/if}
      <div class="field">
        <div class="label-row"><label class="label" for="f-report">Reports</label><InfoTip about="Reports" text="Pending: a test's report isn't ready yet. Ready: a report is waiting to be handed over. Delivered: every report on the bill has been given to the patient." /></div>
        <select id="f-report" class="select" value={q.get("report") ?? ""} onchange={(e) => set({ report: e.currentTarget.value })}>
          <option value="">Any</option><option value="pending">Pending</option><option value="ready">Ready to collect</option><option value="delivered">All delivered</option>
        </select>
      </div>
      <div class="field">
        <label class="label" for="f-discount">Discount</label>
        <select id="f-discount" class="select" value={q.get("discount") ?? ""} onchange={(e) => set({ discount: e.currentTarget.value })}>
          <option value="">With or without</option><option value="yes">Discount given</option><option value="no">No discount</option>
        </select>
      </div>
      <fieldset class="field span-all range">
        <legend class="label range-legend">Bill total (₹) <InfoTip about="Bill total" text="The bill's total after discount. Leave either box empty for no limit." /></legend>
        <div class="range-row">
          <label class="sr-only" for="f-min">At least</label>
          <input id="f-min" class="input money" type="number" min="0" step="1" inputmode="decimal" placeholder="Min" value={q.get("min_total") ?? ""}
                 onchange={(e) => set({ min_total: e.currentTarget.value })} />
          <span class="text-muted" aria-hidden="true">to</span>
          <label class="sr-only" for="f-max">At most</label>
          <input id="f-max" class="input money" type="number" min="0" step="1" inputmode="decimal" placeholder="Max" value={q.get("max_total") ?? ""}
                 onchange={(e) => set({ max_total: e.currentTarget.value })} />
        </div>
        {#if rangeProblem}<p class="field-error" role="alert"><Icon name="alert" size="sm" />{rangeProblem}</p>{/if}
      </fieldset>
      {#if !dues}
        <div class="field">
          <label class="label" for="f-sort">Order</label>
          <select id="f-sort" class="select" value={sort} onchange={(e) => set({ sort: e.currentTarget.value === "newest" ? null : e.currentTarget.value })}>
            <option value="newest">Newest first</option><option value="oldest">Oldest first</option>
          </select>
        </div>
      {/if}
    {/snippet}
    {#snippet actions()}
      <ExportMenu path="/api/exports/bills" kind="bills" query={filters} disabled={!data || data.total === 0}
                  workbook={{ path: "/api/exports/bills-by-doctor.xlsx", query: filters,
                              label: "Workbook by referring doctor (.xlsx)",
                              about: "A summary sheet, then one sheet per referring doctor with their bills and totals. Same filters." }} />
    {/snippet}
  </FilterBar>

  {#if dues}
    {#if loading && !data}
      <div class="empty" aria-busy="true">Loading…</div>
    {:else if loadError}
      <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{loadError} <button class="link-button" onclick={() => reload++}>Try again</button></div></div>
    {:else if !dueGroups.length}
      <div class="empty"><Icon name="wallet" />
        <p>{filtered ? "No bills match these filters." : "No dues. Everything is paid."}</p>
        {#if filtered}<p class="text-sm text-muted">Try a longer date range, or clear the filters.</p>{/if}
      </div>
    {:else}
      <!-- One doctor's bills on screen at a time, picked from the tabs; most owed first. -->
      <div class="tabs due-tabs" role="tablist" aria-label="Which doctor">
        {#each dueGroups as g (g.name)}
          <button class="tab" role="tab" aria-selected={g.name === activeGroup?.name}
                  onclick={() => set({ doctor_tab: g.name === dueGroups[0].name ? null : g.name })}>
            {g.name}
          </button>
        {/each}
      </div>
      {#if activeGroup}
        <table class="table due-group-table">
          <thead><tr><th>Bill</th><th>Patient</th><th class="r">Total</th><th class="r">Paid</th><th class="r">Due</th><th>Payment</th><th class="due-group-actions"></th></tr></thead>
          <tbody>
            {#each visibleBills as b (b.id)}
              <tr class="is-clickable" onclick={() => navigate(`/bills/${b.id}`)}>
                <td>{@render billCell(b)}</td>
                <td>{@render patientCell(b)}</td>
                <td class="r">{@render totalCell(b)}</td>
                <td class="r">{@render paidCell(b)}</td>
                <td class="r">{@render dueCell(b)}</td>
                <td>{@render payCell(b)}</td>
                <td class="due-group-actions" onclick={(e) => e.stopPropagation()}>
                  {#if b.status !== "cancelled" && Number(b.due) > 0 && session.can("payments.collect")}
                    <a class="btn btn-outline btn-sm" href="/bills/{b.id}?collect=1" use:tooltip={`${rupees(b.due)} still to pay`}>
                      <Icon name="wallet" size="sm" /> Collect
                    </a>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        {#if hasMore}<div class="due-more" use:moreSentinel aria-hidden="true">Loading more…</div>{/if}
      {/if}
    {/if}
  {:else}
    <DataTable label="Bills" rows={data?.items ?? []} loading={loading} error={loadError} onretry={() => reload++}
               rowHref={(b) => `/bills/${b.id}`} actions={actionsFor} actionsLabel={(b) => `Actions for ${b.invoice_no}`} page={data}
               empty={{ icon: "receipt", title: filtered ? "No bills match these filters." : "No bills yet.",
                        text: filtered ? "Try a longer date range, or clear the filters." : "" }}
               columns={[
                 { key: "bill", label: "Bill ID", cell: billCell, mobile: "sub" },
                 { key: "patient", label: "Patient", cell: patientCell, mobile: "title" },
                 { key: "doctor", label: "Referred by", cell: doctorCell, optional: true },
                 { key: "total", label: "Total", cell: totalCell, align: "right", tip: "After discount." },
                 { key: "paid", label: "Paid", cell: paidCell, align: "right", optional: true, mobile: "hide", tip: "Payments taken, less any refunds." },
                 { key: "due", label: "Due", cell: dueCell, align: "right", tip: "Total less what's been paid: still to collect." },
                 { key: "pay", label: "Payment", cell: payCell, mobile: "end" },
                 { key: "by", label: "Billed by", cell: byCell, optional: true, mobile: "hide" },
               ]} />
  {/if}
</section>

<style src="./styles/Bills.css"></style>
