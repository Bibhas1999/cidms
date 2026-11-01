// A saved, encrypted copy of what the screens read (GET /api/…), kept in IndexedDB (lib/offline-db.ts, "responses").
//   - Offline (or CIDMS briefly unreachable): a screen shows its last saved copy instead of an error, and the
//     banner says how old it is.
//   - Online: the catalogue (tests, departments, types, doctors, the centre's settings) is served from the copy
//     while it's under a minute old, so lists and drop-downs open at once. Any change made here makes those copies
//     stale straight away, so nobody sees an old list right after editing it.
// Copies belong to whoever was signed in (the key includes the person) and all go on signing out. At most
// MAX_ENTRIES are kept; the least recently saved go first.
import { idbAll, idbClear, idbCount, idbDelete, idbGet, idbKeys, idbPut } from "./offline-db";  // "responses" is stored as is: entries seal themselves
import { seal, unseal, type Sealed } from "./vault";

const MAX_ENTRIES = 600;
const FRESH_MS = 60_000;
// Saved for offline use. Not: signing in, live streams, uploads, the dev monitor, key exchange, background jobs.
const NEVER = [/^\/api\/auth\//, /^\/api\/payload\//, /^\/api\/uploads/, /^\/api\/dev\//, /^\/api\/notifications\/stream/,
               /^\/api\/jobs\//, /^\/api\/client-errors/, /^\/api\/v1\//];
// Served from the copy while it's fresh (changes rarely; every screen needs it).
const FRESH = [/^\/api\/tests(\?|$)/, /^\/api\/departments(\?|$)/, /^\/api\/test-types(\?|$)/, /^\/api\/doctors(\?|$)/,
               /^\/api\/settings(\?|$)/, /^\/api\/roles(\?|$)/];

interface Entry { box: Sealed; saved_at: number; user: string }

// When anything last changed here: older copies aren't "fresh" any more. Kept in localStorage (not just this
// tab's memory), so a reload right after saving doesn't bring back the copy from before the save.
const LAST_WRITE_KEY = "response-cache:last-write";
let lastWrite = (() => {
  try {
    return Number(localStorage.getItem(LAST_WRITE_KEY)) || 0;
  } catch {
    return 0;
  }
})();

class SavedCopies {
  /** Screens showing a saved copy right now: url -> when it was saved. */
  showing = $state<Record<string, number>>({});
  get oldest(): number | null {
    const v = Object.values(this.showing);
    return v.length ? Math.min(...v) : null;
  }
  shown(url: string, at: number) { this.showing = { ...this.showing, [url]: at }; }
  live(url: string) { if (url in this.showing) { const { [url]: _, ...rest } = this.showing; this.showing = rest; } }
  clearShowing() { this.showing = {}; }
}
export const savedCopies = new SavedCopies();

export const cacheable = (path: string) => path.startsWith("/api/") && !NEVER.some((r) => r.test(path));
const keyFor = (user: string, url: string) => `${user}|${url}`;

export async function saveCopy(user: string, url: string, data: unknown): Promise<void> {
  if (!user) return;
  try {
    const box = await seal(data);
    if (!box) return;
    await idbPut("responses", { box, saved_at: Date.now(), user } satisfies Entry, keyFor(user, url));
    if (Math.random() < 0.05) void trim();
  } catch { /* storage full or blocked: carry on without */ }
}

/** The saved copy (and when it was saved), or null. */
export async function savedCopy<T>(user: string, url: string): Promise<{ data: T; saved_at: number } | null> {
  if (!user) return null;
  try {
    const e = await idbGet<Entry>("responses", keyFor(user, url));
    if (!e || e.user !== user) return null;
    const data = await unseal<T>(e.box);
    return data === null ? null : { data, saved_at: e.saved_at };
  } catch {
    return null;
  }
}

/** A copy young enough to use instead of asking CIDMS (catalogue only). */
export async function freshCopy<T>(user: string, url: string): Promise<T | null> {
  if (!FRESH.some((r) => r.test(url))) return null;
  const hit = await savedCopy<T>(user, url);
  return hit && Date.now() - hit.saved_at < FRESH_MS && hit.saved_at > lastWrite ? hit.data : null;
}

/** Something was changed here: fresh copies must be asked for again. */
export function changed(): void {
  lastWrite = Date.now();
  try {
    localStorage.setItem(LAST_WRITE_KEY, String(lastWrite));
  } catch { /* storage full or blocked: this tab's memory still has it */ }
}

async function trim(): Promise<void> {
  const n = await idbCount("responses");
  if (n <= MAX_ENTRIES) return;
  const [all, keys] = await Promise.all([idbAll<Entry>("responses"), idbKeys("responses")]);
  const order = keys.map((k, i) => ({ k: String(k), at: all[i]?.saved_at ?? 0 })).sort((a, b) => a.at - b.at);
  await Promise.all(order.slice(0, n - MAX_ENTRIES).map((o) => idbDelete("responses", o.k)));
}

export async function forgetCopies(): Promise<void> {
  try { await idbClear("responses"); } catch { /* blocked */ }
  savedCopies.clearShowing();
}

export async function copyCount(): Promise<number> {
  try { return await idbCount("responses"); } catch { return 0; }
}
