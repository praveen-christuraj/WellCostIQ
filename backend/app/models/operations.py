"""Well Operations module — persistence models.

Isolated from costing: no FK to any afe* or daily_cost* table, and vice versa.
Every business table is organization_id-scoped, soft-deletable and auditable.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Settings — one row per workspace
# ---------------------------------------------------------------------------
class OpsSettings(Base):
    __tablename__ = "ops_settings"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_ops_settings_org"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day_boundary_hour: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    operating_timezone: Mapped[str] = mapped_column(String(64), default="Africa/Lagos", nullable=False)
    tour_pattern: Mapped[str] = mapped_column(String(20), default="single_24h", nullable=False)
    require_review_before_submit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_extract_on_upload: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    classification_confidence_high: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.85"), nullable=False)
    classification_confidence_low: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.60"), nullable=False)
    require_npt_code: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    require_npt_agency: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_npt_reason: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_daily_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    completeness_tolerance_minutes: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    allow_block_spill: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_depth_unit: Mapped[str] = mapped_column(String(5), default="m", nullable=False)
    default_rop_basis: Mapped[str] = mapped_column(String(20), default="rotating", nullable=False)
    plan_contingency_hours: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    document_max_mb: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    retention_years: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    extraction_timeout_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)


# ---------------------------------------------------------------------------
# Code library — all user-configurable
# ---------------------------------------------------------------------------
class OpsOperationCode(Base):
    __tablename__ = "ops_operation_codes"
    __table_args__ = (
        UniqueConstraint("organization_id", "operation_code", name="uq_ops_operation_codes_org_code"),
        Index("ix_ops_operation_codes_org_deleted", "organization_id", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_code: Mapped[str] = mapped_column(String(50), nullable=False)
    operation_name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="other", nullable=False)
    default_classification: Mapped[str] = mapped_column(String(10), default="Planned", nullable=False)
    is_productive_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    counts_as_on_bottom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_npt_code: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phase_applicable: Mapped[str] = mapped_column(String(20), default="both", nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class OpsActivityCode(Base):
    __tablename__ = "ops_activity_codes"
    __table_args__ = (
        UniqueConstraint("organization_id", "activity_code", name="uq_ops_activity_codes_org_code"),
        Index("ix_ops_activity_codes_org_deleted", "organization_id", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    activity_code: Mapped[str] = mapped_column(String(50), nullable=False)
    activity_name: Mapped[str] = mapped_column(String(150), nullable=False)
    default_allocation: Mapped[str] = mapped_column(String(10), default="PT", nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class OpsNptCode(Base):
    __tablename__ = "ops_npt_codes"
    __table_args__ = (
        UniqueConstraint("organization_id", "npt_code", name="uq_ops_npt_codes_org_code"),
        Index("ix_ops_npt_codes_org_deleted", "organization_id", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    npt_code: Mapped[str] = mapped_column(String(50), nullable=False)
    npt_name: Mapped[str] = mapped_column(String(150), nullable=False)
    family: Mapped[str] = mapped_column(String(30), default="other", nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="other", nullable=False)
    default_responsible_party: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    is_chargeable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_company_caused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_contractor_caused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class OpsAgency(Base):
    __tablename__ = "ops_agencies"
    __table_args__ = (
        UniqueConstraint("organization_id", "agency_code", name="uq_ops_agencies_org_code"),
        Index("ix_ops_agencies_org_deleted", "organization_id", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    agency_code: Mapped[str] = mapped_column(String(50), nullable=False)
    agency_name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="other", nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class OpsCause(Base):
    __tablename__ = "ops_causes"
    __table_args__ = (
        UniqueConstraint("organization_id", "cause_code", name="uq_ops_causes_org_code"),
        Index("ix_ops_causes_org_deleted", "organization_id", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    cause_code: Mapped[str] = mapped_column(String(50), nullable=False)
    cause_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


# ---------------------------------------------------------------------------
# Document vault
# ---------------------------------------------------------------------------
class OpsDocument(Base):
    __tablename__ = "ops_documents"
    __table_args__ = (
        Index("ix_ops_documents_org_well", "organization_id", "well_id"),
        Index("ix_ops_documents_org_status", "organization_id", "status"),
        Index("ix_ops_documents_org_deleted", "organization_id", "is_deleted"),
        Index("ix_ops_documents_checksum", "organization_id", "checksum_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    well_id: Mapped[str | None] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=True, index=True)
    rig_id: Mapped[str | None] = mapped_column(ForeignKey("rigs.id", ondelete="RESTRICT"), nullable=True)
    scope: Mapped[str] = mapped_column(String(20), default="drilling", nullable=False)
    folder_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    document_type: Mapped[str] = mapped_column(String(20), default="DDR", nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), default="application/pdf", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    storage: Mapped[str] = mapped_column(String(20), default="database", nullable=False)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    external_ref: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_no_text: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="uploaded", nullable=False)
    extraction_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    # snapshots
    well_code_snapshot: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    well_name_snapshot: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    rig_code_snapshot: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    rig_name_snapshot: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    uploaded_by_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class OpsExtractionJob(Base):
    __tablename__ = "ops_extraction_jobs"
    __table_args__ = (
        Index("ix_ops_extraction_jobs_org_doc", "organization_id", "document_id"),
        Index("ix_ops_extraction_jobs_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("ops_documents.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    report_type: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), nullable=False)
    findings: Mapped[str] = mapped_column(Text, default="[]", nullable=False)  # JSON array as text
    payload_summary: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    error_message: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


# ---------------------------------------------------------------------------
# Daily reports + time blocks
# ---------------------------------------------------------------------------
class OpsDailyReport(Base):
    __tablename__ = "ops_daily_reports"
    __table_args__ = (
        CheckConstraint("scope IN ('drilling', 'completion')", name="ck_ops_reports_scope"),
        CheckConstraint("status IN ('draft', 'in_review', 'submitted', 'approved', 'rejected')", name="ck_ops_reports_status"),
        CheckConstraint("extraction_status IN ('none', 'running', 'needs_review', 'reviewed', 'failed')", name="ck_ops_reports_extraction_status"),
        UniqueConstraint("organization_id", "well_id", "scope", "report_date", name="uq_ops_reports_org_well_scope_date"),
        Index("ix_ops_reports_org_well_date", "organization_id", "well_id", "report_date"),
        Index("ix_ops_reports_org_status", "organization_id", "status"),
        Index("ix_ops_reports_org_deleted", "organization_id", "is_deleted"),
        Index("ix_ops_reports_org_rig", "organization_id", "rig_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    rig_id: Mapped[str | None] = mapped_column(ForeignKey("rigs.id", ondelete="RESTRICT"), nullable=True, index=True)
    rig_code_snapshot: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    rig_name_snapshot: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True)
    well_code_snapshot: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    well_name_snapshot: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    scope: Mapped[str] = mapped_column(String(20), default="drilling", nullable=False)
    report_type: Mapped[str] = mapped_column(String(10), default="DDR", nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_no_text: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    report_no_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_code: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    period_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_minutes: Mapped[int] = mapped_column(Integer, default=1440, nullable=False)
    hole_section_id: Mapped[str | None] = mapped_column(ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=True)
    phase_id: Mapped[str | None] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True)
    depth_start_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    depth_end_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    depth_unit: Mapped[str] = mapped_column(String(5), default="m", nullable=False)
    tvd_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    progress_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    rotating_hours: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    dfs_days: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    est_days: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    md_auth_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    last_casing_size_in: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    last_casing_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    customer: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    project: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    site: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    datum: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    supervisor: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    engineer: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    uwi: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    block_text: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    extraction_status: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    current_extraction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("ops_documents.id", ondelete="SET NULL"), nullable=True)
    operation_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    forward_plan: Mapped[str] = mapped_column(Text, default="", nullable=False)
    hse_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    remarks: Mapped[str] = mapped_column(Text, default="", nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    rejection_reason: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class OpsActivityBlock(Base):
    __tablename__ = "ops_activity_blocks"
    __table_args__ = (
        CheckConstraint("classification IN ('Planned', 'UPA', 'NPT')", name="ck_ops_blocks_classification"),
        CheckConstraint("allocation IN ('PT', 'NPT', 'UPA', 'SP')", name="ck_ops_blocks_allocation"),
        CheckConstraint("NOT (classification = 'NPT' AND is_productive = true)", name="ck_ops_blocks_npt_productive"),
        CheckConstraint("review_state IN ('suggested', 'accepted', 'edited', 'rejected')", name="ck_ops_blocks_review_state"),
        Index("ix_ops_blocks_org_report_seq", "organization_id", "report_id", "sequence_no"),
        Index("ix_ops_blocks_org_report", "organization_id", "report_id"),
        Index("ix_ops_blocks_org_classification", "organization_id", "classification"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("ops_daily_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    phase_raw: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    operation_code_id: Mapped[str | None] = mapped_column(ForeignKey("ops_operation_codes.id", ondelete="SET NULL"), nullable=True)
    activity_code_id: Mapped[str | None] = mapped_column(ForeignKey("ops_activity_codes.id", ondelete="SET NULL"), nullable=True)
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("activities.id", ondelete="SET NULL"), nullable=True)
    classification: Mapped[str] = mapped_column(String(10), default="Planned", nullable=False)
    allocation: Mapped[str] = mapped_column(String(10), default="PT", nullable=False)
    is_productive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    classification_source: Mapped[str] = mapped_column(String(20), default="keyword", nullable=False)
    npt_code_id: Mapped[str | None] = mapped_column(ForeignKey("ops_npt_codes.id", ondelete="SET NULL"), nullable=True)
    npt_code_snapshot: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    agency_id: Mapped[str | None] = mapped_column(ForeignKey("ops_agencies.id", ondelete="SET NULL"), nullable=True)
    cause_code: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    hole_section_id: Mapped[str | None] = mapped_column(ForeignKey("hole_sections.id", ondelete="SET NULL"), nullable=True)
    phase_id: Mapped[str | None] = mapped_column(ForeignKey("phases.id", ondelete="SET NULL"), nullable=True)
    depth_from_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    depth_to_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    depth_unit: Mapped[str] = mapped_column(String(5), default="m", nullable=False)
    footage_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    bit_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    rotating_hours: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    rop_m_per_hr: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    rop_basis: Mapped[str] = mapped_column(String(20), default="rotating", nullable=False)
    responsible_party: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    vendor_id: Mapped[str | None] = mapped_column(ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    narrative: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_page: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_bbox: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.50"), nullable=False)
    review_state: Mapped[str] = mapped_column(String(20), default="suggested", nullable=False)
    reviewer_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class OpsUnaccountedTime(Base):
    __tablename__ = "ops_unaccounted_time"
    __table_args__ = (
        Index("ix_ops_unaccounted_org_report", "organization_id", "report_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("ops_daily_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    from_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    to_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="computed", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class OpsDailyMetric(Base):
    __tablename__ = "ops_daily_metrics"
    __table_args__ = (
        UniqueConstraint("organization_id", "well_id", "scope", "report_date", name="uq_ops_metrics_org_well_scope_date"),
        Index("ix_ops_metrics_org_well_date", "organization_id", "well_id", "report_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True)
    rig_id: Mapped[str | None] = mapped_column(ForeignKey("rigs.id", ondelete="RESTRICT"), nullable=True)
    scope: Mapped[str] = mapped_column(String(20), default="drilling", nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    day_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logged_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    planned_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    upa_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    npt_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pt_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sp_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    productive_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unaccounted_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    depth_end_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    footage_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    rop_m_per_hr: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    cum_days_from_spud: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    cum_footage_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    plan_cum_days_at_depth: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    lag_days: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    lag_basis: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    npt_block_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), nullable=False)
    review_state: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


# ---------------------------------------------------------------------------
# Plan / Timeline
# ---------------------------------------------------------------------------
class OpsPlanVersion(Base):
    __tablename__ = "ops_plan_versions"
    __table_args__ = (
        Index("ix_ops_plan_versions_org_well_scope", "organization_id", "well_id", "scope"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), default="drilling", nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    label: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    basis: Mapped[str] = mapped_column(String(20), default="engineer", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_days: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    prepared_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    approved_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class OpsPlanItem(Base):
    __tablename__ = "ops_plan_items"
    __table_args__ = (
        Index("ix_ops_plan_items_org_plan", "organization_id", "plan_version_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_version_id: Mapped[str] = mapped_column(ForeignKey("ops_plan_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    hole_section_id: Mapped[str | None] = mapped_column(ForeignKey("hole_sections.id", ondelete="SET NULL"), nullable=True)
    phase_id: Mapped[str | None] = mapped_column(ForeignKey("phases.id", ondelete="SET NULL"), nullable=True)
    operation_code_id: Mapped[str | None] = mapped_column(ForeignKey("ops_operation_codes.id", ondelete="SET NULL"), nullable=True)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    target_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    delta_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    planned_hours: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cum_planned_days: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    hours_source: Mapped[str] = mapped_column(String(20), default="rate", nullable=False)
    rate_basis: Mapped[str] = mapped_column(String(20), default="rop", nullable=False)
    rop_assumption_m_per_hr: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    trip_speed_m_per_hr: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    contingency_hours: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    is_critical_path: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


# ---------------------------------------------------------------------------
# Surveys
# ---------------------------------------------------------------------------
class OpsSurvey(Base):
    __tablename__ = "ops_surveys"
    __table_args__ = (
        Index("ix_ops_surveys_org_well", "organization_id", "well_id"),
        Index("ix_ops_surveys_org_report", "organization_id", "report_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), default="drilling", nullable=False)
    report_id: Mapped[str | None] = mapped_column(ForeignKey("ops_daily_reports.id", ondelete="SET NULL"), nullable=True)
    station_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    md_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    inc_deg: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    azi_deg: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    tvd_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    ns_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    ew_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    vsec_m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    dls_deg_per_30m: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    tool: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.50"), nullable=False)
    survey_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
