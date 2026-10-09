<script lang="ts">
  import AuthLayout from "../components/AuthLayout.svelte";
  import { post } from "../lib/api";
  import { router } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { notifyError } from "../lib/toast.svelte";

  let email = $state(router.query.get("email") ?? "");
  let busy = $state(false);
  let sent = $state("");

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    try {
      sent = (await post<{ message: string }>("/api/auth/forgot-password", { email: email.trim() })).message;
    } catch (err) {
      notifyError(err, { title: "Couldn't send the link" });
    } finally {
      busy = false;
    }
  }
</script>

<AuthLayout>
  <form class="form" onsubmit={submit} novalidate>
    <div class="heading">
      <h2>Forgot your password?</h2>
      <p class="muted">Enter the email you sign in with at {session.workspace?.kind === "platform" ? "the platform" : session.workspace?.name}. We'll email you a link to choose a new one.</p>
    </div>

    {#if sent}
      <div class="sent" role="status">
        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m4 7 8 6 8-6" /></svg>
        <p>{sent} Check your spam folder if it doesn't arrive in a few minutes.</p>
      </div>
    {:else}
      <label class="field">
        <span>Email</span>
        <span class="control">
          <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m4 7 8 6 8-6" /></svg>
          <input type="email" autocomplete="username" placeholder="you@example.com" bind:value={email} required />
        </span>
      </label>
      <button class="submit" type="submit" disabled={busy || !email.trim()}>
        {#if busy}<span class="spinner" aria-hidden="true"></span>Sending…{:else}Email me a reset link{/if}
      </button>
    {/if}

    <a class="back" href="/login">Back to sign in</a>
  </form>
</AuthLayout>

<style>
  .sent { display: flex; gap: 12px; align-items: flex-start; padding: 14px; border-radius: 10px; background: var(--success-tint); color: var(--text); }
  .sent p { margin: 0; line-height: 1.5; }
  .sent svg { width: 22px; height: 22px; flex: none; fill: none; stroke: var(--success); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
</style>
