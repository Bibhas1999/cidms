<script lang="ts">
  import type { ResumableUpload } from "../lib/upload.svelte";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";

  // The progress of a resumable upload, with Pause / Resume and Cancel.
  let { upload, filename, onresume, oncancel }: {
    upload: ResumableUpload; filename: string; onresume: () => void; oncancel: () => void;
  } = $props();

  function size(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  const words = $derived(
    upload.status === "paused" ? "Paused"
    : upload.status === "error" ? "Stopped"
    : upload.status === "done" ? "Uploaded"
    : upload.secondsLeft !== null && upload.secondsLeft > 1 ? `About ${upload.secondsLeft} s left` : "Uploading…");
</script>

<div class="upload" class:is-error={upload.status === "error"} aria-live="polite">
  <div class="row gap-sm upload-head">
    <Icon name="sheet" />
    <div class="grow min-w-0">
      <div class="font-semibold truncate">{filename}</div>
      <div class="text-sm text-muted">{size(upload.sent)} of {size(upload.total)} · {upload.percent}% · {words}</div>
    </div>
    {#if upload.status === "uploading"}
      <Button size="sm" icon="pause" onclick={() => upload.pause()}>Pause</Button>
    {:else if upload.status === "paused" || upload.status === "error"}
      <Button size="sm" variant="primary" icon="play" onclick={onresume}>Resume</Button>
    {/if}
    {#if upload.status !== "done"}
      <Button size="sm" variant="ghost" icon="x" tooltip="Cancel the upload" aria-label="Cancel the upload" onclick={oncancel} />
    {/if}
  </div>
  <div class="progress" role="progressbar" aria-label="Upload progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={upload.percent}>
    <div class="progress-bar" class:is-paused={upload.status !== "uploading" && upload.status !== "done"} style="width: {upload.percent}%"></div>
  </div>
  {#if upload.status === "error"}<p class="text-sm upload-error">{upload.error}</p>{/if}
</div>

<style>
  .upload { display: grid; gap: 8px; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card); }
  .upload.is-error { border-color: var(--destructive); }
  .upload-head { align-items: center; }
  .progress-bar { transition: width 0.2s ease; }
  .progress-bar.is-paused { background: var(--muted-foreground); }
  .upload-error { color: var(--destructive); margin: 0; }
  .min-w-0 { min-width: 0; }
  .truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
