// Shapes of the test-report API (app/schemas_reports.py).

export type ReportStatus = "draft" | "final" | "signed" | "amended";

export const REPORT_STATUS: Record<ReportStatus, [string, string]> = {
  draft: ["badge-warning", "Draft"],
  final: ["badge-info", "Ready to sign"],
  signed: ["badge-success", "Signed"],
  amended: ["badge-navy", "Amended"],
};

export interface ReportItem {
  item_id: string;
  invoice_id: string;
  invoice_no: string;
  bill_date: string;
  test_id: string | null;
  test_name: string;
  department_name: string;
  is_imaging: boolean;
  accession_no: string;
  status: string;
  patient_id: string;
  patient_name: string;
  patient_age: string;
  patient_gender: string;
  patient_mobile: string;
  referring_doctor_name: string;
}

export interface Report {
  id: string;
  invoice_item_id: string;
  status: ReportStatus;
  title: string;
  technique: string;
  modality: string;
  findings: string;
  impression: string;
  reported_by_name: string;
  signed_by: string | null;
  signed_at: string | null;
  signer_name: string;
  signer_degree: string;
  signer_registration_no: string;
  amend_reason: string;
  amendments: number;
  imported: boolean;
  attachment_name: string;
  attachment_pages: number;
  attachment_size: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ReportVersion {
  version: number;
  action: string;
  status: ReportStatus;
  saved_by_name: string;
  reason: string;
  created_at: string;
}

export interface ReportVersionFull extends ReportVersion {
  title: string;
  technique: string;
  modality: string;
  findings: string;
  impression: string;
}

export interface Study {
  id: string;
  study_instance_uid: string;
  modality: string;
  description: string;
  series_count: number;
  instance_count: number;
  size_bytes: number;
  uploaded_by_name: string;
  created_at: string;
  viewer_url: string;
}

export interface PreviousReport {
  item_id: string;
  bill_date: string;
  invoice_no: string;
  test_name: string;
  status: ReportStatus;
  title: string;
  signed_at: string | null;
}

export interface ReportWorkspace {
  item: ReportItem;
  report: Report | null;
  versions: ReportVersion[];
  studies: Study[];
  previous: PreviousReport[];
  image_server: boolean;
}

export interface ReportRow {
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
  item_status: string;
  report_id: string | null;
  report_status: ReportStatus | null;
  report_title: string;
  reported_by_name: string;
  signer_name: string;
  signed_at: string | null;
  updated_at: string | null;
  study_count: number;
  study_uid: string | null;
}

export interface Template {
  id: string;
  test_id: string | null;
  test_name: string;
  name: string;
  title: string;
  technique: string;
  findings: string;
  impression: string;
  is_active: boolean;
  updated_at: string;
}

export interface UploadResult {
  studies: Study[];
  stored: number;
  already_stored: number;
  rejected: number;
  messages: string[];
}

export interface Signature {
  exists: boolean;
  display_name: string;
  degree: string;
  registration_no: string;
  signature: string;
  updated_at: string | null;
}

export interface ReportPrint {
  centre: { legal_name: string; tagline: string; address: string; phones: string; email: string; brand_color: string; has_logo: boolean; report_footer: string };
  item: ReportItem;
  patient_no: string;
  report_id: string;
  status: ReportStatus;
  title: string;
  technique: string;
  modality: string;
  findings: string;
  impression: string;
  version: number;
  amended: boolean;
  amend_reason: string;
  signed_at: string | null;
  signer: { name: string; degree: string; registration_no: string; signature: string } | null;
  is_final: boolean;
  verification: string;
  public_url: string;
}

export interface Delivery {
  id: string;
  channel: string;
  to: string;
  status: "queued" | "sent" | "delivered" | "read" | "failed";
  error: string;
  report_version: number;
  sent_by_name: string;
  created_at: string;
  sent_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
}

export interface Deliveries {
  configured: boolean;
  default_to: string;
  wa_link: string;
  pdf_url: string;
  deliveries: Delivery[];
}

export interface Share {
  exists: boolean;
  active: boolean;
  url: string;
  created_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  views: number;
  last_viewed_at: string | null;
}

export function fileSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

/** Upload with progress (fetch can't report upload progress). Resolves with the parsed JSON. */
export function uploadWithProgress<T>(url: string, body: FormData, csrf: string, onProgress: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.withCredentials = true;
    xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data: any = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else reject(Object.assign(new Error(data?.message ?? `Upload failed (${xhr.status}).`), { status: xhr.status, requestId: data?.request_id ?? null }));
    };
    xhr.onerror = () => reject(Object.assign(new Error("Can't reach CIDMS. Check your connection and try again."), { status: 0 }));
    xhr.send(body);
  });
}
