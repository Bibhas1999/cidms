// Who is signed in, at which workspace, and what they may do. The session itself is the HttpOnly cookie;
// this only holds what the server says about it (and the CSRF token it hands back).

import { rememberAccount } from "./accounts";
import { ApiError, get, post, setApiHooks } from "./api";
import { navigate, router } from "./router.svelte";
import type { Me, Workspace } from "./types";

class Session {
  me = $state<Me | null>(null);
  workspace = $state<Workspace | null>(null);
  ready = $state(false);

  get isPlatform(): boolean {
    return this.workspace?.kind === "platform";
  }

  can(permission: string): boolean {
    return this.me?.permissions.includes(permission) ?? false;
  }

  async load(): Promise<void> {
    this.workspace = await get<Workspace>("/api/workspace");
    if (this.workspace.kind !== "none") {
      try {
        this.me = await get<Me>("/api/auth/me");
      } catch (e) {
        if (!(e instanceof ApiError) || e.status !== 401) throw e;
        this.me = null;
      }
    }
    this.ready = true;
  }

  async login(email: string, password: string, remember = false): Promise<Me> {
    this.me = await post<Me>("/api/auth/login", { email, password, remember });
    rememberAccount({ email: this.me.email, name: this.me.full_name });
    return this.me;
  }

  async logout({ switching = false } = {}): Promise<void> {
    try {
      await post("/api/auth/logout");
    } finally {
      this.me = null;
      navigate(switching ? "/login?switch=1" : "/login", { replace: true });
    }
  }

  setMe(me: Me): void {
    this.me = me;
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
