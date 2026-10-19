// Changes made while CIDMS can't be reached (for now: a payment collected on a bill), kept on this computer
// (encrypted, like everything in lib/offline-db.ts), and sent by themselves when the connection is back, oldest first. Each keeps the
// Idempotency-Key its screen made, so even if it's sent twice CIDMS records it once. One CIDMS won't take as it
// is (nothing is due any more, say) waits in Offline with the reason. Only the person who made it sends it.
import { ApiError, api } from "./api";
import { connection } from "./connection.svelte";
import { idbAll, idbDelete, idbPut } from "./offline-db";
import { navigate } from "./router.svelte";
import { session } from "./session.svelte";
import { notify } from "./toast.svelte";

const KEEP_SENT_MS = 7 * 24 * 3600 * 1000;

export type OutboxStatus = "waiting" | "attention" | "sent";

interface Stored {
  id: string;              // the Idempotency-Key
  user_id: string;
  made_at: string;
  label: string;           // e.g. "₹ 500.00 from Ramen Dey on SHC/2026-27/000123"
  link: string;            // where to look at it (the bill)
  status: OutboxStatus;
  error: string;
  sent_at?: string;
  request: Request;
}
export type OutboxItem = Omit<Stored, "request">;

interface Request { method: "POST" | "PUT" | "PATCH" | "DELETE"; path: string; body: unknown }

class Outbox {
  items = $state<OutboxItem[]>([]);
  sending = $state(false);

  get waiting(): number { return this.items.filter((i) => i.status === "waiting").length; }
  get attention(): number { return this.items.filter((i) => i.status === "attention").length; }

  async reload(): Promise<void> {
    try {
      const all = await idbAll<Stored>("outbox");
      const old = all.filter((i) => i.status === "sent" && Date.now() - new Date(i.sent_at ?? i.made_at).getTime() > KEEP_SENT_MS);
      await Promise.all(old.map((i) => idbDelete("outbox", i.id)));
      this.items = all.filter((i) => !old.includes(i) && (!session.me || i.user_id === session.me.id))
        .map(({ request: _, ...rest }) => rest).sort((a, b) => b.made_at.localeCompare(a.made_at));
    } catch { this.items = []; }
  }

  /** Keep a change to send later. Returns false if this browser can't keep it (then the screen shows the error). */
  async add(id: string, request: Request, label: string, link: string): Promise<boolean> {
    if (!session.me) return false;
    const item: Stored = { id, user_id: session.me.id, made_at: new Date().toISOString(), label, link, status: "waiting", error: "", request };
    try { await idbPut("outbox", item); } catch { return false; }
    await this.reload();
    return true;
  }

  async #set(id: string, change: Partial<Stored>): Promise<void> {
    const all = await idbAll<Stored>("outbox");
    const item = all.find((i) => i.id === id);
    if (item) await idbPut("outbox", { ...item, ...change });
  }

  /** Send what's waiting (oldest first); stops at the first network failure, the rest go on the next try. */
  async send({ only }: { only?: string } = {}): Promise<void> {
    if (this.sending || !connection.usable || !session.me) return;
    this.sending = true;
    let sent = 0, attention = 0;
    try {
      const all = (await idbAll<Stored>("outbox")).filter((i) => i.user_id === session.me!.id && (only ? i.id === only && i.status !== "sent" : i.status === "waiting"))
        .sort((a, b) => a.made_at.localeCompare(b.made_at));
      for (const item of all) {
        const req = item.request;
        try {
          await api(req.method, req.path, { body: req.body, headers: { "Idempotency-Key": item.id }, progress: false });
          await this.#set(item.id, { status: "sent", error: "", sent_at: new Date().toISOString() });
          sent++;
        } catch (e) {
          if (!(e instanceof ApiError) || e.transient || e.status === 401) break;
          attention++;
          await this.#set(item.id, { status: "attention", error: e.message });
        }
      }
    } finally {
      this.sending = false;
      await this.reload();
    }
    if (sent) notify(`${sent === 1 ? "A change made offline is" : `${sent} changes made offline are`} now in CIDMS.`, { title: "Offline changes sent" });
    if (attention) notify(`${attention === 1 ? "A change made offline needs" : `${attention} changes made offline need`} a look.`,
                          { kind: "warning", duration: 0, action: { label: "Open", run: () => navigate("/bills/offline") } });
  }

  async retry(item: OutboxItem): Promise<void> {
    await this.#set(item.id, { status: "waiting", error: "" });
    await this.reload();
    await this.send({ only: item.id });
  }

  async discard(item: OutboxItem): Promise<void> {
    await idbDelete("outbox", item.id);
    await this.reload();
  }
}

export const outbox = new Outbox();
