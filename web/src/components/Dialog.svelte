<script lang="ts">
  import { tooltip } from "../lib/tooltip";
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";

  // A modal on the native <dialog> (focus moves in, Esc closes, the page behind is inert), styled like the
  // Sandhata Registry's: a fixed head and foot with the body scrolling between them when it's long.
  let { open = $bindable(false), title, description = "", icon = "", tone = "", children, footer, wide = false, full = false, onclose }: {
    open?: boolean; title: string; description?: string; icon?: string; tone?: "" | "success" | "info" | "destructive";
    children?: Snippet; footer?: Snippet; wide?: boolean;
    /** Fills almost the whole screen, for something meant to be studied at length (e.g. an expanded live feed). */
    full?: boolean; onclose?: () => void;
  } = $props();

  const uid = $props.id();
  let el: HTMLDialogElement;

  $effect(() => {
    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  });
</script>

<dialog bind:this={el} class="dialog dialog-scroll" class:dialog-lg={wide} class:dialog-full={full} aria-labelledby="{uid}-title"
        aria-describedby={description ? `${uid}-desc` : undefined} onclose={() => { open = false; onclose?.(); }}>
  <div class="dialog-head dialog-sticky">
    {#if icon}<span class="dialog-icon {tone ? `is-${tone}` : ''}"><Icon name={icon} /></span>{/if}
    <div class="grow">
      <h2 id="{uid}-title">{title}</h2>
      {#if description}<p id="{uid}-desc" class="text-sm text-muted mt-2">{description}</p>{/if}
    </div>
    <button class="btn btn-ghost btn-icon" type="button" aria-label="Close" use:tooltip={"Close (Esc)"} onclick={() => (open = false)}><Icon name="x" /></button>
  </div>
  {#if children}<div class="dialog-body">{@render children()}</div>{/if}
  {#if footer}<div class="dialog-foot row justify-end">{@render footer()}</div>{/if}
</dialog>
