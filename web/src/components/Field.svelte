<script lang="ts">
  import type { Snippet } from "svelte";

  // A labelled form field with an optional hint and the error for it. The control itself is passed in and
  // should use `id` and, when there's an error, aria-invalid / aria-describedby (given to the snippet).
  let { id, label, error = "", hint = "", required = false, children }: {
    id: string; label: string; error?: string; hint?: string; required?: boolean;
    children: Snippet<[{ invalid: boolean; describedby: string | undefined }]>;
  } = $props();

  const describedby = $derived([hint ? `${id}-hint` : "", error ? `${id}-error` : ""].filter(Boolean).join(" ") || undefined);
</script>

<div class="field">
  <label for={id}>{label}{#if required}<span class="req" aria-hidden="true"> *</span>{/if}</label>
  {@render children({ invalid: !!error, describedby })}
  {#if hint}<div id="{id}-hint" class="hint">{hint}</div>{/if}
  {#if error}<div id="{id}-error" class="error">{error}</div>{/if}
</div>

<style>
  .field { display: grid; gap: 5px; }
  label { font-weight: 550; font-size: 13px; }
  .req { color: var(--danger); }
  .hint { font-size: 12px; color: var(--text-2); }
  .error { font-size: 12px; color: var(--danger); }
</style>
