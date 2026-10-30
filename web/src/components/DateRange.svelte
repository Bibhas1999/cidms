<script lang="ts">
  import { datePresets, todayISO } from "../lib/dates";

  // The registry's date filter: one Duration drop-down that fills in From and To, plus the two dates for
  // anything else. Typing a date yourself makes it "Custom range". Days are the centre's (India) calendar.
  let { from = "", to = "", onchange, id = "range", anyLabel = "Any time", compact = false }: {
    from?: string; to?: string; onchange: (from: string, to: string) => void; id?: string; anyLabel?: string;
    /** Show the From and To dates only for a custom range (for page headers). */
    compact?: boolean;
  } = $props();

  const today = todayISO();
  const PRESETS = $derived(datePresets(anyLabel));
  const current = $derived(PRESETS.find((p) => p.from === from && p.to === to)?.key ?? "custom");
  let custom = $state(false);
  const showDates = $derived(!compact || custom || current === "custom");

  function pick(value: string) {
    if (value === "custom") { custom = true; return; }
    custom = false;
    const p = PRESETS.find((x) => x.key === value);
    if (p) onchange(p.from, p.to);
  }
</script>

<div class="date-filter" role="group" aria-label="Dates">
  <label class="sr-only" for="{id}-duration">Duration</label>
  <select id="{id}-duration" class="select" value={custom ? "custom" : current} onchange={(e) => pick(e.currentTarget.value)}>
    {#each PRESETS as p (p.key)}<option value={p.key}>{p.label}</option>{/each}
    {#if compact || current === "custom"}<option value="custom">{compact ? "Custom range…" : "Custom range"}</option>{/if}
  </select>
  {#if showDates}
    <span class="date-range">
      <label class="date-field">From <input class="input" type="date" value={from} max={to || today} onchange={(e) => onchange(e.currentTarget.value, to)} /></label>
      <label class="date-field">To <input class="input" type="date" value={to} min={from || undefined} max={today} onchange={(e) => onchange(from, e.currentTarget.value)} /></label>
    </span>
  {/if}
</div>

<style src="./styles/DateRange.css"></style>
