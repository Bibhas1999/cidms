"""Pictures the app keeps (a centre's logo, each person's profile picture), stored in the database as base64
text, never as files on disk. Every upload is opened as an image and saved again as a fresh PNG, which checks
it really is a picture and drops anything else hidden in the file.

Medical images (CT, X-ray) are not handled here: they are far too large for the database and go to the
image server (Orthanc) in phase 4.
"""

import base64
import hashlib
from dataclasses import dataclass
from io import BytesIO

from app.core.errors import Invalid

MAX_LOGO_BYTES = 2_000_000


@dataclass(frozen=True)
class StoredImage:
    data: str      # base64 of the PNG
    mime: str      # always image/png
    version: str   # changes with the picture, for browser caching

    def raw(self) -> bytes:
        return base64.b64decode(self.data)


def _clean_png(data: bytes, field: str, what: str, fit_square: int | None = None, max_side: int = 800) -> StoredImage:
    from PIL import Image, ImageOps, UnidentifiedImageError
    if len(data) > MAX_LOGO_BYTES:
        raise Invalid(f"The {what} must be smaller than 2 MB.", field)
    try:
        with Image.open(BytesIO(data)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise Invalid(f"Upload the {what} as a PNG, JPG or WebP image.", field)
            im = ImageOps.exif_transpose(im)
            if fit_square:
                out = ImageOps.fit(im.convert("RGB"), (fit_square, fit_square))
            else:
                out = im.convert("RGBA")
                out.thumbnail((max_side, max_side))
    except UnidentifiedImageError as exc:
        raise Invalid("That file isn't a picture. Upload a PNG, JPG or WebP.", field) from exc
    buf = BytesIO()
    out.save(buf, "PNG", optimize=True)
    png = buf.getvalue()
    return StoredImage(base64.b64encode(png).decode("ascii"), "image/png", hashlib.sha1(png, usedforsecurity=False).hexdigest()[:12])


def logo_image(data: bytes) -> StoredImage:
    return _clean_png(data, "logo", "logo")


def wordmark_image(data: bytes) -> StoredImage:
    """The wide logo with name and slogan: kept sharp for print, at most 1600 px wide."""
    return _clean_png(data, "wordmark", "logo with name", max_side=1600)


def avatar_image(data: bytes) -> StoredImage:
    """A profile picture: cropped to a square and kept small."""
    return _clean_png(data, "avatar", "picture", fit_square=256)


def decode(data: str) -> bytes | None:
    try:
        return base64.b64decode(data) if data else None
    except ValueError:
        return None
