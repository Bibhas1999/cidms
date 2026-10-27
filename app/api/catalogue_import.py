"""Adding many departments, test types or tests at once: from a grid in the browser or an uploaded Excel sheet."""

import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import client_user
from app.core.db import DB
from app.core.errors import Forbidden
from app.core.security import CurrentUser
from app.services.catalogue_import import MAX_ROWS, CatalogueImport, Kind
from app.services.uploads import UploadService

router = APIRouter(prefix="/api/catalogue", tags=["catalogue"])


def manager(current: CurrentUser = Depends(client_user)) -> CurrentUser:
    if not current.can("catalogue.manage"):
        raise Forbidden("You don't have permission to do that.")
    return current


class CatalogueRowIn(BaseModel):
    """One row as typed or read from a sheet; everything is text here and checked by the service."""
    name: str = Field(default="", max_length=300)
    code: str = Field(default="", max_length=300)
    department: str = Field(default="", max_length=300)
    test_type: str = Field(default="", max_length=300)
    price: str = Field(default="", max_length=300)
    imaging: str = Field(default="", max_length=300)
    qualification: str = Field(default="", max_length=300)
    phone: str = Field(default="", max_length=300)


class RowsIn(BaseModel):
    rows: list[CatalogueRowIn] = Field(max_length=MAX_ROWS)


class ImportIn(BaseModel):
    upload_id: uuid.UUID


class CheckedRow(BaseModel):
    values: dict[str, str]
    errors: dict[str, str]


class CheckedOut(BaseModel):
    rows: list[CheckedRow]
    filename: str = ""


class AddedOut(BaseModel):
    added: int


@router.get("/{kind}/template")
def template(kind: Kind, db: Session = DB, current: CurrentUser = Depends(manager)):
    data = CatalogueImport(db, current).template(kind)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{kind}-template.xlsx"'})


@router.post("/{kind}/check", response_model=CheckedOut)
def check(kind: Kind, data: RowsIn, db: Session = DB, current: CurrentUser = Depends(manager)):
    return CheckedOut(rows=CatalogueImport(db, current).check(kind, [r.model_dump() for r in data.rows]))


@router.post("/{kind}/import", response_model=CheckedOut)
def import_sheet(kind: Kind, data: ImportIn, db: Session = DB, current: CurrentUser = Depends(manager)):
    """Read a finished upload into rows (nothing is added yet): the browser shows them, with any problems, to review."""
    filename, content = UploadService(db, current).take(data.upload_id, "catalogue")
    service = CatalogueImport(db, current)
    return CheckedOut(rows=service.check(kind, service.parse(kind, filename, content)), filename=filename)


@router.post("/{kind}/bulk", response_model=AddedOut, status_code=201)
def bulk_add(kind: Kind, data: RowsIn, db: Session = DB, current: CurrentUser = Depends(manager)):
    return AddedOut(added=CatalogueImport(db, current).save(kind, [r.model_dump() for r in data.rows]))
