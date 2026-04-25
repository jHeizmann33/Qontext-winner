"""
normalize.py — String normalization helpers for entity resolution.

Used by resolver.py to compare attribute values (business names, addresses,
phone numbers, emails) across heterogeneous source records.
"""

import re
from difflib import SequenceMatcher
from typing import Optional


LEGAL_SUFFIXES = re.compile(
    r"\b(inc|llc|ltd|gmbh|corp|corporation|co|company|group|holdings?|partners?|"
    r"associates|sa|ag|plc|pvt|pte|kgaa)\b\.?",
    re.IGNORECASE,
)
APT_SUITE = re.compile(
    r"\b(apt|suite|ste|unit|box|psc|apartment)\.?\s*[\w-]+",
    re.IGNORECASE,
)
PUNCT = re.compile(r"[^a-z0-9 ]")
WS = re.compile(r"\s+")


def _as_str(value) -> str:
    """Coerce any value to a string; returns '' for None."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def normalize_business_name(name) -> str:
    """Lowercase, strip legal suffixes (Inc, LLC, GmbH...), strip punctuation."""
    s = _as_str(name)
    if not s:
        return ""
    s = s.lower()
    s = LEGAL_SUFFIXES.sub("", s)
    s = PUNCT.sub("", s)
    s = WS.sub(" ", s).strip()
    return s


def normalize_address(addr) -> str:
    """Lowercase, strip apartment/suite designators, strip punctuation."""
    s = _as_str(addr)
    if not s:
        return ""
    s = s.lower()
    s = APT_SUITE.sub("", s)
    s = PUNCT.sub("", s)
    s = WS.sub(" ", s).strip()
    return s


def extract_zip(addr) -> Optional[str]:
    """Extract a US-style 5-digit ZIP code from a free-form address."""
    s = _as_str(addr)
    if not s:
        return None
    m = re.search(r"\b(\d{5})(-\d{4})?\b", s)
    return m.group(1) if m else None


def normalize_phone(phone) -> Optional[str]:
    """Strip non-digits, return last 10 digits (US-shape) or None if too short."""
    s = _as_str(phone)
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 7:
        return digits[-10:]
    return None


def normalize_email(email) -> Optional[str]:
    """Lowercase, strip whitespace, validate '@' presence."""
    s = _as_str(email).lower().strip()
    if not s or "@" not in s:
        return None
    return s


def email_domain(email) -> Optional[str]:
    """Extract the domain portion of an email address."""
    e = normalize_email(email)
    if not e:
        return None
    return e.split("@", 1)[1]


def similarity(a: str, b: str) -> float:
    """Sequence-matcher similarity in [0, 1]. Empty strings are considered equal."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()
