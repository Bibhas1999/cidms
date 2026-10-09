<script lang="ts">
  import AuthLayout from "../components/AuthLayout.svelte";
  import { ApiError } from "../lib/api";
  import { navigate, router } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { notifyError } from "../lib/toast.svelte";

  let email = $state("");
  let password = $state("");
  let showPassword = $state(false);
  let capsLock = $state(false);
  let remember = $state(false);
  let busy = $state(false);
  let failed = $state(false);

  const ws = $derived(session.workspace);
  const isPlatform = $derived(ws?.kind === "platform");

  /** Only return to an address inside the app, never to another site. */
  function safeNext(): string {
    const next = router.query.get("next") ?? "/";
    return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login") ? next : "/";
  }

  function onKey(e: KeyboardEvent) {
    capsLock = e.getModifierState?.("CapsLock") ?? false;
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    failed = false;
    try {
      const me = await session.login(email, password, remember);
      navigate(me.must_change_password ? "/change-password" : safeNext(), { replace: true });
    } catch (err) {
      failed = err instanceof ApiError && err.status === 401;
      notifyError(err, { title: "Sign-in failed", fallback: "Couldn't sign in. Please try again." });
      password = "";
    } finally {
      busy = false;
    }
  }
</script>

<AuthLayout>
    <form class="form" onsubmit={submit} novalidate>
      <div class="heading">
        <h2>Welcome back</h2>
        <p class="muted">Sign in to {isPlatform ? "the platform" : ws?.name}</p>
      </div>

      <div class="field">
        <label for="login-email">Email</label>
        <span class="control">
          <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m4 7 8 6 8-6" /></svg>
          <input id="login-email" type="email" autocomplete="username" placeholder="you@example.com" bind:value={email} required aria-invalid={failed} />
        </span>
      </div>

      <div class="field">
        <label for="login-password">Password</label>
        <span class="control">
          <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>
          <input id="login-password" class="password" type={showPassword ? "text" : "password"} autocomplete="current-password" bind:value={password}
                 onkeydown={onKey} onkeyup={onKey} required aria-invalid={failed} />
          <button type="button" class="reveal" aria-label={showPassword ? "Hide password" : "Show password"}
                  title={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword}
                  onclick={() => (showPassword = !showPassword)}>
            {#if showPassword}
              <!-- eye-off -->
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3l18 18" /><path d="M10.6 5.1A10 10 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-3.2 4.1M6.6 6.6A17 17 0 0 0 2.5 12S6 19 12 19a9.6 9.6 0 0 0 5.4-1.6" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" /></svg>
            {:else}
              <!-- eye -->
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7z" /><circle cx="12" cy="12" r="3" /></svg>
            {/if}
          </button>
        </span>
        {#if capsLock}<span class="caps" role="status">Caps Lock is on</span>{/if}
      </div>

      <div class="options">
        <label class="remember">
          <input type="checkbox" bind:checked={remember} />
          <span>Remember me <span class="muted">for 30 days</span></span>
        </label>
        <a class="forgot" href="/forgot-password{email ? `?email=${encodeURIComponent(email)}` : ''}">Forgot password?</a>
      </div>

      <button class="submit" type="submit" disabled={busy || !email || !password}>
        {#if busy}<span class="spinner" aria-hidden="true"></span>Signing in…{:else}Sign in{/if}
      </button>

      <p class="help muted">Don't tick "Remember me" on a computer other people use.</p>
    </form>
</AuthLayout>

<style>
  .reveal { position: absolute; right: 6px; width: 34px; height: 34px; display: grid; place-items: center; border: 0; border-radius: 8px;
    background: transparent; color: var(--text-2); cursor: pointer; }
  .reveal:hover { background: var(--surface-2); }
  .reveal svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
  .password { padding-right: 46px !important; }
  .caps { color: var(--warning); font-weight: 500; font-size: 12px; }
  .options { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; font-size: 13px; }
  .remember { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  .remember input { width: 16px; height: 16px; accent-color: var(--brand); }
  .forgot { color: var(--brand); font-weight: 600; text-decoration: none; }
  .forgot:hover { text-decoration: underline; }
</style>
