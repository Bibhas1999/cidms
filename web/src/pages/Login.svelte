<script lang="ts">
  import Field from "../components/Field.svelte";
  import { ApiError } from "../lib/api";
  import { navigate, router } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";

  let email = $state("");
  let password = $state("");
  let busy = $state(false);
  let error = $state("");

  /** Only return to an address inside the app, never to another site. */
  function safeNext(): string {
    const next = router.query.get("next") ?? "/";
    return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login") ? next : "/";
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    error = "";
    try {
      const me = await session.login(email, password);
      navigate(me.must_change_password ? "/change-password" : safeNext(), { replace: true });
    } catch (err) {
      error = err instanceof ApiError ? err.message : "Couldn't sign in. Please try again.";
      password = "";
    } finally {
      busy = false;
    }
  }
</script>

<div class="wrap">
  <form class="card" onsubmit={submit} novalidate>
    <div class="card-body stack">
      <div>
        <div class="product">Supreme DMS</div>
        <h1>Sign in to {session.workspace?.name}</h1>
      </div>
      {#if error}<div class="alert" role="alert">{error}</div>{/if}
      <Field id="email" label="Email">
        {#snippet children()}<input id="email" type="email" autocomplete="username" bind:value={email} required />{/snippet}
      </Field>
      <Field id="password" label="Password">
        {#snippet children()}<input id="password" type="password" autocomplete="current-password" bind:value={password} required />{/snippet}
      </Field>
      <button class="btn primary" type="submit" disabled={busy || !email || !password}>{busy ? "Signing in…" : "Sign in"}</button>
      <p class="muted small">Forgot your password? Ask your centre's owner or admin to reset it.</p>
    </div>
  </form>
</div>

<style>
  .wrap { min-height: 100vh; display: grid; place-items: center; padding: 16px; }
  form { width: min(400px, 100%); }
  .product { color: var(--brand); font-weight: 700; margin-bottom: 4px; }
  .small { font-size: 12px; margin: 0; }
  button[type="submit"] { justify-content: center; height: 40px; }
</style>
