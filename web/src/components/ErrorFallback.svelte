<script lang="ts">
  import { describe } from "../lib/errors";
  import Icon from "./Icon.svelte";

  // Shown in place of a screen that crashed while drawing. The menu and top bar keep working, and the
  // error has already been reported to the server.
  let { error, reset }: { error: unknown; reset: () => void } = $props();

  const message = $derived(describe(error).message);
</script>

<div class="card" role="alert" style="max-width: 640px; margin: 40px auto">
  <div class="card-content stack">
    <div class="row"><span class="dialog-icon is-destructive"><Icon name="alert" /></span><h1 class="page-title">This screen ran into a problem</h1></div>
    <p class="text-muted">It has been reported automatically. Try again, or go back to the dashboard. Nothing you saved before this has been lost.</p>
    {#if import.meta.env.DEV}<pre class="mono" style="white-space: pre-wrap; background: var(--muted); padding: 10px; border-radius: 6px; margin: 0">{message}</pre>{/if}
    <div class="row-wrap">
      <button class="btn btn-primary" onclick={reset}><Icon name="refresh" /> Try again</button>
      <a class="btn btn-outline" href="/">Go to the dashboard</a>
    </div>
  </div>
</div>
