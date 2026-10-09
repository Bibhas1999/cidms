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
  <Dialog bind:open title={c.title} description={c.message} icon={c.tone === "danger" ? "alert" : "info"}
          tone={c.tone === "danger" ? "destructive" : "info"} onclose={() => confirmState.answer(false)}>
    {#snippet footer()}
      <button class="btn btn-outline" type="button" onclick={() => confirmState.answer(false)}>{c.cancelLabel}</button>
      <button class="btn {c.tone === 'danger' ? 'btn-destructive' : 'btn-primary'}" type="button" bind:this={confirmButton}
              onclick={() => confirmState.answer(true)}>{c.confirmLabel}</button>
    {/snippet}
  </Dialog>
{/if}
