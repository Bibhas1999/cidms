<script lang="ts">
  // The registry's date filter: one Duration drop-down that fills in From and To, plus the two dates for
  // anything else. Typing a date yourself makes it "Custom range". Days are the centre's (India) calendar.
  let { from = "", to = "", onchange, id = "range", anyLabel = "Any time" }: {
    from?: string; to?: string; onchange: (from: string, to: string) => void; id?: string; anyLabel?: string;
  } = $props();

  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  const shift = (iso: string, days: number) => { const d = new Date(`${iso}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); };
  const firstOfMonth = (iso: string) => iso.slice(0, 8) + "01";
  const lastMonthEnd = shift(firstOfMonth(today), -1);
  const fyStart = (() => { const [y, m] = today.split("-").map(Number); return `${m >= 4 ? y : y - 1}-04-01`; })();

  const PRESETS: [string, string, string, string][] = $derived([
    ["any", anyLabel, "", ""],
    ["today", "Today", today, today],
    ["yesterday", "Yesterday", shift(today, -1), shift(today, -1)],
    ["7d", "Last 7 days", shift(today, -6), today],
    ["30d", "Last 30 days", shift(today, -29), today],
    ["month", "This month", firstOfMonth(today), today],
    ["last-month", "Last month", firstOfMonth(lastMonthEnd), lastMonthEnd],
    ["fy", "This financial year", fyStart, today],
  ]);

  const current = $derived(PRESETS.find(([, , f, t]) => f === from && t === to)?.[0] ?? "custom");

  function pick(value: string) {
    const p = PRESETS.find(([v]) => v === value);
    if (p) onchange(p[2], p[3]);
  }
</script>

<div class="date-filter" role="group" aria-label="Dates">
  <label class="sr-only" for="{id}-duration">Duration</label>
  <select id="{id}-duration" class="select" value={current} onchange={(e) => pick(e.currentTarget.value)}>
    {#each PRESETS as [value, label] (value)}<option {value}>{label}</option>{/each}
    {#if current === "custom"}<option value="custom">Custom range</option>{/if}
  </select>
  <span class="date-range">
    <label class="date-field">From <input class="input" type="date" value={from} max={to || today} onchange={(e) => onchange(e.currentTarget.value, to)} /></label>
    <label class="date-field">To <input class="input" type="date" value={to} min={from || undefined} max={today} onchange={(e) => onchange(from, e.currentTarget.value)} /></label>
  </span>
</div>

<style>
  .date-filter { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .date-filter > .select { width: auto; min-width: 170px; }
</style>
