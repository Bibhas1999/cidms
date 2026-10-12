// "Leave this page?" in the app's own dialog (never the browser's), for pages with unsaved work:
//
//   setBeforeLeave(dirty ? confirmLeave({ message: "…" }) : null);
//
// With a draft kept, leaving loses nothing, so the choices are Stay / Leave (draft kept) / Discard draft.

import { chooseDialog } from "./confirm.svelte";

export function confirmLeave({
  title = "Leave this page?",
  message = "Your changes aren't saved yet. If you leave now, they're lost.",
  leaveLabel = "Leave without saving",
  stayLabel = "Stay on this page",
  discard,
}: {
  title?: string; message?: string; leaveLabel?: string; stayLabel?: string;
  /** Offer to throw the draft away too (a third button). */
  discard?: { label: string; run: () => void };
} = {}): () => Promise<boolean> {
  return async () => {
    const choice = await chooseDialog({ title, message, confirmLabel: leaveLabel, cancelLabel: stayLabel,
                                        tone: discard ? "primary" : "danger", extraLabel: discard?.label ?? "" });
    if (choice === "extra") discard?.run();
    return choice !== "cancel";
  };
}
