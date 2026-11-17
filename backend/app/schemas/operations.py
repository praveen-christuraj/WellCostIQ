"""Typed API contracts for Well Operations."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.precision import Decimal10

Scope = Literal["drilling", "completion"]
ReportType = Literal["DDR", "DCR", "DMR", "RMR"]
ReportStatus = Literal["draft", "in_review", "submitted", "approved", "rejected"]
ExtractionStatus = Literal["none", "running", "needs_review", "reviewed", "failed"]
Classification = Literal["Planned", "UPA", "NPT"]
Allocation = Literal["PT", "NPT", "UPA", "SP"]
DocStatus = Literal["uploaded", "extracting", "extracted", "extraction_failed", "reviewed", "archived"]
PlanStatus = Literal["draft", "active", "superseded"]


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class OpsSettingsIn(_Strict):
    day_boundary_hour: int = Field(ge=0, le=23)
    operating_timezone: str = Field(min_length=1, max_length=64)
    tour_pattern: str = Field(min_length=1, max_length=20)
    require_npt_code: bool = True
    require_npt_agency: bool = False
    require_npt_reason: bool = True
    max_daily_hours: int = Field(ge=1, le=48)
    completeness_tolerance_minutes: int = Field(ge=0, le=120)
    default_depth_unit: str = Field(min_length=1, max_length=5)
    default_rop_basis: str = Field(min_length=1, max_length=20)
    document_max_mb: int = Field(ge=1, le=100)

    @field_validator("operating_timezone", "tour_pattern", "default_depth_unit", "default_rop_basis", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OpsSettingsOut(OpsSettingsIn):
    id: str
    organization_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, extra="forbid")


# ---------------------------------------------------------------------------
# Code library
# ---------------------------------------------------------------------------
class OpsOperationCodeIn(_Strict):
    operation_code: str = Field(min_length=1, max_length=50)
    operation_name: str = Field(min_length=1, max_length=150)
    category: str = Field(default="other", max_length=50)
    default_classification: str = Field(default="Planned", max_length=10)
    is_productive_default: bool = True
    counts_as_on_bottom: bool = False
    requires_npt_code: bool = False
    phase_applicable: str = Field(default="both", max_length=20)
    description: str = Field(default="", max_length=500)
    sort_order: int = Field(default=0)
    is_active: bool = True

    @field_validator("operation_code", mode="before")
    @classmethod
    def upper_code(cls, value: Any) -> Any:
        return _trim(value).upper() if isinstance(value, str) else value

    @field_validator("operation_name", "category", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OpsOperationCodeOut(OpsOperationCodeIn):
    id: str
    organization_id: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OpsActivityCodeIn(_Strict):
    activity_code: str = Field(min_length=1, max_length=50)
    activity_name: str = Field(min_length=1, max_length=150)
    default_allocation: str = Field(default="PT", max_length=10)
    description: str = Field(default="", max_length=500)
    sort_order: int = Field(default=0)
    is_active: bool = True

    @field_validator("activity_code", mode="before")
    @classmethod
    def upper_code(cls, value: Any) -> Any:
        return _trim(value).upper() if isinstance(value, str) else value

    @field_validator("activity_name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OpsActivityCodeOut(OpsActivityCodeIn):
    id: str
    organization_id: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OpsNptCodeIn(_Strict):
    npt_code: str = Field(min_length=1, max_length=50)
    npt_name: str = Field(min_length=1, max_length=150)
    family: str = Field(default="other", max_length=30)
    category: str = Field(default="other", max_length=50)
    default_responsible_party: str = Field(default="", max_length=200)
    is_chargeable: bool = False
    is_company_caused: bool = False
    is_contractor_caused: bool = False
    description: str = Field(default="", max_length=500)
    sort_order: int = Field(default=0)
    is_active: bool = True

    @field_validator("npt_code", mode="before")
    @classmethod
    def upper_code(cls, value: Any) -> Any:
        return _trim(value).upper() if isinstance(value, str) else value

    @field_validator("npt_name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OpsNptCodeOut(OpsNptCodeIn):
    id: str
    organization_id: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OpsAgencyIn(_Strict):
    agency_code: str = Field(min_length=1, max_length=50)
    agency_name: str = Field(min_length=1, max_length=150)
    category: str = Field(default="other", max_length=50)
    description: str = Field(default="", max_length=500)
    sort_order: int = Field(default=0)
    is_active: bool = True

    @field_validator("agency_code", mode="before")
    @classmethod
    def upper_code(cls, value: Any) -> Any:
        return _trim(value).upper() if isinstance(value, str) else value

    @field_validator("agency_name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OpsAgencyOut(OpsAgencyIn):
    id: str
    organization_id: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OpsCauseIn(_Strict):
    cause_code: str = Field(min_length=1, max_length=50)
    cause_name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=500)
    sort_order: int = Field(default=0)
    is_active: bool = True

    @field_validator("cause_code", mode="before")
    @classmethod
    def upper_code(cls, value: Any) -> Any:
        return _trim(value).upper() if isinstance(value, str) else value

    @field_validator("cause_name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OpsCauseOut(OpsCauseIn):
    id: str
    organization_id: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class OpsDocumentOut(_Strict):
    id: str
    organization_id: str
    well_id: str | None
    rig_id: str | None
    scope: str
    document_type: str
    file_name: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    document_date: date | None
    report_no_text: str
    status: str
    version_no: int
    well_code_snapshot: str
    well_name_snapshot: str
    rig_code_snapshot: str
    rig_name_snapshot: str
    uploaded_by: str
    uploaded_by_name: str
    notes: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OpsDocumentUploadResponse(_Strict):
    document: OpsDocumentOut
    deduped: bool
    existing_id: str | None = None


class OpsExtractionJobOut(_Strict):
    id: str
    organization_id: str
    document_id: str
    status: str
    report_type: str
    confidence: Decimal
    findings: str
    error_message: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


# ---------------------------------------------------------------------------
# Reports + blocks
# ---------------------------------------------------------------------------
class OpsActivityBlockIn(_Strict):
    sequence_no: int = Field(ge=1, le=200)
    started_at: datetime
    ended_at: datetime
    duration_minutes: int = Field(ge=1, le=1440)
    phase_raw: str = Field(default="", max_length=20)
    operation_code_id: str | None = None
    activity_code_id: str | None = None
    activity_id: str | None = None
    classification: Classification = "Planned"
    allocation: Allocation = "PT"
    is_productive: bool = True
    classification_source: str = Field(default="keyword", max_length=20)
    npt_code_id: str | None = None
    agency_id: str | None = None
    cause_code: str = Field(default="", max_length=50)
    hole_section_id: str | None = None
    phase_id: str | None = None
    depth_from_m: Decimal10 | None = None
    depth_to_m: Decimal10 | None = None
    depth_unit: str = Field(default="m", max_length=5)
    footage_m: Decimal10 | None = None
    bit_depth_m: Decimal10 | None = None
    rotating_hours: Decimal10 | None = None
    rop_m_per_hr: Decimal10 | None = None
    rop_basis: str = Field(default="rotating", max_length=20)
    responsible_party: str = Field(default="", max_length=200)
    vendor_id: str | None = None
    reason: str = Field(default="", max_length=500)
    narrative: str = Field(default="", max_length=5000)
    confidence: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)
    review_state: str = Field(default="suggested", max_length=20)


class OpsActivityBlockOut(OpsActivityBlockIn):
    id: str
    organization_id: str
    report_id: str
    npt_code_snapshot: str
    source_page: int
    source_bbox: str
    reviewer_user_id: str | None
    reviewed_at: datetime | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    # enriched
    operation_code: str | None = None
    operation_name: str | None = None
    activity_code: str | None = None
    activity_name: str | None = None
    npt_code: str | None = None
    npt_name: str | None = None
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OpsReportCreate(_Strict):
    well_id: str = Field(min_length=1, max_length=36)
    rig_id: str | None = Field(default=None, max_length=36)
    scope: Scope = "drilling"
    report_type: str = Field(default="DDR", max_length=10)
    report_date: date
    report_no_text: str = Field(default="", max_length=50)
    day_number: int | None = Field(default=None, ge=1)
    event_code: str = Field(default="", max_length=50)
    period_start_at: datetime | None = None
    period_end_at: datetime | None = None
    hole_section_id: str | None = None
    phase_id: str | None = None
    depth_start_m: Decimal10 | None = None
    depth_end_m: Decimal10 | None = None
    depth_unit: str = Field(default="m", max_length=5)
    tvd_m: Decimal10 | None = None
    progress_m: Decimal10 | None = None
    rotating_hours: Decimal10 | None = None
    dfs_days: Decimal10 | None = None
    operation_summary: str = Field(default="", max_length=10000)
    forward_plan: str = Field(default="", max_length=10000)
    hse_summary: str = Field(default="", max_length=10000)
    remarks: str = Field(default="", max_length=10000)
    source_document_id: str | None = None
    customer: str = Field(default="", max_length=200)
    supervisor: str = Field(default="", max_length=200)
    engineer: str = Field(default="", max_length=200)


class OpsReportUpdate(_Strict):
    rig_id: str | None = None
    report_no_text: str | None = Field(default=None, max_length=50)
    day_number: int | None = Field(default=None, ge=1)
    event_code: str | None = Field(default=None, max_length=50)
    period_start_at: datetime | None = None
    period_end_at: datetime | None = None
    hole_section_id: str | None = None
    phase_id: str | None = None
    depth_start_m: Decimal10 | None = None
    depth_end_m: Decimal10 | None = None
    depth_unit: str | None = Field(default=None, max_length=5)
    tvd_m: Decimal10 | None = None
    progress_m: Decimal10 | None = None
    rotating_hours: Decimal10 | None = None
    dfs_days: Decimal10 | None = None
    operation_summary: str | None = Field(default=None, max_length=10000)
    forward_plan: str | None = Field(default=None, max_length=10000)
    hse_summary: str | None = Field(default=None, max_length=10000)
    remarks: str | None = Field(default=None, max_length=10000)
    status: ReportStatus | None = None


class OpsReportOut(_Strict):
    id: str
    organization_id: str
    well_id: str
    rig_id: str | None
    rig_code_snapshot: str
    rig_name_snapshot: str
    well_code_snapshot: str
    well_name_snapshot: str
    scope: str
    report_type: str
    report_date: date
    report_no_text: str
    report_no_seq: int | None
    day_number: int | None
    event_code: str
    period_start_at: datetime | None
    period_end_at: datetime | None
    period_minutes: int
    hole_section_id: str | None
    phase_id: str | None
    depth_start_m: Decimal | None
    depth_end_m: Decimal | None
    depth_unit: str
    tvd_m: Decimal | None
    progress_m: Decimal | None
    rotating_hours: Decimal | None
    dfs_days: Decimal | None
    est_days: Decimal | None
    operation_summary: str
    forward_plan: str
    hse_summary: str
    remarks: str
    status: str
    extraction_status: str
    current_extraction_id: str | None
    source_document_id: str | None
    supersedes_id: str | None
    superseded_by_id: str | None
    is_current: bool
    revision_no: int
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    created_by: str
    updated_by: str
    # computed
    blocks: list[OpsActivityBlockOut] = []
    unaccounted_minutes: int = 0
    total_block_minutes: int = 0
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OpsReportSaveIn(_Strict):
    report: OpsReportUpdate
    blocks: list[OpsActivityBlockIn] = Field(default_factory=list)


class OpsIDs(_Strict):
    ids: list[str] = Field(min_length=1, max_length=500)


class OpsBulkActionOut(_Strict):
    affected_count: int


class OpsRejectIn(_Strict):
    reason: str = Field(min_length=1, max_length=500)


class OpsBriefOut(_Strict):
    report_id: str
    well_code: str
    well_name: str
    report_date: date
    day_number: int | None
    summary: str
    time_split: dict[str, Any]
    npt_items: list[dict[str, Any]]
    depth_progress: dict[str, Any]
    data_quality: dict[str, Any]


# ---------------------------------------------------------------------------
# Dashboard / analytics
# ---------------------------------------------------------------------------
class OpsKpiOut(_Strict):
    total_reports: int
    draft_reports: int
    submitted_reports: int
    approved_reports: int
    reports_awaiting_review: int
    total_logged_hours: float
    planned_hours: float
    npt_hours: float
    upa_hours: float
    productive_pct: float
    npt_pct: float
    unaccounted_hours: float
    avg_rop: float | None
    lag_days: float | None
    wells_covered: int
    wells_total: int
    data_quality_score: float


class OpsDashboardOut(_Strict):
    kpis: OpsKpiOut
    npt_by_code: list[dict[str, Any]]
    npt_by_agency: list[dict[str, Any]]
    daily_trend: list[dict[str, Any]]
    recent_reports: list[OpsReportOut]
    missing_reports: list[dict[str, Any]]


class OpsTimeDepthPoint(_Strict):
    cum_days: float
    depth_m: float
    report_date: date | None = None
    label: str = ""


class OpsTimeDepthOut(_Strict):
    plan: list[OpsTimeDepthPoint]
    actual: list[OpsTimeDepthPoint]
    npt_bands: list[dict[str, Any]]
    milestones: list[dict[str, Any]]
    lag_series: list[dict[str, Any]]


class OpsNptParetoItem(_Strict):
    code: str
    name: str
    hours: float
    count: int
    pct: float


class OpsReferenceOut(_Strict):
    rigs: list[dict[str, Any]]
    wells: list[dict[str, Any]]
    hole_sections: list[dict[str, Any]]
    phases: list[dict[str, Any]]
    operation_codes: list[OpsOperationCodeOut]
    npt_codes: list[OpsNptCodeOut]
    agencies: list[OpsAgencyOut]
    causes: list[OpsCauseOut]
    activities: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
class OpsPlanVersionIn(_Strict):
    well_id: str = Field(min_length=1, max_length=36)
    scope: Scope = "drilling"
    label: str = Field(min_length=1, max_length=200)
    basis: str = Field(default="engineer", max_length=20)
    planned_start_at: datetime | None = None
    planned_days: Decimal10 | None = None
    notes: str = Field(default="", max_length=5000)


class OpsPlanItemIn(_Strict):
    sequence_no: int = Field(ge=1)
    hole_section_id: str | None = None
    phase_id: str | None = None
    operation_code_id: str | None = None
    description: str = Field(min_length=1, max_length=500)
    target_depth_m: Decimal10 | None = None
    delta_depth_m: Decimal10 | None = None
    planned_hours: Decimal10 = Field(default=Decimal("0"))
    cum_planned_days: Decimal10 | None = None
    rop_assumption_m_per_hr: Decimal10 | None = None
    trip_speed_m_per_hr: Decimal10 | None = None
    contingency_hours: Decimal10 = Field(default=Decimal("0"))
    is_critical_path: bool = True
    notes: str = Field(default="", max_length=500)


class OpsPlanVersionOut(_Strict):
    id: str
    organization_id: str
    well_id: str
    scope: str
    version_no: int
    label: str
    basis: str
    status: str
    planned_start_at: datetime | None
    planned_days: Decimal | None
    notes: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    well_code: str = ""
    well_name: str = ""
    items: list[dict[str, Any]] = []
    model_config = ConfigDict(from_attributes=True, extra="forbid")


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------
class OpsImportRow(_Strict):
    well_code: str = Field(min_length=1, max_length=50)
    scope: str = Field(default="drilling", max_length=20)
    report_date: date
    report_no_text: str = Field(default="", max_length=50)
    rig_code: str = Field(default="", max_length=50)
    depth_start_m: Any = None
    depth_end_m: Any = None
    operation_summary: str = Field(default="", max_length=5000)
    blocks: list[dict[str, Any]] | None = None

    @field_validator("well_code", "scope", "report_no_text", "rig_code", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OpsImportRequest(_Strict):
    rows: list[OpsImportRow] = Field(min_length=1, max_length=2000)


class OpsImportOut(_Strict):
    created_count: int
    errors: list[str]


class OpsExportAudit(_Strict):
    format: Literal["csv", "xlsx", "pdf"] = "csv"
    record_count: int = Field(ge=0)
    include_deleted: bool = False
