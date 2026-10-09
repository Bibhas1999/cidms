<script lang="ts">
  // A person's picture, or their initials when there isn't one (or it fails to load).
  let { name, url = "", size = "" }: { name: string; url?: string; size?: "" | "sm" | "lg" } = $props();

  let broken = $state(false);
  const initials = $derived((name || "?").split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase());
  $effect(() => { url; broken = false; });
</script>

<span class="avatar {size === 'sm' ? 'avatar-sm' : ''}" class:avatar-lg={size === "lg"} aria-hidden="true">
  {#if url && !broken}<img class="avatar-img" src={url} alt="" onerror={() => (broken = true)} />{:else}{initials}{/if}
</span>

<style>
  .avatar { position: relative; overflow: hidden; }
  .avatar-img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
  .avatar-lg { width: 88px; height: 88px; font-size: 28px; }
</style>
