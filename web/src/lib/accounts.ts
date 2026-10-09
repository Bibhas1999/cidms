// Accounts recently used on this computer, for "Switch account" on a shared front-desk PC. Only names and
// email addresses are kept (never passwords or sessions), in this browser, for this centre's address.

export interface RecentAccount {
  email: string;
  name: string;
}

const KEY = `sdms.accounts.${location.host}`;
const MAX = 6;

export function recentAccounts(): RecentAccount[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((a) => a && typeof a.email === "string").slice(0, MAX) : [];
  } catch {
    return [];
  }
}

export function rememberAccount(a: RecentAccount): void {
  try {
    const rest = recentAccounts().filter((x) => x.email !== a.email);
    localStorage.setItem(KEY, JSON.stringify([{ email: a.email, name: a.name }, ...rest].slice(0, MAX)));
  } catch {
    /* private window: nothing to remember */
  }
}

export function forgetAccount(email: string): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(recentAccounts().filter((x) => x.email !== email)));
  } catch {
    /* ignore */
  }
}
