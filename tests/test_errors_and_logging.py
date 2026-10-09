"""Error handling and logging: every failure has the same shape, a request ID, and a log line."""

import json
import logging

from app.services.settings import SettingsService
from tests.conftest import browser, make_user


def test_unexpected_errors_are_logged_and_answered_politely(alpha, monkeypatch, caplog):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")

    def boom(self):
        raise RuntimeError("database exploded with patient data in the message")

    monkeypatch.setattr(SettingsService, "get", boom)
    with caplog.at_level(logging.ERROR, logger="app"):
        r = c.get("/api/settings")
    assert r.status_code == 500
    body = r.json()
    assert "patient data" not in body["message"]  # internals never reach the browser
    assert body["request_id"] == r.headers["x-request-id"]
    assert any("Unhandled error" in rec.getMessage() and rec.exc_info for rec in caplog.records)


def test_not_found_and_wrong_method_have_the_same_shape(alpha):
    c = browser("alpha.localhost")
    r = c.get("/api/does-not-exist")
    assert r.status_code == 404 and set(r.json()) >= {"message", "request_id"}
    r = c.delete("/api/workspace")
    assert r.status_code == 405 and r.json()["request_id"]


def test_a_callers_request_id_is_kept_only_if_it_looks_like_one(alpha):
    c = browser("alpha.localhost")
    assert c.get("/api/workspace", headers={"X-Request-ID": "abc12345-from-proxy"}).headers["x-request-id"] == "abc12345-from-proxy"
    assert c.get("/api/workspace", headers={"X-Request-ID": "<script>"}).headers["x-request-id"] != "<script>"


def test_browser_errors_are_logged_and_rate_limited(alpha, caplog):
    c = browser("alpha.localhost")
    with caplog.at_level(logging.WARNING, logger="app.browser"):
        r = c.post("/api/client-errors", json={"kind": "boundary", "message": "Cannot read properties of undefined", "url": "/staff"})
    assert r.status_code == 204
    assert any("Cannot read properties" in rec.getMessage() for rec in caplog.records)
    codes = [c.post("/api/client-errors", json={"message": "x"}).status_code for _ in range(31)]
    assert codes[-1] == 429


def test_log_lines_are_json_with_the_request_id(alpha, capsys):
    from app.core.logging import JsonFormatter, request_id
    token = request_id.set("req-12345678")
    try:
        rec = logging.LogRecord("app", logging.INFO, __file__, 1, "hello", None, None)
        rec.tenant = "alpha"
        line = json.loads(JsonFormatter().format(rec))
    finally:
        request_id.reset(token)
    assert line["request_id"] == "req-12345678" and line["tenant"] == "alpha" and line["message"] == "hello"


def test_the_activity_log_never_stores_secrets(alpha):
    from app.core.logging import redact
    assert redact({"password": "x", "new_password": "y", "csrf_token": "z", "email": "a@b.in"}) == {
        "password": "[redacted]", "new_password": "[redacted]", "csrf_token": "[redacted]", "email": "a@b.in"}


def test_security_headers_are_on_every_response(alpha):
    r = browser("alpha.localhost").get("/api/workspace")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
