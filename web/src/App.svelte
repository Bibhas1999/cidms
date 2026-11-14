<script lang="ts">
  import type { Component } from "svelte";
  import { untrack } from "svelte";
  import AppShell from "./components/AppShell.svelte";
  import ConfirmHost from "./components/ConfirmHost.svelte";
  import ErrorFallback from "./components/ErrorFallback.svelte";
  import OfflineBanner from "./components/OfflineBanner.svelte";
  import Toasts from "./components/Toasts.svelte";
  import { reportError } from "./lib/errors";
  import { navigate, router, withNext } from "./lib/router.svelte";
  import { FEATURES } from "./lib/features";
  import { session } from "./lib/session.svelte";
  import Landing from "./pages/Landing.svelte";
  import Message from "./pages/Message.svelte";

  /** What a page loads with (its own chunk, fetched the first time its route is opened). */
  type Loader = () => Promise<{ default: Component<any> }>;

  interface Route {
    path: string;              // "/bills/:id" captures id
    component: Loader;
    title: string;
    /** Permission needed in a client workspace / in the platform workspace. undefined = everyone; null = not here. */
    client?: string | null;
    platform?: string | null;
    /** Drawn without the menu and top bar (printouts). */
    bare?: boolean;
  }

  const CLIENT_ONLY = { platform: null };
  const routes: Route[] = [
    { path: "/", component: () => import("./pages/Dashboard.svelte"), title: "Dashboard" },
    { path: "/analytics", component: () => import("./pages/Analytics.svelte"), title: "Analytics", client: "analytics.view", platform: null },
    { path: "/bills", component: () => import("./pages/bills/Bills.svelte"), title: "Bills", ...CLIENT_ONLY },
    { path: "/bills/new", component: () => import("./pages/bills/NewBill.svelte"), title: "New Bill", client: "billing.create", platform: null },
    { path: "/bills/offline", component: () => import("./pages/bills/OfflineBills.svelte"), title: "Offline", client: "billing.create", platform: null },
    { path: "/bills/offline/:offlineId/print", component: () => import("./pages/bills/BillPrint.svelte"), title: "Print bill", bare: true, client: "billing.create", platform: null },
    { path: "/bills/:id", component: () => import("./pages/bills/BillDetail.svelte"), title: "Bill", ...CLIENT_ONLY },
    { path: "/bills/:id/print", component: () => import("./pages/bills/BillPrint.svelte"), title: "Print bill", bare: true, ...CLIENT_ONLY },
    { path: "/dues", component: () => import("./pages/bills/Bills.svelte"), title: "Dues", client: "payments.collect", platform: null },
    { path: "/patients", component: () => import("./pages/patients/Patients.svelte"), title: "Patients", ...CLIENT_ONLY },
    { path: "/patients/:id", component: () => import("./pages/patients/PatientDetail.svelte"), title: "Patient", ...CLIENT_ONLY },
    ...(FEATURES.worklist ? [{ path: "/worklist", component: () => import("./pages/Worklist.svelte"), title: "Investigation Report", ...CLIENT_ONLY }] : []),
    ...(FEATURES.testReports ? [
      { path: "/test-reports", component: () => import("./pages/reports/ReportsDashboard.svelte"), title: "Reporting", ...CLIENT_ONLY },
      { path: "/test-reports/queue", component: () => import("./pages/reports/ReportQueue.svelte"), title: "Test Reports", ...CLIENT_ONLY },
      { path: "/test-reports/:itemId", component: () => import("./pages/reports/TestReport.svelte"), title: "Report", ...CLIENT_ONLY },
    ] : []),
    { path: "/reports", component: () => import("./pages/reports/Reports.svelte"), title: "Financial Reports", client: "business_reports.view", platform: null },
    { path: "/reports/:name", component: () => import("./pages/reports/Reports.svelte"), title: "Financial Reports", client: "business_reports.view", platform: null },
    { path: "/tests", component: () => import("./pages/catalogue/Tests.svelte"), title: "Tests & Prices", ...CLIENT_ONLY },
    { path: "/doctors", component: () => import("./pages/catalogue/Doctors.svelte"), title: "Doctors & Hospitals", ...CLIENT_ONLY },
    { path: "/settings", component: () => import("./pages/settings/SettingsHub.svelte"), title: "Settings" },
    { path: "/settings/:section", component: () => import("./pages/settings/SettingsHub.svelte"), title: "Settings" },
    { path: "/staff", component: () => import("./pages/settings/SettingsHub.svelte"), title: "Settings" },
    { path: "/activity", component: () => import("./pages/settings/SettingsHub.svelte"), title: "Settings" },
    { path: "/clients", component: () => import("./pages/platform/Clients.svelte"), title: "Clients", client: null, platform: "platform.clients.view" },
    { path: "/change-password", component: () => import("./pages/ChangePassword.svelte"), title: "Change password" },
    { path: "/notifications", component: () => import("./pages/Notifications.svelte"), title: "Notifications" },
    // Development only (npm run dev): the live server monitor. Not in production builds.
    ...(import.meta.env.DEV ? [{ path: "/dev/monitor", component: () => import("./pages/DevMonitor.svelte"), title: "Dev Monitor" }] : []),
  ];

  const loginPage: Loader = () => import("./pages/Login.svelte");
  const forgotPasswordPage: Loader = () => import("./pages/ForgotPassword.svelte");
  const resetPasswordPage: Loader = () => import("./pages/ResetPassword.svelte");
  const changePasswordPage: Loader = () => import("./pages/ChangePassword.svelte");
  const termsPage: Loader = () => import("./pages/Terms.svelte");
  const publicBillPage: Loader = () => import("./pages/bills/PublicBill.svelte");

  function match(path: string): { route: Route; params: Record<string, string> } | null {
    const parts = path.split("/").filter(Boolean);
    for (const route of routes) {
      const want = route.path.split("/").filter(Boolean);
      if (want.length !== parts.length) continue;
      const params: Record<string, string> = {};
      const ok = want.every((w, i) => {
        if (w.startsWith(":")) {
          params[w.slice(1)] = decodeURIComponent(parts[i]);
          return true;
        }
        return w === parts[i];
      });
      if (ok) return { route, params };
    }
    return null;
  }

  /** Pages the menu may link to (fixed addresses only). */
  const AVAILABLE = new Set(routes.filter((r) => !r.path.includes(":")).map((r) => r.path));

  // Pages for people who aren't signed in.
  const PUBLIC = ["/login", "/forgot-password", "/reset-password"];
  // Pages anyone can read, signed in or not.
  const OPEN = ["/terms"];
  // The patient's bill, opened from the QR code: /b/<token>, no sign-in, its own check instead.
  const publicBillToken = $derived(router.path.startsWith("/b/") ? router.path.slice(3) : "");

  let startError = $state("");

  // Once, when the app opens (untracked: nothing read while loading may start it again).
  $effect(() => {
    untrack(() => session.load()).catch((e) => {
      startError = e?.message ?? "CIDMS couldn't start.";
      reportError("error", e);
    });
  });

  const found = $derived(match(router.path));
  const route = $derived(found?.route);
  const params = $derived(found?.params ?? {});
  const allowed = $derived.by(() => {
    if (!route) return false;
    const need = session.isPlatform ? route.platform : route.client;
    return need === undefined || (need !== null && session.can(need));
  });

  // Where someone may be: signed out -> sign-in; temporary password -> choose one first; signed in -> not the sign-in page.
  $effect(() => {
    if (!session.ready || session.workspace?.kind === "none") return;
    const path = router.path;
    if (OPEN.includes(path) || publicBillToken) return;
    const here = path === "/" ? "" : path + router.search;
    if (!session.me) {
      if (!PUBLIC.includes(path)) navigate(withNext("/login", here), { replace: true });
    } else if (session.me.must_change_password && path !== "/change-password") {
      navigate(withNext("/change-password", here), { replace: true });
    } else if (path === "/change-password" && !session.me.must_change_password && !session.me.manage_own_account) {
      navigate("/", { replace: true }); // staff only choose a password at first sign-in; after that it's their owner's or admin's job
    } else if (PUBLIC.includes(path)) {
      navigate("/", { replace: true });
    }
  });

  $effect(() => {
    if (publicBillToken) return;  // PublicBill.svelte sets its own title once the centre's name is known
    const where = session.workspace?.name ? ` · ${session.workspace.name}` : "";
    const titles: Record<string, string> = { "/login": "Sign in", "/forgot-password": "Forgot password", "/reset-password": "Choose a new password", "/terms": "Terms and conditions" };
    document.title = `${titles[router.path] ?? route?.title ?? "Not found"}${where} · CIDMS`;
  });
</script>

{#snippet guarded(load: Loader, pageParams: Record<string, string> = {})}
  <!-- A crash while drawing one screen shows a fallback for that screen only; the menu and top bar keep working.
       Each page is its own chunk (import()), fetched the first time its route opens. -->
  {#key router.path}
    <svelte:boundary onerror={(error) => reportError("boundary", error)}>
      {#await load()}
        <div class="splash" aria-busy="true"><span class="text-muted">Loading…</span></div>
      {:then mod}
        {@const Page = mod.default}
        <Page params={pageParams} />
      {/await}
      {#snippet failed(error, reset)}<ErrorFallback {error} {reset} />{/snippet}
    </svelte:boundary>
  {/key}
{/snippet}

<OfflineBanner />

{#if startError}
  <Message title="CIDMS couldn't start" text="{startError} Refresh the page to try again." action={false} />
{:else if !session.ready}
  <div class="splash" aria-busy="true"><span class="text-muted">Loading…</span></div>
{:else if session.workspace?.kind === "none"}
  <Landing ws={session.workspace} />
{:else if OPEN.includes(router.path)}
  {@render guarded(termsPage)}
{:else if publicBillToken}
  {@render guarded(publicBillPage, { token: publicBillToken })}
{:else if !session.me}
  {#if router.path === "/login"}{@render guarded(loginPage)}
  {:else if router.path === "/forgot-password"}{@render guarded(forgotPasswordPage)}
  {:else if router.path === "/reset-password"}{@render guarded(resetPasswordPage)}{/if}
{:else if session.me.must_change_password}
  {#if router.path === "/change-password"}{@render guarded(changePasswordPage)}{/if}
{:else if route?.bare && allowed}
  {@render guarded(route.component, params)}
{:else}
  <AppShell title={route?.title ?? "Not found"} available={AVAILABLE}>
    {#if !route}
      <Message code="Error 404" title="Page not found" text="The address may be mistyped, or the page may have moved." />
    {:else if !allowed}
      <Message code="Error 403" title="You don't have access to this page" text="Ask your centre's owner or admin if you need it." />
    {:else}
      {@render guarded(route.component, params)}
    {/if}
  </AppShell>
{/if}

<Toasts />
<ConfirmHost />

<style src="./styles/App.css"></style>
