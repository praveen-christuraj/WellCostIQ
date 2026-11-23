"""The Planned / UPA / NPT classification of a Master Data Activity.

The Activity record carries the type the workspace chose for it. Activities that
predate that column were backfilled to ``Planned`` by migration ``b7e2f4a91c38``
rather than guessed from their name, so the printed code and name stay a second
signal: an Activity is **NPT** or **UPA** when either its stored type or its code
/ name says so, and **Planned** only when both agree that it is.

Rig & Well reads this rule when it decides whether a well sub activity needs a
responsible party. It is deliberately broader than the stored column, so the API
never demands a party that the screen has disabled, and never accepts a blank
party the screen would have required. Keeping the two in step is what stops the
Rig & Well register and the Daily Cost register disagreeing about the same
Activity.

The Daily Cost module keeps its own code/name classifier
(``app.services.daily_cost.classify_activity``) for priced lines; this module is
not a drop-in replacement for it, because costing classification is stored on
every saved line and changing it would rewrite cost history.
"""

from __future__ import annotations

import re
from typing import Any

CLASSIFICATIONS = ("Planned", "NPT", "UPA")

_NPT_PATTERN = re.compile(r"\bnpt\b|non[ -]?productive")
_UPA_PATTERN = re.compile(r"\bupa\b|unplanned")


def _first_text(activity: Any, *attributes: str) -> str:
    for attribute in attributes:
        value = getattr(activity, attribute, None)
        if value:
            return str(value)
    return ""


def activity_classification(activity: Any) -> str:
    """Return ``"Planned"``, ``"NPT"`` or ``"UPA"`` for a Master Data Activity.

    A stored NPT/UPA type always wins, so an Activity the workspace explicitly
    typed is honoured. Otherwise the code and name are read the same way the
    costing register reads them, which is what this screen did before the typed
    Activity existed.
    """
    declared = str(getattr(activity, "activity_type", "") or "").strip().upper()
    if declared in ("NPT", "UPA"):
        return declared
    text = (
        f"{_first_text(activity, 'activity_code', 'code')} "
        f"{_first_text(activity, 'activity_name', 'name')}"
    ).lower()
    if _NPT_PATTERN.search(text):
        return "NPT"
    if _UPA_PATTERN.search(text):
        return "UPA"
    return "Planned"
