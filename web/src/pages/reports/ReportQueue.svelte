<script lang="ts">
  import DataTable, { type Column } from "../../components/DataTable.svelte";
  import DateRange from "../../components/DateRange.svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import type { RowAction } from "../../components/RowMenu.svelte";
  import { get } from "../../lib/api";
  import { thisMonth } from "../../lib/dates";
  import { date, dateTime } from "../../lib/format";
  import { REPORT_STATUS, type ReportRow } from "../../lib/report-types";
  import { router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { notifyError } from "../../lib/toast.svelte";
  import type { Department, Page } from "../../lib/types";
  import SendWhatsApp from "./SendWhatsApp.svelte";

  // The reporting worklist: tests waiting for a report, drafts (and reports ready to sign), signed reports.
  const writer = $derived(session.can("reports.write") || session.can("reports.sign"));
  const TABS = [
    { key: "pending", label: "To report" },
    { key: "draft", label: "Drafts" },
    { key: "signed", label: "Signed" },
  ] as const;

  const tab = $derived(writer ? (TABS.find((t) => t.key === router.query.get("tab")) ?? TABS[0]) : TABS[2]);
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const search = $derived(router.query.get("search") ?? "");
  const department = $derived(router.query.get("department") ?? "");
  // Nothing in the address = this month (the default everywhere); ?from=all = any bill date.
  const month = thisMonth();
  const allPicked = $derived(router.query.get("from") === "all");
  const from = $derived(allPicked ? "" : router.query.get("from") ?? month.from);
  const to = $derived(allPicked ? "" : router.query.get("to") ?? (router.query.has("from") ? "" : month.to));

  let data = $state<Page<ReportRow> | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);
  let departments = $state<Department[]>([]);
  let searchText = $state(router.query.get("search") ?? "");

  $effect(() => {
    const ctrl = new AbortController();
    reload;
    loading = true;
    get<Page<ReportRow>>("/api/test-reports", { status: tab.key, page, size: 50, search, department_id: department, from, to }, ctrl.signal)
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });
  $effect(() => { get<Department[]>("/api/departments").then((d) => (departments = d)).catch((e) => notifyError(e)); });

  let timer: ReturnType<typeof setTimeout>;
  const onSearch = () => { clearTimeout(timer); timer = setTimeout(() => setQuery({ search: searchText.trim(), page: null }), 300); };

  let sendFor = $state<ReportRow | null>(null);
  let sendOpen = $state(false);

  function actions(r: ReportRow): RowAction[] {
    const out: RowAction[] = [{ label: r.report_id ? "Open report" : writer ? "Write report" : "Open", icon: r.report_id ? "eye" : "edit", href: `/test-reports/${r.item_id}` }];
    if (r.report_id && (r.report_status === "signed" || r.report_status === "amended" || writer))
      out.push({ label: "Print", icon: "printer", href: `/test-reports/${r.item_id}/print`, newTab: true });
    if (r.study_uid) out.push({ label: "View images", icon: "scan", href: `/viewer/viewer?StudyInstanceUIDs=${encodeURIComponent(r.study_uid)}`, newTab: true });
    if (r.report_id && (r.report_status === "signed" || r.report_status === "amended") && session.can("reports.write"))
      out.push({ label: "Send on WhatsApp", icon: "inbox", onclick: () => { sendFor = r; sendOpen = true; } });
    out.push({ label: "Open bill", icon: "receipt", href: `/bills/${r.invoice_id}` });
    return out;
  }
</script>

<PageHeader eyebrow="Reports" title="Reports to write" description="Tests waiting for a report, drafts to finish and sign, and signed reports to print or send.">
  {#snippet actions()}{#if writer}<a class="btn btn-outline" href="/test-reports"><Icon name="activity" /> Reporting dashboard</a>{/if}{/snippet}
</PageHeader>

<section class="card">
  {#if writer}
    <div class="tabs" role="tablist" aria-label="Which reports">
      {#each TABS as t (t.key)}
        <button class="tab" role="tab" aria-selected={tab.key === t.key} onclick={() => setQuery({ tab: t.key === "pending" ? null : t.key, page: null })}>{t.label}</button>
      {/each}
    </div>
  {/if}
  <div class="toolbar">
    <div class="input-group">
      <Icon name="search" />
      <label class="sr-only" for="rq-search">Search reports</label>
      <input id="rq-search" class="input" type="search" placeholder="Search by patient, test, bill or accession number…" bind:value={searchText} oninput={onSearch} />
    </div>
    <label class="sr-only" for="rq-dept">Department</label>
    <select id="rq-dept" class="select" value={department} onchange={(e) => setQuery({ department: e.currentTarget.value, page: null })}>
      <option value="">All departments</option>
      {#each departments as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
    </select>
    <DateRange id="rq" {from} {to} anyLabel="Any bill date"
               onchange={(f, t) => setQuery(!f && !t ? { from: "all", to: null, page: null } : f === month.from && t === month.to ? { from: null, to: null, page: null } : { from: f, to: t, page: null })} />
  </div>

  <DataTable label="Reports" rows={data?.items ?? []} {loading} error={loadError} onretry={() => reload++} page={data}
             actions={actions} actionsLabel={(r) => `Actions for ${r.test_name}, ${r.patient_name}`}
             empty={{ icon: "clipboard",
                      title: search || department ? "No reports match these filters." : tab.key === "pending" ? "Nothing is waiting for a report." : "Nothing here yet.",
                      text: search || department ? "Try a longer date range, or clear the filters." : "" }}
             columns={[
               { key: "bill", label: "Bill", cell: billCell, mobile: "sub" },
               { key: "patient", label: "Patient", cell: patientCell, mobile: "title" },
               { key: "test", label: "Test", cell: testCell },
               { key: "report", label: "Report", cell: reportCell, mobile: "field" },
               { key: "images", label: "Images", cell: imagesCell, align: "right", optional: true, mobile: "hide" },
             ] satisfies Column<ReportRow>[]} />
</section>

{#snippet billCell(r: ReportRow)}<span class="cell-title mono">{r.invoice_no}</span><div class="cell-sub">{date(r.bill_date)}</div>{/snippet}
{#snippet patientCell(r: ReportRow)}<div class="cell-title">{r.patient_name}</div><div class="cell-sub">{[r.patient_age, r.patient_gender].filter(Boolean).join(" · ")}</div>{/snippet}
{#snippet testCell(r: ReportRow)}
  <div class="cell-title"><a href="/test-reports/{r.item_id}">{r.test_name}</a></div>
  <div class="cell-sub">{r.department_name}{#if r.accession_no} · <span class="mono">{r.accession_no}</span>{/if}</div>
{/snippet}
{#snippet reportCell(r: ReportRow)}
  {#if r.report_status}
    <span class="badge {REPORT_STATUS[r.report_status][0]}">{REPORT_STATUS[r.report_status][1]}</span>
    <div class="cell-sub">{r.report_status === "signed" || r.report_status === "amended" ? `${r.signer_name || "—"} · ${dateTime(r.signed_at)}` : `${r.reported_by_name || "—"} · ${dateTime(r.updated_at)}`}</div>
  {:else}
    <span class="badge badge-plain">Not started</span>
  {/if}
{/snippet}
{#snippet imagesCell(r: ReportRow)}{r.is_imaging ? (r.study_count ? `${r.study_count} stud${r.study_count === 1 ? "y" : "ies"}` : "None yet") : "—"}{/snippet}

{#if sendFor?.report_id}
  {#key sendFor.report_id}<SendWhatsApp reportId={sendFor.report_id} patientName={sendFor.patient_name} button={false} bind:open={sendOpen} />{/key}
{/if}
