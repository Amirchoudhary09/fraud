"""Privacy guardrails: block requests for sensitive data and redact it from evidence.

The platform only works with publicly available professional information.
It must never collect phone numbers, home addresses, government IDs,
credentials, or private-account content.
"""
import re

BLOCKED_TERMS = [
    "phone number", "mobile number", "contact number", "whatsapp",
    "home address", "residential address", "house address", "where does he live", "where does she live",
    "where do they live", "where does he stay", "where does she stay", "ghar ka pata", "kahan rehta", "kahan rehti", "aadhaar", "aadhar", "pan card", "passport",
    "password", "leaked", "leak", "breach", "dox", "private account",
    "private profile", "bank account", "credit card", "ssn",
]

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email redacted]"),
    # Aadhaar-like 12 digits (with optional spaces) and long digit runs
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[id redacted]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[id redacted]"),  # PAN
]

# Runs of digits/separators; treated as a phone number only if they hold 10+ digits,
# so year ranges like "2019 - 2023" are left alone.
_PHONE_CANDIDATE = re.compile(r"\+?\(?\d[\d\s().-]{8,}\d")


def _redact_phone(m: re.Match) -> str:
    digits = sum(c.isdigit() for c in m.group(0))
    return "[phone redacted]" if digits >= 10 else m.group(0)


def find_blocked_terms(text: str) -> list[str]:
    low = text.lower()
    return [t for t in BLOCKED_TERMS if t in low]


def redact(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return _PHONE_CANDIDATE.sub(_redact_phone, text)
