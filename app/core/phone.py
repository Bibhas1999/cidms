"""Mobile numbers, checked the same way as the browser (web/src/lib/phone.ts) and saved in the international
(E.164) form, e.g. "+919876543210". A bare 10-digit number (as in the old app) is read as Indian."""

import re

# Country code -> (rule for the national number, what to tell people). Others: 6 to 14 digits.
RULES: dict[str, tuple[re.Pattern[str], str]] = {
    "+91": (re.compile(r"^[6-9]\d{9}$"), "an Indian mobile number: 10 digits, starting 6, 7, 8 or 9"),
    "+880": (re.compile(r"^1\d{9}$"), "a Bangladesh mobile number: 10 digits, starting 1"),
    "+977": (re.compile(r"^9\d{9}$"), "a Nepal mobile number: 10 digits, starting 9"),
    "+975": (re.compile(r"^\d{8}$"), "a Bhutan mobile number: 8 digits"),
    "+94": (re.compile(r"^7\d{8}$"), "a Sri Lanka mobile number: 9 digits, starting 7"),
    "+971": (re.compile(r"^5\d{8}$"), "a UAE mobile number: 9 digits, starting 5"),
    "+966": (re.compile(r"^5\d{8}$"), "a Saudi mobile number: 9 digits, starting 5"),
    "+974": (re.compile(r"^\d{8}$"), "a Qatar mobile number: 8 digits"),
    "+965": (re.compile(r"^\d{8}$"), "a Kuwait mobile number: 8 digits"),
    "+968": (re.compile(r"^\d{8}$"), "an Oman mobile number: 8 digits"),
    "+973": (re.compile(r"^\d{8}$"), "a Bahrain mobile number: 8 digits"),
    "+65": (re.compile(r"^[89]\d{7}$"), "a Singapore mobile number: 8 digits, starting 8 or 9"),
    "+60": (re.compile(r"^1\d{8,9}$"), "a Malaysia mobile number: 9 or 10 digits, starting 1"),
    "+44": (re.compile(r"^7\d{9}$"), "a UK mobile number: 10 digits, starting 7"),
    "+1": (re.compile(r"^[2-9]\d{9}$"), "a US or Canada number: 10 digits"),
    "+61": (re.compile(r"^4\d{8}$"), "an Australian mobile number: 9 digits, starting 4"),
}
_BY_LENGTH = sorted(RULES, key=len, reverse=True)


def normalise_mobile(value: str) -> str:
    """"" stays ""; anything else must be a valid mobile and comes back as +<code><number>."""
    v = re.sub(r"[\s()\-.]", "", value or "")
    if not v:
        return ""
    if not v.startswith("+"):
        digits = re.sub(r"\D", "", v)
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        elif len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        v = "+91" + digits
    if not re.fullmatch(r"\+\d{7,16}", v):
        raise ValueError("Enter a valid mobile number, digits only.")
    code = next((c for c in _BY_LENGTH if v.startswith(c)), None)
    if code is None:
        if not re.fullmatch(r"\+[1-9]\d{7,14}", v):
            raise ValueError("Enter a valid mobile number with its country code.")
        return v
    number = v[len(code):]
    pattern, what = RULES[code]
    if not pattern.fullmatch(number):
        raise ValueError(f"Enter {what}.")
    return v
