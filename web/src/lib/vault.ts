// Encryption for what this browser keeps (lib/response-cache.ts, lib/outbox.svelte.ts): AES-GCM with a key made
// here once and stored in IndexedDB as a non-extractable CryptoKey, so it can be used but never read out, and
// the saved copies show only as scrambled bytes in the browser's storage tools. Without Web Crypto (an old
// browser, or plain http on another machine) nothing is saved at all.
import { rawGet, rawPut } from "./offline-db";

let keying: Promise<CryptoKey | null> | null = null;

function key(): Promise<CryptoKey | null> {
  keying ??= (async () => {
    if (!globalThis.crypto?.subtle || !globalThis.indexedDB) return null;
    try {
      const saved = await rawGet<CryptoKey>("keys", "vault");
      if (saved) return saved;
      const made = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
      await rawPut("keys", made, "vault");
      return made;
    } catch {
      return null;
    }
  })();
  return keying;
}

export interface Sealed { iv: Uint8Array<ArrayBuffer>; data: ArrayBuffer }

/** Encrypt something for keeping; null when this browser can't. */
export async function seal(value: unknown): Promise<Sealed | null> {
  const k = await key();
  if (!k) return null;
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, k, new TextEncoder().encode(JSON.stringify(value)));
  return { iv, data };
}

/** Decrypt something kept by seal(); null if it can't be read (another browser's, or damaged). */
export async function unseal<T>(box: Sealed | undefined | null): Promise<T | null> {
  const k = await key();
  if (!k || !box) return null;
  try {
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: box.iv }, k, box.data);
    return JSON.parse(new TextDecoder().decode(plain)) as T;
  } catch {
    return null;
  }
}

/** Ask the browser to keep this site's data even when space runs low (it may say no). */
export async function persistStorage(): Promise<boolean> {
  try { return (await navigator.storage?.persisted?.()) || (await navigator.storage?.persist?.()) || false; } catch { return false; }
}
