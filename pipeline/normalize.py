import re
from difflib import SequenceMatcher

LEGAL_SUFFIXES = re.compile(
    r"\b(inc|llc|ltd|gmbh|corp|corporation|co|company|group|holdings?|partners?|associates|sa|ag|plc)\b\.?",
    re.IGNORECASE,
)

STATE_ABBR = re.compile(r"\b[A-Z]{2}\s+\d{5}(-\d{4})?\b")
APT_SUITE = re.compile(r"\b(apt|suite|ste|unit|box|psc)\.?\s*[\w-]+", re.IGNORECASE)
PUNCT = re.compile(r"[^a-z0-9 ]")
WS = re.compile(r"\s+")


def _as_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def normalize_business_name(name) -> str:
    s = _as_str(name)
    if not s:
        return ""
    s = s.lower()
    s = LEGAL_SUFFIXES.sub("", s)
    s = PUNCT.sub("", s)
    s = WS.sub(" ", s).strip()
    return s


def normalize_address(addr) -> str:
    s = _as_str(addr)
    if not s:
        return ""
    s = s.lower()
    s = APT_SUITE.sub("", s)
    s = PUNCT.sub("", s)
    s = WS.sub(" ", s).strip()
    return s


def extract_zip(addr) -> str | None:
    s = _as_str(addr)
    if not s:
        return None
    m = re.search(r"\b(\d{5})(-\d{4})?\b", s)
    return m.group(1) if m else None


def normalize_phone(phone) -> str | None:
    s = _as_str(phone)
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 7:
        return digits[-10:]
    return None


def normalize_email(email) -> str | None:
    s = _as_str(email).lower().strip()
    if not s:
        return None
    return s if "@" in s else None


def email_domain(email: str) -> str | None:
    e = normalize_email(email)
    if not e:
        return None
    return e.split("@", 1)[1]


def similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()
