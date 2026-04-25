from dataclasses import dataclass

from .normalize import (
    extract_zip,
    normalize_address,
    normalize_business_name,
    normalize_phone,
    similarity,
)
from .types import Record


@dataclass
class Signal:
    score: float
    reason: str


def tax_id_match(a: Record, b: Record) -> Signal | None:
    ta = (a.attributes.get("tax_id") or "").strip()
    tb = (b.attributes.get("tax_id") or "").strip()
    if ta and tb and ta == tb:
        return Signal(1.0, f"Identical tax_id ({ta})")
    return None


def exact_business_name(a: Record, b: Record) -> Signal | None:
    na = normalize_business_name(a.attributes.get("business_name") or "")
    nb = normalize_business_name(b.attributes.get("business_name") or "")
    if na and nb and na == nb:
        return Signal(0.55, f"Exact normalized business_name ({a.attributes.get('business_name')})")
    return None


def fuzzy_business_name(a: Record, b: Record) -> Signal | None:
    na = normalize_business_name(a.attributes.get("business_name") or "")
    nb = normalize_business_name(b.attributes.get("business_name") or "")
    if not na or not nb or na == nb:
        return None
    sim = similarity(na, nb)
    if sim >= 0.92:
        return Signal(0.45, f"Near-exact name match ({sim:.0%}: '{a.attributes.get('business_name')}' ≈ '{b.attributes.get('business_name')}')")
    if sim >= 0.80:
        return Signal(0.25, f"Fuzzy name match ({sim:.0%})")
    return None


def address_match(a: Record, b: Record) -> Signal | None:
    aa = a.attributes.get("registered_address") or ""
    ab = b.attributes.get("registered_address") or ""
    if not aa or not ab:
        return None
    na = normalize_address(aa)
    nb = normalize_address(ab)
    if na == nb and na:
        return Signal(0.7, "Identical registered_address")
    sim = similarity(na, nb)
    za = extract_zip(aa)
    zb = extract_zip(ab)
    if sim >= 0.85:
        return Signal(0.5, f"Near-identical address ({sim:.0%})")
    if za and zb and za == zb and sim >= 0.6:
        return Signal(0.35, f"Same ZIP ({za}) + similar address ({sim:.0%})")
    return None


def industry_match(a: Record, b: Record) -> Signal | None:
    ia = (a.attributes.get("industry") or "").strip().lower()
    ib = (b.attributes.get("industry") or "").strip().lower()
    if ia and ib and ia == ib:
        return Signal(0.1, f"Same industry ({ia})")
    return None


def email_match(a: Record, b: Record) -> Signal | None:
    ea = (a.attributes.get("contact_email") or "").lower().strip()
    eb = (b.attributes.get("contact_email") or "").lower().strip()
    if ea and eb and ea == eb:
        return Signal(0.8, f"Same contact_email ({ea})")
    return None


def phone_match(a: Record, b: Record) -> Signal | None:
    pa = normalize_phone(a.attributes.get("phone_number") or "")
    pb = normalize_phone(b.attributes.get("phone_number") or "")
    if pa and pb and pa == pb:
        return Signal(0.7, f"Same phone ({pa})")
    return None


STRATEGIES = [
    tax_id_match,
    exact_business_name,
    fuzzy_business_name,
    address_match,
    industry_match,
    email_match,
    phone_match,
]


def score_pair(a: Record, b: Record) -> tuple[float, list[str]]:
    """Combine signals using noisy-OR. Returns (score, reasons)."""
    signals: list[Signal] = []
    for strat in STRATEGIES:
        s = strat(a, b)
        if s is not None:
            signals.append(s)
    if not signals:
        return 0.0, []
    combined = 1.0
    for s in signals:
        combined *= 1.0 - s.score
    return 1.0 - combined, [s.reason for s in signals]
