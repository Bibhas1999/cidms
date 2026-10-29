// Shapes for bills, patients and the catalogue (app/schemas_billing.py).

import type { BillSummary } from "./types";

export type PaymentMode = "cash" | "upi" | "card" | "bank" | "other";
export const PAYMENT_MODES: [PaymentMode, string][] = [["cash", "Cash"], ["upi", "UPI"], ["card", "Card"], ["bank", "Bank Tr"], ["other", "Other"]];
export const modeLabel = (m: string) => PAYMENT_MODES.find(([v]) => v === m)?.[1] ?? m;

export interface BillLine {
  id: string;
  position: number;
  test_id: string | null;
  test_name: string;
  department_name: string;
  is_imaging: boolean;
  unit_price: string;
  quantity: number;
  amount: string;
  status: "billed" | "scanned" | "reported" | "delivered" | "cancelled";
  accession_no: string;
  status_changed_at: string | null;
}

export interface PaymentRow {
  id: string;
  kind: "payment" | "refund";
  amount: string;
  mode: PaymentMode;
  reference: string;
  note: string;
  received_at: string;
  received_by_name: string;
}

export interface Bill extends BillSummary {
  patient_age: string;
  patient_gender: string;
  patient_address: string;
  guardian_name: string;
  referring_doctor_id: string | null;
  subtotal: string;
  discount_type: "none" | "percent" | "amount";
  discount_value: string;
  discount_amount: string;
  notes: string;
  cancel_reason: string;
  updated_at: string;
  items: BillLine[];
  payments: PaymentRow[];
}

export interface BillPage {
  items: BillSummary[];
  total: number;
  page: number;
  size: number;
  /** Across every matching bill. billed is null for people who may not see turnover (no analytics.view). */
  sums: { billed: string | null; paid: string; due: string };
}

export interface Patient {
  id: string;
  patient_no: string;
  name: string;
  guardian_name: string;
  age_years: number | null;
  date_of_birth: string | null;
  gender: "male" | "female" | "other";
  mobile: string;
  email: string;
  address: string;
  created_at: string;
}

export interface LabTest {
  id: string;
  code: string;
  name: string;
  price: string;
  is_active: boolean;
  department: { id: string; name: string; is_active: boolean };
  test_type: { id: string; name: string; is_imaging: boolean; is_active: boolean } | null;
}

export interface Doctor {
  id: string;
  name: string;
  qualification: string;
  phone: string;
  is_active: boolean;
}

export const BILL_STATUS: Record<string, [string, string]> = {
  confirmed: ["badge-success", "Confirmed"],
  on_hold: ["badge-warning", "On hold"],
  cancelled: ["badge-destructive", "Cancelled"],
};

export const LINE_STATUS: Record<string, [string, string]> = {
  billed: ["badge-warning", "Pending"],
  scanned: ["badge-warning", "In progress"],
  reported: ["badge-info", "Ready"],
  delivered: ["badge-success", "Delivered"],
  cancelled: ["badge-destructive", "Taken off"],
};

export function paymentState(b: { total: string; paid: string; due: string; status: string }): [string, string] {
  if (b.status === "cancelled") return ["badge-destructive", "Cancelled"];
  if (Number(b.due) <= 0) return ["badge-success", "Paid"];
  if (Number(b.paid) > 0) return ["badge-warning", "Part paid"];
  return ["badge-destructive", "Unpaid"];
}

/** The one badge a bill shows in lists: its status when not confirmed (on hold, cancelled), else how much is paid. */
export function billBadge(b: { total: string; paid: string; due: string; status: string }): [string, string] {
  return b.status !== "confirmed" ? (BILL_STATUS[b.status] ?? ["badge-info", b.status]) : paymentState(b);
}

/** What each payment state means, for tooltips. */
export const PAYMENT_HELP: Record<string, string> = {
  Paid: "Everything on this bill has been paid.",
  "Part paid": "Some money has been taken; the rest is still due.",
  Unpaid: "Nothing has been paid on this bill yet.",
  Cancelled: "The bill was cancelled; it isn't counted in totals.",
  "On hold": "Saved but put on hold: tests aren't sent to the worklist until it's confirmed.",
  Confirmed: "The bill is confirmed.",
};
