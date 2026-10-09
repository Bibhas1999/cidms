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

  const forced = $derived(session.me?.must_change_password ?? false);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    errors = {};
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

<div class="pw-wrap">
  <form class="card" onsubmit={submit} novalidate style="width: min(460px, 100%)">
    <div class="card-header"><div>
      <span class="eyebrow">Your account</span>
      <h1 class="page-title" style="margin-top:8px">{forced ? "Choose your own password" : "Change password"}</h1>
      <p class="card-description">{forced ? "You signed in with a temporary password. Choose a new one to continue." : "You'll stay signed in here; other devices are signed out."}</p>
    </div></div>
    <div class="card-content stack">
      <Field id="current" label={forced ? "Temporary password" : "Current password"} required error={errors.current_password}>
        {#snippet children({ invalid, describedby })}
          <input id="current" class="input" type="password" autocomplete="current-password" bind:value={current} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="new" label="New password" required error={errors.new_password} hint="At least 10 characters, mixing letters with numbers or symbols.">
        {#snippet children({ invalid, describedby })}
          <input id="new" class="input" type="password" autocomplete="new-password" bind:value={next} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="confirm" label="New password again" required error={errors.confirm}>
        {#snippet children({ invalid, describedby })}
          <input id="confirm" class="input" type="password" autocomplete="new-password" bind:value={confirm} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
    </div>
    <div class="card-footer">
      {#if forced}<button class="btn btn-outline" type="button" onclick={() => session.logout()}>Sign out</button>
      {:else}<a class="btn btn-outline" href="/">Cancel</a>{/if}
      <button class="btn btn-primary" type="submit" disabled={busy || !current || !next || !confirm}>{busy ? "Saving…" : "Save password"}</button>
    </div>
  </form>
</div>

<style>
  .pw-wrap { min-height: 70vh; display: grid; place-items: center; padding: 16px; }
</style>
