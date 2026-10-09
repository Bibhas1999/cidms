<script lang="ts">
  import Field from "../components/Field.svelte";
  import { ApiError, post } from "../lib/api";
  import { navigate } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { notify, notifyError } from "../lib/toast.svelte";
  import type { Me } from "../lib/types";

  let current = $state("");
  let next = $state("");
  let confirm = $state("");
  let busy = $state(false);
  let errors = $state<Record<string, string>>({});
  let formError = $state("");

  const forced = $derived(session.me?.must_change_password ?? false);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    errors = {};
    formError = "";
    if (next !== confirm) {
      errors = { confirm: "The two new passwords don't match." };
      return;
    }
    busy = true;
    try {
      session.setMe(await post<Me>("/api/auth/password", { current_password: current, new_password: next }));
      notify("Password changed. You've been signed out on your other devices.");
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fieldErrors).length) errors = err.fieldErrors;
      else notifyError(err, { title: "Couldn't change the password" });
    } finally {
      busy = false;
    }
  }
</script>

<div class="wrap">
  <form class="card" onsubmit={submit} novalidate>
    <div class="card-body stack">
      <h1>{forced ? "Choose your own password" : "Change password"}</h1>
      {#if forced}<p class="muted">You signed in with a temporary password. Choose a new one to continue.</p>{/if}
      {#if formError}<div class="alert" role="alert">{formError}</div>{/if}
      <Field id="current" label={forced ? "Temporary password" : "Current password"} error={errors.current_password}>
        {#snippet children({ invalid, describedby })}
          <input id="current" type="password" autocomplete="current-password" bind:value={current} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="new" label="New password" error={errors.new_password} hint="At least 10 characters, mixing letters with numbers or symbols.">
        {#snippet children({ invalid, describedby })}
          <input id="new" type="password" autocomplete="new-password" bind:value={next} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="confirm" label="New password again" error={errors.confirm}>
        {#snippet children({ invalid, describedby })}
          <input id="confirm" type="password" autocomplete="new-password" bind:value={confirm} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <div class="toolbar">
        <button class="btn primary" type="submit" disabled={busy || !current || !next || !confirm}>{busy ? "Saving…" : "Save password"}</button>
        {#if forced}
          <button class="btn" type="button" onclick={() => session.logout()}>Sign out</button>
        {:else}
          <a class="btn" href="/">Cancel</a>
        {/if}
      </div>
    </div>
  </form>
</div>

<style>
  .wrap { min-height: 70vh; display: grid; place-items: center; padding: 16px; }
  form { width: min(440px, 100%); }
</style>
