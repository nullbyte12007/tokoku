"""Formatter tampilan."""

import re

# Terima: "12500", "12.500", "12,500", "Rp 12.500", "rp12500".
# TOLAK: "1e9", "abc", "12a500", "-12500" (karakter selain digit/pemisah ditolak).
_PRICE_RE = re.compile(r"^\s*(?:rp\.?\s*)?([0-9.,]+)\s*$", re.IGNORECASE)


def rupiah(value):
    """1250000 -> 'Rp 1.250.000'."""
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return "Rp 0"
    sign = "-" if amount < 0 else ""
    digits = f"{abs(amount):,}".replace(",", ".")
    return f"{sign}Rp {digits}"


def parse_price(raw):
    """'12.500' / 'Rp 12.500' / '12500' -> 12500. None kalau tidak valid."""
    if raw is None:
        return None
    match = _PRICE_RE.match(str(raw))
    if match is None:
        return None
    cleaned = "".join(ch for ch in match.group(1) if ch.isdigit())
    if not cleaned:
        return None
    return int(cleaned)
