<script lang="ts">
  import { z } from "zod";
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import PhoneInput from "../../components/PhoneInput.svelte";
  import { ApiError, get, post } from "../../lib/api";
  import { dateTime } from "../../lib/format";
  import { Form } from "../../lib/form.svelte";
  import { phoneProblem, splitPhone } from "../../lib/phone";
  import type { Deliveries, Delivery } from "../../lib/report-types";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";

  // "Send on WhatsApp" for a signed report: the button, and the dialog with the patient's number, the
  // delivery history, and (when WhatsApp isn't set up on the server) the PDF and a wa.me link to send by hand.
  // `open` lets a list (the report queue) open the dialog without showing the button.
  let { reportId, patientName = "", open = $bindable(false), button = true }: {
    reportId: string; patientName?: string; open?: boolean; button?: boolean;
  } = $props();

  const STATUS: Record<Delivery["status"], [string, string]> = {
    queued: ["badge-info", "Queued"], sent: ["badge-info", "Sent"], delivered: ["badge-success", "Delivered"],
    read: ["badge-success", "Read"], failed: ["badge-destructive", "Failed"],
  };

  let info = $state<Deliveries | null>(null);
  let loadError = $state("");

  const form = new Form({
    schema: z.object({ to: z.string() }),
    initial: { to: "" },
    rules: (v, add) => {
      const p = splitPhone(v.to);
      const problem = phoneProblem(p.dial, p.number, true);
      if (problem) add("to", problem);
    },
    onSubmit: async ({ to }) => {
      info = await post<Deliveries>(`/api/test-reports/${reportId}/whatsapp`, { to });
      const d = info.deliveries[0];
      if (d?.status === "failed") notify(d.error || "WhatsApp couldn't send it.", { kind: "error", title: "Not sent" });
      else notify(`Report sent to ${to} on WhatsApp.`);
    },
  });

  async function load() {
    try {
      info = await get<Deliveries>(`/api/test-reports/${reportId}/whatsapp`);
      form.reset({ to: info.default_to });
      loadError = "";
    } catch (e) {
      loadError = (e as Error).message;
    }
  }
  $effect(() => { if (open) load(); });

  async function send(e: Event) {
    try {
      await form.submit(e);
    } catch (err) {
      if (!(err instanceof ApiError && Object.keys(err.fieldErrors).length)) notifyError(err, { title: "Couldn't send the report" });
    }
  }
  const canSend = $derived(session.can("reports.write"));
</script>

{#if button}
  <button class="btn btn-outline" type="button" onclick={() => (open = true)}><Icon name="inbox" /> Send on WhatsApp</button>
{/if}

<Dialog bind:open title="Send the report on WhatsApp" icon="inbox" tone="info"
        description={patientName ? `The signed report, as a PDF, to ${patientName}.` : "The signed report, as a PDF."}>
  {#if loadError}
    <div class="alert alert-destructive" role="alert"><Icon name="alert" />{loadError}</div>
  {:else if !info}
    <div class="empty" aria-busy="true">Loading…</div>
  {:else}
    <div class="stack">
      {#if !info.configured}
        <div class="alert alert-info"><Icon name="info" /><div><div class="alert-title">WhatsApp sending isn't set up yet</div>
          Download the PDF and send it from the centre's WhatsApp. The link below opens a chat with the patient with a short note (it doesn't include the report).</div></div>
        <div class="row-wrap">
          <a class="btn btn-outline" href="{info.pdf_url}?download=true"><Icon name="download" /> Download PDF</a>
          {#if info.wa_link}<a class="btn btn-primary" href={info.wa_link} target="_blank" rel="noopener noreferrer"><Icon name="inbox" /> Open WhatsApp chat</a>{/if}
        </div>
      {:else}
        <form id="wa-form" class="stack" onsubmit={send} novalidate>
          <FormErrors {form} labels={{ to: "WhatsApp number" }} />
          <Field id="wa-to" label="WhatsApp number" required error={form.error("to")}
                 tip="Filled in from the bill. Change it if the patient wants it on another number; the bill isn't changed.">
            {#snippet children({ invalid, describedby })}
              <PhoneInput id="wa-to" bind:value={form.values.to} {invalid} {describedby} onblur={form.field("to").onblur} oninput={form.field("to").oninput} />
            {/snippet}
          </Field>
          <p class="text-sm text-muted">The message also carries the patient's link to view the report online (the QR code on the printout).</p>
        </form>
      {/if}

      <div>
        <h3 class="text-sm font-semibold" style="margin-bottom: 6px">Sent before</h3>
        {#each info.deliveries as d (d.id)}
          <div class="delivery">
            <div><span class="tabular">{d.to}</span> <span class="cell-sub">· {dateTime(d.created_at)} by {d.sent_by_name || "—"} · v{d.report_version}</span>
              {#if d.error}<div class="field-error" style="margin-top: 2px">{d.error}</div>{/if}</div>
            <span class="badge {STATUS[d.status][0]}">{STATUS[d.status][1]}</span>
          </div>
        {:else}
          <p class="text-sm text-muted">Not sent yet.</p>
        {/each}
      </div>
    </div>
  {/if}
  {#snippet footer()}
    <button class="btn btn-outline" type="button" onclick={() => (open = false)}>Close</button>
    {#if info?.configured && canSend}
      <button class="btn btn-primary" type="submit" form="wa-form" disabled={form.submitting}><Icon name="inbox" /> {form.submitting ? "Sending…" : "Send"}</button>
    {/if}
  {/snippet}
</Dialog>

<style src="./styles/SendWhatsApp.css"></style>
