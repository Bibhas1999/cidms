<script lang="ts">
  import PasswordInput from "../../components/PasswordInput.svelte";
  import { z } from "zod";
  import Avatar from "../../components/Avatar.svelte";
  import Field from "../../components/Field.svelte";
  import FileDrop from "../../components/FileDrop.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import { ApiError, api, put } from "../../lib/api";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import { Form } from "../../lib/form.svelte";
  import { email as emailRule, submitting } from "../../lib/schemas";
  import type { Me } from "../../lib/types";

  // The sign-in email: the owner and the centre admin may change their own (with their password); for
  // everyone else it's plain text.
  const canChangeEmail = !!session.me?.manage_own_account;
  let changingEmail = $state(false);
  const emailForm = new Form({
    schema: z.object({ email: emailRule("Enter the new email."), current_password: z.string().min(1, "Enter your current password.") }),
    initial: { email: "", current_password: "" },
    rules: (v, add) => { if (v.email.trim().toLowerCase() === session.me?.email) add("email", "That's already your email."); },
    onSubmit: async (v) => {
      session.setMe(await put<Me>("/api/auth/email", { email: v.email.toLowerCase(), current_password: v.current_password }));
      notify(`You now sign in with ${session.me?.email}.`);
      changingEmail = false;
      emailForm.reset();
    },
  });

  let name = $state(session.me?.full_name ?? "");
  let mobile = $state(session.me?.mobile ?? "");
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);
  let uploading = $state(false);

  const dirty = $derived(name.trim() !== session.me?.full_name || mobile.trim() !== (session.me?.mobile ?? ""));

  async function save(e: SubmitEvent) {
    e.preventDefault();
    saving = true; errors = {};
    try {
      session.setMe(await put<Me>("/api/auth/profile", { full_name: name.trim(), mobile: mobile.trim() }));
      notify("Your profile is saved.");
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fieldErrors).length) errors = err.fieldErrors;
      else notifyError(err, { title: "Couldn't save your profile" });
    } finally {
      saving = false;
    }
  }

  async function upload(file: File) {
    uploading = true;
    const body = new FormData();
    body.append("avatar", file);
    try {
      const res = await fetch("/api/auth/avatar", { method: "POST", body, credentials: "same-origin", headers: { "X-CSRF-Token": session.me?.csrf_token ?? "" } });
      const data = await res.json();
      if (!res.ok) throw new ApiError(res.status, data.message, data.field, data.detail ?? [], data.request_id);
      session.setMe(data);
      notify("Your picture is updated.");
    } catch (err) {
      notifyError(err, { title: "Couldn't upload the picture" });
    } finally {
      uploading = false;
    }
  }

  async function removePicture() {
    try {
      session.setMe(await api<Me>("DELETE", "/api/auth/avatar"));
      notify("Your picture is removed.");
    } catch (err) {
      notifyError(err, { title: "Couldn't remove the picture" });
    }
  }
</script>

<form class="card" onsubmit={save} novalidate>
  <div class="card-header"><div><h2 class="card-title">My profile</h2>
    <p class="card-description">How you appear to your colleagues, on bills you create and in the activity log.</p></div></div>
  <div class="card-content stack-lg">
    <div class="row" style="gap: 20px">
      <Avatar name={session.me?.full_name ?? ""} url={session.me?.avatar_url} size="lg" />
      <div class="stack-sm">
        <div class="row-wrap">
          <FileDrop variant="button" accept="image/png,image/jpeg,image/webp" disabled={uploading} onfiles={(files) => upload(files[0])}>
            <span class="btn btn-outline">
              <Icon name="user" size="sm" /> {uploading ? "Uploading…" : session.me?.avatar_url ? "Change picture" : "Add a picture"}
            </span>
          </FileDrop>
          {#if session.me?.avatar_url}<button type="button" class="btn btn-ghost-destructive" onclick={removePicture}>Remove</button>{/if}
        </div>
        <span class="hint">A square photo works best. PNG, JPG or WebP, up to 2 MB.</span>
      </div>
    </div>
    <div class="grid-2">
      <Field id="p-name" label="Full name" required error={errors.full_name} tip="As colleagues should see it, on bills you create and in the activity log.">
        {#snippet children({ invalid, describedby })}<input id="p-name" class="input" autocomplete="name" bind:value={name} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
      <Field id="p-mobile" label="Mobile" optional error={errors.mobile} tip="So the centre can reach you. Not shown to patients.">
        {#snippet children({ invalid, describedby })}<input id="p-mobile" class="input tabular" type="tel" autocomplete="tel" bind:value={mobile} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
    </div>
    <div class="stack-sm">
      <span class="label">Sign-in email</span>
      <div class="row-wrap"><span class="tabular">{session.me?.email}</span>
        {#if canChangeEmail && !changingEmail}<button type="button" class="link-button text-sm" onclick={() => (changingEmail = true)}>Change email</button>{/if}</div>
    </div>
    <div class="row-wrap"><span class="text-sm text-muted">Your roles:</span>{#each session.me?.roles ?? [] as r (r)}<span class="badge badge-navy badge-plain">{r}</span>{/each}</div>
  </div>
  <div class="card-footer">
    <button class="btn btn-outline" type="button" disabled={!dirty || saving} onclick={() => { name = session.me?.full_name ?? ""; mobile = session.me?.mobile ?? ""; }}>Discard</button>
    <button class="btn btn-primary" type="submit" disabled={!dirty || saving}><Icon name="check" /> {saving ? "Saving…" : "Save changes"}</button>
  </div>
</form>

{#if canChangeEmail && changingEmail}
  <form class="card" onsubmit={submitting(emailForm, "Couldn't change your email")} novalidate>
    <div class="card-header"><div><h2 class="card-title">Change sign-in email</h2>
      <p class="card-description">You'll sign in with the new email from now on. You stay signed in here.</p></div></div>
    <div class="card-content stack" style="max-width: 460px">
      <FormErrors form={emailForm} labels={{ email: "New email", current_password: "Current password" }} idPrefix="em-" />
      <Field id="em-email" label="New email" required error={emailForm.error("email")} tip="It must not already be used by someone else at this centre.">
        {#snippet children({ invalid, describedby })}<input id="em-email" class="input" type="email" autocomplete="email" bind:value={emailForm.values.email} {...emailForm.field("email")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
      <Field id="em-current_password" label="Current password" required error={emailForm.error("current_password")} tip="To confirm it's you.">
        {#snippet children({ invalid, describedby })}<PasswordInput id="em-current_password" autocomplete="current-password" bind:value={emailForm.values.current_password} {...emailForm.field("current_password")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
    </div>
    <div class="card-footer">
      <button class="btn btn-outline" type="button" disabled={emailForm.submitting} onclick={() => { changingEmail = false; emailForm.reset(); }}>Cancel</button>
      <button class="btn btn-primary" type="submit" disabled={emailForm.submitting}><Icon name="check" /> {emailForm.submitting ? "Saving…" : "Change email"}</button>
    </div>
  </form>
{/if}
