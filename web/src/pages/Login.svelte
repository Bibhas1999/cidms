<script lang="ts">
  import { tooltip } from "../lib/tooltip";
  import AuthLayout from "../components/AuthLayout.svelte";
  import { forgetAccount, recentAccounts, type RecentAccount } from "../lib/accounts";
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

  // Accounts used on this computer before (names and emails only): pick one and type its password.
  let accounts = $state<RecentAccount[]>(recentAccounts());
  let chosen = $state<RecentAccount | null>(null);
  let useOther = $state(recentAccounts().length === 0);
  let passwordInput = $state<HTMLInputElement>();

  function choose(a: RecentAccount) {
    chosen = a;
    email = a.email;
    password = "";
    queueMicrotask(() => passwordInput?.focus());
  }

  function other() {
    chosen = null;
    email = "";
    password = "";
    useOther = true;
  }

  function forget(a: RecentAccount) {
    forgetAccount(a.email);
    accounts = recentAccounts();
    if (!accounts.length) useOther = true;
  }

  const initials = (n: string) => n.split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

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
        <h2>{chosen ? `Hello, ${chosen.name.split(" ")[0]}` : router.query.get("switch") ? "Switch account" : "Welcome back"}</h2>
        <p class="muted">Sign in to {isPlatform ? "the platform" : ws?.name}</p>
      </div>

      {#if !useOther && !chosen}
        <div class="accounts" role="list" aria-label="Accounts used on this computer">
          {#each accounts as a (a.email)}
            <div class="account" role="listitem">
              <button type="button" class="account-pick" onclick={() => choose(a)}>
                <span class="account-avatar" aria-hidden="true">{initials(a.name)}</span>
                <span class="account-text"><span class="account-name">{a.name}</span><span class="account-email">{a.email}</span></span>
              </button>
              <button type="button" class="account-forget" aria-label="Remove {a.name} from this computer" use:tooltip={"Remove from this computer"} onclick={() => forget(a)}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>
              </button>
            </div>
          {/each}
        </div>
        <button type="button" class="other" onclick={other}>Use another account</button>
      {:else}
      {#if chosen}
        <div class="account is-chosen">
          <span class="account-avatar" aria-hidden="true">{initials(chosen.name)}</span>
          <span class="account-text"><span class="account-name">{chosen.name}</span><span class="account-email">{chosen.email}</span></span>
          <button type="button" class="other" onclick={() => { chosen = null; useOther = accounts.length === 0; }}>Not you?</button>
        </div>
      {:else}
      <div class="field">
        <label for="login-email">Email</label>
        <span class="control">
          <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m4 7 8 6 8-6" /></svg>
          <input id="login-email" type="email" autocomplete="username" placeholder="you@example.com" bind:value={email} required aria-invalid={failed} />
        </span>
      </div>
      {/if}

      <div class="field">
        <label for="login-password">Password</label>
        <span class="control">
          <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>
          <input id="login-password" class="password" bind:this={passwordInput} type={showPassword ? "text" : "password"} autocomplete="current-password" bind:value={password}
                 onkeydown={onKey} onkeyup={onKey} required aria-invalid={failed} />
          <button type="button" class="reveal" aria-label={showPassword ? "Hide password" : "Show password"}
                  use:tooltip={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword}
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
      {#if accounts.length && !chosen}<button type="button" class="other" onclick={() => (useOther = false)}>Choose a recent account</button>{/if}
      {/if}
    </form>
</AuthLayout>

<style>
  .accounts { display: grid; gap: 8px; }
  .account { display: flex; align-items: center; gap: 8px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
  .account:hover { border-color: var(--brand); }
  .account.is-chosen { padding: 10px 12px; background: var(--surface-2); }
  .account-pick { flex: 1; min-width: 0; display: flex; align-items: center; gap: 12px; padding: 10px 12px; border: 0; background: none; cursor: pointer; text-align: left; font: inherit; color: inherit; }
  .account-avatar { width: 38px; height: 38px; flex: none; border-radius: 50%; display: grid; place-items: center; background: var(--brand); color: #fff; font-weight: 700; font-size: 14px; }
  .account-text { min-width: 0; display: flex; flex-direction: column; }
  .account-name { font-weight: 650; }
  .account-email { font-size: 12.5px; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .account-forget { flex: none; width: 34px; height: 34px; margin-right: 6px; display: grid; place-items: center; border: 0; border-radius: 8px; background: none; color: var(--text-2); cursor: pointer; }
  .account-forget:hover { background: var(--surface-2); }
  .account-forget svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; }
  .other { justify-self: center; border: 0; background: none; color: var(--brand); font: inherit; font-weight: 600; font-size: 13px; cursor: pointer; padding: 4px; margin-left: auto; }
  .other:hover { text-decoration: underline; }
  .reveal { position: absolute; right: 4px; width: 30px; height: 30px; display: grid; place-items: center; border: 0; border-radius: 8px;
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
