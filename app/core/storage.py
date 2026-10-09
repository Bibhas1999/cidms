"""Files kept for each centre, under <STORAGE_DIR>/tenants/<tenant id>/. Names are chosen by the app, never
taken from an upload, so one file can't overwrite another or escape the centre's folder."""

import uuid
from io import BytesIO
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import Invalid

MAX_LOGO_BYTES = 2_000_000


def tenant_dir(tenant_id: uuid.UUID) -> Path:
    path = Path(get_settings().storage_dir).resolve() / "tenants" / str(tenant_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_logo(tenant_id: uuid.UUID, data: bytes) -> str:
    """Checks the upload really is an image, then re-saves it as PNG (dropping anything hidden in the file)."""
    from PIL import Image, UnidentifiedImageError
    if len(data) > MAX_LOGO_BYTES:
        raise Invalid("The logo must be smaller than 2 MB.", "logo")
    try:
        with Image.open(BytesIO(data)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise Invalid("Upload the logo as a PNG, JPG or WebP image.", "logo")
            im.thumbnail((800, 800))
            out = im.convert("RGBA")
    except UnidentifiedImageError as exc:
        raise Invalid("That file isn't an image. Upload a PNG, JPG or WebP.", "logo") from exc
    name = f"logo-{uuid.uuid4().hex[:8]}.png"
    out.save(tenant_dir(tenant_id) / name, "PNG", optimize=True)
    return name


def logo_path(tenant_id: uuid.UUID, name: str) -> Path | None:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    path = tenant_dir(tenant_id) / name
    return path if path.is_file() else None
