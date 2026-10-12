// Billing without the internet. While online, the desk keeps a copy of what New bill needs (tests and prices,
// doctors, the most recent patients, the centre's bill details). When CIDMS can't be reached, New bill still
// works from that copy: the bill is kept on this computer with a provisional number (OFF-K7Q-0003) and printed.
// When the connection is back, waiting bills are sent by themselves, oldest first, each with its own
// Idempotency-Key so a bill is never made twice, and with the time it was really made (the bill keeps that day).
// A bill CIDMS can't take as it is (prices changed since, a discount above the limit…) waits in Offline bills
// with the reason, for someone to look at. Only the person who made a bill sends it (the bill is in their name).

import { ApiError, api, get } from "./api";
import type { Bill, Doctor, LabTest, Patient } from "./bill-types";
import { connection } from "./connection.svelte";
import { idbAll, idbClear, idbDelete, idbGet, idbPut } from "./offline-db";
import { session } from "./session.svelte";
import { navigate } from "./router.svelte";
import { notify } from "./toast.svelte";
import type { CentreSettings, Page } from "./types";

const REFRESH_EVERY_MS = 30 * 60 * 1000;
const KEEP_SENT_MS = 7 * 24 * 3600 * 1000;   // sent bills stay listed a week (to reprint with the final number)
const RECENT_PATIENTS = 300;

export type OfflineStatus = "waiting" | "attention" | "sent";

export interface OfflineBill {
  id: string;                 // also the Idempotency-Key
  offline_no: string;
  user_id: string;
  made_at: string;
  body: Record<string, unknown>;   // what New bill would have sent
  bill: Bill;                      // for the screen and the printout
  patient_no: string;
  status: OfflineStatus;
  error: string;
  error_field: string;
  accept_new_total: boolean;
  sent?: { id: string; invoice_no: string; at: string };
}

// ---------- the copy of the catalogue ----------

interface CacheEntry<T> { value: T; saved_at: string }

async function cached<T>(key: string): Promise<T | null> {
  try { return ((await idbGet<CacheEntry<T>>("cache", key))?.value) ?? null; } catch { return null; }
}

async function pages<T>(path: string, query: Record<string, string | number | boolean>, max: number): Promise<T[]> {
  const out: T[] = [];
  for (let page = 1; out.length < max; page++) {
    const r = await get<Page<T>>(path, { ...query, page, size: 100 });
    out.push(...r.items);
    if (out.length >= r.total || !r.items.length) break;
  }
  return out.slice(0, max);
}

/** Bring the desk's copy up to date (when online and allowed to bill). Quiet: a failure just keeps the old copy. */
export async function refreshOfflineData(): Promise<void> {
  if (!session.me || session.isPlatform || !session.can("billing.create") || !connection.usable) return;
  try {
    const [tests, doctors, patients, settings] = await Promise.all([
      pages<LabTest>("/api/tests", { active: true }, 2000),
      pages<Doctor>("/api/doctors", { active: true }, 2000),
      pages<Patient>("/api/patients", {}, RECENT_PATIENTS),
      get<CentreSettings>("/api/settings"),
    ]);
    const saved_at = new Date().toISOString();
    await Promise.all([
      idbPut("cache", { value: tests, saved_at }, "tests"),
      idbPut("cache", { value: doctors, saved_at }, "doctors"),
      idbPut("cache", { value: patients, saved_at }, "patients"),
      idbPut("cache", { value: settings, saved_at }, "settings"),
      idbPut("cache", { value: saved_at, saved_at }, "refreshed_at"),
    ]);
    offline.readyAt = saved_at;
  } catch { /* keep the copy we have */ }
}

export const cachedSettings = () => cached<CentreSettings & { max_discount_percent?: string }>("settings");

const norm = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim();
function pageOf<T>(all: T[], page: number, size: number): Page<T> {
  return { items: all.slice((page - 1) * size, page * size), total: all.length, page, size };
}

export async function searchCachedTests(q: string, page: number, size: number): Promise<Page<LabTest>> {
  const words = norm(q);
  const all = (await cached<LabTest[]>("tests")) ?? [];
  return pageOf(words ? all.filter((t) => norm(`${t.name} ${t.code} ${t.department.name}`).includes(words)) : all, page, size);
}

export async function searchCachedDoctors(q: string, page: number, size: number): Promise<Page<Doctor>> {
  const words = norm(q);
  const all = (await cached<Doctor[]>("doctors")) ?? [];
  return pageOf(words ? all.filter((d) => norm(d.name).includes(words)) : all, page, size);
}

export async function searchCachedPatients(q: string, page: number, size: number): Promise<Page<Patient>> {
  const words = norm(q);
  const digits = q.replace(/\D/g, "");
  const all = (await cached<Patient[]>("patients")) ?? [];
  return pageOf(words ? all.filter((p) => norm(`${p.name} ${p.patient_no}`).includes(words) || (digits.length >= 4 && p.mobile.replace(/\D/g, "").includes(digits))) : all, page, size);
}

/** A search that uses CIDMS when it can and the desk's copy when it can't (or the request fails on the network). */
export function withOffline<T>(online: (q: string, page: number, size: number, signal: AbortSignal) => Promise<Page<T>>,
                               local: (q: string, page: number, size: number) => Promise<Page<T>>) {
  return async (q: string, page: number, size: number, signal: AbortSignal): Promise<Page<T>> => {
    if (!connection.usable) return local(q, page, size);
    try {
      return await online(q, page, size, signal);
    } catch (e) {
      if (e instanceof ApiError && e.transient) return local(q, page, size);
      throw e;
    }
  };
}

// ---------- bills made offline ----------

function deviceCode(): string {
  try {
    let code = localStorage.getItem("cidms:device");
    if (!code) {
      const abc = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
      code = Array.from(crypto.getRandomValues(new Uint8Array(3)), (n) => abc[n % abc.length]).join("");
      localStorage.setItem("cidms:device", code);
    }
    return code;
  } catch {
    return "TMP";
  }
}

async function nextOfflineNo(): Promise<string> {
  const dev = deviceCode();
  const used = (await idbAll<OfflineBill>("bills")).map((b) => Number(b.offline_no.split("-").pop()) || 0);
  let n = 0;
  try { n = Number(localStorage.getItem(`cidms:offline-seq:${dev}`) ?? 0); } catch { /* blocked */ }
  n = Math.max(n, ...used) + 1;
  try { localStorage.setItem(`cidms:offline-seq:${dev}`, String(n)); } catch { /* blocked */ }
  return `OFF-${dev}-${String(n).padStart(4, "0")}`;
}

/** Keep a bill on this computer (CIDMS can't be reached). Returns it, ready to print. */
export async function saveOfflineBill(id: string, body: Record<string, unknown>, bill: Omit<Bill, "invoice_no" | "id" | "bill_date" | "created_at" | "updated_at">,
                                      patientNo: string): Promise<OfflineBill> {
  const made = new Date();
  const offline_no = await nextOfflineNo();
  const day = `${made.getFullYear()}-${String(made.getMonth() + 1).padStart(2, "0")}-${String(made.getDate()).padStart(2, "0")}`;
  const record: OfflineBill = {
    id, offline_no, user_id: session.me?.id ?? "", made_at: made.toISOString(), body, patient_no: patientNo,
    bill: { ...bill, id, invoice_no: offline_no, bill_date: day, created_at: made.toISOString(), updated_at: made.toISOString() } as Bill,
    status: "waiting", error: "", error_field: "", accept_new_total: false,
  };
  await idbPut("bills", $state.snapshot(record));
  await offline.reload();
  return record;
}

export const getOfflineBill = (id: string) => idbGet<OfflineBill>("bills", id);

class OfflineState {
  bills = $state<OfflineBill[]>([]);
  sending = $state(false);
  readyAt = $state("");

  get waiting(): number { return this.bills.filter((b) => b.status === "waiting").length; }
  get attention(): number { return this.bills.filter((b) => b.status === "attention").length; }
  /** Bills of mine not yet in CIDMS. */
  get unsent(): number { return this.bills.filter((b) => b.status !== "sent").length; }

  async reload(): Promise<void> {
    try {
      const all = await idbAll<OfflineBill>("bills");
      const old = all.filter((b) => b.status === "sent" && Date.now() - new Date(b.sent?.at ?? b.made_at).getTime() > KEEP_SENT_MS);
      await Promise.all(old.map((b) => idbDelete("bills", b.id)));
      this.bills = all.filter((b) => !old.includes(b) && (!session.me || b.user_id === session.me.id))
        .sort((a, b) => b.made_at.localeCompare(a.made_at));
    } catch { this.bills = []; }
  }

  async #update(b: OfflineBill, change: Partial<OfflineBill>): Promise<void> {
    await idbPut("bills", { ...$state.snapshot(b), ...change });
  }

  /** Send waiting bills now (oldest first). Stops at the first network failure: the rest go on the next try. */
  async send({ only }: { only?: string } = {}): Promise<void> {
    if (this.sending || !connection.usable || !session.me) return;
    this.sending = true;
    const sent: string[] = [];
    let attention = 0;
    try {
      await this.reload();
      const queue = this.bills.filter((b) => (only ? b.id === only && b.status !== "sent" : b.status === "waiting"))
        .sort((a, b) => a.made_at.localeCompare(b.made_at));
      for (const b of queue) {
        try {
          const saved = await api<Bill>("POST", "/api/bills", {
            body: { ...b.body, offline: { made_at: b.made_at, offline_no: b.offline_no, printed_total: b.bill.total, accept_new_total: b.accept_new_total } },
            headers: { "Idempotency-Key": b.id }, progress: false,
          });
          await this.#update(b, { status: "sent", error: "", error_field: "", sent: { id: saved.id, invoice_no: saved.invoice_no, at: new Date().toISOString() } });
          sent.push(saved.invoice_no);
        } catch (e) {
          if (!(e instanceof ApiError) || e.transient || e.status === 401) break;   // try again later
          if (e.field === "offline_duplicate") {                                    // already in CIDMS
            const no = /as (\S+?)\.?$/.exec(e.message)?.[1] ?? "";
            await this.#update(b, { status: "sent", error: "", error_field: "", sent: { id: "", invoice_no: no, at: new Date().toISOString() } });
            continue;
          }
          attention++;
          await this.#update(b, { status: "attention", error: e.message, error_field: e.field ?? "" });
        }
      }
    } finally {
      this.sending = false;
      await this.reload();
    }
    if (sent.length) {
      notify(`${sent.length === 1 ? "The offline bill is" : `${sent.length} offline bills are`} now in CIDMS: ${sent.join(", ")}.`,
             { title: "Offline bills sent", action: { label: "Show", run: () => navigate("/bills/offline") } });
      void refreshOfflineData();
    }
    if (attention) notify(`${attention === 1 ? "An offline bill needs" : `${attention} offline bills need`} a look before it can be sent.`,
                          { kind: "warning", duration: 0, action: { label: "Open", run: () => navigate("/bills/offline") } });
  }

  async retry(b: OfflineBill, { acceptNewTotal = false } = {}): Promise<void> {
    await this.#update(b, { status: "waiting", accept_new_total: acceptNewTotal || b.accept_new_total, error: "", error_field: "" });
    await this.reload();
    await this.send({ only: b.id });
  }

  async discard(b: OfflineBill): Promise<void> {
    await idbDelete("bills", b.id);
    await this.reload();
  }
}

export const offline = new OfflineState();

/** Start keeping the copy fresh and sending waiting bills: on start, when the connection is back, and every
 *  30 seconds while bills wait (or 30 minutes for the copy). */
export function installOffline(): void {
  session.onSignedIn(() => void startOfflineFor());
  session.onSignedOut(() => void forgetOfflineData());
  const tick = () => { if (offline.waiting) void offline.send(); };
  connection.onBack(() => { void session.refresh().then(() => { void offline.send(); void refreshOfflineData(); }); });
  setInterval(tick, 30_000);
  setInterval(() => void refreshOfflineData(), REFRESH_EVERY_MS);
  void cached<string>("refreshed_at").then((at) => { offline.readyAt = at ?? ""; });
}

/** Signed in (or the page opened with a session): load my offline bills, send any waiting, refresh the copy. */
export async function startOfflineFor(): Promise<void> {
  await offline.reload();
  void offline.send();
  void refreshOfflineData();
}

/** Signing out: the copy of patients and the catalogue goes; bills not yet sent stay, for their maker. */
export async function forgetOfflineData(): Promise<void> {
  try { await idbClear("cache"); } catch { /* blocked */ }
  offline.bills = [];
}
