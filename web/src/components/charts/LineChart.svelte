<script lang="ts">
  import { exact, full, nearest, niceTop, short, tick, type Fmt, type Series, type Unit } from "../../lib/chart";

  // Lines over time on one axis (never two scales). 2px lines, recessive grid, labels at the line ends for up
  // to four series, a crosshair tooltip on hover and with the arrow keys. `dashed` series (e.g. an average to
  // compare with) are drawn dashed. The card around it gives the legend and the table view.
  let { keys, series, unit = "day", fmt = "money", height = 240, label, dashed = [], endLabels = true, min = 0 }: {
    keys: string[]; series: Series[]; unit?: Unit; fmt?: Fmt; height?: number;
    /** What the chart shows, for screen readers. */
    label: string;
    dashed?: string[]; endLabels?: boolean; min?: number;
  } = $props();

  let width = $state(640);
  let active = $state<number | null>(null);
  const narrow = $derived(width < 480);
  const showEnds = $derived(endLabels && series.length <= 4 && !narrow);
  const PAD = $derived({ top: 14, right: showEnds ? 78 : 12, bottom: 26, left: narrow ? 40 : 52 });
  const plotW = $derived(Math.max(120, width - PAD.left - PAD.right));
  const max = $derived(Math.max(min, ...series.flatMap((s) => s.values.map((v) => v ?? 0))));
  const top = $derived(fmt === "percent" ? Math.min(100, niceTop(max)) : niceTop(max));
  const ticks = $derived([0, 1, 2, 3, 4].map((i) => (top / 4) * i));
  const x = (i: number) => PAD.left + (keys.length > 1 ? (i / (keys.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => PAD.top + (height - PAD.top - PAD.bottom) * (1 - v / top);
  const every = $derived(Math.ceil(keys.length / Math.max(2, Math.floor(plotW / (unit === "month" ? 52 : 64)))));

  function path(values: (number | null)[]): string {
    let d = "", pen = false;
    values.forEach((v, i) => {
      if (v === null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  }

  // End labels, nudged apart so they never overlap (two lines each: value, name).
  const ends = $derived.by(() => {
    if (!showEnds || !keys.length) return [];
    const lo = PAD.top + 6, hi = height - PAD.bottom - 18;
    const items = series.map((s) => {
      const last = [...s.values].reverse().find((v) => v !== null) ?? 0;
      return { ...s, value: last, y: Math.min(hi, Math.max(lo, y(last))) };
    }).sort((a, b) => a.y - b.y);
    for (let i = 1; i < items.length; i++) if (items[i].y - items[i - 1].y < 28) items[i].y = items[i - 1].y + 28;
    const overflow = items.length ? items[items.length - 1].y - hi : 0;
    if (overflow > 0) items.forEach((it) => (it.y -= overflow));
    return items;
  });

  const pick = (e: PointerEvent) => (active = nearest(e.clientX, (e.currentTarget as SVGElement).getBoundingClientRect(), width, PAD.left, plotW, keys.length));
  function key(e: KeyboardEvent) {
    if (!keys.length) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      active = active === null ? keys.length - 1 : Math.min(keys.length - 1, Math.max(0, active + (e.key === "ArrowRight" ? 1 : -1)));
    } else if (e.key === "Escape") active = null;
  }
</script>

<div class="chart" bind:clientWidth={width}>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
  <svg viewBox="0 0 {width} {height}" {height} role="img" tabindex="0" aria-label="{label}. Use the left and right arrow keys to read each point."
       onpointermove={pick} onpointerleave={() => (active = null)} onkeydown={key} onblur={() => (active = null)}>
    {#each ticks as t (t)}
      <line x1={PAD.left} x2={PAD.left + plotW} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" stroke-width="1" />
      <text x={PAD.left - 8} y={y(t) + 4} text-anchor="end" font-size="11" fill="var(--chart-axis)">{short(t, fmt)}</text>
    {/each}
    {#each keys as k, i (k)}
      {#if i % every === 0 || (i === keys.length - 1 && (keys.length - 1) % every > every / 2)}
        <text x={x(i)} y={height - 8} text-anchor="middle" font-size="11" fill="var(--chart-axis)">{tick(k, unit)}</text>
      {/if}
    {/each}
    {#each series as s (s.key)}
      <path d={path(s.values)} fill="none" stroke={s.color} stroke-width="2" stroke-linejoin="round" stroke-linecap="round"
            stroke-dasharray={dashed.includes(s.key) ? "5 4" : undefined} />
      {#each s.values as v, i (i)}
        {#if v !== null && (s.values[i - 1] ?? null) === null && (s.values[i + 1] ?? null) === null}<circle cx={x(i)} cy={y(v)} r="4" fill={s.color} />{/if}
      {/each}
    {/each}
    {#each ends as e (e.key)}
      <text x={PAD.left + plotW + 8} y={e.y + 4} font-size="12" font-weight="600" fill="var(--foreground)">{short(e.value, fmt)}</text>
      <text x={PAD.left + plotW + 8} y={e.y + 16} font-size="10.5" fill="var(--muted-foreground)">{e.label}</text>
    {/each}
    {#if active !== null}
      <line x1={x(active)} x2={x(active)} y1={PAD.top} y2={height - PAD.bottom} stroke="var(--chart-axis)" stroke-width="1" stroke-dasharray="3 3" />
      {#each series as s (s.key)}
        {#if s.values[active] !== null}<circle cx={x(active)} cy={y(s.values[active] ?? 0)} r="4.5" fill={s.color} stroke="var(--card)" stroke-width="2" />{/if}
      {/each}
    {/if}
  </svg>
  {#if active !== null}
    <div class="chart-tooltip" style="left: {Math.max(0, Math.min(x(active) + 12, width - 200))}px; top: 4px" role="status">
      <div class="font-semibold" style="margin-bottom: 6px">{full(keys[active], unit)}</div>
      {#each series as s (s.key)}
        <div class="row"><span class="key"><i style="background:{s.color}"></i>{s.label}</span><strong class="tabular">{exact(s.values[active], fmt)}</strong></div>
      {/each}
    </div>
  {/if}
</div>
