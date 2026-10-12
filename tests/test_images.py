"""Uploaded logos: a plain white square around the logo turns see-through (for the dark theme); the logo stays."""

from io import BytesIO

from PIL import Image, ImageDraw

from app.core.storage import logo_image


def _upload(im: Image.Image) -> Image.Image:
    buf = BytesIO()
    im.save(buf, "PNG")
    return Image.open(BytesIO(logo_image(buf.getvalue()).raw())).convert("RGBA")


def test_white_square_around_a_logo_becomes_see_through():
    im = Image.new("RGB", (200, 200), "white")
    d = ImageDraw.Draw(im)
    d.ellipse((40, 40, 160, 160), fill=(0, 74, 173))
    d.ellipse((90, 90, 110, 110), fill="white")  # white inside the logo stays
    out = _upload(im)
    assert out.getpixel((2, 2))[3] == 0 and out.getpixel((199, 199))[3] == 0
    assert out.getpixel((60, 100)) == (0, 74, 173, 255)
    assert out.getpixel((100, 100)) == (255, 255, 255, 255)


def test_a_logo_without_a_white_border_is_unchanged():
    im = Image.new("RGB", (120, 120), (0, 74, 173))
    ImageDraw.Draw(im).rectangle((0, 0, 30, 30), fill="white")  # white in one corner only
    out = _upload(im)
    assert out.getpixel((5, 5)) == (255, 255, 255, 255)
