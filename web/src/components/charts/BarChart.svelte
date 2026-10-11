<script lang="ts">
  import { exact, full, niceTop, short, tick, type Fmt, type Series, type Unit } from "../../lib/chart";

  // Bars: vertical (time or categories) or horizontal (ranked lists, long names), one series or several,
  // grouped side by side or stacked. Thin bars with a 4px rounded end away from the baseline, a 2px surface
  // gap between stacked segments and neighbouring bars, values at the bar ends for horizontal bars, and a
  // tooltip per category (hover, tap, or arrow keys). The card gives the legend and the table view.
  let { keys, series, unit = "none", fmt = "money", mode = "grouped", horizontal = false, height = 240, label,
        names = null, showValues = true }: {
    keys: string[]; series: Series[]; unit?: Unit; fmt?: Fmt; mode?: "grouped" | "stacked"; horizontal?: boolean; height?: number;
    label: string;
    /** Display names for the keys, when the keys are ids (horizontal bars). */
    names?: string[] | null;
    showValues?: boolean;
  } = $props();

  let width = $state(640);
  let active = $state<number | null>(null);
  const narrow = $derived(width < 480);
  const stacked = $derived(mode === "stacked" && series.length > 1);
  const totals = $derived(keys.map((_, i) => series.reduce((a, s) => a + (s.values[i] ?? 0), 0)));
  const max = $derived(stacked ? Math.max(0, ...totals) : Math.max(0, ...series.flatMap((s) => s.values.map((v) => v ?? 0))));
  const top = $derived(niceTop(max));
  const nameOf = (i: number) => names?.[i] ?? (unit === "none" ? keys[i] : full(keys[i], unit));

  // Path for a bar with only its far end rounded (r ≤ 4), so it stays anchored to the baseline.
  function barPath(x: number, y: number, w: number, h: number, dir: "up" | "right", round = true): string {
    if (w <= 0 || h <= 0) return "";
    const r = round ? Math.min(4, dir === "up" ? w / 2 : h / 2, dir === "up" ? h : w) : 0;
    if (dir === "up") return `M${x} ${y + h}V${y + r}Q${x} ${y} ${x + r} ${y}H${x + w - r}Q${x + w} ${y} ${x + w} ${y + r}V${y + h}Z`;
    return `M${x} ${y}H${x + w - r}Q${x + w} ${y} ${x + w} ${y + r}V${y + h - r}Q${x + w} ${y + h} ${x + w - r} ${y + h}H${x}Z`;
  }

  // ---------- vertical ----------
  const VP = $derived({ top: 14, right: 8, bottom: 26, left: narrow ? 40 : 52 });
  const plotW = $derived(Math.max(100, width - VP.left - VP.right));
  const plotH = $derived(height - VP.top - VP.bottom);
  const band = $derived(plotW / Math.max(1, keys.length));
  const barW = $derived(Math.max(2, Math.min(36, band * (keys.length > 40 ? 0.8 : 0.66))));
  const vy = (v: number) => VP.top + plotH * (1 - v / top);
  const every = $derived(Math.ceil(keys.length / Math.max(2, Math.floor(plotW / (unit === "month" ? 52 : unit === "none" ? 70 : 64)))));
  const vbars = $derived.by(() => {
    const out: { d: string; color: string; key: string }[] = [];
    keys.forEach((k, i) => {
      const cx = VP.left + band * i + band / 2;
      if (stacked) {
        let acc = 0;
        const last = series.map((s) => (s.values[i] ?? 0) > 0).lastIndexOf(true);
        series.forEach((s, j) => {
          const v = s.values[i] ?? 0;
          if (v <= 0) return;
          const y0 = vy(acc), y1 = vy(acc + v);
          const h = y0 - y1 - (acc > 0 ? 2 : 0); // a 2px surface gap above the segment below
          out.push({ d: barPath(cx - barW / 2, y1, barW, Math.max(0, h), "up", j === last), color: s.color, key: `${k}-${s.key}` });
          acc += v;
        });
      } else {
        const n = series.length, gap = n > 1 ? 2 : 0;
        const w = Math.max(2, (barW - gap * (n - 1)) / n);
        series.forEach((s, j) => {
          const v = s.values[i] ?? 0;
          const y1 = vy(v);
          out.push({ d: barPath(cx - barW / 2 + j * (w + gap), y1, w, VP.top + plotH - y1, "up"), color: s.color, key: `${k}-${s.key}` });
        });
      }
    });
    return out;
  });

  // ---------- horizontal ----------
  // Each row: the name (left) and value (right) on one line, then the bar(s) under it, then a gap.
  const LABEL = 20, BAR = 10, GAP = 14;
  const barArea = $derived(series.length > 1 && !stacked ? series.length * (BAR + 2) - 2 : BAR);
  const ROW = $derived(LABEL + barArea + GAP);
  const hHeight = $derived(keys.length * ROW - GAP + 4);
  const HP = { left: 0, right: 0 };
  const hW = $derived(Math.max(80, width));
  const valueText = (i: number) => (stacked || series.length === 1 ? short(totals[i], fmt) : series.map((s) => short(s.values[i] ?? 0, fmt)).join(" · "));
  const hx = (v: number) => (v / (top || 1)) * hW;
  const hbars = $derived.by(() => {
    const out: { d: string; color: string; key: string }[] = [];
    keys.forEach((k, i) => {
      const y0 = i * ROW + LABEL;
      if (stacked) {
        let acc = 0;
        const last = series.map((s) => (s.values[i] ?? 0) > 0).lastIndexOf(true);
        series.forEach((s, j) => {
          const v = s.values[i] ?? 0;
          if (v <= 0) return;
          const x0 = HP.left + hx(acc) + (acc > 0 ? 2 : 0);
          out.push({ d: barPath(x0, y0, Math.max(0, hx(acc + v) - hx(acc) - (acc > 0 ? 2 : 0)), BAR, "right", j === last), color: s.color, key: `${k}-${s.key}` });
          acc += v;
        });
      } else {
        series.forEach((s, j) => {
          out.push({ d: barPath(HP.left, y0 + j * (BAR + 2), Math.max(0, hx(s.values[i] ?? 0)), BAR, "right"), color: s.color, key: `${k}-${s.key}` });
        });
      }
    });
    return out;
  });

  function pickV(e: PointerEvent) {
    const r = (e.currentTarget as SVGElement).getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * width;
    const i = Math.floor((px - VP.left) / band);
    active = i >= 0 && i < keys.length ? i : null;
  }
  function pickH(e: PointerEvent) {
    const r = (e.currentTarget as SVGElement).getBoundingClientRect();
    const py = ((e.clientY - r.top) / r.height) * hHeight;
    const i = Math.floor(py / ROW);
    active = i >= 0 && i < keys.length ? i : null;
  }
  function key(e: KeyboardEvent) {
    if (!keys.length) return;
    const next = horizontal ? ["ArrowDown", "ArrowUp"] : ["ArrowRight", "ArrowLeft"];
    if (next.includes(e.key)) {
      e.preventDefault();
      active = active === null ? 0 : Math.min(keys.length - 1, Math.max(0, active + (e.key === next[0] ? 1 : -1)));
    } else if (e.key === "Escape") active = null;
  }
  const tipLeft = $derived(active === null ? 0 : horizontal ? Math.min(width - 210, Math.max(0, hx(totals[active] ?? 0) - 100))
    : Math.max(0, Math.min(VP.left + band * active + band / 2 + 12, width - 210)));
  const tipTop = $derived(active === null ? 0 : horizontal ? active * ROW + ROW - GAP + 6 : 4);
</script>

<div class="chart" bind:clientWidth={width}>
  {#if horizontal}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
    <svg viewBox="0 0 {width} {hHeight}" height={hHeight} role="img" tabindex="0" aria-label="{label}. Use the up and down arrow keys to read each bar."
         onpointermove={pickH} onpointerleave={() => (active = null)} onkeydown={key} onblur={() => (active = null)}>
      {#each keys as k, i (k)}
        {#if active === i}<rect x="0" y={i * ROW - 4} width={width} height={ROW - GAP + 8} rx="4" fill="var(--muted)" opacity="0.6" />{/if}
        <text x={HP.left} y={i * ROW + 13} font-size="12.5" fill="var(--foreground)">
          {(() => { const n = nameOf(i); const room = Math.floor((width - (showValues ? valueText(i).length * 7.5 + 16 : 0)) / 6.8); return n.length > room ? n.slice(0, Math.max(4, room - 1)) + "…" : n; })()}
        </text>
        {#if showValues}
          <text x={width} y={i * ROW + 13} text-anchor="end" font-size="12.5" font-weight="600" fill="var(--foreground)" class="tabular">{valueText(i)}</text>
        {/if}
      {/each}
      {#each hbars as b (b.key)}<path d={b.d} fill={b.color} />{/each}
    </svg>
  {:else}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
    <svg viewBox="0 0 {width} {height}" {height} role="img" tabindex="0" aria-label="{label}. Use the left and right arrow keys to read each bar."
         onpointermove={pickV} onpointerleave={() => (active = null)} onkeydown={key} onblur={() => (active = null)}>
      {#each [0, 1, 2, 3, 4] as t (t)}
        <line x1={VP.left} x2={VP.left + plotW} y1={vy((top / 4) * t)} y2={vy((top / 4) * t)} stroke="var(--chart-grid)" stroke-width="1" />
        <text x={VP.left - 8} y={vy((top / 4) * t) + 4} text-anchor="end" font-size="11" fill="var(--chart-axis)">{short((top / 4) * t, fmt)}</text>
      {/each}
      {#if active !== null}<rect x={VP.left + band * active} y={VP.top} width={band} height={plotH} fill="var(--muted)" opacity="0.6" />{/if}
      {#each vbars as b (b.key)}<path d={b.d} fill={b.color} />{/each}
      {#each keys as k, i (k)}
        {#if i % every === 0}
          <text x={VP.left + band * i + band / 2} y={height - 8} text-anchor="middle" font-size="11" fill="var(--chart-axis)">
            {unit === "none" ? (k.length > 10 ? k.slice(0, 9) + "…" : k) : tick(k, unit)}</text>
        {/if}
      {/each}
    </svg>
  {/if}
  {#if active !== null}
    <div class="chart-tooltip" style="left: {tipLeft}px; top: {tipTop}px" role="status">
      <div class="font-semibold" style="margin-bottom: 6px">{nameOf(active)}</div>
      {#each series as s (s.key)}
        <div class="row"><span class="key">{#if series.length > 1}<i style="background:{s.color}"></i>{/if}{s.label}</span><strong class="tabular">{exact(s.values[active], fmt)}</strong></div>
      {/each}
      {#if stacked}<div class="row" style="border-top: 1px solid var(--border); margin-top: 4px; padding-top: 4px"><span class="key">Total</span><strong class="tabular">{exact(totals[active], fmt)}</strong></div>{/if}
    </div>
  {/if}
</div>
