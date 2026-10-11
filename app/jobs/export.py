"""The "export" job: makes a file in the background with a function from app.services.exports, keeps it 24 hours
(job_files) and tells the person who asked that it's ready (download: GET /api/jobs/{id}/file).

Contract for app.services.exports (owned by the exports code):
    BACKGROUND_EXPORTS = {"bills": make_bills_export, ...}          # name -> function
    def make_bills_export(db, current, **params) -> tuple[str, str, bytes]:   # (filename, mime type, content)
`current` is the requester as a CurrentUser with their permissions now, and db is scoped to their centre, so the
function checks permissions and reads exactly as it would in a request. Enqueue from a route with:
    enqueue(db, "export", {"function": "bills", "params": {...}}, created_by=current.id)
"""

import importlib

from app.core.jobs import JobContext, PermanentError, job
from app.services import events


def _function(name: str):
    try:
        exports = importlib.import_module("app.services.exports")
    except ImportError as exc:
        raise PermanentError("Exports aren't available.") from exc
    table = getattr(exports, "BACKGROUND_EXPORTS", None)
    fn = table.get(name) if isinstance(table, dict) else None
    if fn is None or not callable(fn):
        raise PermanentError(f"There's no background export called {name!r}.")
    return fn


@job("export", max_attempts=3, timeout_s=600, notify_failure=True)
def export(ctx: JobContext) -> dict:
    fn = _function(str(ctx.payload.get("function", "")))
    current = ctx.actor()
    if current is None:
        raise PermanentError("An export needs the person who asked for it.")
    filename, mime, data = fn(ctx.db, current, **(ctx.payload.get("params") or {}))
    f = ctx.save_file(filename, mime, data)
    events.export_ready(ctx.db, ctx.tenant_id, current.id, ctx.id, f.filename)
    return {"file_id": str(f.id), "filename": f.filename, "size": f.size_bytes, "mime": f.mime}
