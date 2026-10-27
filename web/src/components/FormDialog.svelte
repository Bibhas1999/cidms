<script lang="ts">
  import type { Snippet } from "svelte";
  import Button from "./Button.svelte";
  import Dialog from "./Dialog.svelte";

  // A dialog that is a form: the app's Dialog with the <form>, Cancel and the save button already in place, so every
  // add / edit / reason dialog looks and behaves the same (Enter saves, Esc or Cancel closes, the button locks and
  // says "Saving…" while it works, and stays off while `disabled`).
  //   <FormDialog bind:open title="Edit CBC" icon="edit" tone="info" submitLabel="Save changes"
  //               busy={form.submitting} onsubmit={form.submit}>
  //     <FormErrors {form} /> <Field …>…</Field>
  //   </FormDialog>
  // submitVariant  primary (default) or destructive (a refund, cancelling a bill)
  // cancelLabel    "Cancel" by default ("Keep it", "Back")
  // oncancel       also runs when Cancel is pressed (e.g. to forget a chosen file)
  // footerStart    anything shown on the left of the footer, before the buttons
  let { open = $bindable(false), title, description = "", icon = "", tone = "", wide = false, onclose,
        submitLabel, submitIcon = "", submitVariant = "primary", busy = false, busyLabel = "Saving…", disabled = false,
        cancelLabel = "Cancel", oncancel, onsubmit, footerStart, children }: {
    open?: boolean; title: string; description?: string; icon?: string; tone?: "" | "success" | "info" | "destructive";
    wide?: boolean; onclose?: () => void;
    submitLabel: string; submitIcon?: string; submitVariant?: "primary" | "destructive"; busy?: boolean; busyLabel?: string;
    disabled?: boolean; cancelLabel?: string; oncancel?: () => void;
    onsubmit: (e: SubmitEvent) => void | Promise<void>;
    footerStart?: Snippet; children: Snippet;
  } = $props();

  const uid = $props.id();
  const formId = `${uid}-form`;

  function submit(e: SubmitEvent) {
    e.preventDefault();
    if (busy || disabled) return;
    void onsubmit(e);
  }
</script>

<Dialog bind:open {title} {description} {icon} {tone} {wide} {onclose}>
  <form id={formId} class="stack" onsubmit={submit} novalidate>
    {@render children()}
  </form>
  {#snippet footer()}
    {#if footerStart}<div class="grow">{@render footerStart()}</div>{/if}
    <Button onclick={() => { open = false; oncancel?.(); }}>{cancelLabel}</Button>
    <Button variant={submitVariant} type="submit" form={formId} icon={submitIcon} loading={busy} loadingText={busyLabel} {disabled}>{submitLabel}</Button>
  {/snippet}
</Dialog>
