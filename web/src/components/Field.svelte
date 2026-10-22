<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";
  import InfoTip from "./InfoTip.svelte";

  // A labelled form field with an optional hint, an ⓘ tip and its error, as in the Sandhata Registry: the
  // error is text plus an icon (never colour alone), linked to the control with aria-describedby.
  //   <Field id="disc" label="Discount" tip="Up to the centre's limit; more needs the owner." error={form.error("discount")}>
  let { id, label, error = "", hint = "", tip = "", required = false, optional = false, children }: {
    id: string; label: string; error?: string; hint?: string;
    /** Shown in an ⓘ toggletip beside the label: what to enter, why it's asked, the rules. */
    tip?: string;
    required?: boolean;
    /** Says "(optional)" after the label. */
    optional?: boolean;
    children: Snippet<[{ invalid: boolean; describedby: string | undefined }]>;
  } = $props();

  // The error takes the hint's place (one line under the box, so a row of fields stays level).
  const describedby = $derived(error ? `${id}-error` : hint ? `${id}-hint` : undefined);
</script>

<div class="field">
  <div class="label-row">
    <label class="label" for={id}>{label}{#if required}<span class="req" aria-hidden="true">*</span>{/if}{#if optional}<span class="optional"> (optional)</span>{/if}</label>
    {#if tip}<InfoTip text={tip} about={label} />{/if}
  </div>
  {@render children({ invalid: !!error, describedby })}
  {#if hint && !error}<div id="{id}-hint" class="hint">{hint}</div>{/if}
  {#if error}<p id="{id}-error" class="field-error"><Icon name="alert" size="sm" />{error}</p>{/if}
</div>

<style>
  .label-row { min-height: 20px; }
  .label-row .label { margin: 0; }
  .optional { margin-left: 4px; font-weight: 400; color: var(--muted-foreground); }
</style>
