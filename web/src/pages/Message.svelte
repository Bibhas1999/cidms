<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "../components/Icon.svelte";

  // A full-page message (page not found, no access, couldn't start), laid out like the registry's error page.
  // children: buttons to show instead of "Go to the dashboard".
  let { title, text, code = "", action = true, children }: { title: string; text: string; code?: string; action?: boolean; children?: Snippet } = $props();
</script>

<div class="message-wrap">
  <div class="card card-content stack" style="max-width: 440px; padding: 32px">
    {#if code}<span class="eyebrow">{code}</span>{/if}
    <h1 class="page-title">{title}</h1>
    <p class="text-muted">{text}</p>
    {#if children}<div class="row-wrap" style="gap: 10px">{@render children()}</div>
    {:else if action}<div><a class="btn btn-primary" href="/"><Icon name="dashboard" /> Go to the dashboard</a></div>{/if}
  </div>
</div>

<style>
  .message-wrap { display: grid; place-items: center; min-height: 60vh; padding: 16px; }
</style>
