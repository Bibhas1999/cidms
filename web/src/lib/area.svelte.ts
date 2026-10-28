// The work area someone is in: Admin, Reception, the OPD or one department. After every sign-in a person picks
// one (/choose-area, after every sign-in) and sees only that area's menu and pages. The server
// enforces who may work where; this only decides what's shown.
//
//   area.current   the chosen Area, or null (none chosen yet, or none given)
//   area.list      every area they may work in (me.areas)
//   area.choose(key) · area.clear() · area.switchTo(key) (choose and go to its home page)
//
// Kept in localStorage per centre address and person, so a reload keeps it; forgotten on every sign-in and sign-out.

import { navigate } from "./router.svelte";
import { session } from "./session.svelte";
import type { Area, AreaKind } from "./types";

const storageKey = (userId: string) => `cidms:area:${location.hostname}:${userId}`;

/** Each area's first page. */
export const AREA_HOME: Record<AreaKind, string> = { admin: "/", reception: "/", opd: "/opd", department: "/worklist" };

/** The icon and one line on what's there, for the area cards and the switcher. */
export const AREA_INFO: Record<AreaKind, { icon: string; line: string }> = {
  admin: { icon: "shield", line: "The dashboard, analytics, billing reports and the catalogue of tests, prices and doctors." },
  reception: { icon: "receipt", line: "New bills, payments, dues and patients at the front desk." },
  opd: { icon: "stethoscope", line: "Today's OPD queue with tokens for each doctor, new visits and their fees." },
  department: { icon: "clipboard", line: "This department's worklist: tests to start, ready and handed over." },
};

class AreaState {
  #key = $state<string | null>(null);
  /** Whose choice it is (still known while signing out, after `me` is gone). */
  #user = "";

  /** Areas are in use in a centre whose server tells us where the person may work (not on the platform). */
  get inUse(): boolean {
    return !!session.me && !session.isPlatform && Array.isArray(session.me.areas);
  }

  /** Every area of the centre (the chooser shows them all), including ones they don't work in. */
  get all(): Area[] {
    return this.inUse ? session.me!.areas : [];
  }

  /** The areas they may work in. */
  get list(): Area[] {
    return this.all.filter((a) => a.allowed !== false);
  }

  /** The area chosen since signing in. Always picked in the chooser, even with only one, as the owner wants. */
  get current(): Area | null {
    return this.list.find((a) => a.key === this.#key) ?? null;
  }

  /** May move between areas (has more than one). */
  get canSwitch(): boolean {
    return this.list.length > 1;
  }

  choose(key: string): void {
    this.#key = key;
    const id = session.me?.id ?? this.#user;
    if (!id) return;
    this.#user = id;
    try { localStorage.setItem(storageKey(id), key); } catch { /* storage blocked: kept for this tab only */ }
  }

  clear(): void {
    const id = session.me?.id ?? this.#user;
    this.#key = null;
    this.#user = session.me?.id ?? "";
    if (!id) return;
    try { localStorage.removeItem(storageKey(id)); } catch { /* storage blocked */ }
  }

  /** Choose an area and go to its first page (or `next`, when given). */
  switchTo(key: string, next = ""): void {
    const a = this.list.find((x) => x.key === key);
    if (!a) return;
    this.choose(key);
    navigate(next || AREA_HOME[a.kind], { replace: !!next });
  }

  /** The area saved for whoever is signed in (the app opened or reloaded). */
  restore(): void {
    const id = session.me?.id ?? "";
    this.#user = id;
    let saved: string | null = null;
    try { saved = id ? localStorage.getItem(storageKey(id)) : null; } catch { /* storage blocked */ }
    this.#key = saved;
  }
}

export const area = new AreaState();

// A fresh sign-in starts with no area (they pick again); opening the app again keeps the one picked.
session.onSignedIn((how) => { if (how === "login") area.clear(); else area.restore(); });
session.onSignedOut(() => { area.clear(); });
