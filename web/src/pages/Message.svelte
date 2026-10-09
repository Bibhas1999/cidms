<script lang="ts">
  // A full-page message: page not found, not allowed, no workspace at this address, couldn't start.
  let { title, text, action = true }: { title: string; text: string; action?: boolean } = $props();
</script>

<div class="wrap">
  <div class="card card-body stack">
    <h1>{title}</h1>
    <p class="muted">{text}</p>
    {#if action}<div><a class="btn" href="/">Go to the dashboard</a></div>{/if}
  </div>
</div>

<style>
  .wrap { display: grid; place-items: center; min-height: 60vh; padding: 16px; }
  .card { max-width: 520px; }
  p { margin: 0; }
</style>
