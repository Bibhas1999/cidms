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
  import BillDetail from "./pages/bills/BillDetail.svelte";
  import BillPrint from "./pages/bills/BillPrint.svelte";
  import Bills from "./pages/bills/Bills.svelte";
  import Dues from "./pages/bills/Dues.svelte";
  import NewBill from "./pages/bills/NewBill.svelte";
  import Doctors from "./pages/catalogue/Doctors.svelte";
  import Tests from "./pages/catalogue/Tests.svelte";
  import PatientDetail from "./pages/patients/PatientDetail.svelte";
  import Patients from "./pages/patients/Patients.svelte";
  import Worklist from "./pages/Worklist.svelte";
  import TestReport from "./pages/reports/TestReport.svelte";
  import Reports from "./pages/reports/Reports.svelte";
  import ChangePassword from "./pages/ChangePassword.svelte";
  import Analytics from "./pages/Analytics.svelte";
  import DevMonitor from "./pages/DevMonitor.svelte";
  import ReportQueue from "./pages/reports/ReportQueue.svelte";
  import ReportsDashboard from "./pages/reports/ReportsDashboard.svelte";
  import Dashboard from "./pages/Dashboard.svelte";
  import ForgotPassword from "./pages/ForgotPassword.svelte";
  import Login from "./pages/Login.svelte";
  import ResetPassword from "./pages/ResetPassword.svelte";
  import Landing from "./pages/Landing.svelte";
  import OfflineBills from "./pages/bills/OfflineBills.svelte";
  import Message from "./pages/Message.svelte";
  import Notifications from "./pages/Notifications.svelte";
  import Terms from "./pages/Terms.svelte";
  import Clients from "./pages/platform/Clients.svelte";
  import SettingsHub from "./pages/settings/SettingsHub.svelte";

  interface Route {
    path: string;              // "/bills/:id" captures id
    component: Component<any>;
    title: string;
    /** Permission needed in a client workspace / in the platform workspace. undefined = everyone; null = not here. */
    client?: string | null;
    platform?: string | null;
    /** Drawn without the menu and top bar (printouts). */
    bare?: boolean;
  }

  const CLIENT_ONLY = { platform: null };
  const routes: Route[] = [
    { path: "/", component: Dashboard, title: "Dashboard" },
    { path: "/analytics", component: Analytics, title: "Analytics", client: "analytics.view", platform: null },
    { path: "/bills", component: Bills, title: "Bills", ...CLIENT_ONLY },
    { path: "/bills/new", component: NewBill, title: "New bill", client: "billing.create", platform: null },
    { path: "/bills/offline", component: OfflineBills, title: "Offline", client: "billing.create", platform: null },
    { path: "/bills/offline/:offlineId/print", component: BillPrint, title: "Print bill", bare: true, client: "billing.create", platform: null },
    { path: "/bills/:id", component: BillDetail, title: "Bill", ...CLIENT_ONLY },
    { path: "/bills/:id/print", component: BillPrint, title: "Print bill", bare: true, ...CLIENT_ONLY },
    { path: "/dues", component: Dues, title: "Dues", client: "payments.collect", platform: null },
    { path: "/patients", component: Patients, title: "Patients", ...CLIENT_ONLY },
    { path: "/patients/:id", component: PatientDetail, title: "Patient", ...CLIENT_ONLY },
    ...(FEATURES.worklist ? [{ path: "/worklist", component: Worklist, title: "Worklist", ...CLIENT_ONLY }] : []),
    ...(FEATURES.testReports ? [
      { path: "/test-reports", component: ReportsDashboard, title: "Test reports", ...CLIENT_ONLY },
      { path: "/test-reports/queue", component: ReportQueue, title: "Test reports", ...CLIENT_ONLY },
      { path: "/test-reports/:itemId", component: TestReport, title: "Report", ...CLIENT_ONLY },
    ] : []),
    { path: "/reports", component: Reports, title: "Billing reports", client: "business_reports.view", platform: null },
    { path: "/reports/:name", component: Reports, title: "Billing reports", client: "business_reports.view", platform: null },
    { path: "/tests", component: Tests, title: "Tests & prices", ...CLIENT_ONLY },
    { path: "/doctors", component: Doctors, title: "Doctors & hospitals", ...CLIENT_ONLY },
    { path: "/settings", component: SettingsHub, title: "Settings" },
    { path: "/settings/:section", component: SettingsHub, title: "Settings" },
    { path: "/staff", component: SettingsHub, title: "Settings" },
    { path: "/activity", component: SettingsHub, title: "Settings" },
    { path: "/clients", component: Clients, title: "Clients", client: null, platform: "platform.clients.view" },
    { path: "/change-password", component: ChangePassword, title: "Change password" },
    { path: "/notifications", component: Notifications, title: "Notifications" },
    // Development only (npm run dev): the live server monitor. Not in production builds.
    ...(import.meta.env.DEV ? [{ path: "/dev/monitor", component: DevMonitor, title: "Dev monitor" }] : []),
  ];

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
    if (OPEN.includes(path)) return;
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
    const where = session.workspace?.name ? ` · ${session.workspace.name}` : "";
    const titles: Record<string, string> = { "/login": "Sign in", "/forgot-password": "Forgot password", "/reset-password": "Choose a new password", "/terms": "Terms and conditions" };
    document.title = `${titles[router.path] ?? route?.title ?? "Not found"}${where} · CIDMS`;
  });
</script>

{#snippet guarded(Page: Component<any>, pageParams: Record<string, string> = {})}
  <!-- A crash while drawing one screen shows a fallback for that screen only; the menu and top bar keep working. -->
  {#key router.path}
    <svelte:boundary onerror={(error) => reportError("boundary", error)}>
      <Page params={pageParams} />
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
  {@render guarded(Terms)}
{:else if !session.me}
  {#if router.path === "/login"}{@render guarded(Login)}
  {:else if router.path === "/forgot-password"}{@render guarded(ForgotPassword)}
  {:else if router.path === "/reset-password"}{@render guarded(ResetPassword)}{/if}
{:else if session.me.must_change_password}
  {#if router.path === "/change-password"}{@render guarded(ChangePassword)}{/if}
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

<style>
  .splash { min-height: 100vh; display: grid; place-items: center; }
</style>
