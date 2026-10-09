// "Are you sure?" in the app's own dialog instead of the browser's, as in the Sandhata Registry.
//
//   if (await confirmDialog({ title: "Suspend Gamma Labs?", message: "…", confirmLabel: "Suspend", tone: "danger" })) …

export interface ConfirmOptions {
  title?: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "primary" | "danger";
}

interface Pending extends Required<ConfirmOptions> {
  resolve: (ok: boolean) => void;
}

class ConfirmState {
  current = $state<Pending | null>(null);

  answer(ok: boolean): void {
    this.current?.resolve(ok);
    this.current = null;
  }
}

export const confirmState = new ConfirmState();

export function confirmDialog({ title = "Are you sure?", message = "", confirmLabel = "Confirm", cancelLabel = "Cancel",
                                tone = "primary" }: ConfirmOptions = {}): Promise<boolean> {
  confirmState.answer(false); // only one at a time
  return new Promise((resolve) => {
    confirmState.current = { title, message, confirmLabel, cancelLabel, tone, resolve };
  });
}
