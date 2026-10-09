"""Files kept for each centre, under <STORAGE_DIR>/tenants/<tenant id>/. Names are chosen by the app, never
taken from an upload, so one file can't overwrite another or escape the centre's folder."""

import uuid
from io import BytesIO
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import Invalid

MAX_LOGO_BYTES = 2_000_000


def tenant_dir(tenant_id: uuid.UUID | None) -> Path:
    """A centre's folder, or the platform's own folder for platform staff (tenant_id None)."""
    base = Path(get_settings().storage_dir).resolve()
    path = base / "platform" if tenant_id is None else base / "tenants" / str(tenant_id)
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


def save_avatar(tenant_id: uuid.UUID | None, data: bytes) -> str:
    """A profile picture: checked to be an image, cropped to a square and saved small, as PNG."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if len(data) > MAX_LOGO_BYTES:
        raise Invalid("The picture must be smaller than 2 MB.", "avatar")
    try:
        with Image.open(BytesIO(data)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise Invalid("Upload a PNG, JPG or WebP picture.", "avatar")
            out = ImageOps.fit(ImageOps.exif_transpose(im).convert("RGB"), (256, 256))
    except UnidentifiedImageError as exc:
        raise Invalid("That file isn't a picture. Upload a PNG, JPG or WebP.", "avatar") from exc
    folder = tenant_dir(tenant_id) / "avatars"
    folder.mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex}.png"
    out.save(folder / name, "PNG", optimize=True)
    return name


def avatar_path(tenant_id: uuid.UUID | None, name: str) -> Path | None:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    path = tenant_dir(tenant_id) / "avatars" / name
    return path if path.is_file() else None
