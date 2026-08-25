"""Money is integer minor units (paise). Never floats in money paths."""
from __future__ import annotations

DECIMALS = 2  # INR paise


def paise(rupees: float | int) -> int:
    """Convert rupees (display) to integer paise."""
    return int(round(float(rupees) * 100))


def rupees(p: int) -> float:
    return p / 100


def format_inr(p: int) -> str:
    """₹12,99,000 full Indian grouping (for dossiers)."""
    n = int(round(p / 100))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + "₹" + s


def compact_inr(p: int) -> str:
    """₹-compact matching Intl.NumberFormat('en-IN',{notation:'compact'}): K / L / Cr."""
    n = abs(p) / 100.0
    sign = "-" if p < 0 else ""

    def fmt(v: float) -> str:
        return f"{v:.1f}".rstrip("0").rstrip(".")

    if n >= 1e7:
        return f"{sign}₹{fmt(n / 1e7)}Cr"
    if n >= 1e5:
        return f"{sign}₹{fmt(n / 1e5)}L"
    if n >= 1e3:
        return f"{sign}₹{fmt(n / 1e3)}K"
    return f"{sign}₹{fmt(n)}"
