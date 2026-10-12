// The browser's IndexedDB, for billing without the internet (lib/offline.svelte.ts): a "cache" of what New bill
// needs (tests and prices, doctors, recent patients, the centre's bill details) and the "bills" made offline,
// waiting to be sent. Each centre's address has its own database (browsers keep sites apart).

const NAME = "cidms-offline";
const VERSION = 1;
export type Store = "cache" | "bills";

let opening: Promise<IDBDatabase> | null = null;

function open(): Promise<IDBDatabase> {
  opening ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(NAME, VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("cache")) db.createObjectStore("cache");
      if (!db.objectStoreNames.contains("bills")) db.createObjectStore("bills", { keyPath: "id" });
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

export const idbGet = <T>(store: Store, key: string) => run<T | undefined>(store, "readonly", (s) => s.get(key) as IDBRequest<T | undefined>);
export const idbAll = <T>(store: Store) => run<T[]>(store, "readonly", (s) => s.getAll() as IDBRequest<T[]>);
export const idbPut = (store: Store, value: unknown, key?: string) => run<IDBValidKey>(store, "readwrite", (s) => s.put(value, key));
export const idbDelete = (store: Store, key: string) => run<undefined>(store, "readwrite", (s) => s.delete(key));
export const idbClear = (store: Store) => run<undefined>(store, "readwrite", (s) => s.clear());
