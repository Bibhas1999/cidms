// Notifications for the signed-in person: the unread count, the latest few, and the live stream.
//
//   import { notifications } from "../lib/notifications.svelte";
//   notifications.start()            once signed in (NotificationBell does it); stop() on sign-out
//   notifications.unread / .items    reactive
//   notifications.markRead(id) / markAllRead()
//
// Live updates come over Server-Sent Events (/api/notifications/stream). The browser reconnects by itself; if
// the stream can't be used (a proxy that buffers, the server refusing), it falls back to asking for the unread
// count every POLL_MS and tries the stream again later. A browser pop-up is shown only when this tab is hidden
// and the person turned pop-ups on (Settings > Notifications), through the service worker when there is one.

import { post, put } from "./api";
import { navigate } from "./router.svelte";
import type { Page } from "./types";

export type Severity = "info" | "success" | "warning" | "danger";

export interface Notice {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string;
  severity: Severity;
  read_at: string | null;
  created_at: string;
}

export interface KindPref { code: string; label: string; description: string; audience: string; can_mute: boolean; enabled: boolean }
export interface Preferences { kinds: KindPref[]; browser_popups: boolean }

const POLL_MS = 30_000;

/** A background read that doesn't show the page's loading bar (and never signs anyone out by itself). */
async function quiet<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${res.status}`);
  return (await res.json()) as T;
}
const LATEST = 8;

export const popupsSupported = (): boolean => typeof window !== "undefined" && "Notification" in window;

/** "just now", "5 min ago", "3 h ago", "yesterday", "4 Oct". */
export function relativeTime(iso: string, now = Date.now()): string {
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86_400) return `${Math.round(s / 3600)} h ago`;
  if (s < 2 * 86_400) return "yesterday";
  if (s < 7 * 86_400) return `${Math.round(s / 86_400)} days ago`;
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }).format(new Date(iso));
}

/** The exact moment, for the tooltip on a relative time. */
export const exactTime = (iso: string): string =>
  new Intl.DateTimeFormat("en-IN", { dateStyle: "full", timeStyle: "short", timeZone: "Asia/Kolkata" }).format(new Date(iso));

/** Show a browser pop-up (service worker if registered, else a page Notification). Clicking opens `link`. */
export async function showPopup(title: string, body: string, link = "", tag = ""): Promise<boolean> {
  if (!popupsSupported() || Notification.permission !== "granted") return false;
  // renotify: a reused tag (e.g. "sdms-test", clicked more than once) would otherwise update the existing
  // OS notification silently instead of alerting again. (Not in this TS version's DOM types, though every
  // browser that supports Notification supports it.)
  const options = { body, tag: tag || undefined, renotify: !!tag, icon: "/icons/icon-192-v2.png", badge: "/icons/favicon.png", data: { link } } as NotificationOptions;
  try {
    const reg = "serviceWorker" in navigator ? await navigator.serviceWorker.getRegistration() : undefined;
    if (reg) { await reg.showNotification(title, options); return true; }
  } catch { /* fall through to a page notification */ }
  try {
    const n = new Notification(title, options);
    n.onclick = () => { window.focus(); if (link) openLink(link); n.close(); };
    return true;
  } catch {
    return false;
  }
}

/** In-app links go through the router; downloads (/api/…) are opened by the browser. */
export function openLink(link: string): void {
  if (!link) return;
  if (link.startsWith("/api/")) window.location.assign(link);
  else navigate(link);
}

class NotificationStore {
  unread = $state(0);
  items = $state<Notice[]>([]);
  loaded = $state(false);
  live = $state(false);            // the stream is connected
  popups = $state(false);          // the person wants browser pop-ups
  #source: EventSource | null = null;
  #poll: ReturnType<typeof setInterval> | null = null;
  #retry: ReturnType<typeof setTimeout> | null = null;
  #failures = 0;
  #running = false;
  // A pop-up clicked while this tab was open (web/public/sw.js): go to its page here.
  #fromWorker = (e: MessageEvent) => { if (e.data?.type === "navigate" && typeof e.data.to === "string") openLink(e.data.to); };
  #visibility = () => { if (document.visibilityState === "visible" && this.#running && !this.live) this.#connect(); };

  start(): void {
    if (this.#running) return;
    this.#running = true;
    void this.refresh();
    void quiet<Preferences>("/api/notifications/preferences").then((p) => (this.popups = p.browser_popups)).catch(() => {});
    document.addEventListener("visibilitychange", this.#visibility);
    if ("serviceWorker" in navigator) navigator.serviceWorker.addEventListener("message", this.#fromWorker);
    this.#connect();
  }

  stop(): void {
    this.#running = false;
    this.#source?.close();
    this.#source = null;
    this.live = false;
    this.#stopPolling();
    if (this.#retry) clearTimeout(this.#retry);
    document.removeEventListener("visibilitychange", this.#visibility);
    if ("serviceWorker" in navigator) navigator.serviceWorker.removeEventListener("message", this.#fromWorker);
    this.items = [];
    this.unread = 0;
    this.loaded = false;
  }

  async refresh(): Promise<void> {
    try {
      const [page, count] = await Promise.all([
        quiet<Page<Notice>>(`/api/notifications?size=${LATEST}`),
        quiet<{ count: number }>("/api/notifications/unread-count"),
      ]);
      this.items = page.items;
      this.unread = count.count;
      this.loaded = true;
    } catch { /* the bell just stays as it was */ }
  }

  async markRead(id: string): Promise<void> {
    const n = this.items.find((i) => i.id === id);
    if (n?.read_at) return;
    if (n) n.read_at = new Date().toISOString();
    this.unread = Math.max(0, this.unread - 1);
    try {
      this.unread = (await post<{ count: number }>(`/api/notifications/${id}/read`)).count;
    } catch {
      void this.refresh();
    }
  }

  async markAllRead(): Promise<void> {
    const now = new Date().toISOString();
    for (const i of this.items) i.read_at ??= now;
    this.unread = 0;
    await post("/api/notifications/read-all");
  }

  async savePreferences(muted: string[], browserPopups: boolean): Promise<Preferences> {
    const p = await put<Preferences>("/api/notifications/preferences", { muted_kinds: muted, browser_popups: browserPopups });
    this.popups = p.browser_popups;
    return p;
  }

  // ----- the stream
  #connect(): void {
    if (!this.#running || typeof EventSource === "undefined") { this.#startPolling(); return; }
    this.#source?.close();
    const es = new EventSource("/api/notifications/stream", { withCredentials: true });
    this.#source = es;
    es.addEventListener("open", () => { this.live = true; this.#failures = 0; this.#stopPolling(); });
    es.addEventListener("unread", (e) => { this.unread = JSON.parse((e as MessageEvent).data).count; });
    es.addEventListener("notification", (e) => this.#arrived(JSON.parse((e as MessageEvent).data) as Notice));
    es.addEventListener("reconnect", () => { es.close(); this.live = false; this.#connect(); });
    es.addEventListener("end", () => { es.close(); this.live = false; this.#running = false; });
    es.onerror = () => {
      this.live = false;
      if (es.readyState === EventSource.CLOSED || ++this.#failures >= 3) {
        // The server refused the stream (signed out, a proxy in the way): poll, and try the stream again later.
        es.close();
        this.#startPolling();
        if (this.#retry) clearTimeout(this.#retry);
        const wait = Math.min(5 * 60_000, 15_000 * 2 ** Math.min(this.#failures, 4));
        this.#retry = setTimeout(() => { if (this.#running && document.visibilityState === "visible") this.#connect(); }, wait);
      }
    };
  }

  #arrived(n: Notice): void {
    if (this.items.some((i) => i.id === n.id)) return;
    this.items = [n, ...this.items].slice(0, LATEST * 2);
    if (this.popups && document.visibilityState === "hidden") void showPopup(n.title, n.body, n.link, n.id);
  }

  #startPolling(): void {
    if (this.#poll || !this.#running) return;
    this.#poll = setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      const before = this.unread;
      try {
        this.unread = (await quiet<{ count: number }>("/api/notifications/unread-count")).count;
        if (this.unread !== before) void this.refresh();
      } catch { /* try again next time */ }
    }, POLL_MS);
  }

  #stopPolling(): void {
    if (this.#poll) clearInterval(this.#poll);
    this.#poll = null;
  }
}

export const notifications = new NotificationStore();

export const SEVERITY_ICON: Record<Severity, string> = { info: "info", success: "check", warning: "alert", danger: "alert" };
