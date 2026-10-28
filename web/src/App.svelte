<script lang="ts">
  import type { Component } from "svelte";
  import { untrack } from "svelte";
  import AppShell from "./components/AppShell.svelte";
  import ConfirmHost from "./components/ConfirmHost.svelte";
  import ErrorFallback from "./components/ErrorFallback.svelte";
  import Icon from "./components/Icon.svelte";
  import OfflineBanner from "./components/OfflineBanner.svelte";
  import Toasts from "./components/Toasts.svelte";
  import { reportError } from "./lib/errors";
  import { navigate, router } from "./lib/router.svelte";
  import { FEATURES } from "./lib/features";
  import { area, AREA_HOME } from "./lib/area.svelte";
  import { session } from "./lib/session.svelte";
  import type { AreaKind } from "./lib/types";
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
  import ChooseArea from "./pages/ChooseArea.svelte";
  import OpdQueue from "./pages/opd/OpdQueue.svelte";
  import OpdDoctors from "./pages/opd/OpdDoctors.svelte";

  interface Route {
    path: string;              // "/bills/:id" captures id
    component: Component<any>;
    title: string;
    /** Permission needed in a client workspace / in the platform workspace. undefined = everyone; null = not here. */
    client?: string | null;
    platform?: string | null;
    /** Drawn without the menu and top bar (printouts). */
    bare?: boolean;
    /** The work areas the page is part of (lib/area.svelte.ts). undefined = every area. */
    areas?: AreaKind[];
  }

  const CLIENT_ONLY = { platform: null };
  const DESK: AreaKind[] = ["reception"];
  const DESK_OR_OPD: AreaKind[] = ["reception", "opd"];
  const ADMIN: AreaKind[] = ["admin"];
  const LAB: AreaKind[] = ["admin", "department"];
  const routes: Route[] = [
    { path: "/", component: Dashboard, title: "Dashboard", areas: ["admin", "reception"] },
    { path: "/analytics", component: Analytics, title: "Analytics", client: "analytics.view", platform: null, areas: ADMIN },
    { path: "/bills", component: Bills, title: "Bills", ...CLIENT_ONLY, areas: DESK },
    { path: "/bills/new", component: NewBill, title: "New bill", client: "billing.create", platform: null, areas: DESK },
    { path: "/bills/offline", component: OfflineBills, title: "Offline", client: "billing.create", platform: null, areas: DESK },
    { path: "/bills/offline/:offlineId/print", component: BillPrint, title: "Print bill", bare: true, client: "billing.create", platform: null, areas: DESK },
    // The OPD opens a visit's fee bill too.
    { path: "/bills/:id", component: BillDetail, title: "Bill", ...CLIENT_ONLY, areas: DESK_OR_OPD },
    { path: "/bills/:id/print", component: BillPrint, title: "Print bill", bare: true, ...CLIENT_ONLY, areas: DESK_OR_OPD },
    { path: "/dues", component: Dues, title: "Dues", client: "payments.collect", platform: null, areas: DESK },
    { path: "/patients", component: Patients, title: "Patients", ...CLIENT_ONLY, areas: DESK_OR_OPD },
    { path: "/patients/:id", component: PatientDetail, title: "Patient", ...CLIENT_ONLY, areas: DESK_OR_OPD },
    { path: "/opd", component: OpdQueue, title: "OPD queue", ...CLIENT_ONLY, areas: ["opd"] },
    { path: "/opd/doctors", component: OpdDoctors, title: "OPD doctors", ...CLIENT_ONLY, areas: ["opd", "admin"] },
    { path: "/worklist", component: Worklist, title: "Worklist", ...CLIENT_ONLY, areas: LAB },
    ...(FEATURES.testReports ? [
      { path: "/test-reports", component: ReportsDashboard, title: "Test reports", ...CLIENT_ONLY, areas: LAB },
      { path: "/test-reports/queue", component: ReportQueue, title: "Test reports", ...CLIENT_ONLY, areas: LAB },
      { path: "/test-reports/:itemId", component: TestReport, title: "Report", ...CLIENT_ONLY, areas: LAB },
    ] : []),
    { path: "/reports", component: Reports, title: "Billing reports", client: "business_reports.view", platform: null, areas: ["admin", "reception"] },
    { path: "/reports/:name", component: Reports, title: "Billing reports", client: "business_reports.view", platform: null, areas: ["admin", "reception"] },
    { path: "/tests", component: Tests, title: "Tests & prices", ...CLIENT_ONLY, areas: ADMIN },
    { path: "/doctors", component: Doctors, title: "Doctors & hospitals", ...CLIENT_ONLY, areas: ADMIN },
    { path: "/settings", component: SettingsHub, title: "Settings" },
    { path: "/settings/:section", component: SettingsHub, title: "Settings" },
    { path: "/staff", component: SettingsHub, title: "Settings" },
    { path: "/activity", component: SettingsHub, title: "Settings" },
    { path: "/clients", component: Clients, title: "Clients", client: null, platform: "platform.clients.view" },
    { path: "/change-password", component: ChangePassword, title: "Change password" },
    { path: "/notifications", component: Notifications, title: "Notifications" },
    // Development only (npm run dev): the live server monitor. Not in production builds.
    // Only for the owner, centre admin and developers (and the platform owner); in a centre, part of the Admin area.
    ...(import.meta.env.DEV ? [{ path: "/dev/monitor", component: DevMonitor, title: "Dev monitor", client: "dev.monitor",
                                 platform: "platform.dev.monitor", areas: ADMIN }] : []),
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
  // Part of the work area they're in (pages for every area, and a server without areas: always).
  const inArea = $derived(!route?.areas || !area.inUse || !area.current || route.areas.includes(area.current.kind));

  // Where someone may be: signed out -> sign-in; temporary password -> choose one first; signed in -> not the sign-in page.
  $effect(() => {
    if (!session.ready || session.workspace?.kind === "none") return;
    const path = router.path;
    if (OPEN.includes(path)) return;
    if (!session.me) {
      if (!PUBLIC.includes(path)) navigate(`/login${path === "/" ? "" : `?next=${encodeURIComponent(path + router.search)}`}`, { replace: true });
    } else if (session.me.must_change_password && path !== "/change-password") {
      navigate("/change-password", { replace: true });
    } else if (path === "/change-password" && !session.me.must_change_password && !session.me.manage_own_account) {
      navigate("/", { replace: true }); // staff only choose a password at first sign-in; after that it's their owner's or admin's job
    } else if (PUBLIC.includes(path)) {
      navigate("/", { replace: true });
    } else if (area.inUse && path !== "/choose-area" && path !== "/change-password" && !area.current) {
      // (A temporary password is changed first, above; then the area.)
      // No work area chosen yet (or none given): choose one first, then on to this page.
      const next = path === "/" ? "" : `?next=${encodeURIComponent(path + router.search)}`;
      navigate(`/choose-area${next}`, { replace: true });
    } else if (area.current && path === "/" && !inArea) {
      navigate(AREA_HOME[area.current.kind], { replace: true }); // the OPD's and a department's first page isn't the dashboard
    }
  });

  $effect(() => {
    const where = session.workspace?.name ? ` · ${session.workspace.name}` : "";
    const titles: Record<string, string> = { "/choose-area": "Choose where you work", "/login": "Sign in", "/forgot-password": "Forgot password", "/reset-password": "Choose a new password", "/terms": "Terms and conditions" };
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
{:else if router.path === "/choose-area" && area.inUse}
  {@render guarded(ChooseArea)}
{:else if route?.bare && allowed && inArea}
  {@render guarded(route.component, params)}
{:else}
  <AppShell title={route?.title ?? "Not found"} available={AVAILABLE}>
    {#if !route}
      <Message code="Error 404" title="Page not found" text="The address may be mistyped, or the page may have moved." />
    {:else if !allowed}
      <Message code="Error 403" title="You don't have access to this page" text="Ask your centre's owner or admin if you need it." />
    {:else if !inArea}
      <Message title="This page isn't part of {area.current?.name}." text="You're working in {area.current?.name} now. Switch to the area this page belongs to, if you work there too.">
        {#if area.canSwitch}<a class="btn btn-primary" href="/choose-area?next={encodeURIComponent(router.path + router.search)}"><Icon name="layers" /> Switch area</a>{/if}
        <a class="btn btn-outline" href={area.current ? AREA_HOME[area.current.kind] : "/"}>Back to {area.current?.name}</a>
      </Message>
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
