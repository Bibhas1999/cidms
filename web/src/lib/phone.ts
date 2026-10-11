// Mobile numbers: a country code and the number, saved in the international (E.164) format, e.g.
// "+919876543210". Numbers brought across from the old app (10 digits, no code) are read as Indian.

export interface Country {
  code: string;   // ISO, for the flag
  dial: string;   // "+91"
  name: string;
  /** National number rule for this country; others use a generic 6–14 digits. */
  pattern?: RegExp;
  hint?: string;
}

export const COUNTRIES: Country[] = [
  { code: "IN", dial: "+91", name: "India", pattern: /^[6-9]\d{9}$/, hint: "10 digits, starting 6, 7, 8 or 9" },
  { code: "BD", dial: "+880", name: "Bangladesh", pattern: /^1\d{9}$/, hint: "10 digits, starting 1" },
  { code: "NP", dial: "+977", name: "Nepal", pattern: /^9\d{9}$/, hint: "10 digits, starting 9" },
  { code: "BT", dial: "+975", name: "Bhutan", pattern: /^\d{8}$/, hint: "8 digits" },
  { code: "LK", dial: "+94", name: "Sri Lanka", pattern: /^7\d{8}$/, hint: "9 digits, starting 7" },
  { code: "AE", dial: "+971", name: "United Arab Emirates", pattern: /^5\d{8}$/, hint: "9 digits, starting 5" },
  { code: "SA", dial: "+966", name: "Saudi Arabia", pattern: /^5\d{8}$/, hint: "9 digits, starting 5" },
  { code: "QA", dial: "+974", name: "Qatar", pattern: /^\d{8}$/, hint: "8 digits" },
  { code: "KW", dial: "+965", name: "Kuwait", pattern: /^\d{8}$/, hint: "8 digits" },
  { code: "OM", dial: "+968", name: "Oman", pattern: /^\d{8}$/, hint: "8 digits" },
  { code: "BH", dial: "+973", name: "Bahrain", pattern: /^\d{8}$/, hint: "8 digits" },
  { code: "SG", dial: "+65", name: "Singapore", pattern: /^[89]\d{7}$/, hint: "8 digits, starting 8 or 9" },
  { code: "MY", dial: "+60", name: "Malaysia", pattern: /^1\d{8,9}$/, hint: "9 or 10 digits, starting 1" },
  { code: "GB", dial: "+44", name: "United Kingdom", pattern: /^7\d{9}$/, hint: "10 digits, starting 7" },
  { code: "US", dial: "+1", name: "United States / Canada", pattern: /^[2-9]\d{9}$/, hint: "10 digits" },
  { code: "AU", dial: "+61", name: "Australia", pattern: /^4\d{8}$/, hint: "9 digits, starting 4" },
];

export const DEFAULT_DIAL = "+91";

export const countryOf = (dial: string) => COUNTRIES.find((c) => c.dial === dial);

export function flag(code: string): string {
  return code.toUpperCase().replace(/./g, (c) => String.fromCodePoint(127397 + c.charCodeAt(0)));
}

/** Split a stored number into its code and national digits. "" -> default code, no digits. */
export function splitPhone(value: string | null | undefined): { dial: string; number: string } {
  const v = (value ?? "").replace(/[\s()-]/g, "");
  if (!v) return { dial: DEFAULT_DIAL, number: "" };
  if (v.startsWith("+")) {
    // Longest matching code first (+880 before +88…).
    const c = [...COUNTRIES].sort((a, b) => b.dial.length - a.dial.length).find((x) => v.startsWith(x.dial));
    if (c) return { dial: c.dial, number: v.slice(c.dial.length) };
    const m = /^(\+\d{1,3})(\d+)$/.exec(v);
    return m ? { dial: m[1], number: m[2] } : { dial: DEFAULT_DIAL, number: v.replace(/\D/g, "") };
  }
  const digits = v.replace(/\D/g, "");
  // Old records: 10 digits (or 0 / 91 in front) are Indian numbers.
  if (digits.length === 11 && digits.startsWith("0")) return { dial: "+91", number: digits.slice(1) };
  if (digits.length === 12 && digits.startsWith("91")) return { dial: "+91", number: digits.slice(2) };
  return { dial: DEFAULT_DIAL, number: digits };
}

export function joinPhone(dial: string, number: string): string {
  const digits = number.replace(/\D/g, "");
  return digits ? `${dial}${digits}` : "";
}

/** A message when the number isn't valid for its country, or "" when it's fine (or empty and optional). */
export function phoneProblem(dial: string, number: string, required = false): string {
  const digits = number.replace(/\D/g, "");
  if (!digits) return required ? "Enter the mobile number." : "";
  if (digits !== number.replace(/[\s-]/g, "")) return "Use digits only.";
  const c = countryOf(dial);
  if (c?.pattern) return c.pattern.test(digits) ? "" : `Enter a valid ${c.name} mobile number: ${c.hint}.`;
  return /^\d{6,14}$/.test(digits) ? "" : "Enter 6 to 14 digits.";
}

/** "+919876543210" -> "+91 98765 43210" for showing; anything else as it is. */
export function formatPhone(value: string | null | undefined): string {
  const { dial, number } = splitPhone(value);
  if (!number) return "";
  if (dial === "+91" && number.length === 10) return `+91 ${number.slice(0, 5)} ${number.slice(5)}`;
  return `${dial} ${number}`;
}
