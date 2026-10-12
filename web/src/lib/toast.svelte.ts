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
  /** A button on the toast, e.g. "Try again". */
  action?: { label: string; run: () => void | Promise<void> };
}

export interface Toast {
  id: number;
  kind: NotifyKind;
  title: string;
  message: string;
  detail: string;
  leaving: boolean;
  action?: { label: string; run: () => void | Promise<void> };
}

let next = 1;
const recent = new Map<string, number>();
const timers = new Map<number, ReturnType<typeof setTimeout>>();
const durations = new Map<number, number>();

class Toasts {
  items = $state<Toast[]>([]);

  show(message: string, { kind = "success", title = "", detail = "", duration, action }: NotifyOptions = {}): number | null {
    const key = `${kind}:${title}:${message}`;
    // The same message twice in a row is shown once; a progress spinner always shows (each is its own request).
    if (kind !== "progress" && !action) {
      if (Date.now() - (recent.get(key) ?? 0) < 4000) return null;
      recent.set(key, Date.now());
    }
    const id = next++;
    this.items.push({ id, kind, title, message, detail, leaving: false, action });
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
  const e = error as { message?: string; requestId?: string | null; status?: number; retry?: () => Promise<unknown> };
  const offline = e?.status === 0;
  // A change lost to the network or a busy server: offer to send it again. When that works, the page may be out
  // of date (it never saw the answer), so the success toast offers a refresh.
  const action = e?.retry ? {
    label: "Try again",
    run: async () => {
      try {
        await e.retry!();
        notify("Done. It went through this time.", { kind: "success", duration: 8000,
          action: { label: "Refresh", run: () => location.reload() } });
      } catch (again) {
        notifyError(again, { title, fallback });
      }
    },
  } : undefined;
  notify(e?.message || fallback, {
    kind: "error",
    title: title || (offline ? "No connection" : ""),
    detail: e?.requestId ? `Reference: ${e.requestId.slice(0, 12)}` : "",
    action,
  });
}

/** Kept for existing callers. */
export const toastError = (error: unknown, fallback?: string) => notifyError(error, { fallback });
