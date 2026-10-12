<script lang="ts">
  // A strip across the top while the device has no connection. Pages keep what's on screen; saving waits for the
  // connection (page loads retry by themselves once it's back).
  let online = $state(typeof navigator === "undefined" ? true : navigator.onLine);
  let back = $state(false);
  let timer: ReturnType<typeof setTimeout>;
  $effect(() => {
    const up = () => { online = true; back = true; clearTimeout(timer); timer = setTimeout(() => (back = false), 4000); };
    const down = () => { online = false; back = false; };
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); clearTimeout(timer); };
  });
</script>

{#if !online}
  <div class="offline-banner" role="status" aria-live="polite">You're offline. Changes can't be saved until the connection is back.</div>
{:else if back}
  <div class="offline-banner is-back" role="status" aria-live="polite">Back online.</div>
{/if}

<style>
  .is-back { background: var(--success, #15803d); }
</style>
