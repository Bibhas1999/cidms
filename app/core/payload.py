"""Encrypted request and response bodies between the browser and the app.

Each browser tab agrees an AES-256 key with the server (ECDH on P-256, then HKDF-SHA256): it sends only its public
key to POST /api/payload/key and gets the server's public key and a key id back, so the key itself never crosses
the network. After that, the tab sends X-Payload-Key: <key id> with every /api request:

  request body   {"iv": base64, "data": base64}  as application/vnd.cidms.enc+json  (AES-GCM, additional data
                 "<METHOD> <path>"), decrypted here before the app sees it;
  response body  JSON responses are encrypted the same way (additional data "<METHOD> <path> response") and marked
                 X-Payload: 1. Files, streams and empty responses pass as they are.

An unknown or expired key id gets 409 with code "payload_key" (in plain JSON): the browser agrees a new key and
sends the request again. This hides bodies from the browser's network tools and anything in between; the page
itself still shows the data, and its code holds the (non-extractable) key in memory."""

import base64
import json
import os
import secrets
import threading
from collections import OrderedDict
from datetime import timedelta

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import delete
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.db import scoped_session
from app.core.errors import Invalid

ENCRYPTED = "application/vnd.cidms.enc+json"
INFO = b"cidms payload v1"
KEY_LIFETIME = timedelta(days=1)
# Never encrypted: the key exchange itself, the integration API, webhooks, health checks and the error reporter.
EXEMPT = ("/api/payload/key", "/api/v1/", "/api/webhooks/", "/api/healthz", "/api/readyz", "/api/client-errors")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ---------- agreeing a key ----------

def agree(browser_public_key: str) -> tuple[str, str]:
    """Take the browser's public key (raw, uncompressed P-256, base64); keep the agreed AES key; return
    (key id, the server's public key in the same form)."""
    from app.models import PayloadKey, utcnow
    try:
        raw = base64.b64decode(browser_public_key, validate=True)
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError as exc:
        raise Invalid("That isn't a P-256 public key.", "public_key") from exc
    private = ec.generate_private_key(ec.SECP256R1())
    shared = private.exchange(ec.ECDH(), peer)
    key_id = secrets.token_hex(16)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=key_id.encode(), info=INFO).derive(shared)
    with scoped_session(platform=True) as db, db.begin():
        db.execute(delete(PayloadKey).where(PayloadKey.created_at < utcnow() - KEY_LIFETIME))
        db.add(PayloadKey(id=key_id, key=_b64(key)))
    _cache.put(key_id, key)
    public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return key_id, _b64(public)


class _Keys:
    """Recently used keys, so most requests don't need the database. A key never changes once agreed."""

    def __init__(self, size: int = 5000):
        self.size = size
        self.items: OrderedDict[str, bytes] = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key_id: str) -> bytes | None:
        with self.lock:
            key = self.items.get(key_id)
            if key is not None:
                self.items.move_to_end(key_id)
            return key

    def put(self, key_id: str, key: bytes) -> None:
        with self.lock:
            self.items[key_id] = key
            self.items.move_to_end(key_id)
            while len(self.items) > self.size:
                self.items.popitem(last=False)


_cache = _Keys()


def _load_key(key_id: str) -> bytes | None:
    from app.models import PayloadKey, utcnow
    key = _cache.get(key_id)
    if key is not None:
        return key
    with scoped_session(platform=True) as db:
        row = db.get(PayloadKey, key_id)
        if row is None or row.created_at < utcnow() - KEY_LIFETIME:
            return None
        key = base64.b64decode(row.key)
    _cache.put(key_id, key)
    return key


def seal(key: bytes, plain: bytes, aad: str) -> bytes:
    iv = os.urandom(12)
    return json.dumps({"iv": _b64(iv), "data": _b64(AESGCM(key).encrypt(iv, plain, aad.encode()))}).encode()


def open_sealed(key: bytes, body: bytes, aad: str) -> bytes:
    box = json.loads(body)
    return AESGCM(key).decrypt(base64.b64decode(box["iv"]), base64.b64decode(box["data"]), aad.encode())


# ---------- the middleware ----------

async def _plain_error(send: Send, status: int, message: str, code: str = "") -> None:
    body = json.dumps({"message": message, **({"code": code} if code else {})}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class PayloadCryptoMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        mode = get_settings().payload_encryption
        path = scope.get("path", "")
        if scope["type"] != "http" or mode == "off" or not path.startswith("/api/") or path.startswith(EXEMPT):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        key_id = headers.get("x-payload-key", "")
        method = scope["method"]
        if not key_id:
            sends_body = method not in ("GET", "HEAD", "OPTIONS") and headers.get("content-type", "").startswith("application/json")
            if mode == "required" and sends_body:
                return await _plain_error(send, 400, "Send this request encrypted.", "payload_required")
            return await self.app(scope, receive, send)

        key = await run_in_threadpool(_load_key, key_id[:64])
        if key is None:
            return await _plain_error(send, 409, "The encryption key has expired. Agree a new one and try again.", "payload_key")
        aad = f"{method} {path}"

        # The request: decrypt an encrypted body, and hand the app plain JSON.
        if headers.get("content-type", "").startswith(ENCRYPTED):
            chunks = []
            more = True
            while more:
                message = await receive()
                chunks.append(message.get("body", b""))
                more = message.get("more_body", False)
            try:
                plain = open_sealed(key, b"".join(chunks), aad)
            except Exception:
                return await _plain_error(send, 400, "That request couldn't be decrypted. Reload the page and try again.", "payload_bad")
            scope = dict(scope)
            scope["headers"] = [(k, v) for k, v in scope["headers"] if k.lower() not in (b"content-type", b"content-length")] + [
                (b"content-type", b"application/json"), (b"content-length", str(len(plain)).encode())]
            delivered = False

            async def receive_plain() -> Message:
                nonlocal delivered
                if delivered:
                    return await receive()  # disconnects
                delivered = True
                return {"type": "http.request", "body": plain, "more_body": False}
            inner_receive = receive_plain
        else:
            inner_receive = receive

        # The response: encrypt JSON bodies; pass anything else through untouched.
        start: Message | None = None
        parts: list[bytes] = []
        passthrough = False

        async def send_sealed(message: Message) -> None:
            nonlocal start, passthrough
            if message["type"] == "http.response.start":
                ctype = next((v.decode() for k, v in message.get("headers", []) if k.lower() == b"content-type"), "")
                if not ctype.startswith("application/json"):
                    passthrough = True
                    return await send(message)
                start = message
                return None
            if message["type"] != "http.response.body" or passthrough:
                return await send(message)
            parts.append(message.get("body", b""))
            if message.get("more_body", False):
                return None
            body = b"".join(parts)
            sealed = seal(key, body, f"{aad} response") if body else body
            out_headers = [(k, v) for k, v in start["headers"] if k.lower() not in (b"content-type", b"content-length")]
            out_headers += [(b"content-type", ENCRYPTED.encode()), (b"content-length", str(len(sealed)).encode()), (b"x-payload", b"1")]
            await send({**start, "headers": out_headers})
            await send({"type": "http.response.body", "body": sealed})
            return None

        await self.app(scope, inner_receive, send_sealed)
