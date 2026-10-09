<script lang="ts">
  import { date, rupees, rupeesShort, shortDate } from "../lib/format";
  import Icon from "./Icon.svelte";

  // Billed and collected per day: two series of the same unit on one axis. Lines 2px, a legend plus
  // labels at the line ends, recessive grid, a crosshair tooltip on hover (and with the arrow keys),
  // and a table for screen readers. Colours: --chart-1 / --chart-2 (validated for colour-blind readers).
  interface Point { day: string; billed: string | number; collected: string | number }
  let { points }: { points: Point[] } = $props();

  const H = 260, PAD = { top: 16, right: 92, bottom: 28, left: 56 };
  let width = $state(720);
  let active = $state<number | null>(null);

  const series = [
    { key: "billed" as const, label: "Billed", color: "var(--chart-1)" },
    { key: "collected" as const, label: "Collected", color: "var(--chart-2)" },
  ];

  const max = $derived(Math.max(1000, ...points.flatMap((p) => [Number(p.billed), Number(p.collected)])));
  const empty = $derived(points.every((p) => !Number(p.billed) && !Number(p.collected)));
  // A rounded top for the axis: 1, 2 or 5 times a power of ten.
  const top = $derived.by(() => {
    const step = 10 ** Math.floor(Math.log10(max / 4));
    const nice = [1, 2, 5, 10].map((m) => m * step).find((s) => s * 4 >= max) ?? step * 10;
    return nice * 4;
  });
  const ticks = $derived([0, 1, 2, 3, 4].map((i) => (top / 4) * i));
  const plotW = $derived(Math.max(200, width - PAD.left - PAD.right));
  const x = (i: number) => PAD.left + (points.length > 1 ? (i / (points.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => PAD.top + (H - PAD.top - PAD.bottom) * (1 - v / top);
  const path = (key: "billed" | "collected") => points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(Number(p[key])).toFixed(1)}`).join("");
  const labelEvery = $derived(Math.ceil(points.length / Math.max(2, Math.floor(plotW / 70))));

  // Line-end labels, nudged apart when the two values are close.
  const ends = $derived.by(() => {
    if (!points.length) return [];
    const last = points[points.length - 1];
    // Each label is two lines (value, name): keep 30px between them and inside the plot, above the dates.
    const lo = PAD.top + 8, hi = H - PAD.bottom - 22;
    const ys = series.map((s) => Math.min(hi, Math.max(lo, y(Number(last[s.key])))));
    if (Math.abs(ys[0] - ys[1]) < 30) {
      const up = ys[0] <= ys[1] ? 0 : 1;
      const mid = Math.min(hi - 15, Math.max(lo + 15, (ys[0] + ys[1]) / 2));
      ys[up] = mid - 15; ys[1 - up] = mid + 15;
    }
    return series.map((s, i) => ({ ...s, y: ys[i], value: Number(last[s.key]) }));
  });

  function pick(e: PointerEvent) {
    const r = (e.currentTarget as SVGElement).getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * width;
    const i = Math.round(((px - PAD.left) / plotW) * (points.length - 1));
    active = Math.min(points.length - 1, Math.max(0, i));
  }

  function key(e: KeyboardEvent) {
    if (!points.length) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const d = e.key === "ArrowRight" ? 1 : -1;
      active = Math.min(points.length - 1, Math.max(0, (active ?? points.length - 1) + (active === null ? 0 : d)));
    } else if (e.key === "Escape") active = null;
  }

  let showTable = $state(false);
</script>

<div class="stack-sm">
  <div class="row-between">
    <div class="chart-legend" aria-hidden="true">
      {#each series as s (s.key)}<span><span class="swatch" style="background:{s.color}"></span>{s.label}</span>{/each}
    </div>
    <button class="link-button text-sm" type="button" aria-pressed={showTable} onclick={() => (showTable = !showTable)}>
      {showTable ? "Show chart" : "Show as table"}
    </button>
  </div>

  {#if empty}
    <div class="empty"><Icon name="trendUp" />No bills or payments in the last 30 days yet.</div>
  {:else if showTable}
    <div class="table-wrap">
      <table class="table">
        <caption class="sr-only">Billed and collected per day, last 30 days</caption>
        <thead><tr><th>Day</th><th class="num">Billed</th><th class="num">Collected</th></tr></thead>
        <tbody>
          {#each [...points].reverse() as p (p.day)}
            <tr><td>{date(p.day)}</td><td class="num">{rupees(p.billed)}</td><td class="num">{rupees(p.collected)}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <div class="chart" bind:clientWidth={width}>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
      <svg viewBox="0 0 {width} {H}" height={H} role="img" tabindex="0"
           aria-label="Billed and collected per day for the last 30 days. Use the left and right arrow keys to read each day."
           onpointermove={pick} onpointerleave={() => (active = null)} onkeydown={key} onblur={() => (active = null)}>
        {#each ticks as t (t)}
          <line x1={PAD.left} x2={PAD.left + plotW} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" stroke-width="1" />
          <text x={PAD.left - 10} y={y(t) + 4} text-anchor="end" font-size="11" fill="var(--chart-axis)">{rupeesShort(t)}</text>
        {/each}
        {#each points as p, i (p.day)}
          {#if i % labelEvery === 0 || i === points.length - 1}
            <text x={x(i)} y={H - 8} text-anchor="middle" font-size="11" fill="var(--chart-axis)">{shortDate(p.day)}</text>
          {/if}
        {/each}
        {#each series as s (s.key)}
          <path d={path(s.key)} fill="none" stroke={s.color} stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
        {/each}
        {#each ends as e (e.key)}
          <text x={PAD.left + plotW + 10} y={e.y + 4} font-size="12" font-weight="600" fill="var(--foreground)">{rupeesShort(e.value)}</text>
          <text x={PAD.left + plotW + 10} y={e.y + 17} font-size="10.5" fill="var(--muted-foreground)">{e.label}</text>
        {/each}
        {#if active !== null}
          {@const p = points[active]}
          <line x1={x(active)} x2={x(active)} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--chart-axis)" stroke-width="1" stroke-dasharray="3 3" />
          {#each series as s (s.key)}
            <circle cx={x(active)} cy={y(Number(p[s.key]))} r="4.5" fill={s.color} stroke="var(--card)" stroke-width="2" />
          {/each}
        {/if}
      </svg>
      {#if active !== null}
        {@const p = points[active]}
        <div class="chart-tooltip" style="left: {Math.min(x(active) + 12, width - 190)}px; top: 8px" role="status">
          <div class="font-semibold" style="margin-bottom: 6px">{date(p.day)}</div>
          {#each series as s (s.key)}
            <div class="row"><span class="key"><i style="background:{s.color}"></i>{s.label}</span><strong class="money">{rupees(p[s.key])}</strong></div>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>
