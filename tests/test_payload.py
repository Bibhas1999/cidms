"""Encrypted request and response bodies: the key is agreed by ECDH, bodies are AES-GCM both ways, tampering and
unknown keys are refused, and plain callers keep working unless encryption is required."""

import base64
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings
from app.core.payload import ENCRYPTED, INFO
from tests.conftest import PASSWORD, browser, make_user


def agree(c) -> tuple[str, bytes]:
    """What the browser does: send its public key, derive the same AES key from the server's."""
    private = ec.generate_private_key(ec.SECP256R1())
    mine = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    r = c.post("/api/payload/key", json={"public_key": base64.b64encode(mine).decode()})
    assert r.status_code == 200, r.text
    body = r.json()
    theirs = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), base64.b64decode(body["public_key"]))
    shared = private.exchange(ec.ECDH(), theirs)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=body["key_id"].encode(), info=INFO).derive(shared)
    return body["key_id"], key


def sealed(key: bytes, data: dict, aad: str) -> str:
    iv = os.urandom(12)
    return json.dumps({"iv": base64.b64encode(iv).decode(),
                       "data": base64.b64encode(AESGCM(key).encrypt(iv, json.dumps(data).encode(), aad.encode())).decode()})


def opened(key: bytes, text: str, aad: str) -> dict:
    box = json.loads(text)
    return json.loads(AESGCM(key).decrypt(base64.b64decode(box["iv"]), base64.b64decode(box["data"]), aad.encode()))


def test_sign_in_and_reads_travel_encrypted_both_ways(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    key_id, key = agree(c)
    h = {"X-Payload-Key": key_id, "Content-Type": ENCRYPTED}
    r = c.post("/api/auth/login", content=sealed(key, {"email": "owner@alpha.in", "password": PASSWORD}, "POST /api/auth/login"), headers=h)
    assert r.status_code == 200 and r.headers["x-payload"] == "1" and r.headers["content-type"].startswith(ENCRYPTED)
    assert PASSWORD not in r.text and "owner@alpha.in" not in r.text
    me = opened(key, r.text, "POST /api/auth/login response")
    c.csrf = me["csrf_token"]
    r = c.get("/api/departments", headers={"X-Payload-Key": key_id})
    assert opened(key, r.text, "GET /api/departments response") == []
    # Changes too (the CSRF token stays a header).
    r = c.post("/api/departments", content=sealed(key, {"name": "Radiology"}, "POST /api/departments"), headers=h)
    assert r.status_code == 201 and opened(key, r.text, "POST /api/departments response")["name"] == "Radiology"


def test_tampered_bodies_wrong_endpoints_and_unknown_keys_are_refused(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    key_id, key = agree(c)
    h = {"X-Payload-Key": key_id, "Content-Type": ENCRYPTED}
    body = {"email": "owner@alpha.in", "password": PASSWORD}
    # Sealed for another endpoint (the path is bound into the encryption): refused.
    r = c.post("/api/auth/login", content=sealed(key, body, "POST /api/departments"), headers=h)
    assert r.status_code == 400 and r.json()["code"] == "payload_bad"
    r = c.post("/api/auth/login", content=sealed(os.urandom(32), body, "POST /api/auth/login"), headers=h)
    assert r.status_code == 400
    r = c.post("/api/auth/login", content=sealed(key, body, "POST /api/auth/login"), headers={**h, "X-Payload-Key": "0" * 32})
    assert r.status_code == 409 and r.json()["code"] == "payload_key"
    assert c.post("/api/payload/key", json={"public_key": base64.b64encode(b"x" * 65).decode()}).status_code == 422


def test_plain_json_works_unless_encryption_is_required(alpha, monkeypatch):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    assert c.login("owner@alpha.in").status_code == 200  # optional (the default): plain callers still work
    monkeypatch.setattr(get_settings(), "payload_encryption", "required")
    r = c.post("/api/departments", json={"name": "Pathology"})
    assert r.status_code == 400 and r.json()["code"] == "payload_required"
    assert c.get("/api/departments").status_code == 200  # reads without a body aren't refused
