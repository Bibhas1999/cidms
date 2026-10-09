<script lang="ts">
  import Field from "../components/Field.svelte";
  import { ApiError, get, put } from "../lib/api";
  import { dateTime } from "../lib/format";
  import { setBeforeLeave } from "../lib/router.svelte";
  import { toastError, toasts } from "../lib/toast.svelte";
  import type { CentreSettings } from "../lib/types";

  type Form = Omit<CentreSettings, "updated_at">;
  const FIELDS: (keyof Form)[] = ["legal_name", "address", "phones", "email", "gst_number", "invoice_prefix", "bill_footer", "report_footer"];

  let saved = $state<CentreSettings | null>(null);
  let form = $state<Form | null>(null);
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);
  let loadError = $state("");

  const dirty = $derived(!!saved && !!form && FIELDS.some((f) => form![f] !== saved![f]));

  function take(s: CentreSettings) {
    saved = s;
    form = Object.fromEntries(FIELDS.map((f) => [f, s[f]])) as Form;
  }

  $effect(() => {
    get<CentreSettings>("/api/settings").then(take).catch((e) => (loadError = e.message));
  });

  // Ask before leaving with unsaved changes (moving inside the app, or closing the tab).
  $effect(() => {
    setBeforeLeave(dirty ? () => confirm("You have unsaved changes. Leave without saving?") : null);
    const onUnload = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); };
    window.addEventListener("beforeunload", onUnload);
    return () => { window.removeEventListener("beforeunload", onUnload); setBeforeLeave(null); };
  });

  async function save(e: SubmitEvent) {
    e.preventDefault();
    if (!form) return;
    saving = true;
    errors = {};
    try {
      take(await put<CentreSettings>("/api/settings", { ...form, gst_number: form.gst_number.trim().toUpperCase(),
                                                         invoice_prefix: form.invoice_prefix.trim().toUpperCase() }));
      toasts.show("Centre settings saved.");
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fieldErrors).length) errors = err.fieldErrors;
      else toastError(err);
    } finally {
      saving = false;
    }
  }
</script>

<div class="stack">
  <h1>Centre settings</h1>
  {#if loadError}
    <div class="alert" role="alert">{loadError}</div>
  {:else if form}
    <form class="card" onsubmit={save} novalidate>
      <div class="card-body stack">
        <p class="muted">These details appear on every bill and report.</p>
        <Field id="legal_name" label="Name on bills and reports" required error={errors.legal_name}>
          {#snippet children({ invalid, describedby })}<input id="legal_name" bind:value={form!.legal_name} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
        </Field>
        <Field id="address" label="Address" error={errors.address}>
          {#snippet children({ invalid, describedby })}<textarea id="address" bind:value={form!.address} aria-invalid={invalid} aria-describedby={describedby}></textarea>{/snippet}
        </Field>
        <div class="row-2">
          <Field id="phones" label="Phone numbers" error={errors.phones} hint="Separate several with commas.">
            {#snippet children({ invalid, describedby })}<input id="phones" bind:value={form!.phones} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
          </Field>
          <Field id="email" label="Email" error={errors.email}>
            {#snippet children({ invalid, describedby })}<input id="email" type="email" bind:value={form!.email} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
          </Field>
        </div>
        <div class="row-2">
          <Field id="gst" label="GST number" error={errors.gst_number} hint="15 characters. Leave blank if you don't charge GST.">
            {#snippet children({ invalid, describedby })}<input id="gst" class="mono" maxlength="15" bind:value={form!.gst_number} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
          </Field>
          <Field id="prefix" label="Bill number prefix" required error={errors.invoice_prefix} hint="Bills will be numbered like PREFIX/2026-27/000123.">
            {#snippet children({ invalid, describedby })}<input id="prefix" class="mono" maxlength="10" bind:value={form!.invoice_prefix} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
          </Field>
        </div>
        <Field id="bill_footer" label="Notes at the foot of every bill" error={errors.bill_footer}>
          {#snippet children({ invalid, describedby })}<textarea id="bill_footer" bind:value={form!.bill_footer} aria-invalid={invalid} aria-describedby={describedby}></textarea>{/snippet}
        </Field>
        <Field id="report_footer" label="Notes at the foot of every report" error={errors.report_footer}>
          {#snippet children({ invalid, describedby })}<textarea id="report_footer" bind:value={form!.report_footer} aria-invalid={invalid} aria-describedby={describedby}></textarea>{/snippet}
        </Field>
        <div class="toolbar">
          <button class="btn primary" type="submit" disabled={saving || !dirty}>{saving ? "Saving…" : "Save changes"}</button>
          <span class="muted">Last saved {dateTime(saved?.updated_at)}</span>
        </div>
      </div>
    </form>
  {:else}
    <p class="muted">Loading…</p>
  {/if}
</div>
