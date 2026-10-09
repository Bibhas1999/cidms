// Dates and money as people in India read them. Stored in UTC; shown in Indian time.

const TZ = "Asia/Kolkata";

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: TZ }).format(new Date(iso));
}

export function date(iso: string | null | undefined): string {
  if (!iso) return "—";
  // A plain date ("2026-10-09") is a calendar day, not a moment: don't shift it by time zone.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T12:00:00Z`) : new Date(iso);
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeZone: TZ }).format(d);
}

export function shortDate(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${iso}T12:00:00Z`));
}

export function rupees(value: string | number, { paise = true } = {}): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: paise ? 2 : 0,
                                          maximumFractionDigits: paise ? 2 : 0 }).format(Number(value));
}

/** ₹4.2L, ₹38k, ₹950: for axes and tight tiles. */
export function rupeesShort(value: string | number): string {
  const v = Number(value);
  if (Math.abs(v) >= 1e7) return `₹${(v / 1e7).toFixed(v >= 1e8 ? 0 : 1)}Cr`;
  if (Math.abs(v) >= 1e5) return `₹${(v / 1e5).toFixed(v >= 1e6 ? 0 : 1)}L`;
  if (Math.abs(v) >= 1e3) return `₹${(v / 1e3).toFixed(v >= 1e4 ? 0 : 1)}k`;
  return `₹${Math.round(v)}`;
}

export function count(n: number): string {
  return n.toLocaleString("en-IN");
}

/** "staff.created" -> "Staff created" */
export function actionLabel(action: string): string {
  const s = action.replace(/[._]/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
