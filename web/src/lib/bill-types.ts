// Shapes for bills, patients and the catalogue (app/schemas_billing.py).

import type { BillSummary } from "./types";

export type PaymentMode = "cash" | "upi" | "card" | "bank" | "other";
export const PAYMENT_MODES: [PaymentMode, string][] = [["cash", "Cash"], ["upi", "UPI"], ["card", "Card"], ["bank", "Bank transfer"], ["other", "Other"]];
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
  sums: { billed: string; due: string };
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
  billed: ["badge-info", "Waiting"],
  scanned: ["badge-warning", "Scanned"],
  reported: ["badge-navy", "Reported"],
  delivered: ["badge-success", "Delivered"],
  cancelled: ["badge-destructive", "Taken off"],
};

export function paymentState(b: { total: string; paid: string; due: string; status: string }): [string, string] {
  if (b.status === "cancelled") return ["badge-destructive", "Cancelled"];
  if (Number(b.due) <= 0) return ["badge-success", "Paid"];
  if (Number(b.paid) > 0) return ["badge-warning", "Part paid"];
  return ["badge-destructive", "Unpaid"];
}
