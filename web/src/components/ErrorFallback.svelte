<script lang="ts">
  import { describe } from "../lib/errors";

  // Shown in place of a screen that crashed while drawing. The rest of the app (menu, top bar) keeps working,
  // and the error has already been reported to the server.
  let { error, reset }: { error: unknown; reset: () => void } = $props();

  const message = $derived(describe(error).message);
</script>

<div class="card fallback" role="alert">
  <div class="card-body stack">
    <h1>This screen ran into a problem</h1>
    <p class="muted">
      It has been reported automatically. You can try again, or go back to the dashboard. Nothing you saved
      before this has been lost.
    </p>
    {#if import.meta.env.DEV}<pre class="mono">{message}</pre>{/if}
    <div class="toolbar">
      <button class="btn primary" onclick={reset}>Try again</button>
      <a class="btn" href="/">Go to the dashboard</a>
    </div>
  </div>
</div>

<style>
  .fallback { max-width: 640px; margin: 40px auto; }
  pre { white-space: pre-wrap; background: var(--surface-2); padding: 10px; border-radius: var(--radius); margin: 0; }
</style>
