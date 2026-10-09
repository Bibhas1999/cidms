<script lang="ts">
  import type { Snippet } from "svelte";

  // A modal built on the native <dialog>: focus moves into it, Esc closes it, and the page behind is inert.
  let { open = $bindable(false), title, children, footer, wide = false, onclose }: {
    open?: boolean; title: string; children: Snippet; footer?: Snippet; wide?: boolean; onclose?: () => void;
  } = $props();

  const uid = $props.id();
  let el: HTMLDialogElement;

  $effect(() => {
    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  });
</script>

<dialog bind:this={el} class:wide aria-labelledby="{uid}-title"
        onclose={() => { open = false; onclose?.(); }}>
  <header>
    <h2 id="{uid}-title">{title}</h2>
    <button class="close" aria-label="Close" onclick={() => (open = false)}>×</button>
  </header>
  <div class="body">{@render children()}</div>
  {#if footer}<footer>{@render footer()}</footer>{/if}
</dialog>

<style>
  dialog { border: 1px solid var(--border); border-radius: 12px; padding: 0; width: min(520px, calc(100vw - 32px));
    background: var(--surface); color: var(--text); box-shadow: 0 20px 50px rgb(0 0 0 / 25%); }
  dialog.wide { width: min(760px, calc(100vw - 32px)); }
  dialog::backdrop { background: rgb(10 15 20 / 45%); }
  header { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--border); }
  .body { padding: 20px; max-height: calc(100vh - 200px); overflow: auto; }
  footer { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 20px; border-top: 1px solid var(--border); }
  .close { border: 0; background: none; font-size: 22px; line-height: 1; color: var(--text-2); cursor: pointer; }
</style>
