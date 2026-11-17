"""Normalisation helpers."""

from datetime import date, datetime
from decimal import Decimal
import re


def parse_depth(value: str | None) -> tuple[Decimal | None, str]:
    if not value:
        return None, "m"
    val = value.strip().replace(",", "")
    # detect unit
    unit = "m"
    low = val.lower()
    if "ft" in low or "feet" in low or "'" in val:
        unit = "ft"
    # extract number
    m = re.search(r"[-+]?\d+[\d,]*\.?\d*", val)
    if not m:
        return None, unit
    try:
        return Decimal(m.group().replace(",", "")), unit
    except Exception:
        return None, unit


def parse_date_flexible(value: str) -> date | None:
    if not value:
        return None
    val = value.strip()
    # Try multiple formats
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%m/%d/%y"):
        try:
            return datetime.strptime(val, fmt).date()
        except Exception:
            continue
    # dd-mm-yyyy with various separators
    m = re.search(r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})", val)
    if m:
        a, b, c = m.groups()
        year = int(c) if len(c) == 4 else 2000 + int(c)
        # Prefer dd/mm/yyyy (as per report-study S1: 00:00 default)
        try:
            # try dd/mm first
            return date(year, int(b), int(a))
        except Exception:
            try:
                return date(year, int(a), int(b))
            except Exception:
                pass
    return None
