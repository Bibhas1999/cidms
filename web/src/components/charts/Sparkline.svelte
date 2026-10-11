<script lang="ts">
  // A word-sized trend line beside a figure (no axes): 1.5px line and a dot on the latest value.
  // Decorative next to its numbers, so it carries a short text summary for screen readers.
  let { values, width = 96, height = 24, color = "var(--chart-1)", label = "" }: {
    values: number[]; width?: number; height?: number; color?: string; label?: string;
  } = $props();

  const max = $derived(Math.max(1, ...values));
  const pts = $derived(values.map((v, i) => [values.length > 1 ? (i / (values.length - 1)) * (width - 4) + 2 : width / 2, height - 3 - (v / max) * (height - 6)]));
  const d = $derived(pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(""));
  const last = $derived(pts[pts.length - 1]);
</script>

{#if values.length}
  <svg {width} {height} viewBox="0 0 {width} {height}" role="img" aria-label={label || `Trend from ${values[0]} to ${values[values.length - 1]}`} style="flex: none; overflow: visible">
    <path {d} fill="none" stroke={color} stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" />
    {#if last}<circle cx={last[0]} cy={last[1]} r="2.5" fill={color} />{/if}
  </svg>
{/if}
