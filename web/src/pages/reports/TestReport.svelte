<script lang="ts">
  import { z } from "zod";
  import Dialog from "../../components/Dialog.svelte";
  import FormDialog from "../../components/FormDialog.svelte";
  import Field from "../../components/Field.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import RichTextEditor from "../../components/RichTextEditor.svelte";
  import { ApiError, get, post, put } from "../../lib/api";
  import { date, dateTime } from "../../lib/format";
  import { Form } from "../../lib/form.svelte";
  import {
    REPORT_STATUS, fileSize, uploadWithProgress,
    type ReportVersionFull, type ReportWorkspace, type Template, type UploadResult,
  } from "../../lib/report-types";
  import { confirmDialog } from "../../lib/confirm.svelte";
  import { confirmLeave } from "../../lib/leave";
  import { setBeforeLeave } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";
  import PatientLink from "./PatientLink.svelte";
  import ReportPdf from "./ReportPdf.svelte";
  import SendWhatsApp from "./SendWhatsApp.svelte";

  // Writing one test's report: the editor on the left (autosaved), images and earlier reports on the right.
  // Every save carries the version it was edited from; if someone else saved first, nothing is overwritten.
  let { params }: { params: Record<string, string> } = $props();

  const AUTOSAVE_MS = 30_000;
  const canWrite = $derived(session.can("reports.write"));
  const canSign = $derived(session.can("reports.sign"));
  const canUpload = $derived(session.can("worklist.update") || session.can("reports.write"));

  let ws = $state<ReportWorkspace | null>(null);
  let loadError = $state("");
  let conflict = $state("");
  let amending = $state(false);
  let lastSaved = $state<string | null>(null);
  let busy = $state<"" | "save" | "finalise" | "sign" | "create">("");

  const schema = z.object({
    title: z.string().trim().max(200, "Keep the title under 200 characters."),
    technique: z.string().trim().max(500, "Keep the technique under 500 characters."),
    modality: z.string().trim().max(40, "Keep the modality under 40 characters."),
    findings: z.string().max(200_000, "The findings are too long."),
    impression: z.string().max(50_000, "The impression is too long."),
  });
  type Content = z.input<typeof schema>;
  const blank: Content = { title: "", technique: "", modality: "", findings: "", impression: "" };
  let saved = $state<Content>({ ...blank });

  const form = new Form({ schema, initial: blank, onSubmit: async () => { await save(false); } });

  const report = $derived(ws?.report ?? null);
  const signedLike = $derived(report?.status === "signed" || report?.status === "amended");
  const editable = $derived(!!report && canWrite && (!signedLike || (amending && canSign)));
  const same = (a: string, b: string) => a.replace(/<p><br><\/p>|\s+/g, "") === b.replace(/<p><br><\/p>|\s+/g, "");
  const dirty = $derived(!!report && (Object.keys(blank) as (keyof Content)[]).some((k) =>
    k === "findings" || k === "impression" ? !same(form.values[k], saved[k]) : form.values[k].trim() !== saved[k]));

  /** Take the server's answer. `sent` (after a save): only fields not edited since the save went out are
   *  replaced by the server's (cleaned) copy, so typing that happened while it was saving is never lost. */
  function take(next: ReportWorkspace, resetForm = true, sent?: Content) {
    ws = next;
    conflict = "";
    if (!next.report || !resetForm) return;
    const r = next.report;
    const server: Content = { title: r.title, technique: r.technique, modality: r.modality, findings: r.findings, impression: r.impression };
    saved = server;
    if (!sent) { form.reset({ ...server }); return; }
    for (const k of Object.keys(blank) as (keyof Content)[]) {
      const now = k === "findings" || k === "impression" ? form.values[k] : form.values[k].trim();
      if (now === sent[k]) form.values[k] = server[k];
    }
  }

  async function load() {
    try {
      take(await get<ReportWorkspace>(`/api/test-reports/for-item/${params.itemId}`));
      document.title = `${ws!.item.test_name} · ${ws!.item.patient_name}`;
      loadError = "";
    } catch (e) {
      loadError = (e as Error).message;
    }
  }
  $effect(() => { params.itemId; amending = false; load(); });

  // Signing needs a signature profile: say so on the button rather than failing.
  let hasSignature = $state(true);
  $effect(() => {
    if (!canSign) return;
    get<{ exists: boolean }>("/api/test-reports/my-signature").then((s) => (hasSignature = s.exists)).catch(() => {});
  });
  const signBlocked = $derived(!hasSignature ? "Add your signature in Settings → My signature first." : "");

  // ---------- templates ----------
  let templates = $state<Template[]>([]);
  let templateId = $state("");
  $effect(() => {
    const testId = ws?.item.test_id;
    if (!canWrite || !ws) return;
    get<Template[]>("/api/test-reports/templates", { test_id: testId ?? undefined, active: true }).then((t) => (templates = t)).catch(() => {});
  });

  async function create() {
    busy = "create";
    try {
      take(await post<ReportWorkspace>(`/api/test-reports/for-item/${params.itemId}`, { template_id: templateId || null }));
      notify("Report started.");
    } catch (e) {
      notifyError(e, { title: "Couldn't start the report" });
    } finally {
      busy = "";
    }
  }

  async function applyTemplate() {
    const t = templates.find((x) => x.id === templateId);
    if (!t) return;
    const hasWords = form.values.findings.replace(/<[^>]+>/g, "").trim() || form.values.impression.replace(/<[^>]+>/g, "").trim();
    if (hasWords && !(await confirmDialog({ title: `Use the "${t.name}" template?`, message: "What's written in the findings and impression is replaced.",
                                            confirmLabel: "Replace", tone: "danger" }))) return;
    form.values.title = t.title || form.values.title;
    form.values.technique = t.technique || form.values.technique;
    form.values.findings = t.findings;
    form.values.impression = t.impression;
  }

  // ---------- saving ----------
  function contentBody() {
    const v = form.values;
    return { title: v.title.trim(), technique: v.technique.trim(), modality: v.modality.trim(), findings: v.findings, impression: v.impression };
  }

  async function save(quiet: boolean): Promise<boolean> {
    if (!report || !editable || signedLike || !dirty || busy === "save" || conflict) return true;
    busy = "save";
    try {
      const sent = contentBody();
      take(await put<ReportWorkspace>(`/api/test-reports/for-item/${params.itemId}`, { version: report.version, ...sent }), true, sent);
      lastSaved = new Date().toISOString();
      if (!quiet) notify("Draft saved.");
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) conflict = e.message;
      else if (!quiet || !(e instanceof ApiError) || e.status !== 0) notifyError(e, { title: "Couldn't save the report" });
      return false;
    } finally {
      busy = "";
    }
  }

  // Autosave every 30 seconds and when the cursor leaves a box.
  $effect(() => {
    const timer = setInterval(() => { if (dirty) save(true); }, AUTOSAVE_MS);
    return () => clearInterval(timer);
  });
  $effect(() => {
    setBeforeLeave(dirty ? confirmLeave({ message: "This report has changes that aren't saved. If you leave now, they're lost." }) : null);
    return () => setBeforeLeave(null);
  });
  $effect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  });
  const blurSave = () => { if (dirty && !amending) save(true); };

  async function act(action: "finalise" | "sign") {
    if (!report) return;
    if (dirty && !(await save(true))) return;
    busy = action;
    try {
      take(await post<ReportWorkspace>(`/api/test-reports/for-item/${params.itemId}/${action}`, { version: ws!.report!.version }));
      notify(action === "sign" ? "The report is signed. The test is marked reported." : "The report is ready to sign.");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) conflict = e.message;
      else if (e instanceof ApiError && e.field === "signature")
        notify(e.message, { kind: "warning", title: "Set up your signature", detail: "Settings → My signature" });
      else notifyError(e, { title: action === "sign" ? "Couldn't sign the report" : "Couldn't finalise the report" });
    } finally {
      busy = "";
    }
  }

  // ---------- amending a signed report ----------
  let amendOpen = $state(false);
  const amendForm = new Form({
    schema: z.object({ reason: z.string().trim().min(3, "Say why the report is being changed (at least 3 characters).").max(500, "Keep it under 500 characters.") }),
    initial: { reason: "" },
    onSubmit: async ({ reason }) => {
      take(await post<ReportWorkspace>(`/api/test-reports/for-item/${params.itemId}/amend`, { version: report!.version, reason, ...contentBody() }));
      amendOpen = false;
      amending = false;
      notify("The amended report is signed. Earlier versions are kept.");
    },
  });
  async function submitAmend(e: Event) {
    try {
      await amendForm.submit(e);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) { conflict = err.message; amendOpen = false; }
      else if (!(err instanceof ApiError && Object.keys(err.fieldErrors).length)) notifyError(err, { title: "Couldn't amend the report" });
    }
  }
  async function cancelAmend() {
    if (dirty && !(await confirmDialog({ title: "Discard your changes?", message: "What's been typed since amending started is lost.",
                                         confirmLabel: "Discard", tone: "danger" }))) return;
    amending = false;
    form.reset({ ...saved });
  }

  // ---------- version history ----------
  let viewing = $state<ReportVersionFull | null>(null);
  async function showVersion(n: number) {
    try {
      viewing = await get<ReportVersionFull>(`/api/test-reports/for-item/${params.itemId}/versions/${n}`);
    } catch (e) {
      notifyError(e);
    }
  }
  const ACTIONS: Record<string, string> = { created: "Started", saved: "Saved", finalised: "Marked ready to sign", signed: "Signed",
                                            amended: "Amended and signed", imported: "Brought across from the old app",
                                            attached: "PDF attached", detached: "PDF removed" };

  // ---------- images ----------
  let progress = $state<number | null>(null);
  let dragging = $state(false);
  async function uploadFiles(files: FileList | File[] | null | undefined) {
    const list = [...(files ?? [])];
    if (!list.length || !ws) return;
    const body = new FormData();
    for (const f of list) body.append("files", f, f.name);
    progress = 0;
    try {
      const res = await uploadWithProgress<UploadResult>(`/api/imaging/items/${params.itemId}/upload`, body, session.me?.csrf_token ?? "",
                                                         (f) => (progress = f));
      const added = res.stored + res.already_stored;
      if (res.studies.length) notify(`${added} image${added === 1 ? "" : "s"} saved in ${res.studies.length} stud${res.studies.length === 1 ? "y" : "ies"}.`);
      for (const m of res.messages) notify(m, { kind: res.studies.length ? "info" : "warning" });
      take(await get<ReportWorkspace>(`/api/test-reports/for-item/${params.itemId}`), false);
    } catch (e) {
      notifyError(e, { title: "Couldn't upload the images" });
    } finally {
      progress = null;
    }
  }

  const statusBadge = $derived(report ? REPORT_STATUS[report.status] : ["badge-info", "Not started"]);
</script>

{#if loadError}
  <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div><div class="alert-title">Couldn't open this report</div>{loadError}</div></div>
  <a class="btn btn-outline" href="/test-reports" style="align-self: flex-start">Back to reports</a>
{:else if !ws}
  <div class="card"><div class="empty" aria-busy="true">Loading…</div></div>
{:else}
  {@const item = ws.item}
  <div class="page-header">
    <div>
      <a class="link-button" href="/test-reports"><Icon name="chevronRight" size="sm" class="flip" /> Reports</a>
      <div class="meta-row" style="margin-top: 8px">
        <span class="eyebrow">Report</span>
        <span class="badge {statusBadge[0]}">{statusBadge[1]}</span>
        {#if report?.imported}<span class="badge badge-plain">From the old app</span>{/if}
        {#if report && report.amendments > 0}<span class="badge badge-navy badge-plain">Amended {report.amendments}×</span>{/if}
      </div>
      <h1 class="page-title">{item.test_name}</h1>
      <p class="page-description">
        <strong>{item.patient_name}</strong>{#if item.patient_age || item.patient_gender} · {[item.patient_age, item.patient_gender].filter(Boolean).join(" · ")}{/if}
        · Bill <a class="mono" href="/bills/{item.invoice_id}">{item.invoice_no}</a> · {date(item.bill_date)}
        {#if item.accession_no} · <span class="mono">{item.accession_no}</span>{/if}
        · Referred by {item.referring_doctor_name || "Self"}
      </p>
    </div>
    <div class="row-wrap">
      {#if report && (signedLike || canWrite)}
        <a class="btn btn-outline" href="/test-reports/{item.item_id}/print" target="_blank" rel="noopener"><Icon name="printer" /> Print</a>
      {/if}
      {#if report && signedLike && canWrite}<SendWhatsApp reportId={report.id} patientName={item.patient_name} />{/if}
    </div>
  </div>

  {#if conflict}
    <div class="alert alert-warning" role="alert"><Icon name="alert" /><div><div class="alert-title">Someone else changed this report</div>{conflict}
      <div class="row-wrap mt-2"><button class="btn btn-outline btn-sm" onclick={() => { form.reset({ ...saved }); load(); }}>Reload their version</button></div></div></div>
  {/if}

  <div class="grid-3 items-start">
    <div class="span-2 stack">
      {#if !report}
        <section class="card" aria-labelledby="start-title">
          <div class="card-header"><div><h2 class="card-title" id="start-title">No report yet</h2>
            <p class="card-description">{canWrite ? "Start from a template or a blank page." : "The report hasn't been signed yet."}</p></div></div>
          {#if canWrite}
            <div class="card-content row-wrap" style="align-items: flex-end">
              <Field id="start-template" label="Template" optional tip="Ready-made wording for this test. You can change everything afterwards.">
                {#snippet children({ describedby })}
                  <select id="start-template" class="select" bind:value={templateId} aria-describedby={describedby}>
                    <option value="">Blank report</option>
                    {#each templates as t (t.id)}<option value={t.id}>{t.name}{t.test_id ? "" : " (any test)"}</option>{/each}
                  </select>
                {/snippet}
              </Field>
              <button class="btn btn-primary" disabled={busy === "create"} onclick={create}><Icon name="edit" /> {busy === "create" ? "Starting…" : "Write report"}</button>
            </div>
          {/if}
        </section>
        <ReportPdf itemId={params.itemId} report={null} {canWrite} {canSign} onchanged={(next) => take(next)} onconflict={(m) => (conflict = m)} />
      {:else}
        <form class="card" onsubmit={form.submit} novalidate aria-labelledby="report-title">
          <div class="card-header">
            <div><h2 class="card-title" id="report-title">Report</h2>
              <p class="card-description">
                Version {report.version} · {report.reported_by_name || "—"} · {dateTime(report.updated_at)}
                {#if busy === "save"} · Saving…{:else if dirty && editable} · Unsaved changes{:else if lastSaved} · Saved{/if}
              </p></div>
            {#if editable && !signedLike && templates.length}
              <div class="row" style="gap: 6px">
                <label class="sr-only" for="tpl">Apply a template</label>
                <select id="tpl" class="select select-sm" bind:value={templateId}>
                  <option value="">Template…</option>
                  {#each templates as t (t.id)}<option value={t.id}>{t.name}</option>{/each}
                </select>
                <button type="button" class="btn btn-outline btn-sm" disabled={!templateId} onclick={applyTemplate}>Apply</button>
              </div>
            {/if}
          </div>
          <div class="card-content stack">
            <FormErrors {form} labels={{ title: "Title", technique: "Technique", modality: "Modality", findings: "Findings", impression: "Impression" }} />
            {#if amending}
              <div class="alert alert-info"><Icon name="info" /><div>You're amending a signed report. When you sign the amendment you'll be asked why; the earlier version is kept.</div></div>
            {/if}
            <div class="grid-2">
              <Field id="title" label="Title" error={form.error("title")} tip="Printed as the report's heading. Usually the study, e.g. “X-ray chest PA view”.">
                {#snippet children({ invalid, describedby })}<input id="title" class="input" bind:value={form.values.title} {...form.field("title")}
                  onblur={() => { form.field("title").onblur(); blurSave(); }} disabled={!editable} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
              </Field>
              <Field id="modality" label="Modality" optional error={form.error("modality")} tip="The DICOM modality code: CR or DX for X-ray, CT, MR, US for ultrasound.">
                {#snippet children({ invalid, describedby })}<input id="modality" class="input" placeholder="CR, CT, US…" bind:value={form.values.modality} {...form.field("modality")}
                  onblur={() => { form.field("modality").onblur(); blurSave(); }} disabled={!editable} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
              </Field>
            </div>
            <Field id="technique" label="Technique" optional error={form.error("technique")} tip="How the study was done, e.g. “Digital radiograph, PA view”. One line.">
              {#snippet children({ invalid, describedby })}<input id="technique" class="input" bind:value={form.values.technique} {...form.field("technique")}
                onblur={() => { form.field("technique").onblur(); blurSave(); }} disabled={!editable} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
            <Field id="findings" label="Findings" error={form.error("findings")} tip="What the study shows. Use the toolbar for bold, headings and lists. Saved automatically every 30 seconds and when you click away.">
              {#snippet children({ invalid, describedby })}<RichTextEditor id="findings" label="Findings" bind:value={form.values.findings} disabled={!editable}
                {invalid} {describedby} minHeight={220} onblur={blurSave} />{/snippet}
            </Field>
            <Field id="impression" label="Impression" error={form.error("impression")} tip="The conclusion, printed in bold under the findings.">
              {#snippet children({ invalid, describedby })}<RichTextEditor id="impression" label="Impression" bind:value={form.values.impression} disabled={!editable}
                {invalid} {describedby} minHeight={90} onblur={blurSave} />{/snippet}
            </Field>
            {#if signedLike && report.signer_name}
              <p class="text-sm text-muted">Signed by <strong>{report.signer_name}</strong>{report.signer_degree ? `, ${report.signer_degree}` : ""}
                {#if report.signed_at} on {dateTime(report.signed_at)}{/if}{#if report.amend_reason} · Last change: {report.amend_reason}{/if}</p>
            {/if}
          </div>
          <div class="card-footer">
            {#if !signedLike && canWrite}
              <button type="submit" class="btn btn-outline" disabled={!dirty || !!busy}><Icon name="check" /> {busy === "save" ? "Saving…" : "Save draft"}</button>
              {#if report.status === "draft"}
                <span use:tooltip={"Tells the doctor it's ready for signing. Editing it again makes it a draft."}>
                  <button type="button" class="btn btn-outline" disabled={!!busy} onclick={() => act("finalise")}>Mark ready to sign</button>
                </span>
              {/if}
              {#if canSign}
                <span use:tooltip={signBlocked || "Sign as yourself; the test is marked reported"}>
                  <button type="button" class="btn btn-primary" disabled={!!busy || !!signBlocked} aria-describedby={signBlocked ? "sign-why" : undefined}
                          onclick={() => act("sign")}><Icon name="lock" /> {busy === "sign" ? "Signing…" : "Sign report"}</button>
                </span>
                {#if signBlocked}<span id="sign-why" class="sr-only">{signBlocked}</span>{/if}
              {/if}
            {:else if signedLike && canSign && canWrite}
              {#if amending}
                <button type="button" class="btn btn-outline" onclick={cancelAmend}>Cancel</button>
                <span use:tooltip={signBlocked || (!dirty ? "Change the report first" : "Sign the changed report")}>
                  <button type="button" class="btn btn-primary" disabled={!dirty || !!signBlocked} onclick={() => { amendForm.reset(); amendOpen = true; }}><Icon name="lock" /> Sign amendment</button>
                </span>
              {:else}
                <button type="button" class="btn btn-outline" onclick={() => (amending = true)}><Icon name="edit" /> Amend</button>
              {/if}
            {/if}
          </div>
        </form>

        <ReportPdf itemId={params.itemId} {report} {canWrite} {canSign} onchanged={(next) => take(next)} onconflict={(m) => (conflict = m)} />

        {#if ws.versions.length}
          <section class="card" aria-labelledby="history-title">
            <div class="card-header"><div><h2 class="card-title" id="history-title">Version history</h2>
              <p class="card-description">Every saved version is kept and can't be changed.</p></div></div>
            <div class="card-flush"><div class="table-wrap"><table class="table" style="min-width: 0">
              <thead><tr><th>Version</th><th>What</th><th>Who</th><th>When</th><th><span class="sr-only">Open</span></th></tr></thead>
              <tbody>
                {#each ws.versions as v (v.version)}
                  <tr>
                    <td class="tabular">v{v.version}</td>
                    <td>{ACTIONS[v.action] ?? v.action}{#if v.reason}<div class="cell-sub">{v.reason}</div>{/if}</td>
                    <td class="text-sm">{v.saved_by_name || "—"}</td>
                    <td class="text-sm nowrap">{dateTime(v.created_at)}</td>
                    <td class="num"><button class="btn btn-ghost btn-sm" onclick={() => showVersion(v.version)}>View</button></td>
                  </tr>
                {/each}
              </tbody>
            </table></div></div>
          </section>
        {/if}
      {/if}
    </div>

    <div class="stack">
      {#if item.is_imaging}
        <section class="card" aria-labelledby="images-title">
          <div class="card-header"><div><h2 class="card-title" id="images-title">Images</h2>
            <p class="card-description">DICOM studies for this test.</p></div></div>
          <div class="card-content stack">
            {#if !ws.image_server}
              <div class="alert alert-warning"><Icon name="alert" /><div>The image server isn't available right now. Uploading and viewing images will work again when it's back.</div></div>
            {/if}
            {#each ws.studies as s (s.id)}
              <div class="study">
                <div>
                  <div class="cell-title">{s.description || "Study"} {#if s.modality}<span class="badge badge-plain">{s.modality}</span>{/if}</div>
                  <div class="cell-sub">{s.series_count} series · {s.instance_count} image{s.instance_count === 1 ? "" : "s"} · {fileSize(s.size_bytes)}</div>
                  <div class="cell-sub">{s.uploaded_by_name || "—"} · {dateTime(s.created_at)}</div>
                </div>
                <a class="btn btn-outline btn-sm" href={s.viewer_url} target="_blank" rel="noopener" use:tooltip={"Opens the image viewer in a new tab"}><Icon name="eye" size="sm" /> View images</a>
              </div>
            {:else}
              <p class="text-sm text-muted">No images yet.</p>
            {/each}
            {#if canUpload && ws.image_server}
              <label class="drop" class:is-over={dragging}
                     ondragover={(e) => { e.preventDefault(); dragging = true; }} ondragleave={() => (dragging = false)}
                     ondrop={(e) => { e.preventDefault(); dragging = false; uploadFiles(e.dataTransfer?.files); }}>
                <Icon name="download" />
                <span>{progress !== null ? `Uploading… ${Math.round(progress * 100)}%` : "Add DICOM files (.dcm) or a .zip"}</span>
                <span class="hint">Drop them here or choose. Up to 500 MB at a time.</span>
                <input type="file" class="sr-only" multiple accept=".dcm,.zip,application/dicom,application/zip" disabled={progress !== null}
                       onchange={(e) => { uploadFiles(e.currentTarget.files); e.currentTarget.value = ""; }} />
              </label>
              {#if progress !== null}<progress max="1" value={progress} aria-label="Upload progress"></progress>{/if}
            {/if}
          </div>
        </section>
      {/if}

      {#if report && signedLike && canWrite}<PatientLink reportId={report.id} />{/if}

      <section class="card" aria-labelledby="prev-title">
        <div class="card-header"><div><h2 class="card-title" id="prev-title">Earlier reports</h2>
          <p class="card-description">{item.patient_name}'s other reports for this test.</p></div></div>
        <div class="card-content stack-sm">
          {#each ws.previous as p (p.item_id)}
            <a class="prev" href="/test-reports/{p.item_id}">
              <span><span class="cell-title">{date(p.bill_date)}</span><span class="cell-sub"> · {p.title || p.test_name}</span></span>
              <span class="badge {REPORT_STATUS[p.status][0]}">{REPORT_STATUS[p.status][1]}</span>
            </a>
          {:else}
            <p class="text-sm text-muted">None.</p>
          {/each}
        </div>
      </section>
    </div>
  </div>

  <FormDialog bind:open={amendOpen} title="Sign the amendment?" icon="lock" tone="info"
          description="The amended report is signed in your name and printed as “Amended”. The earlier version is kept."
              submitLabel="Sign amendment" cancelLabel="Back" busy={amendForm.submitting} busyLabel="Signing…" onsubmit={submitAmend}>
      <FormErrors form={amendForm} labels={{ reason: "Reason" }} />
      <Field id="reason" label="Reason for the change" required error={amendForm.error("reason")} tip="Shown in the version history and on the printed report.">
        {#snippet children({ invalid, describedby })}<textarea id="reason" class="textarea" style="min-height: 80px" bind:value={amendForm.values.reason}
          {...amendForm.field("reason")} aria-invalid={invalid} aria-describedby={describedby}></textarea>{/snippet}
      </Field>
  </FormDialog>

  <Dialog open={!!viewing} onclose={() => (viewing = null)} wide title="Version {viewing?.version ?? ''}"
          description={viewing ? `${ACTIONS[viewing.action] ?? viewing.action} by ${viewing.saved_by_name || "—"} · ${dateTime(viewing.created_at)}` : ""}>
    {#if viewing}
      <div class="stack report-text">
        <h3>{viewing.title}</h3>
        {#if viewing.technique}<p><strong>Technique:</strong> {viewing.technique}</p>{/if}
        <!-- Cleaned on the server to a small set of safe tags before it was saved. -->
        <div>{@html viewing.findings}</div>
        {#if viewing.impression}<div><strong>Impression</strong>{@html viewing.impression}</div>{/if}
        {#if viewing.reason}<p class="text-sm text-muted">Reason: {viewing.reason}</p>{/if}
      </div>
    {/if}
    {#snippet footer()}<button class="btn btn-outline" type="button" onclick={() => (viewing = null)}>Close</button>{/snippet}
  </Dialog>
{/if}

<style>
  .study { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
  .drop { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 18px; border: 1.5px dashed var(--border);
    border-radius: 10px; text-align: center; cursor: pointer; font-size: 14px; font-weight: 600; }
  .drop:hover, .drop.is-over, .drop:focus-within { border-color: var(--primary); background: var(--muted); }
  progress { width: 100%; }
  .prev { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 6px 0; color: inherit; text-decoration: none; }
  .prev:hover .cell-title { text-decoration: underline; }
  .report-text :global(p) { margin: 0 0 6px; }
  .report-text :global(ul), .report-text :global(ol) { padding-left: 22px; }
</style>
