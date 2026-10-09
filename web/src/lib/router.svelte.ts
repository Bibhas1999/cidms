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

let beforeLeave: (() => boolean) | null = null;

/** A page with unsaved changes can ask before the person moves away. Return false to stay. */
export function setBeforeLeave(check: (() => boolean) | null): void {
  beforeLeave = check;
}

export function navigate(to: string, { replace = false } = {}): void {
  const url = new URL(to, location.origin);
  if (url.pathname + url.search === location.pathname + location.search) return;
  if (beforeLeave && !beforeLeave()) return;
  beforeLeave = null;
  history[replace ? "replaceState" : "pushState"]({}, "", url.pathname + url.search);
  router.sync();
  window.scrollTo(0, 0);
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
  router.sync();
}

export function installRouter(): void {
  window.addEventListener("popstate", () => router.sync());
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
