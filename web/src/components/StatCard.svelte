<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";
  import InfoTip from "./InfoTip.svelte";

  // A figure on its own tile: label (with an ⓘ tip saying how it's worked out), the value, a note.
  //   <StatCard label="Still due" value={rupees(due)} icon="wallet" tone="red" tip="Unpaid balance of the bills shown." />
  // With `href` the whole tile is a link. `tone` colours the icon: blue (default) | orange | green | red.
  let { label, value, note = "", icon = "", tone = "", tip = "", href = "", loading = false, valueClass = "", extra }: {
    label: string; value: string | number; note?: string; icon?: string; tone?: "" | "orange" | "green" | "red";
    tip?: string; href?: string; loading?: boolean; valueClass?: string; extra?: Snippet;
  } = $props();
</script>

<svelte:element this={href ? "a" : "div"} class="card stat stat-card" href={href || undefined} aria-busy={loading || undefined}>
  {#if icon}<span class="stat-icon {tone ? `is-${tone}` : ''}" aria-hidden="true"><Icon name={icon} size="sm" /></span>{/if}
  <span class="stat-label">{label}{#if tip}<InfoTip text={tip} about={label} />{/if}</span>
  {#if loading}<span class="skeleton" style="width: 60%; height: 26px"></span>
  {:else}<span class="stat-value {valueClass}">{value}</span>{/if}
  {#if note}<span class="stat-note">{note}</span>{/if}
  {#if extra}{@render extra()}{/if}
</svelte:element>

<style src="./styles/StatCard.css"></style>
