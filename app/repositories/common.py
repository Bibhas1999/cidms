"""Shared query helpers."""


def contains(search: str) -> str:
    """A LIKE pattern matching `search` anywhere, with the caller's own % and _ taken literally (use escape='\\')."""
    return "%" + search.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
