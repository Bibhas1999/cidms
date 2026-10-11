<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "../Icon.svelte";
  import InfoTip from "../InfoTip.svelte";

  // One headline figure: label (with an ⓘ tip saying exactly what's counted), the value, a note, and an
  // optional change against the period before. A link when `href` is given. No chart, so no hover layer.
  let { label, value, note = "", tip = "", delta = null, deltaWords = "", href = "", icon = "", tone = "", loading = false, children }: {
    label: string; value: string; note?: string; tip?: string;
    /** Percentage change against the comparison period (null: none to show). */
    delta?: number | null; deltaWords?: string; href?: string; icon?: string; tone?: "" | "green" | "orange"; loading?: boolean;
    children?: Snippet;
  } = $props();

  const cut = $derived(label.lastIndexOf(" "));
  const head = $derived(cut > 0 ? label.slice(0, cut + 1) : "");
  const tail = $derived(cut > 0 ? label.slice(cut + 1) : label);
</script>

{#snippet body()}
  {#if icon}<span class="stat-icon {tone ? `is-${tone}` : ''}"><Icon name={icon} /></span>{/if}
  <span class="kpi-label">{head}<span class="nowrap">{tail}{#if tip}<InfoTip text={tip} about={label} />{/if}</span></span>
  <span class="kpi-value" aria-busy={loading}>{loading ? "—" : value}</span>
  <span class="kpi-note">
    {#if note}<span>{note}</span>{/if}
    {#if delta !== null && delta !== undefined}
      <span class="stat-delta {delta >= 0 ? 'is-up' : 'is-down'}"><Icon name={delta >= 0 ? "trendUp" : "trendDown"} size="sm" />{Math.abs(delta)}%{deltaWords ? ` ${deltaWords}` : ""}</span>
    {/if}
    {#if children}{@render children()}{/if}
  </span>
{/snippet}

<!-- A linked tile is a div with a stretched link under its content, so the ⓘ button isn't nested in the link. -->
<div class="card stat kpi" class:is-link={!!href}>
  {#if href}<a class="kpi-link" {href} aria-label="{label}: {loading ? '' : value}. Open the list"></a>{/if}
  {@render body()}
</div>
