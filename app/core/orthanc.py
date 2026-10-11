"""Talking to the Orthanc image server. Only the app reaches it (bound to 127.0.0.1, with its own user and
password); browsers get images through the app's DICOMweb proxy, which checks the study is theirs first.

Tests swap the network for an httpx.MockTransport by setting `transport`."""

import logging
import re
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import DomainError

log = logging.getLogger("app.orthanc")

transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None  # tests only

LABEL_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ImageServerUnavailable(DomainError):
    status = 503

    def __init__(self, message: str = "The image server isn't available right now. Please try again in a few minutes."):
        super().__init__(message)


def tenant_label(tenant_id: object) -> str:
    """The label every study of a client carries on the image server (labels allow letters, digits, - and _)."""
    return f"tenant_{getattr(tenant_id, 'hex', str(tenant_id).replace('-', ''))}"


def _auth() -> tuple[str, str]:
    s = get_settings()
    return s.orthanc_user, s.orthanc_password


def sync_client(timeout: float = 60) -> httpx.Client:
    url = get_settings().orthanc_url.rstrip("/")
    return httpx.Client(base_url=url, auth=_auth(), timeout=timeout, transport=transport,  # type: ignore[arg-type]
                        verify=url.startswith("https"))


_shared: dict[tuple, httpx.AsyncClient] = {}


def shared_async_client(base_url: str, auth: tuple[str, str] | None = None) -> httpx.AsyncClient:
    """One long-lived client per server and event loop, so proxied requests reuse connections instead of setting
    up a new client (and its TLS context) every time. Never closed by callers; close only the responses."""
    import asyncio
    key = (id(asyncio.get_running_loop()), base_url, auth, id(transport))
    client = _shared.get(key)
    if client is None or client.is_closed:
        limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
        client = httpx.AsyncClient(base_url=base_url.rstrip("/"), auth=auth, timeout=httpx.Timeout(300, connect=5), limits=limits,
                                   transport=transport, verify=base_url.startswith("https"))  # type: ignore[arg-type]
        if len(_shared) > 20:  # event loops come and go in tests; don't keep their clients forever
            _shared.clear()
        _shared[key] = client
    return client


def async_client() -> httpx.AsyncClient:
    """The shared client for Orthanc's web port."""
    return shared_async_client(get_settings().orthanc_url, _auth())


class Orthanc:
    """A few REST calls, on one connection. Use as a context manager."""

    def __init__(self, timeout: float = 120):
        self.http = sync_client(timeout)

    def __enter__(self) -> "Orthanc":
        return self

    def __exit__(self, *exc) -> None:
        self.http.close()

    def _call(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            r = self.http.request(method, path, **kw)
        except httpx.TransportError as exc:
            log.warning("Orthanc unreachable: %s", type(exc).__name__)
            raise ImageServerUnavailable() from exc
        if r.status_code in (401, 403) or r.status_code >= 500:
            log.warning("Orthanc answered %s on %s %s", r.status_code, method, path)
            raise ImageServerUnavailable()
        return r

    def store(self, data: bytes) -> dict[str, Any] | None:
        """Store one DICOM file. None when the image server says it isn't DICOM."""
        r = self._call("POST", "/instances", content=data, headers={"Content-Type": "application/dicom"})
        if r.status_code >= 400:
            return None
        body = r.json()
        return body[0] if isinstance(body, list) and body else body

    def study(self, orthanc_id: str) -> dict[str, Any]:
        return self._call("GET", f"/studies/{orthanc_id}").json()

    def statistics(self, orthanc_id: str) -> dict[str, Any]:
        r = self._call("GET", f"/studies/{orthanc_id}/statistics")
        return r.json() if r.status_code == 200 else {}

    def series(self, orthanc_id: str) -> list[dict[str, Any]]:
        r = self._call("GET", f"/studies/{orthanc_id}/series")
        return r.json() if r.status_code == 200 else []

    def labels(self, orthanc_id: str) -> list[str]:
        r = self._call("GET", f"/studies/{orthanc_id}/labels")
        return r.json() if r.status_code == 200 else []

    def add_label(self, orthanc_id: str, label: str) -> None:
        if LABEL_OK.match(label):
            self._call("PUT", f"/studies/{orthanc_id}/labels/{label}", content=b"")

    def delete_instance(self, instance_id: str) -> None:
        self._call("DELETE", f"/instances/{instance_id}")


def is_up() -> bool:
    try:
        with sync_client(timeout=3) as c:
            return c.get("/system").status_code == 200
    except httpx.HTTPError:
        return False
