// "Are you sure?" in the app's own dialog instead of the browser's, as in the Sandhata Registry.
//
//   if (await confirmDialog({ title: "Suspend Gamma Labs?", message: "…", confirmLabel: "Suspend", tone: "danger" })) …
//
// With a third choice (e.g. "Discard" beside "Stay" and "Leave"), use chooseDialog: it answers "confirm",
// "cancel" or "extra".

export interface ConfirmOptions {
  title?: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "primary" | "danger";
  /** A third button, on the left (e.g. "Discard draft"). */
  extraLabel?: string;
}

export type Choice = "confirm" | "cancel" | "extra";

interface Pending extends Required<ConfirmOptions> {
  resolve: (choice: Choice) => void;
}

class ConfirmState {
  current = $state<Pending | null>(null);

  answer(choice: Choice | boolean): void {
    this.current?.resolve(choice === true ? "confirm" : choice === false ? "cancel" : choice);
    this.current = null;
  }
}

export const confirmState = new ConfirmState();

export function chooseDialog({ title = "Are you sure?", message = "", confirmLabel = "Confirm", cancelLabel = "Cancel",
                               tone = "primary", extraLabel = "" }: ConfirmOptions = {}): Promise<Choice> {
  confirmState.answer(false); // only one at a time
  return new Promise((resolve) => {
    confirmState.current = { title, message, confirmLabel, cancelLabel, tone, extraLabel, resolve };
  });
}

export async function confirmDialog(options: ConfirmOptions = {}): Promise<boolean> {
  return (await chooseDialog({ ...options, extraLabel: "" })) === "confirm";
}
