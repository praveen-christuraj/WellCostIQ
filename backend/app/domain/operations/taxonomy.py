"""Clean source tokens, never infer downtime from a bracketed activity number."""

import re


def code_key(value):
    """Normalise e.g. '02' and '[2]' for lookup against the workspace's code library."""
    text = " ".join(str(value if value is not None else "").strip().casefold().split())
    match = re.fullmatch(r"(?:\[\s*(\d+)\s*\]|\(\s*(\d+)\s*\)|(\d+))", text)
    return (next(g for g in match.groups() if g is not None).lstrip("0") or "0") if match else text
