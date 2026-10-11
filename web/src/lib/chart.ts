// Shared pieces for the charts in components/charts: series colours (in fixed order, by entity), rounded
// axis tops, labels for time buckets, and value formats. Colours are CSS tokens (styles in charts.css),
// validated with the dataviz palette checker against the light and dark card surfaces.

import { count, date, rupees, rupeesShort, shortDate } from "./format";

/** Categorical slots in fixed order. Never cycled: a sixth series folds into "Other". */
export const SERIES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];

/** Payment modes always wear the same colour, whichever of them appear. */
export const MODE_COLORS: Record<string, string> = {
  cash: "var(--chart-1)", upi: "var(--chart-2)", card: "var(--chart-3)", bank: "var(--chart-4)", other: "var(--chart-5)",
};
export const MODE_LABELS: Record<string, string> = { cash: "Cash", upi: "UPI", card: "Card", bank: "Bank", other: "Other" };
export const MODE_ORDER = ["cash", "upi", "card", "bank", "other"];

export type Unit = "day" | "week" | "month" | "hour" | "none";
export type Fmt = "money" | "count" | "percent" | "hours";

export interface Series { key: string; label: string; color: string; values: (number | null)[] }

/** A rounded top for the axis: 1, 2 or 5 times a power of ten, in four steps. */
export function niceTop(max: number, steps = 4): number {
  if (!(max > 0)) return steps;
  const step = 10 ** Math.floor(Math.log10(max / steps));
  const nice = [1, 2, 2.5, 5, 10].map((m) => m * step).find((s) => s * steps >= max) ?? step * 10;
  return nice * steps;
}

const monthName = (iso: string, style: "short" | "long") =>
  new Intl.DateTimeFormat("en-IN", { month: style, year: style === "long" ? "numeric" : "2-digit", timeZone: "UTC" })
    .format(new Date(`${iso}T12:00:00Z`));

/** Short label under the axis. */
export function tick(key: string, unit: Unit): string {
  if (unit === "month") return monthName(key, "short");
  if (unit === "day" || unit === "week") return shortDate(key);
  if (unit === "hour") return hourLabel(Number(key));
  return key;
}

/** The full name of a bucket, for tooltips and tables. */
export function full(key: string, unit: Unit): string {
  if (unit === "month") return monthName(key, "long");
  if (unit === "week") return `Week of ${date(key)}`;
  if (unit === "day") return date(key);
  if (unit === "hour") return `${hourLabel(Number(key))}–${hourLabel((Number(key) + 1) % 24)}`;
  return key;
}

export const hourLabel = (h: number) => `${h % 12 || 12}${h < 12 ? "am" : "pm"}`;

/** Axis and label text: compact. */
export function short(v: number | null, fmt: Fmt): string {
  if (v === null || Number.isNaN(v)) return "—";
  if (fmt === "money") return rupeesShort(v);
  if (fmt === "percent") return `${Math.round(v)}%`;
  if (fmt === "hours") return `${v < 10 ? v.toFixed(1) : Math.round(v)}h`;
  return v >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : v >= 1e3 ? `${(v / 1e3).toFixed(v >= 1e4 ? 0 : 1)}k` : count(Math.round(v * 10) / 10);
}

/** Tooltip and table text: exact. */
export function exact(v: number | null, fmt: Fmt): string {
  if (v === null || Number.isNaN(v)) return "—";
  if (fmt === "money") return rupees(v, { paise: false });
  if (fmt === "percent") return `${v.toFixed(1)}%`;
  if (fmt === "hours") return v >= 48 ? `${(v / 24).toFixed(1)} days` : `${v.toFixed(1)} hours`;
  return count(Math.round(v * 10) / 10);
}

export const num = (v: string | number | null | undefined): number => (v === null || v === undefined || v === "" ? 0 : Number(v));

/** Index of the nearest point to a pointer x, given the plot's left edge and width. */
export function nearest(clientX: number, rect: DOMRect, width: number, left: number, plotW: number, n: number): number {
  const px = ((clientX - rect.left) / rect.width) * width;
  return Math.min(n - 1, Math.max(0, Math.round(((px - left) / plotW) * (n - 1))));
}
