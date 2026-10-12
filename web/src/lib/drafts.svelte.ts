// Unsaved forms kept on this computer as you type, so nothing is lost when you move to another page, the tab
// closes or the power goes: open the form again and it carries on where you left off. Kept in the browser's
// localStorage, separately for each centre and each person (another person signing in on the same computer
// doesn't see your drafts), and thrown away after 7 days or once the form is saved.
//
//   const draft = readDraft<BillDraft>("new-bill");      // when the page opens
//   autosaveDraft("new-bill", () => ({ ... }), (v) => !v.lines.length && !v.patient);
//   clearDraft("new-bill");                               // once saved

import { session } from "./session.svelte";

const PREFIX = "cidms:draft:";
const MAX_AGE_MS = 7 * 24 * 3600 * 1000;

export interface Draft<T> { value: T; saved_at: string; version: number }

const key = (name: string) => `${PREFIX}${location.hostname}:${session.me?.id ?? "anon"}:${name}`;

/** The saved draft of a form, or null. A draft of an older shape (version) or older than 7 days is dropped. */
export function readDraft<T>(name: string, version = 1): Draft<T> | null {
  try {
    const raw = localStorage.getItem(key(name));
    if (!raw) return null;
    const d = JSON.parse(raw) as Draft<T>;
    if (d.version !== version || Date.now() - new Date(d.saved_at).getTime() > MAX_AGE_MS) {
      localStorage.removeItem(key(name));
      return null;
    }
    return d;
  } catch {
    return null;
  }
}

export function writeDraft<T>(name: string, value: T, version = 1): void {
  try {
    localStorage.setItem(key(name), JSON.stringify({ value, saved_at: new Date().toISOString(), version } satisfies Draft<T>));
  } catch {
    /* storage full or blocked (private window): the form still works, just without a draft */
  }
}

export function clearDraft(name: string): void {
  try { localStorage.removeItem(key(name)); } catch { /* blocked */ }
}

/** Drop drafts older than 7 days (on every computer the app opens on), so old patient details don't linger. */
export function pruneDrafts(): void {
  try {
    for (const k of Object.keys(localStorage)) {
      if (!k.startsWith(PREFIX)) continue;
      const saved = (JSON.parse(localStorage.getItem(k) ?? "{}") as Partial<Draft<unknown>>).saved_at;
      if (!saved || Date.now() - new Date(saved).getTime() > MAX_AGE_MS) localStorage.removeItem(k);
    }
  } catch { /* blocked */ }
}

/** Save the form as a draft whenever what read() returns changes; when it's empty, there's no draft.
 *  Call while the component starts (it uses $effect). Pause with paused() while a saved form is leaving. */
export function autosaveDraft<T>(name: string, read: () => T, isEmpty: (value: T) => boolean,
                                 { version = 1, paused = () => false }: { version?: number; paused?: () => boolean } = {}): void {
  $effect(() => {
    const value = $state.snapshot(read()) as T;
    if (paused()) return;
    if (isEmpty(value)) clearDraft(name);
    else writeDraft(name, value, version);
  });
}

/** "5 minutes ago", for "Your unsaved bill from 5 minutes ago is back". */
export function savedAgo(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}
