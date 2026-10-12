// Who is signed in, at which workspace, and what they may do. The session itself is the HttpOnly cookie;
// this only holds what the server says about it (and the CSRF token it hands back).

import { rememberAccount } from "./accounts";
import { ApiError, get, post, setApiHooks } from "./api";
import { navigate, router } from "./router.svelte";
import type { Me, Workspace } from "./types";

// The last answers about the workspace and the person, kept so the app still opens without the internet
// (billing goes on offline: lib/offline.svelte.ts). Forgotten on signing out.
const BOOT = `cidms:boot:${location.hostname}`;
type Listener = () => void;

class Session {
  me = $state<Me | null>(null);
  workspace = $state<Workspace | null>(null);
  ready = $state(false);
  /** Opened from the saved copy because CIDMS couldn't be reached. */
  offlineStart = $state(false);
  #signedIn = new Set<Listener>();
  #signedOut = new Set<Listener>();

  onSignedIn(fn: Listener): void { this.#signedIn.add(fn); }
  onSignedOut(fn: Listener): void { this.#signedOut.add(fn); }

  get isPlatform(): boolean {
    return this.workspace?.kind === "platform";
  }

  can(permission: string): boolean {
    return this.me?.permissions.includes(permission) ?? false;
  }

  async load(): Promise<void> {
    const before = this.me?.id;
    try {
      this.workspace = await get<Workspace>("/api/workspace");
      if (this.workspace.kind !== "none") {
        try {
          this.me = await get<Me>("/api/auth/me");
        } catch (e) {
          if (!(e instanceof ApiError) || e.status !== 401) throw e;
          this.me = null;
        }
      }
      this.offlineStart = false;
      this.#keep();
    } catch (e) {
      // No connection: open from the saved copy, so billing can go on offline.
      const saved = e instanceof ApiError && e.transient ? this.#saved() : null;
      if (!saved) throw e;
      this.workspace = saved.workspace;
      this.me = saved.me;
      this.offlineStart = true;
    }
    this.ready = true;
    if (this.me && this.me.id !== before) this.#signedIn.forEach((fn) => fn());
  }

  /** Ask CIDMS again who's signed in (when the connection is back: a fresh CSRF token). Quiet on failure. */
  async refresh(): Promise<void> {
    try { await this.load(); } catch { /* still unreachable */ }
  }

  #keep(): void {
    try {
      if (this.me && this.workspace) localStorage.setItem(BOOT, JSON.stringify({ workspace: this.workspace, me: this.me }));
      else localStorage.removeItem(BOOT);
    } catch { /* storage blocked */ }
  }

  #saved(): { workspace: Workspace; me: Me } | null {
    try { return JSON.parse(localStorage.getItem(BOOT) ?? "null"); } catch { return null; }
  }

  async login(email: string, password: string, remember = false): Promise<Me> {
    this.me = await post<Me>("/api/auth/login", { email, password, remember });
    rememberAccount({ email: this.me.email, name: this.me.full_name });
    this.#keep();
    this.#signedIn.forEach((fn) => fn());
    return this.me;
  }

  async logout({ switching = false } = {}): Promise<void> {
    try {
      await post("/api/auth/logout");
    } finally {
      this.me = null;
      this.#keep();
      this.#signedOut.forEach((fn) => fn());
      navigate(switching ? "/login?switch=1" : "/login", { replace: true });
    }
  }

  setMe(me: Me): void {
    this.me = me;
    this.#keep();
    rememberAccount({ email: me.email, name: me.full_name });
  }
}

export const session = new Session();

setApiHooks({
  csrf: () => session.me?.csrf_token ?? "",
  onUnauthorized: () => {
    // The session ended (signed out elsewhere, timed out): back to sign-in, then return here.
    if (session.me) session.me = null;
    if (router.path !== "/login") navigate(`/login?next=${encodeURIComponent(router.path + router.search)}`, { replace: true });
  },
  onMustChangePassword: () => navigate("/change-password", { replace: true }),
});
