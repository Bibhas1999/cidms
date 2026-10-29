// Date ranges on the centre's (India) calendar: the Duration presets shared by every date filter, and
// the words for a range ("Today", "This month", "1 Feb – 9 Oct 2026"). An empty `from` and `to` is "all time".

import { date } from "./format";

export const todayISO = (): string => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());

export function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

const firstOfMonth = (iso: string) => iso.slice(0, 8) + "01";

export interface Preset { key: string; label: string; from: string; to: string }

/** The Duration choices, worked out for today. The first is "all time" (no dates), named by `anyLabel`. */
export function datePresets(anyLabel = "Any time"): Preset[] {
  const today = todayISO();
  const lastMonthEnd = shiftDays(firstOfMonth(today), -1);
  const [y, m] = today.split("-").map(Number);
  const fyStart = `${m >= 4 ? y : y - 1}-04-01`;
  return [
    { key: "any", label: anyLabel, from: "", to: "" },
    { key: "today", label: "Today", from: today, to: today },
    { key: "yesterday", label: "Yesterday", from: shiftDays(today, -1), to: shiftDays(today, -1) },
    { key: "7d", label: "Last 7 days", from: shiftDays(today, -6), to: today },
    { key: "30d", label: "Last 30 days", from: shiftDays(today, -29), to: today },
    { key: "month", label: "This month", from: firstOfMonth(today), to: today },
    { key: "last-month", label: "Last month", from: firstOfMonth(lastMonthEnd), to: lastMonthEnd },
    { key: "year", label: "This year", from: `${y}-01-01`, to: today },
    { key: "last-year", label: "Last year", from: `${y - 1}-01-01`, to: `${y - 1}-12-31` },
    { key: "fy", label: "This financial year", from: fyStart, to: today },
  ];
}

/** The preset a range matches, if any. */
export const presetOf = (from: string, to: string, anyLabel?: string): Preset | undefined =>
  datePresets(anyLabel).find((p) => p.from === from && p.to === to);

/** "Today", "Last 7 days", "9 Oct 2026", "1 Feb 2026 – 9 Oct 2026", "Since 1 Feb 2026", "All time". */
export function rangeLabel(from: string, to: string, anyLabel = "All time"): string {
  const p = presetOf(from, to, anyLabel);
  if (p) return p.label;
  if (from && to) return from === to ? date(from) : `${date(from)} – ${date(to)}`;
  if (from) return `Since ${date(from)}`;
  if (to) return `Up to ${date(to)}`;
  return anyLabel;
}

/** The 1st of this month to today: the dashboard's default period. */
export function thisMonth(): { from: string; to: string } {
  const today = todayISO();
  return { from: `${today.slice(0, 8)}01`, to: today };
}
