"""Idempotent changes: the browser sends an Idempotency-Key with "create bill" and "take payment". The first
request does the work and its answer is stored; a retry with the same key (double click, a lost response, a
flaky connection) gets that same answer back and nothing is done twice."""

import re
from collections.abc import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Invalid
from app.core.security import CurrentUser
from app.models import Operation

KEY = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def run_once(request: Request, db: Session, current: CurrentUser, kind: str, produce: Callable[[], BaseModel],
             status_code: int = 200) -> BaseModel | JSONResponse:
    key = request.headers.get("idempotency-key", "")
    if not key:
        return produce()
    if not KEY.match(key):
        raise Invalid("The request key isn't valid. Refresh the page and try again.")
    tenant_id = current.user.tenant_id
    done = db.get(Operation, (tenant_id, key))
    if done is not None:
        if done.user_id != current.id or done.kind != kind:
            raise Conflict("That request key was already used for something else. Refresh the page and try again.")
        return JSONResponse(done.response, status_code=done.status_code, headers={"Idempotent-Replayed": "true"})
    result = produce()
    body = result.model_dump(mode="json")
    # If the same key arrives twice at the same moment, the second insert waits for the first transaction and
    # then fails on the primary key, so the work is never committed twice.
    db.add(Operation(tenant_id=tenant_id, key=key, user_id=current.id, kind=kind, status_code=status_code, response=body))
    db.flush()
    return JSONResponse(body, status_code=status_code)
