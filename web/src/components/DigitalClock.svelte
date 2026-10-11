<script lang="ts">
  // A digital clock on the centre's time (India): 10:42:07 am, with the day and date under it. Ticks every second
  // while the tab is open; stops while it's in the background (and catches up when you come back).
  let { class: cls = "" }: { class?: string } = $props();

  const TZ = "Asia/Kolkata";
  const timeFmt = new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true, timeZone: TZ });
  const dayFmt = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "short", year: "numeric", timeZone: TZ });

  let now = $state(new Date());
  $effect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      now = new Date();
      if (!document.hidden) timer = setTimeout(tick, 1000 - (Date.now() % 1000)); // land on the second
    };
    const onVisible = () => { clearTimeout(timer); if (!document.hidden) tick(); };
    tick();
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearTimeout(timer); document.removeEventListener("visibilitychange", onVisible); };
  });

  const parts = $derived(timeFmt.formatToParts(now));
  const part = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const hh = $derived(part("hour"));
  const mm = $derived(part("minute"));
  const ss = $derived(part("second"));
  const ampm = $derived(part("dayPeriod").toUpperCase());
  const day = $derived(dayFmt.format(now));
</script>

<div class="clock {cls}" role="timer" aria-label="Time now: {hh}:{mm} {ampm}, {day}">
  <div class="clock-time" aria-hidden="true">
    <span>{hh}</span><span class="colon">:</span><span>{mm}</span><span class="colon">:</span><span class="secs">{ss}</span><span class="ampm">{ampm}</span>
  </div>
  <div class="clock-day" aria-hidden="true">{day}</div>
</div>

<style>
  .clock { display: inline-flex; flex-direction: column; justify-content: center; align-items: flex-end; height: 38px; padding: 0 12px;
    border: 1px solid var(--border); border-radius: 9px; background: var(--card); line-height: 1; white-space: nowrap; }
  .clock-time { display: flex; align-items: baseline; font-size: 16px; font-weight: 650; letter-spacing: 0.02em; color: var(--foreground);
    font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }
  .colon { padding: 0 1px; color: var(--muted-foreground); }
  .secs { color: var(--primary-text); }
  .ampm { margin-left: 5px; font-size: 10.5px; font-weight: 600; color: var(--muted-foreground); letter-spacing: 0.04em; }
  .clock-day { margin-top: 3px; font-size: 10.5px; color: var(--muted-foreground); }
  @media (max-width: 640px) { .clock { align-items: flex-start; } }
</style>
