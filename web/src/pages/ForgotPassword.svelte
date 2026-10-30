<script lang="ts">
  import Icon from "../components/Icon.svelte";
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
        <Icon name="mail" />
        <p>{sent} Check your spam folder if it doesn't arrive in a few minutes.</p>
      </div>
    {:else}
      <label class="field">
        <span>Email</span>
        <span class="control">
          <Icon name="mail" />
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

<style src="./styles/ForgotPassword.css"></style>
