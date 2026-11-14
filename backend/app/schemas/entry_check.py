"""Request and response contracts for the daily-sheet entry checks.

An entry check is advice, never a rule: it does not stop a save and it does not
change a figure. Each finding names what was compared (``basis``), where the
value sits on the sheet (``lines``), and -- when one keying slip explains the
value -- the corrected value the user may apply (``suggested_value`` on the
lines listed in ``apply_to``).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CheckSeverity = Literal["info", "warning"]
# Where a line lives inside the sheet's save payload.
CheckGroup = Literal["services", "consumables", "tangibles", "other_expenses"]
# The entered field a finding is about; "" when it is about the sheet as a whole.
CheckField = Literal[
    "", "quantity", "quantity_unit", "override_rate", "exchange_rate", "actual_depth", "actual_depth_unit",
    "usd_exchange_rate",
]
# What the value was compared with: other sheets of the AFE, the workspace's
# other wells, the AFE's locked figures, the locked well plan, or the sheet itself.
CheckScope = Literal["afe", "workspace", "baseline", "plan", "sheet"]


class DailyCostCheckLine(BaseModel):
    """One line of the sheet: its group and its position inside that group."""

    group: CheckGroup
    index: int


class DailyCostEntryCheck(BaseModel):
    """One finding on a daily cost sheet."""

    # Stable identity of the finding on this sheet.
    key: str
    code: str
    severity: CheckSeverity
    title: str
    message: str
    # The evidence, in one sentence: what the value was compared with.
    basis: str = ""
    scope: CheckScope = "afe"
    subject_label: str = ""
    # The lines the finding is about, in sheet order. Empty for a finding about
    # the sheet as a whole.
    lines: list[DailyCostCheckLine] = Field(default_factory=list)
    field: CheckField = ""
    # The entered value, as plain text for the field and as it reads on the sheet.
    current_value: str | None = None
    current_display: str = ""
    # Offered only when one keying slip explains the value. Applying it sets
    # ``field`` to ``suggested_value`` on every line of ``apply_to`` (or on the
    # sheet itself when ``field`` is a sheet field).
    suggested_value: str | None = None
    suggested_display: str = ""
    apply_to: list[DailyCostCheckLine] = Field(default_factory=list)
    usual_display: str = ""
    history_count: int = 0
    # Identifies the exact value a review accepts.
    fingerprint: str = ""
    reviewed: bool = False
    reviewed_by: str = ""
    reviewed_at: datetime | None = None
    review_note: str = ""


class DailyCostEntryChecksOut(BaseModel):
    entry_id: str
    # False when the deployment has turned entry checks off; the lists are then empty.
    enabled: bool = True
    checks: list[DailyCostEntryCheck] = Field(default_factory=list)
    # Findings still waiting for a decision, by severity.
    open_warnings: int = 0
    open_notices: int = 0
    reviewed: int = 0
    # How many other sheets of the same AFE the values were compared with.
    history_sheets: int = 0


class _StrictIn(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DailyCostCheckReviewItem(_StrictIn):
    """A finding exactly as the user saw it: its key and the value it is about."""

    key: str = Field(min_length=3, max_length=240)
    fingerprint: str = Field(min_length=1, max_length=80)

    @field_validator("key", "fingerprint", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class DailyCostCheckReviewIn(_StrictIn):
    """Keep the values behind these findings as entered."""

    items: list[DailyCostCheckReviewItem] = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=300)

    @field_validator("note", mode="before")
    @classmethod
    def trim_note(cls, value):
        return value.strip() if isinstance(value, str) else value


class DailyCostCheckReopenIn(_StrictIn):
    """Bring reviewed findings back for another look."""

    keys: list[str] = Field(min_length=1, max_length=100)

    @field_validator("keys")
    @classmethod
    def bounded_keys(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not 3 <= len(item) <= 240 for item in cleaned):
            raise ValueError("each key must be between 3 and 240 characters")
        return cleaned


class DailyCostSheetChecks(BaseModel):
    """The findings of one sheet, for the well-level review."""

    entry_id: str
    daily_cost_code: str
    cost_date: date
    status: str
    afe_code: str
    open_warnings: int = 0
    open_notices: int = 0
    reviewed: int = 0
    checks: list[DailyCostEntryCheck] = Field(default_factory=list)


class DailyCostWellChecksOut(BaseModel):
    well_id: str
    enabled: bool = True
    sheets_checked: int = 0
    sheets_with_findings: int = 0
    open_warnings: int = 0
    open_notices: int = 0
    reviewed: int = 0
    # Set when the well has more sheets than one review covers.
    truncated: bool = False
    sheets: list[DailyCostSheetChecks] = Field(default_factory=list)
