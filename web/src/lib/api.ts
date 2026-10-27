import * as loader from "./loader";
import { connection } from "./connection.svelte";
import { ENCRYPTED, open, payloadKey, resetPayloadKey, seal } from "./payload";
import { cacheable, changed, freshCopy, saveCopy, savedCopies, savedCopy } from "./response-cache.svelte";
import { toasts } from "./toast.svelte";

// The one way the app talks to the server. The session lives in an HttpOnly cookie that JavaScript never
// sees; every change carries the session's CSRF token. Errors come back as ApiError with a readable message,
// the field it's about, and the request ID to quote to support.

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public field: string | null = null,
    public detail: { field: string; message: string }[] = [],
    public requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** For a change that failed on the network or a busy server: send the very same request again. */
  retry?: () => Promise<unknown>;

  /** The connection dropped or the server was briefly unavailable (worth trying again). */
  get transient(): boolean {
    return this.status === 0 || this.status === 502 || this.status === 503 || this.status === 504;
  }

  /** field name -> message, for showing under each form field. */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const d of this.detail) out[d.field] ??= d.message;
    if (this.field && !(this.field in out)) out[this.field] = this.message;
    return out;
  }
}

interface Hooks {
  csrf: () => string;
  onUnauthorized: () => void;
  onMustChangePassword: () => void;
  /** Who is signed in (whose saved copies to use); "" for nobody. */
  user?: () => string;
}

let hooks: Hooks = { csrf: () => "", onUnauthorized: () => {}, onMustChangePassword: () => {} };

export function setApiHooks(h: Hooks): void {
  hooks = h;
}

/** The session's CSRF token, for requests made outside api() (resumable uploads send pieces with XMLHttpRequest). */
export function csrfToken(): string {
  return hooks.csrf();
}

type Query = Record<string, string | number | boolean | null | undefined>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

/** Waits that grow: 1 s, then 2 s, then 4 s (a little jitter so many browsers don't retry at the same moment). */
const backoff = (attempt: number) => 1000 * 2 ** (attempt - 1) + Math.floor(Math.random() * 250);
const sleep = (ms: number, signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
  const t = setTimeout(resolve, ms);
  signal?.addEventListener("abort", () => { clearTimeout(t); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
});

// Changes that take a moment show a spinner toast ("Saving…") at the top right while they run, so the page never
// looks stuck and people can carry on. Quick ones (most) finish before it appears. Background chatter is left out.
const PROGRESS_AFTER_MS = 350;
const QUIET = [/^\/api\/auth\/(login|logout)/, /^\/api\/notifications/, /^\/api\/client-errors/, /^\/api\/auth\/me/];
function progressWords(method: string, path: string): string {
  if (method === "DELETE") return "Removing…";
  if (/\/cancel$/.test(path)) return "Cancelling…";
  if (/\/refunds$/.test(path)) return "Recording the refund…";
  if (/\/payments$/.test(path)) return "Recording the payment…";
  if (/\/reset-password$/.test(path)) return "Resetting the password…";
  if (path === "/api/bills" && method === "POST") return "Saving the bill…";
  return method === "POST" ? "Saving…" : "Saving changes…";
}

export async function api<T>(method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE", path: string,
                             options: { body?: unknown; query?: Query; signal?: AbortSignal; headers?: Record<string, string>;
                                        /** Words for the spinner toast on a slow change; false for none. */
                                        progress?: string | false } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...(options.headers ?? {}) };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = hooks.csrf();

  const showProgress = method !== "GET" && options.progress !== false && !QUIET.some((r) => r.test(path));
  let toastId: number | null = null;
  const timer = showProgress
    ? setTimeout(() => { toastId = toasts.show(options.progress || progressWords(method, path), { kind: "progress" }); }, PROGRESS_AFTER_MS)
    : undefined;

  // Saved copies (lib/response-cache): the catalogue straight from a fresh copy; any screen from its last copy
  // when CIDMS can't be reached.
  const url = withQuery(path, options.query);
  const user = hooks.user?.() ?? "";
  const copyable = method === "GET" && !!user && cacheable(new URL(path, location.origin).pathname);
  if (copyable) {
    const fresh = await freshCopy<T>(user, url);
    if (fresh !== null) { clearTimeout(timer); return fresh; }
  }

  loader.start();
  try {
    const result = await send<T>(method, path, options, headers);
    if (copyable) { void saveCopy(user, url, result); savedCopies.live(url); }
    else if (method !== "GET") changed();
    return result;
  } catch (e) {
    if (copyable && e instanceof ApiError && e.transient) {
      const hit = await savedCopy<T>(user, url);
      if (hit) { savedCopies.shown(url, hit.saved_at); return hit.data; }
    }
    // A change that failed on the network or a busy server can be sent again from the error toast ("Try again").
    if (e instanceof ApiError && method !== "GET" && e.transient) e.retry = () => api<T>(method, path, options);
    throw e;
  } finally {
    clearTimeout(timer);
    if (toastId !== null) toasts.dismiss(toastId);
    loader.done();
  }
}

// Bodies are encrypted to and from the server (lib/payload.ts), except for the few paths it doesn't encrypt.
const PLAIN = ["/api/payload/key", "/api/v1/", "/api/webhooks/", "/api/client-errors"];

async function send<T>(method: string, path: string, options: { body?: unknown; query?: Query; signal?: AbortSignal },
                       plainHeaders: Record<string, string>, renewed = false): Promise<T> {
  let response: Response | null = null;
  const headers = { ...plainHeaders };
  const pathname = new URL(path, location.origin).pathname;
  const key = pathname.startsWith("/api/") && !PLAIN.some((p) => pathname.startsWith(p)) ? await payloadKey() : null;
  const aad = `${method} ${pathname}`;
  let body: string | undefined = options.body === undefined ? undefined : JSON.stringify(options.body);
  if (key) {
    headers["X-Payload-Key"] = key.id;
    if (body !== undefined) { body = await seal(key, body, aad); headers["Content-Type"] = ENCRYPTED; }
  }
  // Retries, when repeating can't do anything twice:
  //   reads (GET): up to 3 tries on a dropped connection or a busy/restarting server (502, 503, 504);
  //   changes with an Idempotency-Key (bills, payments): 2 tries; the server does the change only once;
  //   other changes: never automatically (the error toast offers "Try again").
  const tries = method === "GET" ? 3 : headers["Idempotency-Key"] ? 2 : 1;
  for (let attempt = 1; ; attempt++) {
    const last = attempt >= tries;
    try {
      response = await fetch(withQuery(path, options.query), {
        method, headers, credentials: "same-origin", signal: options.signal, body,
      });
    } catch (e) {
      if ((e as Error).name === "AbortError") throw e;
      if (last || !navigator.onLine) {
        connection.markDown();
        throw new ApiError(0, "Can't reach CIDMS. Check your internet connection and try again.");
      }
      await sleep(backoff(attempt), options.signal);
      continue;
    }
    if (![502, 503, 504].includes(response.status)) { connection.markUp(); break; }
    if (last) { connection.markDown(); break; }
    await sleep(Math.min(8000, Number(response.headers.get("Retry-After") ?? 0) * 1000) || backoff(attempt), options.signal);
  }
  const res = response!;
  if (res.status === 204) return undefined as T;

  let data: any = null;
  try {
    data = key && res.headers.get("X-Payload") === "1" ? JSON.parse(await open(key, await res.text(), `${aad} response`)) : await res.json();
  } catch {
    /* not JSON: an error page from a proxy, for example */
  }
  if (res.ok) return data as T;
  // The server no longer has this tab's key (it expired, or the database was restored): agree a new one, once.
  if (res.status === 409 && data?.code === "payload_key" && !renewed) {
    resetPayloadKey();
    return send<T>(method, path, options, plainHeaders, true);
  }

  const err = new ApiError(res.status, data?.message ?? `Request failed (${res.status}).`, data?.field ?? null,
                           data?.detail ?? [], data?.request_id ?? res.headers.get("X-Request-ID"));
  if (res.status === 401 && !path.startsWith("/api/auth/login")) hooks.onUnauthorized();
  if (res.status === 403 && err.field === "must_change_password") hooks.onMustChangePassword();
  throw err;
}

export const get = <T>(path: string, query?: Query, signal?: AbortSignal) => api<T>("GET", path, { query, signal });
export const post = <T>(path: string, body?: unknown, headers?: Record<string, string>) => api<T>("POST", path, { body: body ?? {}, headers });

/** A key for one attempt at a change: retries with the same key are done only once (bills, payments). */
export const newRequestKey = () => crypto.randomUUID();
export const put = <T>(path: string, body: unknown) => api<T>("PUT", path, { body });
export const patch = <T>(path: string, body: unknown) => api<T>("PATCH", path, { body });
