"""Typed API contracts for Well Operations."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.precision import Decimal3
from app.schemas.ai import AiErrorCode

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
    require_operations: bool = True
    require_npt_agency: bool = False
    require_npt_reason: bool = True
    max_daily_hours: int = Field(ge=1, le=48)
    completeness_tolerance_minutes: int = Field(ge=0, le=120)
    default_depth_unit: str = Field(min_length=1, max_length=5)
    default_rop_basis: str = Field(min_length=1, max_length=20)
    document_max_mb: int = Field(ge=1, le=100)

    # Sequence codes and lead / lag. Every default is the requested behaviour, so a
    # workspace that never opens this screen gets the corrected arithmetic.
    #: ``lag`` — hours against no sequence code raise actual hours and produce lag.
    #: ``exclude`` — the hours are shown but not subtracted.
    sequence_uncoded_policy: Literal["lag", "exclude"] = "lag"
    #: Whether NPT hours take part in the unplanned lag or are only shown.
    sequence_npt_policy: Literal["include", "exclude"] = "include"
    #: ``separate`` — a skipped activity's hours are reported as saved;
    #: ``net`` — they are also added to the sequence variance as a lead.
    sequence_skipped_credit: Literal["separate", "net"] = "separate"
    #: Over-plan percentage at which closing an activity is suggested to a reviewer.
    sequence_auto_close_tolerance_pct: Decimal = Field(default=Decimal(0), ge=0, le=1000)
    #: Apply that suggestion with nobody confirming it. Deliberately off by default.
    sequence_auto_close: bool = False
    #: Refuse to submit a line that carries no sequence code and no unplanned
    #: acknowledgement. Off by default: it advises, it does not block a report.
    sequence_require_code_on_submit: bool = False
    #: Only current report revisions vote on the confirmed figure.
    sequence_current_run_only: bool = True

    document_types: list[Annotated[str, Field(min_length=1, max_length=20)]] | None = Field(
        default=None, min_length=1, max_length=80
    )

    @field_validator("document_types")
    @classmethod
    def distinct_types(cls, values):
        if values is None:
            return None
        values = [v.strip() for v in values]
        if not all(values) or len({v.casefold() for v in values}) != len(values):
            raise ValueError("Document types must be nonempty and unique.")
        return values

    @field_validator("operating_timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown operating timezone") from exc
        return value

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
class OpsOperationIn(_Strict):
    """One Operations code — the downtime work list of the Code Library."""

    operation_code: str = Field(min_length=1, max_length=50)
    operation_name: str = Field(min_length=1, max_length=150)
    family: str = Field(default="other", max_length=30)
    category: str = Field(default="other", max_length=50)
    default_responsible_party: str = Field(default="", max_length=200)
    is_chargeable: bool = False
    is_company_caused: bool = False
    is_contractor_caused: bool = False
    description: str = Field(default="", max_length=500)
    sort_order: int = Field(default=0)
    is_active: bool = True

    @field_validator("operation_code", mode="before")
    @classmethod
    def upper_code(cls, value: Any) -> Any:
        return _trim(value).upper() if isinstance(value, str) else value

    @field_validator("operation_name", "family", "category", "default_responsible_party", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OpsOperationOut(OpsOperationIn):
    id: str
    organization_id: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OpsSubPhaseIn(_Strict):
    """A sub-phase of one Master Data phase, configured in the Code Library."""

    phase_id: str = Field(min_length=1, max_length=36)
    sub_phase_code: str = Field(min_length=1, max_length=50)
    sub_phase_name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=500)
    sort_order: int = Field(default=0)
    is_active: bool = True

    @field_validator("sub_phase_code", mode="before")
    @classmethod
    def upper_code(cls, value: Any) -> Any:
        return _trim(value).upper() if isinstance(value, str) else value

    @field_validator("sub_phase_name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OpsSubPhaseOut(OpsSubPhaseIn):
    id: str
    organization_id: str
    phase_code_snapshot: str = ""
    phase_name_snapshot: str = ""
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OpsMarkRuleIn(_Strict):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    mark_code: str = Field(min_length=1, max_length=20)
    mark_name: str = Field(min_length=1, max_length=150)
    default_classification: Classification = "Planned"
    default_allocation: Allocation = "PT"
    description: str = Field(default="", max_length=500)
    is_active: bool = True


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


class OpsDocumentEdit(_Strict):
    document_type: str = Field(min_length=1, max_length=20)
    document_date: date | None = None
    notes: str = Field(default="", max_length=1000)


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
    block_id: str | None = Field(default=None, max_length=36)
    sequence_no: int = Field(ge=1, le=2000)
    started_at: datetime
    ended_at: datetime
    duration_minutes: int = Field(ge=1, le=1440)
    phase_raw: str = Field(default="", max_length=20)
    # Review order: Hole Section -> Phase -> Sub-phase -> Activity -> Allocation
    # -> Cause -> Operations -> Agency / service vendor -> Responsible agency label.
    hole_section_id: str | None = None
    phase_id: str | None = None
    sub_phase_id: str | None = None
    activity_id: str | None = None
    classification: Classification = "Planned"
    allocation: Allocation = "PT"
    is_productive: bool = True
    classification_evidence: str = Field(default="", max_length=500)
    source_page: int = Field(default=0, ge=0)
    source_bbox: str = Field(default="", max_length=200)
    classification_source: str = Field(default="keyword", max_length=20)
    cause_code: str = Field(default="", max_length=50)
    operation_id: str | None = None
    responsible_agency_id: str | None = None
    depth_from_m: Decimal3 | None = None
    depth_to_m: Decimal3 | None = None
    tvd_from_m: Decimal3 | None = None
    tvd_to_m: Decimal3 | None = None
    depth_unit: str = Field(default="m", max_length=5)
    footage_m: Decimal3 | None = None
    bit_depth_m: Decimal3 | None = None
    mud_weight_ppg: Decimal3 | None = None
    rotating_hours: Decimal3 | None = None
    rop_m_per_hr: Decimal3 | None = None
    rop_basis: str = Field(default="rotating", max_length=20)
    responsible_party: str = Field(default="", max_length=200)
    vendor_id: str | None = None
    reason: str = Field(default="", max_length=500)
    narrative: str = Field(default="", max_length=5000)
    confidence: Decimal3 = Field(default=Decimal("0.500"), ge=0, le=1)
    review_state: Literal["suggested", "accepted", "edited", "rejected"] = "suggested"
    # The timeline comparison stays visible and reviewable. The system fills it;
    # the engineer accepts, edits or rejects it with a note.
    timeline_comparison: Literal["ahead", "behind", "on"] = "on"
    timeline_review_state: Literal["suggested", "accepted", "edited", "rejected"] = "suggested"
    timeline_note: str = Field(default="", max_length=500)
    #: Sequence code of the programme activity this line logs ("" clears the link).
    timeline_code: str | None = Field(default=None, max_length=20)

    @field_validator("timeline_code", mode="before")
    @classmethod
    def _blank_code_to_none(cls, value: Any) -> Any:
        value = _trim(value)
        return value or None


class OpsActivityBlockOut(OpsActivityBlockIn):
    # Extracted drafts can have more rows or out-of-range durations. Return the
    # stored values for review; the editor limits apply on write, not on read.
    sequence_no: int
    duration_minutes: int
    id: str
    organization_id: str
    report_id: str
    operation_snapshot: str = ""
    source_page: int
    source_bbox: str
    reviewer_user_id: str | None
    reviewed_at: datetime | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    source_activity_code: str = ''
    source_activity_label: str = ''
    source_operation_label: str = ''
    source_phase_label: str = ''
    source_mark_label: str = ''
    source_cause_label: str = ''
    # enriched
    hole_section_label: str = ""
    phase_label: str = ""
    sub_phase_label: str = ""
    activity_label: str = ""
    activity_type: str = ""
    operation_code: str | None = None
    operation_name: str | None = None
    cause_label: str = ""
    responsible_agency_label: str = ""
    timeline_variance_days: Decimal | None = None
    timeline_planned_days: Decimal | None = None
    timeline_actual_days: Decimal | None = None
    timeline_basis: str = ""
    #: The state of the code this line logs (``in_progress``, ``complete``, ...).
    #: An open code has no lead and no lag — only progress and remaining hours.
    timeline_sequence_state: str = ""
    #: ``split`` when the line's hours are shared between several codes.
    timeline_split_state: str = ""
    timeline_reviewed_by: str = ""
    timeline_reviewed_at: datetime | None = None
    #: The programme row this block logs, and the hours each side took.
    timeline_plan_item_id: str | None = None
    timeline_plan_step_no: int | None = None
    timeline_plan_label: str = ""
    timeline_planned_hours: Decimal | None = None
    timeline_actual_hours: Decimal | None = None
    timeline_system_actual_hours: Decimal | None = None
    timeline_variance_hours: Decimal | None = None
    timeline_cum_planned_days: Decimal | None = None
    timeline_actual_edited: bool = False
    timeline_edited_by: str = ""
    timeline_edited_at: datetime | None = None
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
    depth_start_m: Decimal3 | None = None
    depth_end_m: Decimal3 | None = None
    depth_unit: str = Field(default="m", max_length=5)
    tvd_start_m: Decimal3 | None = None
    tvd_m: Decimal3 | None = None
    tvd_source: str = Field(default="", max_length=40)
    bit_depth_m: Decimal3 | None = None
    progress_m: Decimal3 | None = None
    rotating_hours: Decimal3 | None = None
    cum_rotating_hours: Decimal3 | None = None
    spud_date: date | None = None
    dfs_days: Decimal3 | None = None
    est_days: Decimal3 | None = None
    md_auth_m: Decimal3 | None = None
    last_casing_size_in: Decimal3 | None = None
    last_casing_depth_m: Decimal3 | None = None
    hole_section_text: str = Field(default="", max_length=120)
    hole_size_in: Decimal3 | None = None
    current_status: str = Field(default="", max_length=500)
    mud_type: str = Field(default="", max_length=100)
    mud_weight_ppg: Decimal3 | None = None
    mud_viscosity_sec: Decimal3 | None = None
    mud_pv_cp: Decimal3 | None = None
    mud_yp_lbf: Decimal3 | None = None
    bha_summary: str = Field(default="", max_length=500)
    pob_count: int | None = Field(default=None, ge=0, le=50000)
    operation_summary: str = Field(default="", max_length=10000)
    forward_plan: str = Field(default="", max_length=10000)
    hse_summary: str = Field(default="", max_length=10000)
    remarks: str = Field(default="", max_length=10000)
    source_document_id: str | None = None
    customer: str = Field(default="", max_length=200)
    project: str = Field(default="", max_length=200)
    site: str = Field(default="", max_length=200)
    datum: str = Field(default="", max_length=100)
    supervisor: str = Field(default="", max_length=200)
    engineer: str = Field(default="", max_length=200)
    uwi: str = Field(default="", max_length=100)
    block_text: str = Field(default="", max_length=100)


class OpsReportUpdate(_Strict):
    completed_plan_item_id: str | None = None
    customer: str | None = Field(default=None, max_length=200)
    project: str | None = Field(default=None, max_length=200)
    site: str | None = Field(default=None, max_length=200)
    datum: str | None = Field(default=None, max_length=100)
    supervisor: str | None = Field(default=None, max_length=200)
    engineer: str | None = Field(default=None, max_length=200)
    uwi: str | None = Field(default=None, max_length=100)
    block_text: str | None = Field(default=None, max_length=100)
    rig_id: str | None = None
    report_no_text: str | None = Field(default=None, max_length=50)
    day_number: int | None = Field(default=None, ge=1)
    event_code: str | None = Field(default=None, max_length=50)
    period_start_at: datetime | None = None
    period_end_at: datetime | None = None
    hole_section_id: str | None = None
    phase_id: str | None = None
    depth_start_m: Decimal3 | None = None
    depth_end_m: Decimal3 | None = None
    depth_unit: str | None = Field(default=None, max_length=5)
    tvd_start_m: Decimal3 | None = None
    tvd_m: Decimal3 | None = None
    tvd_source: str | None = Field(default=None, max_length=40)
    bit_depth_m: Decimal3 | None = None
    progress_m: Decimal3 | None = None
    rotating_hours: Decimal3 | None = None
    cum_rotating_hours: Decimal3 | None = None
    spud_date: date | None = None
    dfs_days: Decimal3 | None = None
    est_days: Decimal3 | None = None
    md_auth_m: Decimal3 | None = None
    last_casing_size_in: Decimal3 | None = None
    last_casing_depth_m: Decimal3 | None = None
    hole_section_text: str | None = Field(default=None, max_length=120)
    hole_size_in: Decimal3 | None = None
    current_status: str | None = Field(default=None, max_length=500)
    mud_type: str | None = Field(default=None, max_length=100)
    mud_weight_ppg: Decimal3 | None = None
    mud_viscosity_sec: Decimal3 | None = None
    mud_pv_cp: Decimal3 | None = None
    mud_yp_lbf: Decimal3 | None = None
    bha_summary: str | None = Field(default=None, max_length=500)
    pob_count: int | None = Field(default=None, ge=0, le=50000)
    operation_summary: str | None = Field(default=None, max_length=10000)
    forward_plan: str | None = Field(default=None, max_length=10000)
    hse_summary: str | None = Field(default=None, max_length=10000)
    remarks: str | None = Field(default=None, max_length=10000)
    status: ReportStatus | None = None


class OpsReportOut(_Strict):
    completed_plan_item_id: str | None = None
    plan_checkpoints: list[dict[str, str]] = []
    rejection_reason: str = ""
    reopened_at: datetime | None = None
    reopened_by: str = ""
    reopen_reason: str = ""
    submitted_at: datetime | None = None
    submitted_by: str = ""
    approved_at: datetime | None = None
    approved_by: str = ""
    baseline_plan_id: str | None = None
    customer: str = ""
    project: str = ""
    site: str = ""
    datum: str = ""
    supervisor: str = ""
    engineer: str = ""
    uwi: str = ""
    block_text: str = ""
    surveys: list["OpsSurveyIn"] = []
    extraction_notes: str = ""
    sources: list[dict[str, str]] = []
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
    tvd_start_m: Decimal | None = None
    tvd_m: Decimal | None
    tvd_source: str = ""
    bit_depth_m: Decimal | None = None
    progress_m: Decimal | None
    rotating_hours: Decimal | None
    cum_rotating_hours: Decimal | None = None
    spud_date: date | None = None
    dfs_days: Decimal | None
    est_days: Decimal | None
    md_auth_m: Decimal | None = None
    last_casing_size_in: Decimal | None = None
    last_casing_depth_m: Decimal | None = None
    hole_section_text: str = ""
    hole_size_in: Decimal | None = None
    current_status: str = ""
    mud_type: str = ""
    mud_weight_ppg: Decimal | None = None
    mud_viscosity_sec: Decimal | None = None
    mud_pv_cp: Decimal | None = None
    mud_yp_lbf: Decimal | None = None
    bha_summary: str = ""
    pob_count: int | None = None
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


class OpsSurveyIn(_Strict):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    md_m: Decimal3 | None = None
    tvd_m: Decimal3 | None = None
    inc_deg: Decimal3 | None = Field(default=None, ge=0, le=180)
    azi_deg: Decimal3 | None = Field(default=None, ge=0, le=360)
    ns_m: Decimal3 | None = None
    ew_m: Decimal3 | None = None
    vsec_m: Decimal3 | None = None
    dls_deg_per_30m: Decimal3 | None = None
    tool: str = Field(default="", max_length=100)
    source: str = Field(default="manual", max_length=20)
    survey_at: datetime | None = None


class OpsPlanSurveyStationIn(OpsSurveyIn):
    md_m: Decimal3 = Field(ge=0)
    inc_deg: Decimal3 = Field(ge=0, le=180)
    dls_deg_per_30m: Decimal3 | None = Field(default=None, ge=0)
    source_file: str = Field(default="", max_length=255)
    source_sheet: str = Field(default="", max_length=100)


class OpsPlanSurveyIn(_Strict):
    expected_updated_at: datetime
    shared_reference: bool = False
    stations: list[OpsPlanSurveyStationIn] = Field(max_length=5000)


class OpsPlanSurveyOut(_Strict):
    updated_at: datetime
    shared_reference: bool
    stations: list[OpsPlanSurveyStationIn]


class OpsSurveyPreviewStation(_Strict):
    """A station as read from a file, with the file's own numbers kept as-is.

    Range limits are deliberately not enforced here: the point of the preview is
    to *show* what the file contains — including figures that are obviously off —
    so the engineer can drop or correct them before applying anything. The
    limits are enforced again when the stations are saved onto the report.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")
    station_no: int = 0
    md_m: Decimal | None = None
    tvd_m: Decimal | None = None
    inc_deg: Decimal | None = None
    azi_deg: Decimal | None = None
    ns_m: Decimal | None = None
    ew_m: Decimal | None = None
    vsec_m: Decimal | None = None
    dls_deg_per_30m: Decimal | None = None
    tool: str = ""
    source: str = ""
    survey_at: datetime | None = None


class OpsSurveyPreviewOut(_Strict):
    """What the study engine read out of a survey file. Nothing is written."""

    format: Literal["csv", "excel", "pdf"]
    file_name: str
    unit: Literal["m", "ft"]
    detected_sheet: str | None = None
    sheets: list[str] = Field(default_factory=list)
    station_count: int
    stations: list[OpsSurveyPreviewStation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class OpsReportSaveIn(_Strict):
    expected_updated_at: datetime | None = None
    confirm_review: bool = False
    report: OpsReportUpdate
    blocks: list[OpsActivityBlockIn] | None = Field(default=None, max_length=2000)
    surveys: list[OpsSurveyIn] | None = Field(default=None, max_length=200)


class OpsIDs(_Strict):
    ids: list[str] = Field(min_length=1, max_length=500)


class OpsBulkAssign(_Strict):
    """One explicit instruction, applied to the selected blocks."""

    report_ids: list[str] = Field(default_factory=list, max_length=100)
    block_ids: list[str] = Field(default_factory=list, max_length=2000)
    block_kind: Literal["", "drilling", "completion"] = ""
    hole_section_id: str | None = None
    phase_id: str | None = None
    sub_phase_id: str | None = None
    activity_id: str | None = None
    operation_id: str | None = None
    cause_id: str | None = None
    cause_code: str | None = Field(default=None, max_length=50)
    responsible_agency_id: str | None = None
    vendor_id: str | None = None
    allocation: Allocation | None = None


class OpsBulkAssignOut(_Strict):
    changed_count: int = 0
    skipped: list[dict] = []
    remaining_mandatory: list[str] = []
    summary: str = ""


class OpsBulkAssignPreviewOut(_Strict):
    changes: list[dict] = []
    skipped: list[dict] = []
    summary: str = ""
    assigned_fields: list[str] = []


class OpsTimelineCodeOut(_Strict):
    """One programme activity as a link target for daily-report lines."""

    sequence_no: int
    description: str
    planned_hours: Decimal | None = None
    target_depth_m: Decimal | None = None
    cum_planned_days: Decimal | None = None
    #: The identity of the code. Sequence numbers are positional, so a link made
    #: today is stored against this id and cannot slide sideways on a later save.
    item_id: str | None = None
    state: str = "not_started"
    allowed_states: list[str] = Field(
        default_factory=lambda: ["not_started", "in_progress", "overrun_open", "complete", "skipped"]
    )
    remaining_hours: Decimal | None = None
    actual_hours: Decimal | None = None
    is_skipped: bool = False
    closed: bool = False
    effective_cum_days: Decimal | None = None


class OpsReportTimelineCodesOut(_Strict):
    """The baseline programme a report is compared against, and its codes."""

    plan_version_id: str | None = None
    plan_label: str = ""
    plan_status: str = ""
    basis: str = ""
    codes: list[OpsTimelineCodeOut] = Field(default_factory=list)
    policy: "OpsSequencePolicyOut | None" = None


class OpsSeqCodeIn(_Strict):
    """Link the selected daily-report lines to one programme sequence code.

    ``item_id`` is preferred: it is the code's identity. ``sequence_no`` stays for
    existing callers and for a code that was typed from a printed programme.
    """

    block_ids: list[str] = Field(min_length=1, max_length=500)
    sequence_no: int | None = Field(default=None, ge=1)
    item_id: str | None = Field(default=None, max_length=36)

    @field_validator("sequence_no")
    @classmethod
    def _need_one(cls, value, info):
        return value


class OpsSeqCodeSkip(_Strict):
    block_id: str
    sequence_no: int | None = None
    reason: str


class OpsSeqCodeSplitLine(_Strict):
    """Hours of one line that belong to one code."""

    sequence_no: int | None = Field(default=None, ge=1)
    item_id: str | None = Field(default=None, max_length=36)
    hours: Decimal3 = Field(ge=0)


class OpsSeqCodeSplitIn(_Strict):
    """Share one daily-report line's hours between several programme codes."""

    block_id: str = Field(min_length=1, max_length=36)
    allocations: list[OpsSeqCodeSplitLine] = Field(min_length=1, max_length=20)
    #: The hours left over stay in the unplanned bucket and are named, never dropped.
    remainder_to_unplanned: bool = True
    note: str = Field(default="", max_length=500)


class OpsSeqCodeClearIn(_Strict):
    """Remove the code from these lines, deliberately making them unplanned."""

    block_ids: list[str] = Field(min_length=1, max_length=500)
    acknowledge_unplanned: bool = True


class OpsSeqCodePreviewOut(_Strict):
    sequence_no: int
    description: str = ""
    planned_hours: Decimal | None = None
    eligible: int = 0
    lines: list[dict] = Field(default_factory=list)
    skipped: list[OpsSeqCodeSkip] = Field(default_factory=list)
    summary: str = ""
    #: What the code's arithmetic will say once these lines carry it. Work in
    #: progress has no verdict: it has progress and remaining hours.
    code_state: str = ""
    actual_hours: Decimal | None = None
    remaining_hours: Decimal | None = None
    variance_hours: Decimal | None = None
    variance_days: Decimal | None = None
    warnings: list[str] = Field(default_factory=list)


class OpsSeqCodeApplyOut(_Strict):
    applied_count: int = 0
    sequence_no: int | None = None
    item_id: str | None = None
    skipped: list[OpsSeqCodeSkip] = Field(default_factory=list)
    summary: str = ""
    code_state: str = ""
    variance_hours: Decimal | None = None
    variance_days: Decimal | None = None


class OpsSeqCodeSplitOut(_Strict):
    block_id: str
    item_id: str | None = None
    allocated_hours: Decimal | None = None
    line_hours: Decimal | None = None
    remainder_hours: Decimal | None = None
    allocations: list[dict] = Field(default_factory=list)
    summary: str = ""


class OpsSequenceStateIn(_Strict):
    """Skip or un-skip a planned activity, with a reason that is kept."""

    state: Literal["planned", "skipped"]
    reason: str = Field(default="", max_length=500)
    #: A stale screen must not overwrite a fresher decision.
    expected_updated_at: datetime | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def trim(cls, value: Any) -> Any:
        return _trim(value)


class OpsSequenceCloseIn(_Strict):
    """State that a planned activity is finished, and record on what evidence."""

    #: The actual hours to close on, when they differ from the summed logs.
    actual_hours: Decimal3 | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=500)
    block_ids: list[str] = Field(default_factory=list, max_length=2000)
    expected_updated_at: datetime | None = None

    @field_validator("note", mode="before")
    @classmethod
    def trim(cls, value: Any) -> Any:
        return _trim(value)


class OpsSequenceCloseOut(_Strict):
    item_id: str
    sequence_no: int
    state: str
    planned_hours: Decimal | None = None
    actual_hours: Decimal | None = None
    variance_hours: Decimal | None = None
    variance_days: Decimal | None = None
    comparison: Literal["ahead", "behind", "on"] = "on"
    summary: str = ""


class OpsSequencePolicyOut(_Strict):
    """The policy every figure in the ledger was produced under."""

    uncoded: str = "lag"
    npt: str = "include"
    skipped_credit: str = "separate"
    auto_close_tolerance_pct: Decimal = Decimal(0)
    auto_close: bool = False


class OpsTimelineRollupCodeOut(_Strict):
    sequence_no: int
    description: str
    planned_hours: Decimal | None = None
    target_depth_m: Decimal | None = None
    actual_hours: Decimal | None = None
    variance_hours: Decimal | None = None
    variance_days: Decimal | None = None
    comparison: Literal["ahead", "behind", "on"] = "on"
    line_count: int = 0
    report_count: int = 0
    # --- the state model -----------------------------------------------------
    item_id: str = ""
    state: str = "not_started"
    #: reported − but only meaningful while the code is open.
    progress_pct: Decimal | None = None
    remaining_hours: Decimal | None = None
    #: True when the hours look finished but no engineer has closed the activity.
    close_suggested: bool = False
    closed_at: datetime | None = None
    close_source: str = ""
    close_note: str = ""
    saved_planned_hours: Decimal | None = None
    skip_reason: str = ""
    skipped_by: str = ""
    skipped_at: datetime | None = None
    #: Cumulative days on the curve with skipped activities removed, and the shift
    #: from the saved curve. The saving reaches the schedule here, once.
    effective_cum_days: Decimal | None = None
    cum_shift_days: Decimal | None = None
    saved_cum_days: Decimal | None = None
    provisional_actual_hours: Decimal | None = None


class OpsTimelineUnplannedOut(_Strict):
    """Hours logged against no sequence code — they can only produce lag."""

    code: str = "—"
    actual_hours: Decimal | None = None
    upa_hours: Decimal | None = None
    npt_hours: Decimal | None = None
    other_hours: Decimal | None = None
    variance_hours: Decimal | None = None
    variance_days: Decimal | None = None
    comparison: Literal["ahead", "behind", "on"] = "on"
    line_count: int = 0
    provisional_hours: Decimal | None = None
    unmatched_hours: Decimal | None = None


class OpsTimelineTotalsOut(_Strict):
    """The totals, each named for the question it answers."""

    planned_in_scope: Decimal | None = None
    planned_in_scope_days: Decimal | None = None
    planned_saved: Decimal | None = None
    actual_coded: Decimal | None = None
    actual_unplanned: Decimal | None = None
    actual_total: Decimal | None = None
    #: Did the work we finished take the hours allowed? Closed codes only.
    realised_variance: Decimal | None = None
    realised_variance_days: Decimal | None = None
    comparison: Literal["ahead", "behind", "on"] = "on"
    closed_coverage_pct: Decimal | None = None
    #: Actual ÷ plan over the whole plan. Burn, not a verdict.
    plan_coverage_pct: Decimal | None = None
    plan_coverage_days: Decimal | None = None
    provisional_actual_hours: Decimal | None = None
    closed_code_count: int = 0
    open_code_count: int = 0
    not_started_count: int = 0
    skipped_count: int = 0
    missing_planned_hours: int = 0
    unattributed_hours: Decimal | None = None


class OpsTimelineFindingOut(_Strict):
    kind: str
    message: str
    item_id: str | None = None
    block_id: str | None = None
    severity: Literal["note", "warning"] = "note"


class OpsTimelineRollupOut(_Strict):
    """Planned vs actual hours per sequence code, across the baseline's logs."""

    plan_version_id: str
    plan_label: str = ""
    actual_hours: Decimal | None = None
    planned_hours: Decimal | None = None
    variance_hours: Decimal | None = None
    comparison: Literal["ahead", "behind", "on"] = "on"
    codes: list[OpsTimelineRollupCodeOut] = Field(default_factory=list)
    uncoded_lines: int = 0
    # --- the state model and the honest totals -------------------------------
    unplanned: OpsTimelineUnplannedOut | None = None
    totals: OpsTimelineTotalsOut | None = None
    findings: list[OpsTimelineFindingOut] = Field(default_factory=list)
    policy: OpsSequencePolicyOut | None = None
    confirmed_report_count: int = 0
    provisional_report_count: int = 0
    #: Days ahead (+) or behind (−) the programme on the effective curve.
    schedule_position_days: Decimal | None = None
    schedule_position_basis: str = ""


class OpsTimelineHoursEdit(_Strict):
    """One engineer correction to the hours an activity actually took.

    ``actual_hours = None`` clears a correction and restores the logged
    duration as the proposal; a value recomputes the variance and the lead/lag
    mark for that block.
    """

    block_id: str = Field(min_length=1, max_length=36)
    actual_hours: Decimal3 | None = Field(default=None, ge=0)


class OpsTimelineReviewIn(_Strict):
    """Confirm, correct or reject the system's plan-vs-timeline comparison.

    Lead and lag come from the hours, not from a remark: each block is compared
    with the programme activity it logged, and ``hours`` carries the engineer's
    correction to the actual hours. ``note`` explains why a corrected figure
    differs from the time log.
    """

    review_state: Literal["accepted", "edited", "rejected"] = "accepted"
    comparison: Literal["ahead", "behind", "on"] | None = None
    note: str = Field(default="", max_length=500)
    block_ids: list[str] = Field(default_factory=list, max_length=2000)
    #: Engineer corrections, one row per block. Empty means "the system read the
    #: log correctly and I am only accepting or rejecting it".
    hours: list[OpsTimelineHoursEdit] = Field(default_factory=list, max_length=2000)


class OpsTimelineReviewOut(_Strict):
    review_state: str
    updated_count: int = 0
    comparison: str = "on"
    summary: str = ""
    #: planned − actual for the first reviewed block, in hours (lead positive).
    variance_hours: Decimal | None = None
    #: Sum of the reviewed blocks' variances, in hours.
    total_variance_hours: Decimal | None = None
    corrected_blocks: int = 0


# Source kinds describe where to look for a printed token, not which field to pre-fill.
CORRELATION_KINDS = ("operation", "cause", "sub-phase", "responsible-party", "agency")

CorrelationKind = Literal["operation", "cause", "sub-phase", "responsible-party", "agency"]

_COMPANION_FIELDS = (
    # (request/response field, max length)
    ("target_hole_section_id", 36),
    ("target_phase_id", 36),
    ("target_sub_phase_id", 36),
    ("target_activity_id", 36),
    ("target_operation_id", 36),
    ("target_cause_id", 36),
    ("target_agency_id", 36),
    ("target_responsible_agency_id", 36),
    ("target_vendor_id", 36),
    ("target_mark_rule_id", 36),
)


class OpsCorrelationFields(_Strict):
    """Every workspace criterion one correlation rule may pre-select."""

    scope: Literal["", "drilling", "completion"] = ""
    target_allocation: Literal["", "PT", "UPA", "NPT", "SP"] = ""
    target_hole_section_id: str | None = Field(default=None, max_length=36)
    target_phase_id: str | None = Field(default=None, max_length=36)
    target_sub_phase_id: str | None = Field(default=None, max_length=36)
    target_activity_id: str | None = Field(default=None, max_length=36)
    target_operation_id: str | None = Field(default=None, max_length=36)
    target_cause_id: str | None = Field(default=None, max_length=36)
    target_agency_id: str | None = Field(default=None, max_length=36)
    target_responsible_agency_id: str | None = Field(default=None, max_length=36)
    target_vendor_id: str | None = Field(default=None, max_length=36)
    target_mark_rule_id: str | None = Field(default=None, max_length=36)


class OpsCorrelationIn(OpsCorrelationFields):
    kind: CorrelationKind
    source_family: str = Field(default="", max_length=60)
    source_code: str = Field(min_length=1, max_length=100)
    source_label: str = Field(default="", max_length=200)
    target_id: str | None = Field(default=None, min_length=1, max_length=36)
    note: str = Field(default="", max_length=500)


class OpsCorrelationBatchIn(_Strict):
    items: list[OpsCorrelationIn] = Field(min_length=1, max_length=200)


class OpsCorrelationUpdate(OpsCorrelationFields):
    target_id: str | None = Field(default=None, min_length=1, max_length=36)
    is_active: bool = True
    note: str = Field(default="", max_length=500)


class OpsCorrelationOut(OpsCorrelationFields):
    id: str
    kind: str
    source_family: str = ""
    source_code: str
    source_label: str = ""
    target_label: str = ""
    target_id: str | None = None
    extra_criteria_summary: str = ""
    note: str = ""
    is_active: bool = True
    is_deleted: bool = False
    created_by: str = ""
    updated_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OpsCorrelationBatchOut(_Strict):
    created_count: int
    items: list[OpsCorrelationOut]


class OpsCodeLinkIn(_Strict):
    rule_name: str = Field(default="", max_length=160)
    scope: Literal["", "drilling", "completion"] = ""
    default_allocation: Literal["", "PT", "UPA", "NPT", "SP"] = ""
    hole_section_id: str | None = Field(default=None, max_length=36)
    phase_id: str | None = Field(default=None, max_length=36)
    sub_phase_id: str | None = Field(default=None, max_length=36)
    activity_id: str | None = Field(default=None, max_length=36)
    operation_id: str | None = Field(default=None, max_length=36)
    cause_id: str | None = Field(default=None, max_length=36)
    responsible_agency_id: str | None = Field(default=None, max_length=36)
    vendor_id: str | None = Field(default=None, max_length=36)
    mark_rule_id: str | None = Field(default=None, max_length=36)
    is_active: bool = True
    note: str = Field(default="", max_length=500)

    @field_validator("rule_name", "note", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OpsCodeLinkBatchIn(_Strict):
    items: list[OpsCodeLinkIn] = Field(min_length=1, max_length=200)


class OpsCodeLinkOut(_Strict):
    id: str
    rule_name: str = ""
    scope: str = ""
    default_allocation: str = ""
    hole_section_id: str | None = None
    hole_section_label: str = ""
    phase_id: str | None = None
    phase_code: str = ""
    phase_label: str = ""
    sub_phase_id: str | None = None
    sub_phase_label: str = ""
    activity_id: str | None = None
    activity_label: str = ""
    activity_type: str = ""
    operation_id: str | None = None
    operation_label: str = ""
    cause_id: str | None = None
    cause_code: str = ""
    cause_label: str = ""
    responsible_agency_id: str | None = None
    responsible_agency_label: str = ""
    vendor_id: str | None = None
    vendor_label: str = ""
    mark_rule_id: str | None = None
    mark_label: str = ""
    criteria_count: int = 0
    summary_label: str = ""
    note: str = ""
    is_active: bool = True
    is_deleted: bool = False
    created_by: str = ""
    updated_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OpsCodeLinkBatchOut(_Strict):
    created_count: int
    items: list[OpsCodeLinkOut]


class OpsBulkEdit(OpsIDs):
    remarks: str = Field(min_length=1, max_length=1000)


class OpsExtractIn(_Strict):
    document_id: str = Field(min_length=1, max_length=36)
    report_date: date | None = None
    use_ai: bool = False


class OpsBulkActionOut(_Strict):
    affected_count: int


class OpsRejectIn(_Strict):
    reason: str = Field(min_length=1, max_length=500)


class OpsReopenIn(_Strict):
    remarks: str = Field(min_length=3, max_length=500)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim(value)


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
    productive_hours: float
    nonproductive_hours: float
    allocation_hours: dict[str, float]
    productive_pct: float
    npt_pct: float
    unaccounted_hours: float
    avg_rop: float | None
    #: **Schedule position**, not the sequence variance: planned cumulative days at the
    #: confirmed checkpoint minus elapsed days. Negative = ahead of the programme.
    lag_days: float | None
    wells_covered: int
    wells_total: int
    data_quality_score: float


class OpsDashboardOut(_Strict):
    kpis: OpsKpiOut
    npt_by_code: list[dict[str, Any]]
    npt_by_operation: list[dict[str, Any]]
    npt_by_agency: list[dict[str, Any]]
    daily_trend: list[dict[str, Any]]
    recent_reports: list[OpsReportOut]
    missing_reports: list[dict[str, Any]]
    #: Casing schematic and current depth for one selected well (null for a
    #: multi-well filter, where one drawing would misrepresent the rest). The
    #: full trajectory is on ``GET /operations/well-path``.
    well_visual: dict[str, Any] | None = None


class OpsTimeDepthPoint(_Strict):
    """One point on the time-vs-progress curve.

    ``depth_m`` is null for completions, where there is no meaningful depth axis;
    ``activity_no`` then carries the programme activity number (1..n) instead.
    """

    cum_days: float
    depth_m: float | None = None
    activity_no: int | None = None
    activity_id: str | None = None
    report_date: date | None = None
    report_id: str | None = None
    label: str = ""
    rop: float | None = None
    basis: str = ""


class OpsTimeDepthOut(_Strict):
    mode: Literal["depth", "activity"] = "depth"
    plan: list[OpsTimeDepthPoint]
    actual: list[OpsTimeDepthPoint]
    npt_bands: list[dict[str, Any]]
    milestones: list[dict[str, Any]]
    lag_series: list[dict[str, Any]]
    projection: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Well path and well diagram (vertical section, plan view and casing schematic)
# ---------------------------------------------------------------------------
class OpsWellPathStation(_Strict):
    """One integrated trajectory station. Every value is arithmetic on surveys.

    ``dls_deg_per_30m`` is nullable because severity belongs to the interval that
    *ends* at the station: the first station has no interval above it, and a pair
    the record cannot support has no number. A straight pair is ``0.0``.
    """

    md_m: float
    inc_deg: float
    azi_deg: float
    tvd_m: float
    ns_m: float
    ew_m: float
    vsec_m: float
    dls_deg_per_30m: float | None = None
    build_deg_per_30m: float | None = None
    turn_deg_per_30m: float | None = None
    is_anchor: bool = False
    interval_valid: bool = True
    interval_issue: str = ""


class OpsWellPathInterval(_Strict):
    """One survey-to-survey interval, the unit dogleg severity is defined on."""

    from_md_m: float
    to_md_m: float
    delta_md_m: float
    inc1_deg: float
    azi1_deg: float
    inc2_deg: float
    azi2_deg: float
    beta_deg: float | None = None
    dls_deg_per_30m: float | None = None
    recorded_dls_deg_per_30m: float | None = None
    dls_difference_deg_per_30m: float | None = None
    valid: bool = True
    issue: str = ""


class OpsWellPathSurveyStation(_Strict):
    """Recorded provenance for one drawn station, for the source drawer."""

    survey_id: str
    station_no: int | None = None
    md_m: float
    inc_deg: float | None = None
    azi_deg: float | None = None
    recorded_tvd_m: float | None = None
    recorded_ns_m: float | None = None
    recorded_ew_m: float | None = None
    recorded_vsec_m: float | None = None
    recorded_dls_deg_per_30m: float | None = None
    tool: str = ""
    source: str = ""
    source_page: int | None = None
    confidence: float | None = None
    survey_at: str | None = None
    report_id: str | None = None
    report_date: str | None = None
    report_no: str = ""
    report_status: str = ""
    computed_tvd_m: float | None = None
    tvd_difference_m: float | None = None
    rows_at_md: int = 1


class OpsWellPathSurvey(_Strict):
    """The survey itself: where it starts and ends, and what it is anchored to."""

    stations: int = 0
    first_md_m: float | None = None
    last_md_m: float | None = None
    first_survey_at: str | None = None
    last_survey_at: str | None = None
    sources: list[str] = []
    tools: list[str] = []
    anchor: dict[str, Any] | None = None
    anchor_basis: str = ""
    intervals: int = 0
    invalid_intervals: int = 0
    branch: str = ""


class OpsWellPathPosition(_Strict):
    """The marker on the drawing: survey endpoint, report depth, or the gap."""

    marker_md_m: float | None = None
    marker_tvd_m: float | None = None
    marker_tvd_basis: str = ""
    survey_end_md_m: float | None = None
    report_depth_md_m: float | None = None
    gap_m: float | None = None
    basis: str = ""
    comparable: bool = False
    note: str = ""


class OpsWellPathSnapshot(_Strict):
    """One report's positions, kept separate from the trajectory."""

    hole_depth_m: float | None = None
    hole_tvd_m: float | None = None
    bit_depth_m: float | None = None
    off_bottom_m: float | None = None
    off_bottom_note: str = ""
    report_id: str | None = None
    report_date: str | None = None
    report_no: str = ""
    status: str = ""
    verified: bool = False
    basis: str = ""
    current_status_text: str = ""
    tvd_source: str = ""
    label: str = ""


class OpsWellPathSummary(_Strict):
    stations: int
    md_m: float | None = None
    tvd_m: float | None = None
    departure_m: float | None = None
    displacement_m: float | None = None
    closure_azimuth_deg: float | None = None
    max_inc_deg: float | None = None
    max_dls_deg_per_30m: float | None = None
    max_dls_to_md_m: float | None = None
    intervals: int = 0
    invalid_intervals: int = 0
    vertical_section_m: float | None = None
    kickoff_md_m: float | None = None
    current_md_m: float | None = None
    current_tvd_m: float | None = None
    current_tvd_basis: str = ""
    bit_depth_m: float | None = None
    latest_report_date: str | None = None
    latest_report_status: str = ""
    depth_basis: str = ""
    casing_seats: int = 0
    sections_drawn: int = 0
    survey_end_md_m: float | None = None
    report_depth_md_m: float | None = None
    survey_to_report_gap_m: float | None = None
    position_basis: str = ""


class OpsWellDiagramSection(_Strict):
    """One drawn casing string, from the shoe above it down to its own shoe."""

    from_depth_m: float
    to_depth_m: float
    length_m: float
    casing_size_in: float
    casing_label: str
    source: str
    hole_size_in: float | None = None
    is_deepest: bool = False


class OpsWellPathPlan(_Strict):
    label: str = ""
    version_no: int | None = None
    points: list[dict[str, Any]] = []
    planned_days: float | None = None
    planned_start_at: str | None = None
    items: int = 0


class OpsPlannedTrajectory(_Strict):
    plan_version_id: str
    label: str
    version_no: int
    status: str
    curve: list[OpsWellPathStation]
    shared_reference: bool
    anchor_basis: str
    sources: list[str] = Field(default_factory=list)


class OpsTrajectoryComparison(_Strict):
    vertical_section_azimuth_deg: float
    planned_trajectory: OpsPlannedTrajectory
    curve: list[OpsWellPathStation]
    survey_stations: list[OpsWellPathSurveyStation]
    comparison_basis: str = ""
    comparable: bool = False
    actual_visible: bool


class OpsWellPathOut(_Strict):
    """A well's trajectory and drawing, with the provenance of every figure.

    ``is_surveyed`` is false when no usable station exists: the pages must then
    show the diagram as unavailable rather than a straight line that was never
    drilled. ``assumption`` states, in words, any fallback that *was* applied.
    """

    well_id: str
    well_code: str
    well_name: str
    scope: str
    datum: str = ""
    vertical_section_azimuth_deg: float = 0.0
    curve: list[OpsWellPathStation] = []
    summary: OpsWellPathSummary
    #: Intervals between accepted stations: the DLS chart reads these.
    intervals: list[OpsWellPathInterval] = []
    #: Recorded provenance for each drawn station: the source drawer reads these.
    survey_stations: list[OpsWellPathSurveyStation] = []
    survey: OpsWellPathSurvey = OpsWellPathSurvey()
    position: OpsWellPathPosition = OpsWellPathPosition()
    snapshot: OpsWellPathSnapshot = OpsWellPathSnapshot()
    sections: list[OpsWellDiagramSection] = []
    open_hole: dict[str, Any] | None = None
    casing_seats: list[dict[str, Any]] = []
    planned: OpsWellPathPlan = OpsWellPathPlan()
    planned_trajectory: OpsPlannedTrajectory | None = None
    comparison_basis: str = ""
    comparable: bool = False
    depth: dict[str, Any] = {}
    survey_discrepancies: list[dict[str, Any]] = []
    notes: list[str] = []
    assumption: str = ""
    is_surveyed: bool = False
    generated_at: str = ""


class OpsWellDiagramOut(_Strict):
    """Trajectory drawing across every configured well of the current filter."""

    scope: str
    wells: list[OpsWellPathOut]


class OpsNptParetoItem(_Strict):
    code: str
    name: str
    hours: float
    count: int
    pct: float


class OpsRegisterFolderOut(_Strict):
    rig_key: str
    well_key: str
    rig_id: str | None
    well_id: str | None
    rig_code: str
    well_code: str
    well_name: str
    scope: str
    record_count: int


class OpsDefaultCodeOut(_Strict):
    id: str
    family: str
    code: str
    name: str
    description: str
    source: str
    classification: str
    allocation: str


class OpsReferenceOut(_Strict):
    """Every dropdown the daily report needs, in one payload.

    Master Data supplies Hole Sections, Phases, Activities and vendors; the Code
    Library supplies sub-phases, Operations, causes and responsible agency
    labels. ``classification_rules`` is keyed by Activity type.
    """

    document_types: list[str]
    vendors: list[dict[str, str]]
    rigs: list[dict[str, Any]]
    wells: list[dict[str, Any]]
    hole_sections: list[dict[str, Any]] = Field(default_factory=list)
    phases: list[dict[str, Any]] = Field(default_factory=list)
    activities: list[dict[str, Any]] = Field(default_factory=list)
    sub_phases: list[OpsSubPhaseOut] = Field(default_factory=list)
    operations: list[OpsOperationOut] = Field(default_factory=list)
    causes: list[OpsCauseOut] = Field(default_factory=list)
    agencies: list[OpsAgencyOut] = Field(default_factory=list)
    code_links: list[OpsCodeLinkOut] = Field(default_factory=list)
    classification_rules: dict[str, list[str]] = {}


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
class OpsPlanVersionIn(_Strict):
    well_id: str = Field(min_length=1, max_length=36)
    scope: Scope = "drilling"
    label: str = Field(min_length=1, max_length=200)
    basis: str = Field(default="engineer", max_length=20)
    planned_start_at: datetime | None = None
    planned_days: Decimal3 | None = None
    notes: str = Field(default="", max_length=5000)


class OpsPlanUpdateIn(_Strict):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    basis: str | None = Field(default=None, min_length=1, max_length=20)
    planned_start_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("label", "basis", "notes", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OpsPlanItemIn(_Strict):
    #: The row's identity, when the editor is re-saving a row it already holds.
    #: Sequence numbers are positional, so without this the save would have to
    #: delete and re-create every item — which re-points every historical link.
    item_id: str | None = Field(default=None, max_length=36)
    sequence_no: int = Field(ge=1)
    hole_section_id: str | None = None
    phase_id: str | None = None
    operation_id: str | None = None
    description: str = Field(min_length=1, max_length=500)
    target_depth_m: Decimal3 | None = Field(default=None, ge=0)
    delta_depth_m: Decimal3 | None = None
    planned_hours: Decimal3 = Field(ge=0)
    cum_planned_days: Decimal3 | None = None
    rop_assumption_m_per_hr: Decimal3 | None = None
    trip_speed_m_per_hr: Decimal3 | None = None
    contingency_hours: Decimal3 = Field(default=Decimal(0))
    is_critical_path: bool = True
    notes: str = Field(default="", max_length=500)


class OpsBriefRequest(_Strict):
    use_ai: bool = False


class OpsPlanStudyRequest(OpsBriefRequest):
    items: list[OpsPlanItemIn] | None = Field(default=None, min_length=1, max_length=2000)


class OpsStudyOut(_Strict):
    summary: str
    warnings: list[str] = Field(default_factory=list)
    ai_text: str = ''
    ai_model: str = ''
    ai_error: str = ''
    ai_error_code: AiErrorCode = ''


class OpsNarrativeRequest(_Strict):
    use_ai: bool = True
    focus: str = Field(default="", max_length=500)

    @field_validator("focus", mode="before")
    @classmethod
    def trim_focus(cls, value: Any) -> Any:
        return _trim(value)


class OpsNarrativeOut(_Strict):
    operation_summary: str = ""
    forward_plan: str = ""
    hse_summary: str = ""
    engineering_brief: str = ""
    warnings: list[str] = Field(default_factory=list)
    ai_used: bool = False
    ai_model: str = ""
    ai_error: str = ""
    ai_error_code: AiErrorCode = ""


class OpsAiPrefillOut(_Strict):
    report: OpsReportOut
    updated_header_fields: list[str] = Field(default_factory=list)
    updated_block_count: int = 0
    notes: list[str] = Field(default_factory=list)
    ai_used: bool = False
    ai_model: str = ""
    ai_error: str = ""
    ai_error_code: AiErrorCode = ""


class OpsAiReviewRequest(_Strict):
    well_id: str | None = Field(default=None, max_length=36)
    rig_id: str | None = Field(default=None, max_length=36)
    scope: Scope | None = None
    date_from: date | None = None
    date_to: date | None = None
    focus: str = Field(default="", max_length=500)
    use_ai: bool = True

    @field_validator("focus", mode="before")
    @classmethod
    def trim_focus(cls, value: Any) -> Any:
        return _trim(value)


class OpsAiReviewItem(_Strict):
    severity: Literal["high", "medium", "low", "info"] = "info"
    category: str = ""
    title: str
    detail: str
    well_code: str = ""
    report_date: str = ""
    report_id: str = ""


class OpsAiReviewOut(_Strict):
    generated_at: datetime
    timezone_label: str = "WAT (UTC+1:00)"
    scope_label: str = ""
    deterministic_summary: str = ""
    executive_summary: str = ""
    highlights: list[str] = Field(default_factory=list)
    anomalies: list[OpsAiReviewItem] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    ai_used: bool = False
    ai_model: str = ""
    ai_endpoint: str = ""
    ai_error: str = ""
    ai_error_code: AiErrorCode = ""


class OpsWellSummaryOut(_Strict):
    generated_at: datetime
    timezone: str = "Africa/Lagos"
    timezone_label: str = "WAT (UTC+1:00)"
    well_id: str
    well_code: str
    well_name: str
    rig_code: str = ""
    rig_name: str = ""
    block_text: str = ""
    field_site: str = ""
    customer: str = ""
    uwi: str = ""
    datum: str = ""
    scope_label: str = ""
    include_drafts: bool = True
    spud_date: date | None = None
    first_report_date: date | None = None
    last_report_date: date | None = None
    latest_status: str = ""
    latest_hole_section: str = ""
    last_casing: str = ""
    latest_mud: str = ""
    latest_bha: str = ""
    kpis: dict[str, Any] = Field(default_factory=dict)
    activities: list[dict[str, Any]] = Field(default_factory=list)
    daily_rollup: list[dict[str, Any]] = Field(default_factory=list)
    pt_npt_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    phase_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    surveys: list[dict[str, Any]] = Field(default_factory=list)


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
    approved_by: str = ""
    reopened_at: datetime | None = None
    reopened_by: str = ""
    reopen_reason: str = ""
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
    depth_start_m: Decimal3 | None = None
    depth_end_m: Decimal3 | None = None
    operation_summary: str = Field(default="", max_length=5000)
    report_type: str = Field(default="DDR", max_length=10)

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
