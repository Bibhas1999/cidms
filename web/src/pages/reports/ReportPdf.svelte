<script lang="ts">
  import Button from "../../components/Button.svelte";
  import FormDialog from "../../components/FormDialog.svelte";
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
  import UploadProgress from "../../components/UploadProgress.svelte";
  import { api, ApiError } from "../../lib/api";
  import { fileSize, type Report, type ReportWorkspace } from "../../lib/report-types";
  import { confirmDialog } from "../../lib/confirm.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import { ResumableUpload } from "../../lib/upload.svelte";

  // The report as an uploaded PDF (an outside lab's or a machine's), instead of or as well as typed findings.
  // It goes up in pieces (pause / resume). The PDF that's printed, shared and sent has the centre's signed page
  // first, then these pages. Replacing the PDF of a signed report is an amendment: it asks why and signs again.
  let { itemId, report, canWrite, canSign, onchanged, onconflict }: {
    itemId: string; report: Report | null; canWrite: boolean; canSign: boolean;
    onchanged: (ws: ReportWorkspace) => void; onconflict: (message: string) => void;
  } = $props();

  const signed = $derived(report?.status === "signed" || report?.status === "amended");
  const mayChange = $derived(canWrite && (!signed || canSign));
  const base = $derived(`/api/test-reports/for-item/${itemId}/attachment`);

  let upload = $state<ResumableUpload | null>(null);
  let uploadName = $state("");
  let attaching = $state(false);
  let file: File | null = null;
  let fileInput = $state<HTMLInputElement>();
  let reasonOpen = $state(false);
  let reason = $state("");
  let reasonError = $state("");

  function choose(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const chosen = input.files?.[0];
    input.value = "";
    if (!chosen) return;
    if (!chosen.name.toLowerCase().endsWith(".pdf")) { notify("Choose a PDF file.", { kind: "error" }); return; }
    file = chosen;
    if (signed) { reason = ""; reasonError = ""; reasonOpen = true; return; }
    send();
  }

  async function send() {
    if (!file) return;
    if (!upload) { upload = new ResumableUpload(file, "report_pdf"); uploadName = file.name; }
    try {
      const id = await upload.start();
      attaching = true;
      const ws = await api<ReportWorkspace>("POST", base, { body: { upload_id: id, version: report?.version ?? null, reason: signed ? reason.trim() : "" },
                                                           progress: "Attaching the PDF…" });
      onchanged(ws);
      notify(signed ? "The new PDF is attached and the amended report is signed." : `${uploadName} is attached as the report.`);
      upload = null;
      file = null;
    } catch (e) {
      if ((e as Error).name === "AbortError") return; // paused
      if (upload?.status === "error") return;         // the progress box shows it, with Resume
      upload = null;
      if (e instanceof ApiError && e.status === 409 && e.field === "version") onconflict(e.message);
      else notifyError(e, { title: "Couldn't attach the PDF" });
    } finally {
      attaching = false;
    }
  }

  async function cancel() {
    await upload?.cancel();
    upload = null;
    file = null;
  }

  function submitReason(e: Event) {
    e.preventDefault();
    if (reason.trim().length < 3) { reasonError = "Say why the PDF is being replaced (at least 3 characters)."; return; }
    reasonOpen = false;
    send();
  }

  async function remove() {
    if (!report) return;
    if (!(await confirmDialog({ title: "Remove the attached PDF?", message: "The report goes back to a draft. Earlier versions are kept.",
                                confirmLabel: "Remove", tone: "danger" }))) return;
    try {
      onchanged(await api<ReportWorkspace>("DELETE", `${base}?version=${report.version}`));
      notify("The PDF is removed.");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.field === "version") onconflict(e.message);
      else notifyError(e, { title: "Couldn't remove the PDF" });
    }
  }
</script>

{#if report?.attachment_name || canWrite}
  <section class="card" aria-labelledby="pdf-title">
    <div class="card-header"><div><h2 class="card-title" id="pdf-title">Report as a PDF</h2>
      <p class="card-description">
        {report?.attachment_name ? "Printed, shared and sent with the centre's signed page in front."
          : "Upload a finished report (e.g. from an outside lab or a machine) instead of typing it."}
      </p></div></div>
    <div class="card-content stack">
      <input bind:this={fileInput} type="file" accept="application/pdf,.pdf" class="sr-only" id="report-pdf-file" onchange={choose} />
      {#if report?.attachment_name}
        <div class="row gap-sm attached">
          <Icon name="fileText" />
          <div class="grow min-w-0">
            <div class="font-semibold truncate">{report.attachment_name}</div>
            <div class="text-sm text-muted">{report.attachment_pages} page{report.attachment_pages === 1 ? "" : "s"} · {fileSize(report.attachment_size)}</div>
          </div>
          <a class="btn btn-outline btn-sm" href={base} target="_blank" rel="noopener"><Icon name="eye" size="sm" /> View</a>
        </div>
      {/if}
      {#if upload}
        <UploadProgress {upload} filename={uploadName} onresume={send} oncancel={cancel} />
      {:else if mayChange}
        <div class="row-wrap">
          <Button icon="upload" loading={attaching} loadingText="Attaching…" onclick={() => fileInput?.click()}>
            {report?.attachment_name ? "Replace PDF" : "Upload PDF report"}
          </Button>
          {#if report?.attachment_name && !signed}<Button variant="ghost-destructive" icon="trash" onclick={remove}>Remove</Button>{/if}
          <span class="text-sm text-muted">PDF, up to 20 MB.{signed ? " Replacing it amends the signed report." : ""}</span>
        </div>
      {/if}
    </div>
  </section>
{/if}

<FormDialog bind:open={reasonOpen} title="Replace the signed PDF?" icon="edit" tone="info"
        description="This amends the signed report and signs it again as you. The earlier version is kept."
            submitLabel="Replace and sign" submitIcon="lock" oncancel={() => (file = null)} onsubmit={submitReason}>
    <Field id="pdf-reason-text" label="Why is it being replaced?" required error={reasonError}>
      {#snippet children({ invalid, describedby })}
        <input id="pdf-reason-text" class="input" bind:value={reason} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
</FormDialog>

<style src="./styles/ReportPdf.css"></style>
