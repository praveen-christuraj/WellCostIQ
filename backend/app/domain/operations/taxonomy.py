"""Clean source tokens, never infer downtime from a bracketed activity number."""

import re


def code_key(value):
    """Normalise e.g. '02' and '[2]' for lookup against the workspace's code library."""
    text = str(value or "").strip().casefold()
    match = re.fullmatch(r"[\[(]?0*(\d+)[\])]?", text)
    return (match[1].lstrip("0") or "0") if match else text
