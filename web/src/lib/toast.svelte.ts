// Short messages after an action: "Saved", or what went wrong and the request ID to quote.

export type ToastKind = "success" | "error" | "info";

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  detail?: string;
}

let next = 1;

class Toasts {
  items = $state<Toast[]>([]);

  show(message: string, kind: ToastKind = "success", detail?: string): void {
    const id = next++;
    this.items.push({ id, kind, message, detail });
    // Errors stay longer: people need time to read them (and copy the reference).
    setTimeout(() => this.dismiss(id), kind === "error" ? 12_000 : 4_000);
  }

  dismiss(id: number): void {
    this.items = this.items.filter((t) => t.id !== id);
  }
}

export const toasts = new Toasts();

export function toastError(error: unknown, fallback = "That didn't work. Please try again."): void {
  const e = error as { message?: string; requestId?: string | null };
  toasts.show(e?.message || fallback, "error", e?.requestId ? `Reference: ${e.requestId.slice(0, 12)}` : undefined);
}
