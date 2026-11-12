"""Contracts for reusable record templates (AFE estimate, well plan, daily sheet).

A template is a *starting point*. The user picks one, fills only the values that
change for this well or this day, and saves a normal record — no Excel file and
no retyping of the standard structure.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TemplateKind = Literal["afe", "well", "daily-cost"]
TemplateAfeType = Literal["Drilling", "Completion"]


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _blank_to_none(value: Any) -> Any:
    """An empty cell means "keep the current value", not zero."""
    return None if value in (None, "") else value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TemplateServiceLineIn(_Strict):
    service_id: str = Field(min_length=1, max_length=36)
    charging_basis: Literal["Day Rate", "Per Service Rate", "Per Section Rate"] = "Day Rate"
    # Plan scopes travel as codes so one template applies to any well whose plan
    # uses the same hole sections and phases.
    section_code: str = Field(default="", max_length=60)
    phase_code: str = Field(default="", max_length=60)
    currency: str = Field(default="", max_length=10)
    service_amount: str = Field(default="0", max_length=40)
    operation_rate: str | None = Field(default=None, max_length=40)
    standby_rate: str | None = Field(default=None, max_length=40)
    repair_rate: str | None = Field(default=None, max_length=40)
    operation_days: str | None = Field(default=None, max_length=40)
    standby_days: str | None = Field(default=None, max_length=40)
    repair_days: str | None = Field(default=None, max_length=40)
    quantity_unit: Literal["days", "hours"] = "days"
    remarks: str = Field(default="", max_length=500)

    @field_validator("operation_rate", "standby_rate", "repair_rate", "operation_days", "standby_days", "repair_days", mode="before")
    @classmethod
    def blank_means_keep(cls, value: Any) -> Any:
        return _blank_to_none(_trim(value))

    @field_validator("section_code", "phase_code", "currency", "service_amount", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class TemplateConsumableLineIn(_Strict):
    category: Literal["Mud Chemicals", "Cement Additives", "Fuel", "Drill Bits"]
    section_code: str = Field(default="", max_length=60)
    phase_code: str = Field(default="", max_length=60)
    drill_bit_id: str | None = Field(default=None, max_length=36)
    quantity: str = Field(default="1", max_length=40)
    estimated_amount: str | None = Field(default=None, max_length=40)
    currency: str = Field(default="", max_length=10)
    remarks: str = Field(default="", max_length=500)

    @field_validator("drill_bit_id", "estimated_amount", mode="before")
    @classmethod
    def blank_means_keep(cls, value: Any) -> Any:
        return _blank_to_none(_trim(value))

    @field_validator("section_code", "phase_code", "quantity", "currency", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class TemplateTangibleLineIn(_Strict):
    tangible_id: str = Field(min_length=1, max_length=36)
    quantity: str = Field(default="1", max_length=40)
    remarks: str = Field(default="", max_length=500)

    @field_validator("quantity", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class TemplateWellPhaseIn(_Strict):
    phase_id: str = Field(min_length=1, max_length=36)
    days: str = Field(default="0", max_length=40)
    remarks: str = Field(default="", max_length=500)

    @field_validator("days", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class TemplateWellSectionIn(_Strict):
    hole_section_id: str = Field(min_length=1, max_length=36)
    from_depth: str = Field(default="0", max_length=40)
    to_depth: str = Field(default="0", max_length=40)
    remarks: str = Field(default="", max_length=500)
    phases: list[TemplateWellPhaseIn] = Field(default_factory=list, max_length=40)

    @field_validator("from_depth", "to_depth", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class TemplateCreate(_Strict):
    template_kind: TemplateKind
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    scope: str = Field(default="General", max_length=60)
    afe_type: TemplateAfeType = "Drilling"
    standard_currency: str = Field(default="", max_length=10)
    is_shared: bool = False
    services: list[TemplateServiceLineIn] = Field(default_factory=list, max_length=500)
    consumables: list[TemplateConsumableLineIn] = Field(default_factory=list, max_length=500)
    tangibles: list[TemplateTangibleLineIn] = Field(default_factory=list, max_length=500)
    sections: list[TemplateWellSectionIn] = Field(default_factory=list, max_length=40)

    @field_validator("name", "description", "scope", "standard_currency", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("name")
    @classmethod
    def require_name(cls, value: str) -> str:
        if not value:
            raise ValueError("Enter a name for this template.")
        return value


class TemplateUpdate(TemplateCreate):
    pass


class TemplateServiceLineOut(_Strict):
    service_id: str
    service_code: str
    service_name: str
    charging_basis: str
    section_code: str
    section_label: str
    phase_code: str
    phase_label: str
    currency: str
    service_amount: str
    operation_rate: str | None
    standby_rate: str | None
    repair_rate: str | None
    operation_days: str | None
    standby_days: str | None
    repair_days: str | None
    quantity_unit: str
    remarks: str
    is_available: bool


class TemplateConsumableLineOut(_Strict):
    category: str
    section_code: str
    section_label: str
    phase_code: str
    phase_label: str
    drill_bit_id: str | None
    drill_bit_code: str
    drill_bit_name: str
    quantity: str
    estimated_amount: str | None
    currency: str
    remarks: str
    is_available: bool


class TemplateTangibleLineOut(_Strict):
    tangible_id: str
    tangible_code: str
    tangible_name: str
    quantity: str
    remarks: str
    is_available: bool


class TemplateWellPhaseOut(_Strict):
    phase_id: str
    phase_code: str
    phase_name: str
    days: str
    remarks: str
    is_available: bool


class TemplateWellSectionOut(_Strict):
    hole_section_id: str
    section_code: str
    section_name: str
    from_depth: str
    to_depth: str
    depth_unit: str
    remarks: str
    phases: list[TemplateWellPhaseOut]
    is_available: bool


class TemplateOut(_Strict):
    id: str
    owner_id: str
    owner_name: str
    template_kind: TemplateKind
    name: str
    description: str
    scope: str
    afe_type: str
    standard_currency: str
    is_shared: bool
    is_owner: bool
    use_count: int
    last_used_at: datetime | None
    line_count: int
    unavailable_count: int
    services: list[TemplateServiceLineOut]
    consumables: list[TemplateConsumableLineOut]
    tangibles: list[TemplateTangibleLineOut]
    sections: list[TemplateWellSectionOut]
    created_at: datetime
    updated_at: datetime


class TemplateSummaryOut(_Strict):
    """A template in a picker: enough to choose one, nothing to edit."""

    id: str
    owner_id: str
    owner_name: str
    template_kind: TemplateKind
    name: str
    description: str
    scope: str
    afe_type: str
    standard_currency: str
    is_shared: bool
    is_owner: bool
    use_count: int
    last_used_at: datetime | None
    line_count: int
    unavailable_count: int
    updated_at: datetime


class TemplateApplyIn(_Strict):
    """Where a template is being applied, so its saved scope can be matched."""

    # A well plan template needs the target well's plan to match section and
    # phase codes against.
    well_id: str = Field(default="", max_length=36)


class TemplateApplyLineOut(_Strict):
    kind: Literal["service", "consumable", "tangible", "section"]
    label: str
    is_available: bool
    note: str = ""


class TemplateApplyPreviewOut(_Strict):
    template_id: str
    template_kind: TemplateKind
    name: str
    services: list[TemplateApplyLineOut]
    consumables: list[TemplateApplyLineOut]
    tangibles: list[TemplateApplyLineOut]
    sections: list[TemplateApplyLineOut]
    warnings: list[str]
    can_apply: bool


class TemplateExportAuditIn(_Strict):
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = Field(ge=0, le=100000)
