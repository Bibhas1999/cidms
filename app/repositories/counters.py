"""Running numbers per client, taken atomically: the row stays locked until the transaction ends, so two
bills saved at the same moment get consecutive numbers and a rolled-back bill doesn't skip one."""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def next_number(db: Session, tenant_id: uuid.UUID, name: str) -> int:
    return db.execute(
        text("""INSERT INTO counters (tenant_id, name, value) VALUES (:t, :n, 1)
                ON CONFLICT (tenant_id, name) DO UPDATE SET value = counters.value + 1
                RETURNING value"""),
        {"t": tenant_id, "n": name},
    ).scalar_one()


def set_at_least(db: Session, tenant_id: uuid.UUID, name: str, value: int) -> None:
    """Used by the data move, so new numbers continue after the imported ones."""
    db.execute(
        text("""INSERT INTO counters (tenant_id, name, value) VALUES (:t, :n, :v)
                ON CONFLICT (tenant_id, name) DO UPDATE SET value = greatest(counters.value, :v)"""),
        {"t": tenant_id, "n": name, "v": value},
    )
