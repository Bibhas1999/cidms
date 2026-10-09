<script lang="ts">
  import Avatar from "../../components/Avatar.svelte";
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
  import { ApiError, api, put } from "../../lib/api";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import type { Me } from "../../lib/types";

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

  async function upload(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
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
      input.value = "";
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
          <label class="btn btn-outline" style="cursor: pointer">
            <Icon name="user" size="sm" /> {uploading ? "Uploading…" : session.me?.avatar_url ? "Change picture" : "Add a picture"}
            <input type="file" accept="image/png,image/jpeg,image/webp" class="sr-only" onchange={upload} disabled={uploading} />
          </label>
          {#if session.me?.avatar_url}<button type="button" class="btn btn-ghost-destructive" onclick={removePicture}>Remove</button>{/if}
        </div>
        <span class="hint">A square photo works best. PNG, JPG or WebP, up to 2 MB.</span>
      </div>
    </div>
    <div class="grid-2">
      <Field id="p-name" label="Full name" required error={errors.full_name}>
        {#snippet children({ invalid, describedby })}<input id="p-name" class="input" autocomplete="name" bind:value={name} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
      <Field id="p-mobile" label="Mobile" error={errors.mobile}>
        {#snippet children({ invalid, describedby })}<input id="p-mobile" class="input tabular" type="tel" autocomplete="tel" bind:value={mobile} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
    </div>
    <Field id="p-email" label="Email" hint="You sign in with this, so it can't be changed here. Ask your owner or admin if it needs to change.">
      {#snippet children({ describedby })}<input id="p-email" class="input" value={session.me?.email} disabled aria-describedby={describedby} />{/snippet}
    </Field>
    <div class="row-wrap"><span class="text-sm text-muted">Your roles:</span>{#each session.me?.roles ?? [] as r (r)}<span class="badge badge-navy badge-plain">{r}</span>{/each}</div>
  </div>
  <div class="card-footer">
    <button class="btn btn-outline" type="button" disabled={!dirty || saving} onclick={() => { name = session.me?.full_name ?? ""; mobile = session.me?.mobile ?? ""; }}>Discard</button>
    <button class="btn btn-primary" type="submit" disabled={!dirty || saving}><Icon name="check" /> {saving ? "Saving…" : "Save changes"}</button>
  </div>
</form>
