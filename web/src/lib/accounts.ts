// Accounts recently used on this computer, for "Switch account" on a shared front-desk PC. Only names, email
// addresses and which centre's address they sign in at are kept (never passwords or sessions) - in a cookie
// shared by every centre's subdomain on this device, not just the one you're on right now.

export interface RecentAccount {
  email: string;
  name: string;
  /** The address (host) this account signs in at, e.g. "alpha.cidms.duckdns.org". */
  host: string;
  /** The centre's name, for display when it's a different address than the one you're on now. */
  centreName?: string;
}

const COOKIE = "sdms_accounts";
const MAX = 10;
const MAX_AGE = 60 * 60 * 24 * 180; // 180 days

/** The domain every centre's subdomain shares (drop the leftmost label), or null with nothing to share across. */
function sharedDomain(): string | null {
  const parts = location.hostname.split(".");
  return parts.length > 1 ? parts.slice(1).join(".") : null;
}

function isAccount(v: unknown): v is RecentAccount {
  return !!v && typeof v === "object" && typeof (v as RecentAccount).email === "string" && typeof (v as RecentAccount).host === "string";
}

function readAll(): RecentAccount[] {
  try {
    const m = document.cookie.match(/(?:^|;\s*)sdms_accounts=([^;]*)/);
    if (!m) return [];
    const v = JSON.parse(decodeURIComponent(m[1]));
    return Array.isArray(v) ? v.filter(isAccount) : [];
  } catch {
    return [];
  }
}

function writeAll(list: RecentAccount[]): void {
  try {
    const domain = sharedDomain();
    const attrs = `path=/; max-age=${MAX_AGE}; samesite=lax${location.protocol === "https:" ? "; secure" : ""}${domain ? `; domain=.${domain}` : ""}`;
    document.cookie = `${COOKIE}=${encodeURIComponent(JSON.stringify(list))}; ${attrs}`;
  } catch {
    /* blocked: nothing to remember */
  }
}

/** Every account signed in before on this device, any centre's address, most recent first. */
export function recentAccounts(): RecentAccount[] {
  return readAll().slice(0, MAX);
}

export function rememberAccount(a: { email: string; name: string; centreName?: string }): void {
  const entry: RecentAccount = { email: a.email, name: a.name, host: location.host, centreName: a.centreName };
  const rest = readAll().filter((x) => !(x.email === entry.email && x.host === entry.host));
  writeAll([entry, ...rest].slice(0, MAX));
}

export function forgetAccount(email: string, host: string): void {
  writeAll(readAll().filter((x) => !(x.email === email && x.host === host)));
}
