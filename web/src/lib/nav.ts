// The sidebar: grouped sections (only the current work area's: areaNav) as in the Sandhata Registry. Settings (staff, centre, activity log, your
// profile) are in the profile menu, not here. An item shows when its page exists (see
// App.svelte's routes) and the person holds its permission.

import { FEATURES } from "./features";
import type { AreaKind } from "./types";

export interface NavItem {
  href: string;
  label: string;
  icon: string;
  permission?: string;
}

export interface NavSection {
  heading: string;
  items: NavItem[];
}

// The live server monitor: development builds only, and only for the owner, centre admin and developers.
const DEV: NavItem[] = import.meta.env.DEV ? [{ href: "/dev/monitor", label: "Dev monitor", icon: "activity", permission: "dev.monitor" }] : [];
const TEST_REPORTS = FEATURES.testReports ? [{ href: "/test-reports", label: "Test reports", icon: "fileText" }] : [];

/** The front desk's billing pages (Reception, and the menu for a server without work areas). */
const FRONT_DESK: NavSection = {
  heading: "Front desk",
  items: [
    { href: "/bills/new", label: "New bill", icon: "filePlus", permission: "billing.create" },
    { href: "/bills", label: "Bills", icon: "receipt" },
    { href: "/patients", label: "Patients", icon: "users" },
    { href: "/dues", label: "Dues", icon: "wallet", permission: "payments.collect" },
  ],
};

const CATALOGUE: NavSection = {
  heading: "Catalogue",
  items: [
    { href: "/tests", label: "Tests & prices", icon: "flask" },
    { href: "/doctors", label: "Doctors & hospitals", icon: "stethoscope" },
    { href: "/opd/doctors", label: "OPD doctors", icon: "stethoscope" },
  ],
};

/** Everything, for a server that doesn't know work areas yet (and the saved copy of one). */
export const CLIENT_NAV: NavSection[] = [
  {
    heading: "Overview",
    items: [
      { href: "/", label: "Dashboard", icon: "dashboard" },
      { href: "/analytics", label: "Analytics", icon: "barChart", permission: "analytics.view" },
      ...DEV,
    ],
  },
  FRONT_DESK,
  {
    heading: "Reports",
    items: [
      // Test reports: the reporting dashboard (work in hand, turnaround) and the full list at /test-reports/queue.
      ...TEST_REPORTS,
      { href: "/reports", label: "Billing reports", icon: "barChart", permission: "business_reports.view" },
    ],
  },
  { ...CATALOGUE, items: CATALOGUE.items.filter((i) => i.href !== "/opd/doctors") },
];

/** The menu of one work area (lib/area.svelte.ts): only that area's pages. */
export function areaNav(kind: AreaKind | null, name = ""): NavSection[] {
  switch (kind) {
    case "admin":
      return [
        { heading: "Overview", items: [
          { href: "/", label: "Dashboard", icon: "dashboard" },
          { href: "/analytics", label: "Analytics", icon: "barChart", permission: "analytics.view" },
          ...DEV,
        ] },
        { heading: "Reports", items: [...TEST_REPORTS, { href: "/reports", label: "Billing reports", icon: "barChart", permission: "business_reports.view" }] },
        CATALOGUE,
        { heading: "Departments", items: [{ href: "/worklist", label: "Worklist", icon: "clipboard" }] },
      ];
    case "reception":
      return [
        { heading: "Overview", items: [{ href: "/", label: "Dashboard", icon: "dashboard" }] },
        FRONT_DESK,
        { heading: "Reports", items: [{ href: "/reports", label: "Billing reports", icon: "barChart", permission: "business_reports.view" }] },
      ];
    case "opd":
      return [
        { heading: "OPD", items: [
          { href: "/opd", label: "OPD queue", icon: "list" },
          { href: "/opd?new=1", label: "New visit", icon: "plus", permission: "appointments.manage" },
          { href: "/patients", label: "Patients", icon: "users" },
          { href: "/opd/doctors", label: "OPD doctors", icon: "stethoscope", permission: "appointments.manage" },
        ] },
      ];
    case "department":
      return [{ heading: name || "Department", items: [{ href: "/worklist", label: "Worklist", icon: "clipboard" }] }];
    default:
      return CLIENT_NAV;
  }
}

export const PLATFORM_NAV: NavSection[] = [
  { heading: "Overview", items: [{ href: "/", label: "Dashboard", icon: "dashboard" },
                                 ...(import.meta.env.DEV ? [{ href: "/dev/monitor", label: "Dev monitor", icon: "activity", permission: "platform.dev.monitor" }] : [])] },
  { heading: "Clients", items: [{ href: "/clients", label: "Clients", icon: "building", permission: "platform.clients.view" }] },
];
