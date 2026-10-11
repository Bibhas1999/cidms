// Shapes returned by the API (app/schemas.py).

export interface Workspace {
  kind: "client" | "platform" | "none";
  name: string;
  slug: string;
  active: boolean;
  brand_color?: string;
  tagline?: string;
  logo_url?: string;
  /** The wide logo with the centre's name and slogan, when it has one. */
  wordmark_url?: string;
  /** Development only: the workspaces to open when this address has none. */
  links?: { name: string; url: string }[];
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  mobile: string;
  avatar_url: string;
  roles: string[];
  permissions: string[];
  must_change_password: boolean;
  /** May change their own email and password (owner, centre admin, platform staff). */
  manage_own_account: boolean;
  csrf_token: string;
  workspace: Workspace;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

export interface Role {
  id: string;
  code: string;
  name: string;
  description: string;
}

export interface Staff {
  id: string;
  email: string;
  full_name: string;
  avatar_url: string;
  mobile: string;
  is_active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
  roles: Role[];
}

export interface CentreSettings {
  legal_name: string;
  tagline: string;
  brand_color: string;
  logo_file: string;
  wordmark_file: string;
  address: string;
  phones: string;
  email: string;
  gst_number: string;
  invoice_prefix: string;
  bill_paper?: "A4" | "A5";
  bill_footer: string;
  report_footer: string;
  updated_at: string;
}

export interface Activity {
  id: number;
  created_at: string;
  user_name: string | null;
  action: string;
  entity: string;
  entity_id: string;
  details: Record<string, unknown>;
  ip_address: string | null;
}

export interface Plan {
  id: string;
  code: string;
  name: string;
  max_users: number;
  max_bills_per_month: number;
  storage_gb: number;
  price_monthly: string;
}

export interface Client {
  id: string;
  slug: string;
  name: string;
  kind: "diagnostic" | "opd" | "clinic";
  status: "active" | "suspended";
  plan: Plan | null;
  paid_until: string | null;
  created_at: string;
}

// ---------- billing ----------

export interface BillSummary {
  id: string;
  invoice_no: string;
  legacy_no: number | null;
  bill_date: string;
  patient_id: string;
  patient_name: string;
  patient_mobile: string;
  referring_doctor_name: string;
  status: "confirmed" | "on_hold" | "cancelled";
  total: string;
  paid: string;
  due: string;
  created_by_name: string;
  created_at: string;
}

export interface DaySummary {
  day: string;
  bills: number;
  billed: string;
  discounts: string;
  collected: Record<string, string>;
  collected_total: string;
  dues_collected: string;
  refunds: string;
  outstanding_dues: string;
  items_by_status: Record<string, number>;
}

export interface Breakdown {
  name: string;
  bills: number;
  amount: string;
}

/** GET /api/summary/desk: the dashboard for staff without analytics.view (no billed totals). */
export interface DeskSummary {
  date_from: string;
  date_to: string;
  all_time: boolean;
  bills: number;
  billed: string;
  collected: Record<string, string>;
  collected_total: string;
  dues_collected: string;
  refunds: string;
  due_on_bills: string;
  due_bills: number;
  outstanding_dues: string;
  dues_count: number;
  pending_tests: { billed: number; scanned: number };
}

export interface Overview {
  date_from: string;
  date_to: string;
  days: number;
  all_time: boolean;
  period: {
    bills: number; billed: string; discounts: string; due_on_bills: string; patients: number;
    collected: Record<string, string>; collected_total: string; dues_collected: string; refunds: string;
  };
  previous: { date_from: string; date_to: string; bills: number; billed: string; collected_total: string };
  dues_count: number;
  outstanding_dues: string;
  trend: { day: string; billed: string; collected: string }[];
  trend_unit: "day" | "month";
  departments: Breakdown[];
  doctors: Breakdown[];
  pending_tests: { billed: number; scanned: number };
  oldest_dues: BillSummary[];
}

// ---------- catalogue, patients, worklist ----------

export interface Department {
  id: string;
  name: string;
  is_active: boolean;
}

export interface TestType {
  id: string;
  name: string;
  is_imaging: boolean;
  is_active: boolean;
}

export interface LabTest {
  id: string;
  code: string;
  name: string;
  price: string;
  is_active: boolean;
  department: Department;
  test_type: TestType | null;
}

export interface Doctor {
  id: string;
  name: string;
  qualification: string;
  phone: string;
  is_active: boolean;
}

export type Gender = "male" | "female" | "other";

export interface Patient {
  id: string;
  patient_no: string;
  name: string;
  guardian_name: string;
  age_years: number | null;
  date_of_birth: string | null;
  gender: string;
  mobile: string;
  email: string;
  address: string;
  created_at: string;
}

export type ItemStatus = "billed" | "scanned" | "reported" | "delivered";

export interface WorklistRow {
  item_id: string;
  invoice_id: string;
  invoice_no: string;
  bill_date: string;
  patient_name: string;
  patient_age: string;
  patient_gender: string;
  test_name: string;
  department_name: string;
  is_imaging: boolean;
  accession_no: string;
  status: ItemStatus;
  bill_status: string;
  due: string;
  status_changed_at: string | null;
}

export const GENDER_LABELS: Record<string, string> = { male: "Male", female: "Female", other: "Other" };

/** "34 y · Female", from the age in years or the date of birth. */
export function ageGender(p: Pick<Patient, "age_years" | "date_of_birth" | "gender">): string {
  let age: number | null = p.age_years;
  if (p.date_of_birth) {
    const dob = new Date(`${p.date_of_birth}T12:00:00Z`), now = new Date();
    age = now.getUTCFullYear() - dob.getUTCFullYear()
      - (now.getUTCMonth() < dob.getUTCMonth() || (now.getUTCMonth() === dob.getUTCMonth() && now.getUTCDate() < dob.getUTCDate()) ? 1 : 0);
  }
  const g = GENDER_LABELS[p.gender] ?? p.gender;
  return [age === null ? "" : `${age} y`, g].filter(Boolean).join(" · ") || "—";
}
