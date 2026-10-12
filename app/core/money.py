"""Money and the centre's calendar. Money is always Decimal, rounded half up to paise; never float."""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.core.config import get_settings

PAISA = Decimal("0.01")
ZERO = Decimal("0.00")


def q2(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(PAISA, rounding=ROUND_HALF_UP)


def rupees(value: Decimal) -> str:
    """₹1,23,456.00 in the Indian grouping, for messages."""
    v = q2(value)
    whole, frac = f"{abs(v):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])
    return f"{'-' if v < 0 else ''}₹{whole}.{frac}"


def local_now() -> datetime:
    return datetime.now(ZoneInfo(get_settings().display_timezone))


def local_today() -> date:
    return local_now().date()


def local_date(moment: datetime) -> date:
    """The day a moment fell on, in the centre's time zone (India)."""
    return moment.astimezone(ZoneInfo(get_settings().display_timezone)).date()


def financial_year(d: date) -> str:
    """Indian financial year, April to March: 9 Oct 2026 -> "2026-27"."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"
