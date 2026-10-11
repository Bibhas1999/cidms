<script lang="ts">
  import BarChart from "../../components/charts/BarChart.svelte";
  import ChartCard from "../../components/charts/ChartCard.svelte";
  import KpiCard from "../../components/charts/KpiCard.svelte";
  import LineChart from "../../components/charts/LineChart.svelte";
  import DateRange from "../../components/DateRange.svelte";
  import Icon from "../../components/Icon.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import { get } from "../../lib/api";
  import { exact, full } from "../../lib/chart";
  import { rangeLabel, thisYear } from "../../lib/dates";
  import { count, dateTime } from "../../lib/format";
  import { REPORT_STATUS, type ReportStatus } from "../../lib/report-types";
  import { router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";

  // The reporting dashboard, for doctors and reporting staff: the work in hand now, and what was signed in the
  // period with how long it took. Counts and times only (no money). The list of everything is /test-reports/queue.

  interface Row {
    item_id: string; invoice_no: string; bill_date: string; patient_name: string; test_name: string; department_name: string;
    is_imaging: boolean; report_status: ReportStatus | null; reported_by_name: string; signer_name: string; signed_at: string | null;
    updated_at: string | null; age_hours?: number; target_hours?: number; state?: "on_time" | "due_soon" | "overdue";
  }
  interface Summary {
    trend_unit: "day" | "month";
    target_hours: { imaging: number; other: number };
    kpis: { waiting: number; drafts: number; ready_to_sign: number; signed: number; amended: number; overdue: number;
            avg_turnaround_hours: number | null; p90_turnaround_hours: number | null; sent_whatsapp: number; link_views: number };
    trend: { day: string; signed: number; avg_hours: number | null }[];
    by_department: { name: string; count: number; avg_hours: number | null }[];
    by_modality: { name: string; count: number }[];
    by_doctor: { name: string; count: number; avg_hours: number | null }[];
    images: { day: string; studies: number; images: number }[];
    oldest_waiting: Row[]; recently_signed: Row[]; my_drafts: Row[]; awaiting_my_signature: Row[];
  }

  // One period for the page (?from=&to=): nothing = this year; ?from=all = all time.
  const year = thisYear();
  const allPicked = $derived(router.query.get("from") === "all");
  const from = $derived(allPicked ? "" : router.query.get("from") ?? year.from);
  const to = $derived(allPicked ? "" : router.query.get("to") ?? (router.query.has("from") ? "" : year.to));
  const label = $derived(rangeLabel(from, to));
  const setRange = (f: string, t: string) =>
    setQuery(!f && !t ? { from: "all", to: null } : f === year.from && t === year.to ? { from: null, to: null } : { from: f, to: t });

  let data = $state<Summary | null>(null);
  let failed = $state("");
  $effect(() => {
    const ctrl = new AbortController();
    failed = "";
    get<Summary>("/api/test-reports/summary", { from: from || undefined, to: to || undefined }, ctrl.signal)
      .then((d) => (data = d))
      .catch((e) => { if (e.name !== "AbortError") failed = e.message; });
    return () => ctrl.abort();
  });

  const hours = (h: number | null | undefined) => (h === null || h === undefined ? "—" : exact(h, "hours"));
  const AGE: Record<string, [string, string]> = { on_time: ["badge-success", "On time"], due_soon: ["badge-warning", "Due soon"], overdue: ["badge-destructive", "Overdue"] };
  const unit = $derived(data?.trend_unit ?? "day");
  const per = $derived(unit === "month" ? "Per month" : "Per day");
  const keys = $derived(data?.trend.map((p) => p.day) ?? []);
  const imageKeys = $derived(data?.images.map((p) => p.day) ?? []);
  const canSign = $derived(session.can("reports.sign"));
</script>

<PageHeader eyebrow="Reports" title="Reporting" description="Tests waiting for a report, drafts, and how quickly reports are signed.">
  {#snippet actions()}
    <DateRange id="rep-dash" {from} {to} anyLabel="All time" compact onchange={setRange} />
    <a class="btn btn-primary" href="/test-reports/queue"><Icon name="clipboard" /> Reports to write</a>
  {/snippet}
</PageHeader>

{#if failed}
  <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div><div class="alert-title">Couldn't load the figures</div>{failed}</div></div>
{/if}

<div class="grid-4">
  <KpiCard icon="clipboard" href="/test-reports/queue" label="Waiting to report" loading={!data} value={data ? count(data.kpis.waiting) : ""}
           tip="Tests on live bills (billed or scanned) that don't have a signed report yet, whatever their date."
           note={data ? `${count(data.kpis.overdue)} overdue` : ""} tone={data && data.kpis.overdue ? "orange" : ""} />
  <KpiCard icon="edit" href="/test-reports/queue?tab=draft" label="Drafts" loading={!data} value={data ? count(data.kpis.drafts) : ""}
           tip="Reports started but not yet marked ready to sign. Right now, any date." />
  <KpiCard icon="lock" href="/test-reports/queue?tab=draft" label="Ready to sign" loading={!data} value={data ? count(data.kpis.ready_to_sign) : ""}
           tip="Reports marked ready and waiting for a doctor's signature. Right now, any date." />
  <KpiCard icon="alert" tone="orange" label="Overdue" loading={!data} value={data ? count(data.kpis.overdue) : ""}
           tip={data ? `Waiting longer than the target since the bill was made: ${data.target_hours.imaging} hours for scans, ${data.target_hours.other} hours for other tests.` : "Waiting longer than the target."} />
  <KpiCard icon="check" tone="green" label="Signed · {label}" loading={!data} value={data ? count(data.kpis.signed) : ""}
           tip="Reports signed for the first time in the period (amendments aren't counted again)." note={data ? `${count(data.kpis.amended)} amended` : ""} />
  <KpiCard icon="clock" label="Average turnaround" loading={!data} value={data ? hours(data.kpis.avg_turnaround_hours) : ""}
           tip="From when the bill was made to when the report was first signed, averaged over the reports signed in the period." />
  <KpiCard icon="clock" label="90% within" loading={!data} value={data ? hours(data.kpis.p90_turnaround_hours) : ""}
           tip="Nine out of ten reports signed in the period were signed within this time of billing (the 90th percentile turnaround)." />
  <KpiCard icon="inbox" label="Sent to patients" loading={!data} value={data ? count(data.kpis.sent_whatsapp) : ""}
           tip="Reports sent on WhatsApp in the period (failed sends left out). The note counts views of the patient link (the QR code)."
           note={data ? `${count(data.kpis.link_views)} link views` : ""} />
</div>

{#snippet rows(list: Row[], empty: string, kind: "age" | "status" | "signed")}
  {#if list.length}
    <ul class="worklist">
      {#each list as r (r.item_id)}
        <li>
          <a href="/test-reports/{r.item_id}">
            <span class="grow"><span class="cell-title">{r.patient_name}</span><span class="cell-sub">{r.test_name} · <span class="mono">{r.invoice_no}</span></span></span>
            {#if kind === "age" && r.state}
              <span class="badge {AGE[r.state][0]}">{AGE[r.state][1]} · {hours(r.age_hours)}</span>
            {:else if kind === "signed"}
              <span class="cell-sub nowrap">{r.signer_name || "—"} · {dateTime(r.signed_at)}</span>
            {:else if r.report_status}
              <span class="badge {REPORT_STATUS[r.report_status][0]}">{REPORT_STATUS[r.report_status][1]}</span>
            {/if}
          </a>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="text-sm text-muted">{empty}</p>
  {/if}
{/snippet}

<div class="grid-3 items-start">
  <section class="card" aria-labelledby="mine-title">
    <div class="card-header"><h2 class="card-title" id="mine-title">My work<InfoTip about="My work" text="Drafts you started and haven't finished, and (if you sign reports) reports marked ready to sign." /></h2></div>
    <div class="card-content stack">
      {#if !data}<p class="text-sm text-muted" aria-busy="true">Loading…</p>{:else}
        <div><h3 class="sub">My drafts</h3>{@render rows(data.my_drafts, "No drafts.", "status")}</div>
        {#if canSign}<div><h3 class="sub">Waiting for a signature</h3>{@render rows(data.awaiting_my_signature, "Nothing to sign.", "status")}</div>{/if}
      {/if}
    </div>
  </section>
  <section class="card" aria-labelledby="oldest-title">
    <div class="card-header"><h2 class="card-title" id="oldest-title">Oldest waiting<InfoTip about="Oldest waiting" text="The ten tests that have waited longest for a signed report. Due soon = past three quarters of the target time." /></h2>
      <a class="btn btn-ghost btn-sm" href="/test-reports/queue">All</a></div>
    <div class="card-content">{#if data}{@render rows(data.oldest_waiting, "Nothing is waiting.", "age")}{:else}<p class="text-sm text-muted" aria-busy="true">Loading…</p>{/if}</div>
  </section>
  <section class="card" aria-labelledby="recent-title">
    <div class="card-header"><h2 class="card-title" id="recent-title">Recently signed<InfoTip about="Recently signed" text="The last ten reports signed or amended, any date." /></h2>
      <a class="btn btn-ghost btn-sm" href="/test-reports/queue?tab=signed">All</a></div>
    <div class="card-content">{#if data}{@render rows(data.recently_signed, "No signed reports yet.", "signed")}{:else}<p class="text-sm text-muted" aria-busy="true">Loading…</p>{/if}</div>
  </section>
</div>

{#if data}
  <div class="grid-2 items-start">
    <ChartCard title="Reports signed" description="{per} · {label}" tip="Reports signed for the first time, by the day (or month) they were signed."
               empty={!data.trend.length} emptyText="No reports signed in this period."
               table={{ columns: [{ label: "Period" }, { label: "Signed", num: true }], rows: [...data.trend].reverse().map((p) => [full(p.day, unit), p.signed]) }}>
      <BarChart {keys} {unit} fmt="count" label="Reports signed, {per.toLowerCase()}"
                series={[{ key: "signed", label: "Signed", color: "var(--chart-1)", values: data.trend.map((p) => p.signed) }]} />
    </ChartCard>
    <ChartCard title="Turnaround" description="{per} · average hours from bill to signature" tip="For the reports signed in each day (or month): the average time from billing to the first signature."
               empty={!data.trend.length} emptyText="No reports signed in this period."
               table={{ columns: [{ label: "Period" }, { label: "Average", num: true }], rows: [...data.trend].reverse().map((p) => [full(p.day, unit), hours(p.avg_hours)]) }}>
      <LineChart {keys} {unit} fmt="hours" endLabels={false} label="Average turnaround, {per.toLowerCase()}"
                 series={[{ key: "tat", label: "Average turnaround", color: "var(--chart-2)", values: data.trend.map((p) => p.avg_hours) }]} />
    </ChartCard>
    <ChartCard title="By department" description="Signed · {label}" tip="Reports signed in the period by the test's department, with the average turnaround."
               empty={!data.by_department.length} emptyText="No reports signed in this period."
               table={{ columns: [{ label: "Department" }, { label: "Signed", num: true }, { label: "Average turnaround", num: true }], rows: data.by_department.map((d) => [d.name, d.count, hours(d.avg_hours)]) }}>
      <BarChart keys={data.by_department.map((d) => d.name)} horizontal fmt="count" height={Math.max(120, data.by_department.length * 34)} label="Reports signed by department"
                series={[{ key: "count", label: "Signed", color: "var(--chart-1)", values: data.by_department.map((d) => d.count) }]} />
    </ChartCard>
    <ChartCard title="By reporting doctor" description="Signed · {label}" tip="Reports signed in the period by each doctor, with their average turnaround."
               empty={!data.by_doctor.length} emptyText="No reports signed in this period."
               table={{ columns: [{ label: "Doctor" }, { label: "Signed", num: true }, { label: "Average turnaround", num: true }], rows: data.by_doctor.map((d) => [d.name, d.count, hours(d.avg_hours)]) }}>
      <BarChart keys={data.by_doctor.map((d) => d.name)} horizontal fmt="count" height={Math.max(120, data.by_doctor.length * 34)} label="Reports signed by doctor"
                series={[{ key: "count", label: "Signed", color: "var(--chart-3)", values: data.by_doctor.map((d) => d.count) }]} />
    </ChartCard>
    <ChartCard title="By modality" description="Signed · {label}" tip="Reports signed in the period by the modality written on the report (CR, CT, US…); “—” when none was given."
               empty={!data.by_modality.length} emptyText="No reports signed in this period."
               table={{ columns: [{ label: "Modality" }, { label: "Signed", num: true }], rows: data.by_modality.map((d) => [d.name, d.count]) }}>
      <BarChart keys={data.by_modality.map((d) => d.name)} horizontal fmt="count" height={Math.max(120, data.by_modality.length * 34)} label="Reports signed by modality"
                series={[{ key: "count", label: "Signed", color: "var(--chart-4)", values: data.by_modality.map((d) => d.count) }]} />
    </ChartCard>
    <ChartCard title="Images uploaded" description="{per} · {label}" tip="DICOM studies uploaded for tests, by the day (or month) they were uploaded, and the images in them."
               empty={!data.images.length} emptyText="No images uploaded in this period."
               table={{ columns: [{ label: "Period" }, { label: "Studies", num: true }, { label: "Images", num: true }], rows: [...data.images].reverse().map((p) => [full(p.day, unit), p.studies, p.images]) }}>
      <BarChart keys={imageKeys} {unit} fmt="count" label="Studies uploaded, {per.toLowerCase()}"
                series={[{ key: "studies", label: "Studies", color: "var(--chart-2)", values: data.images.map((p) => p.studies) }]} />
    </ChartCard>
  </div>
{/if}

<p class="text-sm text-muted">Signed, turnaround, sent and the charts are for {label}; waiting, drafts, ready to sign and overdue are as of now.</p>

<style>
  .worklist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  .worklist a { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--border); color: inherit; text-decoration: none; }
  .worklist a:hover .cell-title { text-decoration: underline; }
  .worklist .grow { display: flex; flex-direction: column; min-width: 0; }
  .sub { font-size: 13px; font-weight: 600; color: var(--muted-foreground); margin: 0 0 4px; }
</style>
