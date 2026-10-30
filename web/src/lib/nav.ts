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
    heading: "Front Desk",
    items: [
      { href: "/bills/new", label: "New Bill", icon: "filePlus", permission: "billing.create" },
      { href: "/bills", label: "Bills", icon: "receipt" },
      { href: "/dues", label: "Dues", icon: "wallet", permission: "payments.collect" },
      { href: "/patients", label: "Patients", icon: "users" },
    ],
  },
  ...(FEATURES.worklist || FEATURES.testReports ? [{
    heading: "Lab",
    items: [
      ...(FEATURES.worklist ? [{ href: "/worklist", label: "Investigation Report", icon: "clipboard" }] : []),
      // Reporting: the dashboard (work in hand, turnaround). Test Reports: the actual list of items to
      // report on or already reported (To report / Drafts / Signed).
      ...(FEATURES.testReports ? [
        { href: "/test-reports", label: "Reporting", icon: "fileText" },
        { href: "/test-reports/queue", label: "Test Reports", icon: "clipboard" },
      ] : []),
    ],
  }] : []),
  {
    heading: "Finance",
    items: [
      { href: "/reports", label: "Financial Reports", icon: "barChart", permission: "business_reports.view" },
    ],
  },
  {
    heading: "Catalogue",
    items: [
      { href: "/tests", label: "Tests & Prices", icon: "flask" },
      { href: "/doctors", label: "Doctors & Hospitals", icon: "stethoscope" },
    ],
  },
  ...(import.meta.env.DEV ? [{ heading: "Monitoring", items: [{ href: "/dev/monitor", label: "Dev Monitor", icon: "activity" }] }] : []),
];

export const PLATFORM_NAV: NavSection[] = [
  { heading: "Overview", items: [{ href: "/", label: "Dashboard", icon: "dashboard" }] },
  { heading: "Clients", items: [{ href: "/clients", label: "Clients", icon: "building", permission: "platform.clients.view" }] },
  ...(import.meta.env.DEV ? [{ heading: "Monitoring", items: [{ href: "/dev/monitor", label: "Dev Monitor", icon: "activity" }] }] : []),
];
