<script lang="ts">
  import Icon from "../components/Icon.svelte";
  import { tooltip } from "../lib/tooltip";
  import AuthLayout from "../components/AuthLayout.svelte";
  import { forgetAccount, recentAccounts, type RecentAccount } from "../lib/accounts";
  import { ApiError } from "../lib/api";
  import { navigate, router, safeNext, withNext } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { notifyError } from "../lib/toast.svelte";

  let email = $state("");
  let password = $state("");
  let showPassword = $state(false);
  let capsLock = $state(false);
  let remember = $state(false);
  let busy = $state(false);
  let failed = $state(false);

  // Accounts used on this computer before, any centre's address (names and emails only): pick one and type
  // its password. One from another centre takes you to that centre's own sign-in page first.
  const queryEmail = router.query.get("email");
  const initialChosen: RecentAccount | null = queryEmail
    ? { email: queryEmail, name: router.query.get("name") || queryEmail, host: location.host }
    : null;

  let accounts = $state<RecentAccount[]>(recentAccounts());
  let chosen = $state<RecentAccount | null>(initialChosen);
  let useOther = $state(recentAccounts().length === 0 && !initialChosen);
  let passwordInput = $state<HTMLInputElement>();

  if (initialChosen) email = initialChosen.email;

  function choose(a: RecentAccount) {
    if (a.host !== location.host) {
      location.href = `${location.protocol}//${a.host}/login?email=${encodeURIComponent(a.email)}&name=${encodeURIComponent(a.name)}`;
      return;
    }
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
    forgetAccount(a.email, a.host);
    accounts = recentAccounts();
    if (!accounts.length) useOther = true;
  }

  const initials = (n: string) => n.split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

  const ws = $derived(session.workspace);
  const isPlatform = $derived(ws?.kind === "platform");

  function onKey(e: KeyboardEvent) {
    capsLock = e.getModifierState?.("CapsLock") ?? false;
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    failed = false;
    try {
      const me = await session.login(email, password, remember);
      navigate(me.must_change_password ? withNext("/change-password", router.query.get("next") ?? "") : safeNext(), { replace: true });
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
        <p class="muted">Sign in to {isPlatform ? "the CIDMS platform" : ws?.name}</p>
      </div>

      {#if !useOther && !chosen}
        <div class="accounts" role="list" aria-label="Accounts used on this computer">
          {#each accounts as a (`${a.email}|${a.host}`)}
            <div class="account" role="listitem">
              <button type="button" class="account-pick" onclick={() => choose(a)}>
                <span class="account-avatar" aria-hidden="true">{initials(a.name)}</span>
                <span class="account-text"><span class="account-name">{a.name}</span>
                  <span class="account-email">{a.email}{#if a.host !== location.host} · {a.centreName || a.host}{/if}</span></span>
              </button>
              <button type="button" class="account-forget" aria-label="Remove {a.name} from this computer" use:tooltip={"Remove from this computer"} onclick={() => forget(a)}>
                <Icon name="x" />
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
          <Icon name="mail" />
          <input id="login-email" type="email" autocomplete="username" placeholder="you@example.com" bind:value={email} required aria-invalid={failed} />
        </span>
      </div>
      {/if}

      <div class="field">
        <label for="login-password">Password</label>
        <span class="control">
          <Icon name="lock" />
          <input id="login-password" class="password" bind:this={passwordInput} type={showPassword ? "text" : "password"} autocomplete="current-password" bind:value={password}
                 onkeydown={onKey} onkeyup={onKey} required aria-invalid={failed} />
          <button type="button" class="reveal" aria-label={showPassword ? "Hide password" : "Show password"}
                  use:tooltip={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword}
                  onclick={() => (showPassword = !showPassword)}>
            {#if showPassword}
              <!-- eye-off -->
              <Icon name="eyeOff" />
            {:else}
              <!-- eye -->
              <Icon name="eye" />
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

<style src="./styles/Login.css"></style>
