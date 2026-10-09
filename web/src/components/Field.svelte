<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";

  // A labelled form field with an optional hint and its error, as in the Sandhata Registry: the error is
  // text plus an icon (never colour alone), linked to the control with aria-describedby.
  let { id, label, error = "", hint = "", required = false, children }: {
    id: string; label: string; error?: string; hint?: string; required?: boolean;
    children: Snippet<[{ invalid: boolean; describedby: string | undefined }]>;
  } = $props();

  const describedby = $derived([hint ? `${id}-hint` : "", error ? `${id}-error` : ""].filter(Boolean).join(" ") || undefined);
</script>

<div class="field">
  <label class="label" for={id}>{label}{#if required}<span class="req" aria-hidden="true">*</span>{/if}</label>
  {@render children({ invalid: !!error, describedby })}
  {#if hint}<div id="{id}-hint" class="hint">{hint}</div>{/if}
  {#if error}<p id="{id}-error" class="field-error"><Icon name="alert" size="sm" />{error}</p>{/if}
</div>
