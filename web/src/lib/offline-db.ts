// The browser's IndexedDB, for working without the internet. Each centre's address has its own database
// (browsers keep sites apart).
//   cache      what New bill needs (tests and prices, doctors, recent patients, the centre's bill details)
//   bills      bills made offline, waiting to be sent (lib/offline.svelte.ts)
//   responses  a saved copy of every screen's data (lib/response-cache.svelte.ts)
//   outbox     changes made offline (payments), waiting to be sent (lib/outbox.svelte.ts)
//   keys       this browser's encryption key (lib/vault.ts): a CryptoKey that can be used but never read out
// Everything but the key is stored encrypted (AES-GCM, lib/vault.ts): idbPut seals a record and idbGet/idbAll open
// it again, so the browser's storage tools show only scrambled bytes. A record saved before this (or where the
// browser can't encrypt) is read as it is. Records with a key path keep just that field in the clear.

import { seal, unseal, type Sealed } from "./vault";

const NAME = "cidms-offline";
const VERSION = 2;
export type Store = "cache" | "bills" | "responses" | "outbox" | "keys";
const KEY_PATH: Partial<Record<Store, string>> = { bills: "id", outbox: "id" };
const PLAIN: Store[] = ["keys", "responses"];   // the key itself; responses seal their own contents

let opening: Promise<IDBDatabase> | null = null;

function open(): Promise<IDBDatabase> {
  opening ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(NAME, VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("cache")) db.createObjectStore("cache");
      if (!db.objectStoreNames.contains("bills")) db.createObjectStore("bills", { keyPath: "id" });
      if (!db.objectStoreNames.contains("responses")) db.createObjectStore("responses");
      if (!db.objectStoreNames.contains("outbox")) db.createObjectStore("outbox", { keyPath: "id" });
      if (!db.objectStoreNames.contains("keys")) db.createObjectStore("keys");
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => { opening = null; reject(req.error); };
  });
  return opening;
}

function run<T>(store: Store, mode: IDBTransactionMode, work: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T> {
  return open().then((db) => new Promise<T>((resolve, reject) => {
    const tx = db.transaction(store, mode);
    const req = work(tx.objectStore(store));
    tx.oncomplete = () => resolve(req ? req.result : (undefined as T));
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  }));
}

// ---------- as stored (the vault uses these for its key) ----------
export const rawGet = <T>(store: Store, key: string) => run<T | undefined>(store, "readonly", (s) => s.get(key) as IDBRequest<T | undefined>);
export const rawPut = (store: Store, value: unknown, key?: string) => run<IDBValidKey>(store, "readwrite", (s) => s.put(value, key));

// ---------- encrypted ----------
interface Wrapped { sealed: Sealed; [keyPath: string]: unknown }
const isWrapped = (v: unknown): v is Wrapped => !!v && typeof v === "object" && "sealed" in (v as object);

async function wrap(store: Store, value: unknown): Promise<unknown> {
  if (PLAIN.includes(store)) return value;
  const box = await seal(value);
  if (!box) return value;   // this browser can't encrypt: keep it as it is rather than lose it
  const kp = KEY_PATH[store];
  return kp ? { [kp]: (value as Record<string, unknown>)[kp], sealed: box } : { sealed: box };
}

async function unwrap<T>(store: Store, value: unknown): Promise<T | undefined> {
  if (value === undefined || PLAIN.includes(store) || !isWrapped(value)) return value as T | undefined;
  return (await unseal<T>(value.sealed)) ?? undefined;
}

export async function idbGet<T>(store: Store, key: string): Promise<T | undefined> {
  return unwrap<T>(store, await rawGet(store, key));
}
export async function idbAll<T>(store: Store): Promise<T[]> {
  const rows = await run<unknown[]>(store, "readonly", (s) => s.getAll());
  const open = await Promise.all(rows.map((r) => unwrap<T>(store, r)));
  return open.filter((r): r is Awaited<T> => r !== undefined) as T[];
}
export async function idbPut(store: Store, value: unknown, key?: string): Promise<IDBValidKey> {
  return rawPut(store, await wrap(store, value), key);
}
export const idbDelete = (store: Store, key: string) => run<undefined>(store, "readwrite", (s) => s.delete(key));
export const idbClear = (store: Store) => run<undefined>(store, "readwrite", (s) => s.clear());
export const idbKeys = (store: Store) => run<IDBValidKey[]>(store, "readonly", (s) => s.getAllKeys());
export const idbCount = (store: Store) => run<number>(store, "readonly", (s) => s.count());
