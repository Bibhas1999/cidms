<script lang="ts">
  import { confirmState } from "../lib/confirm.svelte";
  import Dialog from "./Dialog.svelte";

  let open = $state(false);
  let confirmButton = $state<HTMLButtonElement>();

  $effect(() => {
    open = !!confirmState.current;
    if (open) queueMicrotask(() => confirmButton?.focus());
  });
</script>

{#if confirmState.current}
  {@const c = confirmState.current}
  <Dialog bind:open title={c.title} onclose={() => confirmState.answer(false)}>
    {#if c.message}<p class="message">{c.message}</p>{/if}
    {#snippet footer()}
      <button class="btn" type="button" onclick={() => confirmState.answer(false)}>{c.cancelLabel}</button>
      <button class="btn {c.tone === 'danger' ? 'danger-solid' : 'primary'}" type="button" bind:this={confirmButton}
              onclick={() => confirmState.answer(true)}>{c.confirmLabel}</button>
    {/snippet}
  </Dialog>
{/if}

<style>
  .message { margin: 0; line-height: 1.55; }
</style>
