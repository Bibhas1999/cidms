// A small history router: real addresses (/staff?page=2) that can be shared and bookmarked, and moving
// between pages without reloading. Links are plain <a href="/..."> elements; clicks on them are handled here.

class RouterState {
  path = $state(location.pathname);
  search = $state(location.search);

  get query(): URLSearchParams {
    return new URLSearchParams(this.search);
  }

  sync(): void {
    this.path = location.pathname;
    this.search = location.search;
  }
}

export const router = new RouterState();

// Where someone was headed before they were bounced to sign in (or a forced password change): carried as
// ?next=, so they land back there instead of always on the home page. Read from the real address bar, not
// `router.query`, so it works the same from an event handler as from a derived value.
const NEXT_BLOCKED = ["/login", "/change-password", "/forgot-password", "/reset-password"];

/** Only ever a path inside this app, and never back into the sign-in/password-change chain (which would loop). */
export function safeNext(fallback = "/"): string {
  const next = new URLSearchParams(location.search).get("next");
  if (!next || !next.startsWith("/") || next.startsWith("//")) return fallback;
  return NEXT_BLOCKED.includes(next.split(/[?#]/)[0]) ? fallback : next;
}

/** `base`, with `next` carried forward as its own ?next= (e.g. from /login's onto /change-password's). */
export function withNext(base: string, next: string): string {
  return next && next !== "/" ? `${base}?next=${encodeURIComponent(next)}` : base;
}

type LeaveCheck = () => boolean | Promise<boolean>;
let beforeLeave: LeaveCheck | null = null;
let here = location.pathname + location.search;   // where we are, to come back to if a Back press is cancelled

/** A page with unsaved changes can ask before the person moves away (a link, or the browser's Back button).
 *  Return (or resolve to) false to stay. Use confirmLeave() for the app's own "Leave this page?" dialog. */
export function setBeforeLeave(check: LeaveCheck | null): void {
  beforeLeave = check;
}

function go(url: URL, replace: boolean): void {
  beforeLeave = null;
  history[replace ? "replaceState" : "pushState"]({}, "", url.pathname + url.search);
  here = url.pathname + url.search;
  router.sync();
  window.scrollTo(0, 0);
}

export function navigate(to: string, { replace = false } = {}): void {
  const url = new URL(to, location.origin);
  if (url.pathname + url.search === location.pathname + location.search) return;
  if (!beforeLeave) { go(url, replace); return; }
  void Promise.resolve(beforeLeave()).then((ok) => { if (ok) go(url, replace); });
}

/** Change the query string of the current page (filters, paging) without adding a history entry per keystroke. */
export function setQuery(values: Record<string, string | number | null | undefined>, { replace = true } = {}): void {
  const q = new URLSearchParams(location.search);
  for (const [k, v] of Object.entries(values)) {
    if (v === null || v === undefined || v === "" ) q.delete(k);
    else q.set(k, String(v));
  }
  const s = q.toString();
  history[replace ? "replaceState" : "pushState"]({}, "", location.pathname + (s ? `?${s}` : ""));
  here = location.pathname + location.search;
  router.sync();
}

export function installRouter(): void {
  window.addEventListener("popstate", () => {
    const check = beforeLeave;
    if (!check) { here = location.pathname + location.search; router.sync(); return; }
    // Back (or Forward) with unsaved work: put this page back for now, and go only if they say so.
    const wanted = location.pathname + location.search;
    history.pushState({}, "", here);
    void Promise.resolve(check()).then((ok) => { if (ok) go(new URL(wanted, location.origin), true); });
  });
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = (e.target as Element).closest?.("a");
    if (!a || a.target || a.hasAttribute("download") || a.origin !== location.origin) return;
    const href = a.getAttribute("href");
    if (!href || !href.startsWith("/") || href.startsWith("/api/")) return;
    e.preventDefault();
    navigate(href);
  });
}
