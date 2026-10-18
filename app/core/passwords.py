"""Password hashing: Argon2id for every new or changed password.

People brought across from the old Laravel app keep their bcrypt ($2y$) hash until they next sign in; it is
checked once and replaced with an Argon2 hash straight away.
"""

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings
from app.core.errors import Invalid

_hasher = PasswordHasher()
# Checked when the email matches nobody, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str | None) -> tuple[bool, bool]:
    """(matches, needs_rehash)."""
    if not stored:
        _safe_verify(_DUMMY_HASH, password)
        return False, False
    if stored.startswith(("$2y$", "$2a$", "$2b$")):
        ok = bcrypt.checkpw(password.encode()[:72], ("$2b$" + stored[4:]).encode())
        return ok, ok
    if not _safe_verify(stored, password):
        return False, False
    return True, _hasher.check_needs_rehash(stored)


def _safe_verify(stored: str, password: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False


_TEMP_LETTERS = "abcdefghjkmnpqrstuvwxyz"  # no i, l or o: easy to read out over the phone
_TEMP_DIGITS = "23456789"


def random_temporary_password() -> str:
    """A one-time password for a new person or a reset, e.g. "Kmrt-4829-Vbxe": different for everyone, easy to read
    out, and they must choose their own at the first sign-in."""
    import secrets
    word = lambda: "".join(secrets.choice(_TEMP_LETTERS) for _ in range(4)).capitalize()  # noqa: E731
    return f"{word()}-{''.join(secrets.choice(_TEMP_DIGITS) for _ in range(4))}-{word()}"


def check_strength(password: str, field: str = "new_password") -> None:
    """Long enough, not all one kind of character. (Length matters far more than symbols.)"""
    n = get_settings().min_password_length
    if len(password) < n:
        raise Invalid(f"Use at least {n} characters.", field)
    if len(password) > 200:
        raise Invalid("Use at most 200 characters.", field)
    if password.isdigit() or password.isalpha():
        raise Invalid("Mix letters with numbers or symbols.", field)
