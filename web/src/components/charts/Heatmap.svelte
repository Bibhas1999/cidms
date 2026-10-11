<script lang="ts">
  import { exact, type Fmt } from "../../lib/chart";

  // A grid of cells shaded by value: one hue (the series blue), light to dark, so darker means more. Cells
  // keep a 2px surface gap; hover, tap or the arrow keys show the exact value. A small scale explains the shading.
  let { rows, cols, values, fmt = "count", label, rowLabel = "", colLabel = "", unitWord = "" }: {
    rows: string[]; cols: string[];
    /** values[row][col] */
    values: number[][];
    fmt?: Fmt; label: string; rowLabel?: string; colLabel?: string;
    /** "bills": used in the tooltip after the number. */
    unitWord?: string;
  } = $props();

  let width = $state(640);
  let active = $state<[number, number] | null>(null);
  const narrow = $derived(width < 480);
  const LEFT = $derived(narrow ? 34 : 44), TOP = 4, BOTTOM = 22;
  const cellW = $derived((width - LEFT) / Math.max(1, cols.length));
  const cellH = $derived(narrow ? 22 : 26);
  const height = $derived(TOP + rows.length * cellH + BOTTOM);
  const max = $derived(Math.max(1, ...values.flat()));
  // Shade from the surface (nothing) to the full series colour (the most), in perceptual steps.
  const fill = (v: number) => (v <= 0 ? "var(--muted)" : `color-mix(in oklab, var(--chart-1) ${Math.round(12 + 88 * Math.sqrt(v / max))}%, var(--card))`);
  const every = $derived(Math.ceil(cols.length / Math.max(2, Math.floor((width - LEFT) / 34))));

  function pick(e: PointerEvent) {
    const r = (e.currentTarget as SVGElement).getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * width, py = ((e.clientY - r.top) / r.height) * height;
    const c = Math.floor((px - LEFT) / cellW), rr = Math.floor((py - TOP) / cellH);
    active = c >= 0 && c < cols.length && rr >= 0 && rr < rows.length ? [rr, c] : null;
  }
  function key(e: KeyboardEvent) {
    const [r, c] = active ?? [0, 0];
    const moves: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (moves[e.key]) {
      e.preventDefault();
      active = active === null ? [0, 0] : [Math.min(rows.length - 1, Math.max(0, r + moves[e.key][0])), Math.min(cols.length - 1, Math.max(0, c + moves[e.key][1]))];
    } else if (e.key === "Escape") active = null;
  }
</script>

<div class="chart" bind:clientWidth={width}>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
  <svg viewBox="0 0 {width} {height}" {height} role="img" tabindex="0" aria-label="{label}. Use the arrow keys to read each cell."
       onpointermove={pick} onpointerleave={() => (active = null)} onkeydown={key} onblur={() => (active = null)}>
    {#each rows as r, i (r)}
      <text x={LEFT - 6} y={TOP + i * cellH + cellH / 2 + 4} text-anchor="end" font-size="11" fill="var(--chart-axis)">{r}</text>
      {#each cols as _, j (j)}
        <rect x={LEFT + j * cellW + 1} y={TOP + i * cellH + 1} width={Math.max(1, cellW - 2)} height={cellH - 2} rx="3"
              fill={fill(values[i]?.[j] ?? 0)} stroke={active && active[0] === i && active[1] === j ? "var(--foreground)" : "none"} stroke-width="1.5" />
      {/each}
    {/each}
    {#each cols as c, j (j)}
      {#if j % every === 0}<text x={LEFT + j * cellW + cellW / 2} y={height - 6} text-anchor="middle" font-size="11" fill="var(--chart-axis)">{c}</text>{/if}
    {/each}
  </svg>
  <div class="row" style="gap: 8px; margin-top: 6px; font-size: 12px; color: var(--muted-foreground)" aria-hidden="true">
    <span>Fewer</span>
    {#each [0.05, 0.25, 0.5, 0.75, 1] as s (s)}<span style="width: 18px; height: 10px; border-radius: 2px; background: {fill(s * max)}"></span>{/each}
    <span>More</span>
  </div>
  {#if active}
    {@const [r, c] = active}
    <div class="chart-tooltip" style="left: {Math.max(0, Math.min(LEFT + c * cellW + cellW / 2 - 90, width - 190))}px; top: {TOP + (r + 1) * cellH + 4}px" role="status">
      <div class="font-semibold" style="margin-bottom: 4px">{rowLabel}{rows[r]} · {colLabel}{cols[c]}</div>
      <strong class="tabular">{exact(values[r]?.[c] ?? 0, fmt)}</strong> {unitWord}
    </div>
  {/if}
</div>
