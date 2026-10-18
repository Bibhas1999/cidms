<script lang="ts">
  import Icon from "../components/Icon.svelte";
  import AuthLayout from "../components/AuthLayout.svelte";
  import { ApiError, post } from "../lib/api";
  import { navigate, router } from "../lib/router.svelte";
  import { notify, notifyError } from "../lib/toast.svelte";

  const token = router.query.get("token") ?? "";
  let password = $state("");
  let again = $state("");
  let show = $state(false);
  let busy = $state(false);
  let errors = $state<Record<string, string>>({});

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    errors = {};
    if (password !== again) {
      errors = { again: "The two passwords don't match." };
      return;
    }
    busy = true;
    try {
      await post("/api/auth/reset-password", { token, new_password: password });
      notify("Your password has been changed. Sign in with the new one.", { title: "Password changed" });
      navigate("/login", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.field === "new_password") errors = { new_password: err.message };
      else notifyError(err, { title: "Couldn't change the password" });
    } finally {
      busy = false;
    }
  }
</script>

<AuthLayout>
  <form class="form" onsubmit={submit} novalidate>
    <div class="heading">
      <h2>Choose a new password</h2>
      <p class="muted">At least 10 characters, mixing letters with numbers or symbols.</p>
    </div>

    {#if !token}
      <p class="muted">This link is incomplete. Open the link from the email again, or ask for a new one.</p>
      <a class="back" href="/forgot-password">Ask for a new link</a>
    {:else}
      <label class="field">
        <span>New password</span>
        <span class="control">
          <Icon name="lock" />
          <input type={show ? "text" : "password"} autocomplete="new-password" bind:value={password}
                 aria-invalid={!!errors.new_password} aria-describedby={errors.new_password ? "pw-error" : undefined} />
        </span>
        {#if errors.new_password}<span id="pw-error" class="error">{errors.new_password}</span>{/if}
      </label>
      <label class="field">
        <span>New password again</span>
        <span class="control">
          <Icon name="lock" />
          <input type={show ? "text" : "password"} autocomplete="new-password" bind:value={again}
                 aria-invalid={!!errors.again} aria-describedby={errors.again ? "again-error" : undefined} />
        </span>
        {#if errors.again}<span id="again-error" class="error">{errors.again}</span>{/if}
      </label>
      <label class="show"><input type="checkbox" bind:checked={show} /> Show passwords</label>
      <button class="submit" type="submit" disabled={busy || !password || !again}>
        {#if busy}<span class="spinner" aria-hidden="true"></span>Saving…{:else}Save new password{/if}
      </button>
      <a class="back" href="/login">Back to sign in</a>
    {/if}
  </form>
</AuthLayout>

<style>
  .error { color: var(--danger); font-weight: 500; font-size: 12px; }
  .show { display: flex; gap: 8px; align-items: center; font-size: 13px; cursor: pointer; }
  .show input { width: 16px; height: 16px; accent-color: var(--brand); }
</style>
