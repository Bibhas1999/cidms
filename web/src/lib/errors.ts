// Reports browser errors to the server (POST /api/client-errors), where they're logged next to the
// request that caused them. Never throws: a broken error report must not cause another error.

type Kind = "boundary" | "error" | "unhandledrejection" | "api";

const recent = new Map<string, number>();
const DEDUPE_MS = 30_000;

export function describe(error: unknown): { message: string; stack: string } {
  if (error instanceof Error) return { message: error.message || error.name, stack: error.stack ?? "" };
  try {
    return { message: typeof error === "string" ? error : JSON.stringify(error), stack: "" };
  } catch {
    return { message: String(error), stack: "" };
  }
}

export function reportError(kind: Kind, error: unknown): void {
  const { message, stack } = describe(error);
  const key = `${kind}:${message}`;
  const now = Date.now();
  if ((recent.get(key) ?? 0) > now - DEDUPE_MS) return; // the same failure repeating in a loop
  recent.set(key, now);
  const body = JSON.stringify({ kind, message: message.slice(0, 2000), stack: stack.slice(0, 8000), url: location.pathname });
  try {
    if (navigator.sendBeacon?.("/api/client-errors", new Blob([body], { type: "application/json" }))) return;
    void fetch("/api/client-errors", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch(() => {});
  } catch {
    /* nothing more we can do */
  }
  if (import.meta.env.DEV) console.error(`[${kind}]`, error);
}

/** Errors outside any component (event handlers, timers, promises nobody awaited). */
export function installGlobalErrorHandlers(): void {
  window.addEventListener("error", (e) => reportError("error", e.error ?? e.message));
  window.addEventListener("unhandledrejection", (e) => reportError("unhandledrejection", e.reason));
}
