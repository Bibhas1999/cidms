"""Logos already uploaded on a plain white square get that white made see-through, as new uploads now do, so
they don't show as a white box on the dark theme. Only white touching the picture's edge changes.

Revision ID: 0013_clear_logo_backgrounds
Revises: 0012_wordmark
Create Date: 2026-10-12
"""

import base64
import hashlib
from io import BytesIO

import sqlalchemy as sa
from alembic import op

revision = "0013_clear_logo_backgrounds"
down_revision = "0012_wordmark"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from PIL import Image

    from app.core.storage import clear_white_background
    db = op.get_bind()
    for kind in ("logo", "wordmark"):
        rows = db.execute(sa.text(f"SELECT tenant_id, {kind}_data FROM tenant_settings WHERE {kind}_data <> ''")).all()
        for tenant_id, data in rows:
            try:
                im = Image.open(BytesIO(base64.b64decode(data)))
                im.load()
            except Exception:  # noqa: BLE001, S112 - a broken picture stays as it is
                continue
            out = clear_white_background(im)
            buf = BytesIO()
            out.save(buf, "PNG", optimize=True)
            png = buf.getvalue()
            db.execute(sa.text(f"UPDATE tenant_settings SET {kind}_data = :d, {kind}_mime = 'image/png', {kind}_file = :v "  # noqa: S608
                               "WHERE tenant_id = :t"),
                       {"d": base64.b64encode(png).decode("ascii"), "v": hashlib.sha1(png, usedforsecurity=False).hexdigest()[:12],
                        "t": tenant_id})


def downgrade() -> None:
    pass  # the white background isn't kept; upload the original again to get it back
