<script lang="ts">
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import { ApiError, get, put } from "../../lib/api";
  import { dateTime } from "../../lib/format";
  import { setBeforeLeave } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import type { CentreSettings } from "../../lib/types";

  type Form = Omit<CentreSettings, "updated_at" | "logo_file" | "wordmark_file">;
  const FIELDS: (keyof Form)[] = ["legal_name", "tagline", "brand_color", "address", "phones", "email", "gst_number", "invoice_prefix",
                                   "bill_footer", "report_footer"];

  let saved = $state<CentreSettings | null>(null);
  let form = $state<Form | null>(null);
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);
  let uploading = $state(false);
  let loadError = $state("");
  let logoVersion = $state(Date.now());

  const dirty = $derived(!!saved && !!form && FIELDS.some((f) => form![f] !== saved![f]));

  function take(s: CentreSettings) {
    saved = s;
    form = Object.fromEntries(FIELDS.map((f) => [f, s[f] ?? ""])) as Form;
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
      notify("Centre settings saved.");
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fieldErrors).length) errors = err.fieldErrors;
      else notifyError(err, { title: "Couldn't save the settings" });
    } finally {
      saving = false;
    }
  }

  let wmUploading = $state(false);
  let wmVersion = $state(Date.now());

  async function uploadWordmark(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    wmUploading = true;
    const body = new FormData();
    body.append("wordmark", file);
    try {
      const res = await fetch("/api/settings/wordmark", { method: "POST", body, credentials: "same-origin",
                                                          headers: { "X-CSRF-Token": session.me?.csrf_token ?? "" } });
      const data = await res.json();
      if (!res.ok) throw new ApiError(res.status, data.message, data.field, data.detail ?? [], data.request_id);
      take(data);
      wmVersion = Date.now();
      await session.load(); // the menu and sign-in page pick it up
      notify("Logo with name updated.");
    } catch (err) {
      notifyError(err, { title: "Couldn't upload the logo" });
    } finally {
      wmUploading = false;
      input.value = "";
    }
  }

  async function removeWordmark() {
    wmUploading = true;
    try {
      const res = await fetch("/api/settings/wordmark", { method: "DELETE", credentials: "same-origin",
                                                          headers: { "X-CSRF-Token": session.me?.csrf_token ?? "" } });
      const data = await res.json();
      if (!res.ok) throw new ApiError(res.status, data.message, data.field, data.detail ?? [], data.request_id);
      take(data);
      await session.load();
      notify("Logo with name removed. The square logo and name are shown instead.");
    } catch (err) {
      notifyError(err);
    } finally {
      wmUploading = false;
    }
  }

  async function uploadLogo(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    if (!file) return;
    uploading = true;
    const body = new FormData();
    body.append("logo", file);
    try {
      const res = await fetch("/api/settings/logo", { method: "POST", body, credentials: "same-origin",
                                                      headers: { "X-CSRF-Token": session.me?.csrf_token ?? "" } });
      const data = await res.json();
      if (!res.ok) throw new ApiError(res.status, data.message, data.field, data.detail ?? [], data.request_id);
      take(data);
      logoVersion = Date.now();
      await session.load(); // the sidebar and sign-in page pick up the new logo
      notify("Logo updated.");
    } catch (err) {
      notifyError(err, { title: "Couldn't upload the logo" });
    } finally {
      uploading = false;
      (e.currentTarget as HTMLInputElement).value = "";
    }
  }
</script>

<PageHeader compact eyebrow="Settings" title="Centre details" description="What your bills, reports and sign-in page show.">
  {#snippet actions()}{#if saved}<span class="text-sm text-muted">Last saved {dateTime(saved.updated_at)}</span>{/if}{/snippet}
</PageHeader>

{#if loadError}
  <div class="alert alert-destructive" role="alert"><Icon name="alert" />{loadError}</div>
{:else if form && saved}
  <form class="card" onsubmit={save} novalidate>
    <div class="card-content stack-lg">
      <div class="form-section">
        <h2 class="form-section-title"><Icon name="building" /> Your centre</h2>
        <div class="stack">
          <div class="row" style="gap: 16px; align-items: center">
            {#if saved.logo_file}
              <img src="/api/workspace/logo?v={logoVersion}" alt="Current logo" width="72" height="72" style="border-radius: 12px; object-fit: contain; background: #fff; border: 1px solid var(--border); padding: 4px" />
            {:else}
              <span class="centre-mark" style="width:72px;height:72px;border-radius:12px;display:grid;place-items:center;background:var(--muted);color:var(--muted-foreground)"><Icon name="building" /></span>
            {/if}
            <div class="stack-sm">
              <label class="btn btn-outline" style="cursor: pointer">
                <Icon name="download" size="sm" class="flip-v" /> {uploading ? "Uploading…" : saved.logo_file ? "Change logo" : "Upload logo"}
                <input type="file" accept="image/png,image/jpeg,image/webp" class="sr-only" onchange={uploadLogo} disabled={uploading} />
              </label>
              <span class="hint">Square, PNG, JPG or WebP, up to 2 MB. Used where space is small, and as the app icon.</span>
            </div>
          </div>
          <div class="wordmark-row">
            <div class="wordmark-preview">
              {#if saved.wordmark_file}<img src="/api/workspace/wordmark?v={wmVersion}" alt="Current logo with name" />
              {:else}<span class="text-sm text-muted">No logo with name yet</span>{/if}
            </div>
            <div class="stack-sm">
              <div class="label-row"><span class="label">Logo with name and slogan</span>
                <InfoTip about="Logo with name and slogan" text="The wide version of your logo, with the centre's name and slogan in it. When set, it replaces the square logo and name at the top of the menu, on the sign-in page, on printed bills and on PDF downloads. A transparent PNG about 4 times wider than tall looks best." /></div>
              <div class="row" style="gap: 8px">
                <label class="btn btn-outline" style="cursor: pointer">
                  <Icon name="download" size="sm" class="flip-v" /> {wmUploading ? "Uploading…" : saved.wordmark_file ? "Change" : "Upload"}
                  <input type="file" accept="image/png,image/jpeg,image/webp" class="sr-only" onchange={uploadWordmark} disabled={wmUploading} />
                </label>
                {#if saved.wordmark_file}<button class="btn btn-ghost" type="button" disabled={wmUploading} onclick={removeWordmark}>Remove</button>{/if}
              </div>
              <span class="hint">Wide, PNG, JPG or WebP, up to 2 MB. Stored in the database.</span>
            </div>
          </div>
          <Field id="legal_name" label="Name on bills and reports" tip="Your registered business name. It is printed at the top of every bill and report, so use the exact legal name." required error={errors.legal_name}>
            {#snippet children({ invalid, describedby })}<input id="legal_name" class="input" bind:value={form!.legal_name} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
          </Field>
          <div class="grid-2">
            <Field id="tagline" label="Tagline" optional tip="Shown under your name on the sign-in page and the bill letterhead. Keep it short: one line." error={errors.tagline} hint="A short line under your name, e.g. Improving Lives Together.">
              {#snippet children({ invalid, describedby })}<input id="tagline" class="input" maxlength="120" bind:value={form!.tagline} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
            <Field id="brand_color" label="Brand colour" tip="A hex colour like #004aad. It colours your sign-in page, so staff know they are on your centre's address." error={errors.brand_color} hint="Used on your sign-in page.">
              {#snippet children({ invalid, describedby })}
                <div class="row"><input type="color" bind:value={form!.brand_color} aria-label="Pick a colour" style="width:48px;height:40px;padding:2px;border:1px solid var(--input);border-radius:6px;background:var(--background)" />
                  <input id="brand_color" class="input mono" bind:value={form!.brand_color} aria-invalid={invalid} aria-describedby={describedby} /></div>
              {/snippet}
            </Field>
          </div>
        </div>
      </div>

      <div class="form-section">
        <h2 class="form-section-title"><Icon name="info" /> Contact details</h2>
        <div class="stack">
          <Field id="address" label="Address" tip="Printed on bills and reports. Include the area, town and PIN code so patients can find you." error={errors.address}>
            {#snippet children({ invalid, describedby })}<textarea id="address" class="textarea" style="min-height:72px" bind:value={form!.address} aria-invalid={invalid} aria-describedby={describedby}></textarea>{/snippet}
          </Field>
          <div class="grid-2">
            <Field id="phones" label="Phone numbers" tip="Printed on bills and reports for patients to call. Add the country code, e.g. +91 76880 17623, and separate several with commas." error={errors.phones} hint="Separate several with commas.">
              {#snippet children({ invalid, describedby })}<input id="phones" class="input" bind:value={form!.phones} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
            <Field id="email" label="Email" optional tip="The centre's contact email, printed on bills. Staff sign-in emails are set separately in Staff." error={errors.email}>
              {#snippet children({ invalid, describedby })}<input id="email" class="input" type="email" bind:value={form!.email} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
          </div>
        </div>
      </div>

      <div class="form-section">
        <h2 class="form-section-title"><Icon name="receipt" /> Bills and reports</h2>
        <div class="stack">
          <div class="grid-2">
            <Field id="gst" label="GST number" optional tip="Your 15-character GSTIN, e.g. 19ABCDE1234F1Z5. When set, it is printed on every bill. Medical diagnostic services are usually GST-exempt; ask your accountant if unsure." error={errors.gst_number} hint="15 characters. Leave blank if you don't charge GST.">
              {#snippet children({ invalid, describedby })}<input id="gst" class="input mono" maxlength="15" bind:value={form!.gst_number} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
            <Field id="prefix" label="Bill number prefix" tip="The letters at the start of every bill number. Numbers restart from 1 each financial year (April). Changing it only affects new bills." required error={errors.invoice_prefix} hint="Bills are numbered like {form.invoice_prefix || 'SHC'}/2026-27/000123.">
              {#snippet children({ invalid, describedby })}<input id="prefix" class="input mono" maxlength="10" bind:value={form!.invoice_prefix} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
          </div>
          <Field id="bill_footer" label="Notes at the foot of every bill" optional tip="Short notes printed at the bottom of each bill, e.g. report collection times or refund policy. One note per line." error={errors.bill_footer}>
            {#snippet children({ invalid, describedby })}<textarea id="bill_footer" class="textarea" bind:value={form!.bill_footer} aria-invalid={invalid} aria-describedby={describedby}></textarea>{/snippet}
          </Field>
          <Field id="report_footer" label="Notes at the foot of every report" optional tip="Printed at the bottom of each medical report, e.g. 'This report is not valid for medico-legal purposes'. One note per line." error={errors.report_footer}>
            {#snippet children({ invalid, describedby })}<textarea id="report_footer" class="textarea" bind:value={form!.report_footer} aria-invalid={invalid} aria-describedby={describedby}></textarea>{/snippet}
          </Field>
        </div>
      </div>
    </div>
    <div class="card-footer">
      {#if dirty}<span class="text-sm text-muted" style="margin-right:auto">You have unsaved changes.</span>{/if}
      <button class="btn btn-outline" type="button" disabled={!dirty || saving} onclick={() => saved && take(saved)}>Discard</button>
      <button class="btn btn-primary" type="submit" disabled={saving || !dirty}><Icon name="check" /> {saving ? "Saving…" : "Save changes"}</button>
    </div>
  </form>
{:else}
  <div class="card"><div class="empty" aria-busy="true">Loading…</div></div>
{/if}

<style>
  .wordmark-row { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
  .wordmark-preview { display: grid; place-items: center; width: 260px; height: 72px; padding: 6px 10px; border: 1px solid var(--border); border-radius: 12px; background: #fff; }
  .wordmark-preview img { max-width: 100%; max-height: 100%; object-fit: contain; }
  :global(.flip-v) { transform: scaleY(-1); }
</style>
