// In-page notifications (toasts) for the whole app, the same way the Sandhata Registry does them.
//
//   notify("Saved.")                                         success, hides after a few seconds
//   notify("Couldn't save.", { kind: "error" })              error, stays until closed
//   notify("…", { kind: "error", title: "Sign-in failed", detail: "Reference: 1a2b3c" })
//
// Accessibility (WCAG 4.1.3 status messages, 2.2.1 timing adjustable):
//  - successes go to a polite live region; errors to an assertive one (announced immediately)
//  - errors never disappear by themselves; others pause while hovered or focused
//  - every toast has a Dismiss button; Esc dismisses the one that has focus
//  - the same message isn't stacked twice within a few seconds

export type NotifyKind = "success" | "error" | "warning" | "info" | "progress";

export interface NotifyOptions {
  kind?: NotifyKind;
  title?: string;
  detail?: string;
  /** Milliseconds before it hides by itself; 0 keeps it until dismissed. Default depends on the kind. */
  duration?: number;
}

export interface Toast {
  id: number;
  kind: NotifyKind;
  title: string;
  message: string;
  detail: string;
  leaving: boolean;
}

let next = 1;
const recent = new Map<string, number>();
const timers = new Map<number, ReturnType<typeof setTimeout>>();
const durations = new Map<number, number>();

class Toasts {
  items = $state<Toast[]>([]);

  show(message: string, { kind = "success", title = "", detail = "", duration }: NotifyOptions = {}): number | null {
    const key = `${kind}:${title}:${message}`;
    if (Date.now() - (recent.get(key) ?? 0) < 4000) return null;
    recent.set(key, Date.now());
    const id = next++;
    this.items.push({ id, kind, title, message, detail, leaving: false });
    const ms = duration ?? (kind === "error" || kind === "progress" ? 0 : kind === "warning" ? 9000 : 5000);
    if (ms) {
      durations.set(id, ms);
      timers.set(id, setTimeout(() => this.dismiss(id), ms));
    }
    return id;
  }

  /** Hovered or focused: keep it on screen. */
  pause(id: number): void {
    clearTimeout(timers.get(id));
  }

  /** Left alone again: hide it shortly. */
  resume(id: number): void {
    if (!durations.has(id)) return;
    clearTimeout(timers.get(id));
    timers.set(id, setTimeout(() => this.dismiss(id), 2500));
  }

  dismiss(id: number): void {
    clearTimeout(timers.get(id));
    timers.delete(id);
    durations.delete(id);
    const t = this.items.find((x) => x.id === id);
    if (!t) return;
    t.leaving = true;
    setTimeout(() => (this.items = this.items.filter((x) => x.id !== id)), 150);
  }
}

export const toasts = new Toasts();

export const notify = (message: string, options: NotifyOptions = {}) => toasts.show(message, options);

/** An error from the server or the network, with its reference so support can find it in the logs. */
export function notifyError(error: unknown, { title = "", fallback = "That didn't work. Please try again." } = {}): void {
  const e = error as { message?: string; requestId?: string | null; status?: number };
  const offline = e?.status === 0;
  notify(e?.message || fallback, {
    kind: "error",
    title: title || (offline ? "No connection" : ""),
    detail: e?.requestId ? `Reference: ${e.requestId.slice(0, 12)}` : "",
  });
}

/** Kept for existing callers. */
export const toastError = (error: unknown, fallback?: string) => notifyError(error, { fallback });
