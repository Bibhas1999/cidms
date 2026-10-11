// The sidebar: grouped sections as in the Sandhata Registry. Settings (staff, centre, activity log, your
// profile) are in the profile menu, not here. An item shows when its page exists (see
// App.svelte's routes) and the person holds its permission.

import { FEATURES } from "./features";

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

export const CLIENT_NAV: NavSection[] = [
  {
    heading: "Overview",
    items: [
      { href: "/", label: "Dashboard", icon: "dashboard" },
      { href: "/analytics", label: "Analytics", icon: "barChart", permission: "analytics.view" },
    ],
  },
  {
    heading: "Front desk",
    items: [
      { href: "/bills/new", label: "New bill", icon: "filePlus", permission: "billing.create" },
      { href: "/bills", label: "Bills", icon: "receipt" },
      { href: "/patients", label: "Patients", icon: "users" },
      { href: "/dues", label: "Dues", icon: "wallet", permission: "payments.collect" },
    ],
  },
  ...(FEATURES.worklist ? [{ heading: "Lab", items: [{ href: "/worklist", label: "Worklist", icon: "clipboard" }] }] : []),
  {
    heading: "Reports",
    items: [
      // Test reports: scanned tests waiting for a report (the reporting dashboard replaces this when it lands).
      ...(FEATURES.testReports ? [{ href: "/worklist?tab=scanned", label: "Test reports", icon: "fileText", permission: "reports.write" }] : []),
      { href: "/reports", label: "Billing reports", icon: "barChart", permission: "business_reports.view" },
    ],
  },
  {
    heading: "Catalogue",
    items: [
      { href: "/tests", label: "Tests & prices", icon: "flask" },
      { href: "/doctors", label: "Referring doctors", icon: "stethoscope" },
    ],
  },
];

export const PLATFORM_NAV: NavSection[] = [
  { heading: "Overview", items: [{ href: "/", label: "Dashboard", icon: "dashboard" }] },
  { heading: "Clients", items: [{ href: "/clients", label: "Clients", icon: "building", permission: "platform.clients.view" }] },
];
