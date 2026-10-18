// Encrypted request and response bodies (see app/core/payload.py). The tab makes an ECDH key pair, sends only its
// public key, and derives the same AES-256-GCM key as the server (HKDF-SHA256, salt = the key id). The key is
// non-extractable and lives only in this tab's memory; a reload agrees a new one. If the server doesn't offer
// encryption (switched off, or an old server), requests simply go as plain JSON.

export const ENCRYPTED = "application/vnd.cidms.enc+json";
const INFO = new TextEncoder().encode("cidms payload v1");

interface Agreed { id: string; key: CryptoKey }

let agreed: Promise<Agreed | null> | null = null;

const b64 = (bytes: ArrayBuffer | Uint8Array) => btoa(String.fromCharCode(...new Uint8Array(bytes)));
const unb64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function agree(): Promise<Agreed | null> {
  if (!globalThis.crypto?.subtle) return null; // not a secure context (plain http on another machine): send plain
  const pair = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
  const mine = await crypto.subtle.exportKey("raw", pair.publicKey);
  const res = await fetch("/api/payload/key", {
    method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ public_key: b64(mine) }),
  });
  if (!res.ok) return null;
  const { key_id, public_key } = await res.json() as { key_id: string; public_key: string };
  const theirs = await crypto.subtle.importKey("raw", unb64(public_key), { name: "ECDH", namedCurve: "P-256" }, false, []);
  const shared = await crypto.subtle.deriveBits({ name: "ECDH", public: theirs }, pair.privateKey, 256);
  const hkdf = await crypto.subtle.importKey("raw", shared, "HKDF", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: new TextEncoder().encode(key_id), info: INFO },
                                            hkdf, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  return { id: key_id, key };
}

/** The tab's key, agreed once (null when the server doesn't encrypt). */
export function payloadKey(): Promise<Agreed | null> {
  agreed ??= agree().catch(() => { agreed = null; return null; });
  return agreed;
}

/** Forget the key (the server said it expired); the next request agrees a new one. */
export function resetPayloadKey(): void {
  agreed = null;
}

export async function seal(k: Agreed, plain: string, aad: string): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: new TextEncoder().encode(aad) }, k.key,
                                           new TextEncoder().encode(plain));
  return JSON.stringify({ iv: b64(iv), data: b64(data) });
}

export async function open(k: Agreed, sealed: string, aad: string): Promise<string> {
  const box = JSON.parse(sealed) as { iv: string; data: string };
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(box.iv), additionalData: new TextEncoder().encode(aad) },
                                            k.key, unb64(box.data));
  return new TextDecoder().decode(plain);
}
