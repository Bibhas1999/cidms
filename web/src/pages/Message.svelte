<script lang="ts">
  import Icon from "../components/Icon.svelte";

  // A full-page message (page not found, no access, couldn't start), laid out like the registry's error page.
  let { title, text, code = "", action = true }: { title: string; text: string; code?: string; action?: boolean } = $props();
</script>

<div class="message-wrap">
  <div class="card card-content stack" style="max-width: 440px; padding: 32px">
    {#if code}<span class="eyebrow">{code}</span>{/if}
    <h1 class="page-title">{title}</h1>
    <p class="text-muted">{text}</p>
    {#if action}<div><a class="btn btn-primary" href="/"><Icon name="dashboard" /> Go to the dashboard</a></div>{/if}
  </div>
</div>

<style src="./styles/Message.css"></style>
