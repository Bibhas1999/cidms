<script lang="ts">
  import type { Component } from "svelte";
  import AppShell from "./components/AppShell.svelte";
  import ConfirmHost from "./components/ConfirmHost.svelte";
  import ErrorFallback from "./components/ErrorFallback.svelte";
  import Toasts from "./components/Toasts.svelte";
  import { reportError } from "./lib/errors";
  import { navigate, router } from "./lib/router.svelte";
  import { session } from "./lib/session.svelte";
  import Activity from "./pages/Activity.svelte";
  import ChangePassword from "./pages/ChangePassword.svelte";
  import Dashboard from "./pages/Dashboard.svelte";
  import ForgotPassword from "./pages/ForgotPassword.svelte";
  import Login from "./pages/Login.svelte";
  import ResetPassword from "./pages/ResetPassword.svelte";
  import Message from "./pages/Message.svelte";
  import Clients from "./pages/platform/Clients.svelte";
  import Settings from "./pages/Settings.svelte";
  import Staff from "./pages/Staff.svelte";

  interface Route {
    component: Component<any>;
    title: string;
    /** Permission needed in a client workspace / in the platform workspace. undefined = everyone; null = not here. */
    client?: string | null;
    platform?: string | null;
  }

  const routes: Record<string, Route> = {
    "/": { component: Dashboard, title: "Dashboard" },
    "/staff": { component: Staff, title: "Staff", client: "staff.manage", platform: "platform.staff.manage" },
    "/settings": { component: Settings, title: "Centre settings", client: "settings.manage", platform: null },
    "/activity": { component: Activity, title: "Activity log", client: "activity.view", platform: "platform.activity.view" },
    "/clients": { component: Clients, title: "Clients", client: null, platform: "platform.clients.view" },
    "/change-password": { component: ChangePassword, title: "Change password" },
  };

  // Pages for people who aren't signed in.
  const PUBLIC = ["/login", "/forgot-password", "/reset-password"];

  let startError = $state("");

  $effect(() => {
    session.load().catch((e) => {
      startError = e?.message ?? "Supreme DMS couldn't start.";
      reportError("error", e);
    });
  });

  const route = $derived(routes[router.path]);
  const allowed = $derived.by(() => {
    if (!route) return false;
    const need = session.isPlatform ? route.platform : route.client;
    return need === undefined || (need !== null && session.can(need));
  });

  // Where someone may be: signed out -> sign-in; temporary password -> choose one first; signed in -> not the sign-in page.
  $effect(() => {
    if (!session.ready || session.workspace?.kind === "none") return;
    const path = router.path;
    if (!session.me) {
      if (!PUBLIC.includes(path)) navigate(`/login${path === "/" ? "" : `?next=${encodeURIComponent(path + router.search)}`}`, { replace: true });
    } else if (session.me.must_change_password && path !== "/change-password") {
      navigate("/change-password", { replace: true });
    } else if (PUBLIC.includes(path)) {
      navigate("/", { replace: true });
    }
  });

  $effect(() => {
    const where = session.workspace?.name ? ` · ${session.workspace.name}` : "";
    const titles: Record<string, string> = { "/login": "Sign in", "/forgot-password": "Forgot password", "/reset-password": "Choose a new password" };
    document.title = `${titles[router.path] ?? route?.title ?? "Not found"}${where} · Supreme DMS`;
  });
</script>

{#snippet guarded(Page: Component<any>)}
  <!-- A crash while drawing one screen shows a fallback for that screen only; the menu and top bar keep working. -->
  {#key router.path}
    <svelte:boundary onerror={(error) => reportError("boundary", error)}>
      <Page />
      {#snippet failed(error, reset)}<ErrorFallback {error} {reset} />{/snippet}
    </svelte:boundary>
  {/key}
{/snippet}

{#if startError}
  <Message title="Supreme DMS couldn't start" text="{startError} Refresh the page to try again." action={false} />
{:else if !session.ready}
  <div class="splash" aria-busy="true"><span class="muted">Loading…</span></div>
{:else if session.workspace?.kind === "none"}
  <div class="nows">
    <div class="card card-body stack">
      <h1>There's no workspace at this address</h1>
      <p class="muted">Each centre has its own address, with the centre's name at the front. Use the address your centre gave you.</p>
      {#if session.workspace.links?.length}
        <p>On this computer, open one of these:</p>
        <ul>
          {#each session.workspace.links as link (link.url)}<li><a href={link.url}>{link.name}</a> <span class="muted mono">{link.url}</span></li>{/each}
        </ul>
      {/if}
    </div>
  </div>
{:else if !session.me}
  {#if router.path === "/login"}{@render guarded(Login)}
  {:else if router.path === "/forgot-password"}{@render guarded(ForgotPassword)}
  {:else if router.path === "/reset-password"}{@render guarded(ResetPassword)}{/if}
{:else if session.me.must_change_password}
  {#if router.path === "/change-password"}{@render guarded(ChangePassword)}{/if}
{:else}
  <AppShell>
    {#if !route}
      <Message title="We couldn't find that page" text="The address may be mistyped, or the page may have moved." />
    {:else if !allowed}
      <Message title="You don't have access to this page" text="Ask your centre's owner or admin if you need it." />
    {:else}
      {@render guarded(route.component)}
    {/if}
  </AppShell>
{/if}

<Toasts />
<ConfirmHost />

<style>
  .splash { min-height: 100vh; display: grid; place-items: center; }
  .nows { display: grid; place-items: center; min-height: 80vh; padding: 16px; }
  .nows .card { max-width: 560px; }
  .nows ul { margin: 0; padding-left: 20px; display: grid; gap: 6px; }
  .nows p { margin: 0; }
</style>
