// Shapes returned by the API (app/schemas.py).

export interface Workspace {
  kind: "client" | "platform" | "none";
  name: string;
  slug: string;
  active: boolean;
  brand_color?: string;
  tagline?: string;
  logo_url?: string;
  /** Development only: the workspaces to open when this address has none. */
  links?: { name: string; url: string }[];
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  roles: string[];
  permissions: string[];
  must_change_password: boolean;
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
  mobile: string;
  is_active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
  roles: Role[];
}

export interface CentreSettings {
  legal_name: string;
  address: string;
  phones: string;
  email: string;
  gst_number: string;
  invoice_prefix: string;
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
