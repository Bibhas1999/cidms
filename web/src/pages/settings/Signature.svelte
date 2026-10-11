<script lang="ts">
  import { z } from "zod";
  import Field from "../../components/Field.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import { ApiError, api, get, put } from "../../lib/api";
  import { dateTime } from "../../lib/format";
  import { Form } from "../../lib/form.svelte";
  import type { Signature } from "../../lib/report-types";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";

  // My signature (Settings): how I sign reports. Printed under every report I sign, exactly as it was when I signed.
  let { embedded = false }: { embedded?: boolean } = $props();

  let sig = $state<Signature | null>(null);
  let loadError = $state("");
  let uploading = $state(false);

  const form = new Form({
    schema: z.object({
      display_name: z.string().trim().min(2, "Enter your name as it should be printed.").max(200, "Keep it under 200 characters."),
      degree: z.string().trim().max(200, "Keep it under 200 characters."),
      registration_no: z.string().trim().min(2, "Enter your medical council registration number.").max(60, "Keep it under 60 characters."),
    }),
    initial: { display_name: "", degree: "", registration_no: "" },
    onSubmit: async (data) => {
      sig = await put<Signature>("/api/test-reports/my-signature", data);
      form.reset({ display_name: sig.display_name, degree: sig.degree, registration_no: sig.registration_no });
      notify("Your signature details are saved.");
    },
  });

  $effect(() => {
    get<Signature>("/api/test-reports/my-signature")
      .then((s) => { sig = s; form.reset({ display_name: s.display_name, degree: s.degree, registration_no: s.registration_no }); })
      .catch((e) => (loadError = e.message));
  });

  async function save(e: Event) {
    try {
      await form.submit(e);
    } catch (err) {
      if (!(err instanceof ApiError && Object.keys(err.fieldErrors).length)) notifyError(err, { title: "Couldn't save your signature" });
    }
  }

  async function upload(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    uploading = true;
    const body = new FormData();
    body.append("signature", file);
    try {
      const res = await fetch("/api/test-reports/my-signature/image", { method: "POST", body, credentials: "same-origin",
                                                                       headers: { "X-CSRF-Token": session.me?.csrf_token ?? "" } });
      const data = await res.json();
      if (!res.ok) throw new ApiError(res.status, data.message, data.field, data.detail ?? [], data.request_id);
      sig = data;
      notify("Your signature picture is updated.");
    } catch (err) {
      notifyError(err, { title: "Couldn't upload the picture" });
    } finally {
      uploading = false;
      input.value = "";
    }
  }

  async function removeImage() {
    try {
      sig = await api<Signature>("DELETE", "/api/test-reports/my-signature/image");
      notify("Your signature picture is removed.");
    } catch (err) {
      notifyError(err);
    }
  }
</script>

<PageHeader compact={embedded} eyebrow="Settings" title="My signature" description="How you sign test reports. Each signed report keeps the details as they were when you signed it.">
  {#snippet actions()}{#if sig?.updated_at}<span class="text-sm text-muted">Last saved {dateTime(sig.updated_at)}</span>{/if}{/snippet}
</PageHeader>

{#if loadError}
  <div class="alert alert-destructive" role="alert"><Icon name="alert" />{loadError}</div>
{:else if sig}
  <form class="card" onsubmit={save} novalidate>
    <div class="card-content stack-lg">
      <FormErrors {form} labels={{ display_name: "Name", degree: "Degree", registration_no: "Registration number" }} />
      {#if !sig.exists}<div class="alert alert-info"><Icon name="info" /><div>Save these details before you sign your first report.</div></div>{/if}
      <div class="grid-2">
        <Field id="display_name" label="Name as printed" required error={form.error("display_name")} tip="Printed in bold under your signature, e.g. “Dr. Ananya Sen”.">
          {#snippet children({ invalid, describedby })}<input id="display_name" class="input" bind:value={form.values.display_name} {...form.field("display_name")}
            aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
        </Field>
        <Field id="degree" label="Degrees" optional error={form.error("degree")} tip="Your qualifications, e.g. “MBBS, MD (Radiodiagnosis)”.">
          {#snippet children({ invalid, describedby })}<input id="degree" class="input" bind:value={form.values.degree} {...form.field("degree")}
            aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
        </Field>
      </div>
      <Field id="registration_no" label="Registration number" required error={form.error("registration_no")}
             tip="Your medical council registration, e.g. “WBMC 12345”. Printed on every report you sign.">
        {#snippet children({ invalid, describedby })}<input id="registration_no" class="input mono" bind:value={form.values.registration_no} {...form.field("registration_no")}
          aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
      <div class="stack-sm">
        <span class="label">Signature picture</span>
        <div class="row" style="gap: 16px; align-items: center">
          <div class="sig-box">{#if sig.signature}<img src={sig.signature} alt="Your signature" />{:else}<span class="text-sm text-muted">None yet</span>{/if}</div>
          <div class="row-wrap">
            <label class="btn btn-outline" style="cursor: pointer" aria-disabled={!sig.exists}>
              <Icon name="edit" size="sm" /> {uploading ? "Uploading…" : sig.signature ? "Change picture" : "Add a picture"}
              <input type="file" accept="image/png,image/jpeg,image/webp" class="sr-only" onchange={upload} disabled={uploading || !sig.exists} />
            </label>
            {#if sig.signature}<button type="button" class="btn btn-ghost-destructive" onclick={removeImage}>Remove</button>{/if}
          </div>
        </div>
        <span class="hint">{sig.exists ? "Sign on white paper, photograph or scan it, and crop close. PNG with a transparent background looks best. Up to 2 MB." : "Save your details first."}</span>
      </div>
    </div>
    <div class="card-footer">
      <button class="btn btn-primary" type="submit" disabled={form.submitting}><Icon name="check" /> {form.submitting ? "Saving…" : "Save details"}</button>
    </div>
  </form>
{:else}
  <div class="card"><div class="empty" aria-busy="true">Loading…</div></div>
{/if}

<style>
  .sig-box { width: 200px; height: 80px; border: 1px dashed var(--border); border-radius: 8px; display: grid; place-items: center; background: #fff; }
  .sig-box img { max-width: 190px; max-height: 70px; object-fit: contain; }
</style>
