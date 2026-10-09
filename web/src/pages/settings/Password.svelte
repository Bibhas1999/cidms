<script lang="ts">
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
  import { ApiError, post } from "../../lib/api";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import type { Me } from "../../lib/types";

  let current = $state("");
  let next = $state("");
  let again = $state("");
  let errors = $state<Record<string, string>>({});
  let busy = $state(false);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    errors = {};
    if (next !== again) { errors = { again: "The two new passwords don't match." }; return; }
    busy = true;
    try {
      session.setMe(await post<Me>("/api/auth/password", { current_password: current, new_password: next }));
      current = next = again = "";
      notify("Password changed. You've been signed out on your other devices.");
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fieldErrors).length) errors = err.fieldErrors;
      else notifyError(err, { title: "Couldn't change the password" });
    } finally {
      busy = false;
    }
  }
</script>

<form class="card" onsubmit={submit} novalidate>
  <div class="card-header"><div><h2 class="card-title">Password</h2>
    <p class="card-description">You stay signed in here; your other devices are signed out.</p></div></div>
  <div class="card-content stack" style="max-width: 460px">
    <Field id="pw-current" label="Current password" required error={errors.current_password}>
      {#snippet children({ invalid, describedby })}<input id="pw-current" class="input" type="password" autocomplete="current-password" bind:value={current} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
    </Field>
    <Field id="pw-new" label="New password" required error={errors.new_password} hint="At least 10 characters, mixing letters with numbers or symbols.">
      {#snippet children({ invalid, describedby })}<input id="pw-new" class="input" type="password" autocomplete="new-password" bind:value={next} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
    </Field>
    <Field id="pw-again" label="New password again" required error={errors.again}>
      {#snippet children({ invalid, describedby })}<input id="pw-again" class="input" type="password" autocomplete="new-password" bind:value={again} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
    </Field>
  </div>
  <div class="card-footer">
    <button class="btn btn-primary" type="submit" disabled={busy || !current || !next || !again}><Icon name="lock" /> {busy ? "Saving…" : "Change password"}</button>
  </div>
</form>
