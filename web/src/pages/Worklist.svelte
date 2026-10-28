<script lang="ts">
  import { FEATURES } from "../lib/features";
  import DateRange from "../components/DateRange.svelte";
  import Icon from "../components/Icon.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import Pagination from "../components/Pagination.svelte";
  import { get, post } from "../lib/api";
  import { confirmDialog } from "../lib/confirm.svelte";
  import { date, dateTime, rupees } from "../lib/format";
  import { router, setQuery } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { tooltip } from "../lib/tooltip";
  import { notify, notifyError } from "../lib/toast.svelte";
  import { area } from "../lib/area.svelte";
  import InfoTip from "../components/InfoTip.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import { LINE_STATUS } from "../lib/bill-types";
  import type { Department, ItemStatus, Page, WorklistRow } from "../lib/types";

  // A department's own screen: its tests as they move along, Pending -> In progress -> Ready -> Delivered.
  // In a department's work area the department is fixed; in Admin (or a server without work areas) any can be chosen.
  const TABS = [
    { key: "pending", label: "Pending", status: "billed" },
    { key: "progress", label: "In progress", status: "scanned" },
    { key: "ready", label: "Ready", status: "reported" },
    { key: "delivered", label: "Delivered", status: "delivered" },
  ] as const;
  const TAB_TIP = "Pending: billed, not started. In progress: started (being done or scanned). Ready: the report is ready to hand over. Delivered: handed over to the patient.";

  /** Words for a status, as on the bill page. */
  const statusWord = (s: ItemStatus) => (LINE_STATUS[s]?.[1] ?? s).toLowerCase();

  // The server shows the last 7 days (Indian time) when no dates are given; the inputs show the same.
  const istToday = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  const weekAgo = (() => { const d = new Date(`${istToday}T12:00:00Z`); d.setUTCDate(d.getUTCDate() - 6); return d.toISOString().slice(0, 10); })();

  const SIZE = $derived(Math.min(100, Number(router.query.get("size")) || 50));
  const tab = $derived(TABS.find((t) => t.key === router.query.get("tab")) ?? TABS[0]);
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const search = $derived(router.query.get("search") ?? "");
  /** The department of the work area they're in, when it's a department (fixed: no filter). */
  const fixed = $derived(area.current?.kind === "department" ? area.current : null);
  const department = $derived(fixed?.department_id ?? router.query.get("department") ?? "");
  // A bill opens at Reception; in a department or Admin the bill number is shown without a link.
  const billLinks = $derived(!area.inUse || !area.current || area.current.kind === "reception");
  const from = $derived(router.query.get("from") ?? "");
  const to = $derived(router.query.get("to") ?? "");
  const canUpdate = $derived(session.can("worklist.update") || session.can("reports.deliver"));

  let data = $state<Page<WorklistRow> | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);
  let departments = $state<Department[]>([]);
  let searchText = $state(router.query.get("search") ?? "");
  let busy = $state<string | null>(null);

  $effect(() => {
    const ctrl = new AbortController();
    // status repeats (?status=billed&status=scanned), so the address is built here rather than from a query object.
    const qs = new URLSearchParams();
    qs.append("status", tab.status);
    const extra: Record<string, string | number> = { page, size: SIZE, search, department_id: department, from, to };
    for (const [k, v] of Object.entries(extra)) if (v !== "") qs.set(k, String(v));
    reload;
    loading = true;
    get<Page<WorklistRow>>(`/api/worklist?${qs}`, undefined, ctrl.signal)
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  $effect(() => {
    if (fixed) return;
    get<Department[]>("/api/departments").then((d) => (departments = d)).catch((e) => notifyError(e));
  });

  let searchTimer: ReturnType<typeof setTimeout>;
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setQuery({ search: searchText.trim(), page: null }), 300);
  }

  function setDate(key: "from" | "to", value: string) {
    // Changing one end fixes the other at what's shown, so the range doesn't jump back to the default.
    const other = key === "from" ? { to: to || istToday } : { from: from || weekAgo };
    setQuery({ [key]: value, ...other, page: null });
  }

  const canReport = $derived(session.can("reports.write") || session.can("reports.sign"));

  /** Opens the test's first study in the viewer (a tab opened at the click, so it isn't blocked as a pop-up). */
  async function viewImages(r: WorklistRow) {
    const tab = window.open("about:blank", "_blank");
    try {
      const studies = await get<{ viewer_url: string }[]>(`/api/imaging/items/${r.item_id}/studies`);
      if (!studies.length) {
        tab?.close();
        notify(`No images have been uploaded for ${r.test_name} yet. Add them on the report page.`, { kind: "info" });
        return;
      }
      if (tab) tab.location.href = studies[0].viewer_url;
    } catch (e) {
      tab?.close();
      notifyError(e, { title: "Couldn't open the images" });
    }
  }

  const hasDue = (r: WorklistRow) => Number(r.due) > 0;
  /** One step back along the tabs. */
  const undoTarget = (r: WorklistRow): ItemStatus | null =>
    r.status === "scanned" ? "billed" : r.status === "reported" ? "scanned" : r.status === "delivered" ? "reported" : null;

  async function setStatus(r: WorklistRow, status: ItemStatus, message: string) {
    busy = r.item_id;
    try {
      await post(`/api/worklist/${r.item_id}/status`, { status });
      notify(message);
      reload++;
    } catch (e) {
      notifyError(e, { title: "Couldn't update the test" });
    } finally {
      busy = null;
    }
  }

  async function markDelivered(r: WorklistRow) {
    if (hasDue(r) && !(await confirmDialog({
      title: `${rupees(r.due)} is still due`,
      message: `Bill ${r.invoice_no} for ${r.patient_name} hasn't been fully paid. Hand over ${r.test_name} anyway?`,
      confirmLabel: "Hand over anyway", tone: "danger",
    }))) return;
    await setStatus(r, "delivered", `${r.test_name} for ${r.patient_name} marked delivered.`);
  }

  async function undo(r: WorklistRow) {
    const target = undoTarget(r);
    if (!target) return;
    await setStatus(r, target, `${r.test_name} for ${r.patient_name} moved back to ${statusWord(target)}.`);
  }
</script>

<PageHeader eyebrow={fixed ? "Department" : "Lab"} title={fixed ? `${fixed.name} worklist` : "Worklist"}
            description={fixed ? `The tests billed for ${fixed.name}. Start each one, mark it ready, then hand it over.`
                               : "Every department's tests as they move along: start each one, mark it ready, then hand it over."} />

<section class="card">
  <div class="row wl-tabs">
    <div class="tabs grow" role="tablist" aria-label="Which tests">
      {#each TABS as t (t.key)}
        <button class="tab" role="tab" aria-selected={tab.key === t.key} onclick={() => setQuery({ tab: t.key === "pending" ? null : t.key, page: null })}>{t.label}</button>
      {/each}
    </div>
    <InfoTip text={TAB_TIP} about="the tabs" />
  </div>

  <div class="toolbar">
    <div class="input-group">
      <Icon name="search" />
      <label class="sr-only" for="search">Search the worklist</label>
      <input id="search" class="input" type="search" placeholder="Search by patient, bill number or accession number…" bind:value={searchText} oninput={onSearch} />
    </div>
    {#if !fixed}
      <label class="sr-only" for="department">Department</label>
      <select id="department" class="select" value={department} onchange={(e) => setQuery({ department: e.currentTarget.value, page: null })}>
        <option value="">All departments</option>
        {#each departments as d (d.id)}<option value={d.id}>{d.name}{d.is_active ? "" : " (switched off)"}</option>{/each}
      </select>
    {/if}
    <DateRange id="worklist" from={from || weekAgo} to={to || istToday}
               onchange={(f, t) => setQuery({ from: f || null, to: t || null, page: null })} />
  </div>

  {#if loadError}
    <div class="card-content"><div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{loadError} <button class="link-button" onclick={() => reload++}>Try again</button></div></div></div>
  {:else if data}
    <div class="table-wrap" aria-busy={loading}>
      <table class="table">
        <thead><tr><th>Bill</th><th>Patient</th><th>Test</th><th>Status</th><th class="num">Due</th>{#if canUpdate}<th><span class="sr-only">Actions</span></th>{/if}</tr></thead>
        <tbody>
          {#each data.items as r (r.item_id)}
            <tr>
              <td><div class="cell-title mono">{#if billLinks}<a href="/bills/{r.invoice_id}">{r.invoice_no}</a>{:else}{r.invoice_no}{/if}</div><div class="cell-sub">{date(r.bill_date)}</div></td>
              <td><div class="cell-title">{r.patient_name}</div><div class="cell-sub">{[r.patient_age, r.patient_gender].filter(Boolean).join(" · ")}</div></td>
              <td><div class="cell-title">{r.test_name}</div>
                <div class="cell-sub">{r.department_name}{#if r.accession_no} · <span class="mono">{r.accession_no}</span>{/if}</div>
                <div class="row-wrap" style="gap: 10px; margin-top: 2px">
                  {#if FEATURES.testReports && (canReport || r.status === "reported")}
                    <a class="link-button text-sm" href="/test-reports/{r.item_id}" aria-label="{canReport ? 'Write report' : 'Report'} for {r.test_name}, {r.patient_name}">
                      <Icon name="clipboard" size="sm" /> {canReport && r.status !== "reported" && r.status !== "delivered" ? "Write report" : "Report"}</a>
                  {/if}
                  {#if FEATURES.testReports && r.is_imaging && r.status !== "billed"}
                    <button class="link-button text-sm" type="button" aria-label="View images for {r.test_name}, {r.patient_name}"
                            use:tooltip={"Opens the image viewer in a new tab"} onclick={() => viewImages(r)}><Icon name="eye" size="sm" /> View images</button>
                  {/if}
                </div></td>
              <td><StatusBadge line={r.status} help={r.status_changed_at ? `Since ${dateTime(r.status_changed_at)}` : ""} /></td>
              <td class="num">
                {#if hasDue(r)}<div class="row justify-end gap-sm"><span class="badge badge-destructive badge-plain">Due</span><span class="money money-due">{rupees(r.due)}</span></div>
                {:else}<span class="money text-muted">{rupees(r.due)}</span>{/if}
              </td>
              {#if canUpdate}
                <td class="num">
                  <div class="row justify-end gap-sm nowrap">
                    {#if r.status === "billed"}
                      <button class="btn btn-outline btn-sm" disabled={busy === r.item_id} aria-label="Start {r.test_name} for {r.patient_name}"
                              use:tooltip={"Moves it to In progress"}
                              onclick={() => setStatus(r, "scanned", `${r.test_name} for ${r.patient_name} is in progress.`)}><Icon name="play" size="sm" /> Start</button>
                    {/if}
                    {#if r.status === "billed" || r.status === "scanned"}
                      <button class="btn btn-outline btn-sm" disabled={busy === r.item_id} aria-label="Mark {r.test_name} for {r.patient_name} ready"
                              use:tooltip={"The report is ready to hand over"}
                              onclick={() => setStatus(r, "reported", `${r.test_name} for ${r.patient_name} is ready.`)}><Icon name="fileText" size="sm" /> Ready</button>
                    {/if}
                    {#if r.status === "billed" || r.status === "scanned" || r.status === "reported"}
                      <button class="btn btn-outline btn-sm" disabled={busy === r.item_id} aria-label="Mark {r.test_name} for {r.patient_name} delivered"
                              use:tooltip={"Handed over to the patient"}
                              onclick={() => markDelivered(r)}><Icon name="check" size="sm" /> Delivered</button>
                    {/if}
                    {#if undoTarget(r)}
                      <button class="btn btn-ghost btn-sm" disabled={busy === r.item_id} aria-label="Undo the last step for {r.test_name} for {r.patient_name}"
                              onclick={() => undo(r)}><Icon name="refresh" size="sm" /> Undo</button>
                    {/if}
                  </div>
                </td>
              {/if}
            </tr>
          {:else}
            <tr><td colspan={canUpdate ? 6 : 5}><div class="empty"><Icon name="clipboard" />{search || (department && !fixed) ? "No tests match these filters." : `No ${tab.label.toLowerCase()} tests for these dates.`}</div></td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if data.total > 0}<Pagination page={data.page} size={data.size} total={data.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />{/if}
  {:else}
    <div class="empty" aria-busy="true">Loading…</div>
  {/if}
</section>

<style>
  .wl-tabs { gap: 4px; align-items: center; padding-right: 12px; }
  .wl-tabs .tabs { min-width: 0; }
</style>
