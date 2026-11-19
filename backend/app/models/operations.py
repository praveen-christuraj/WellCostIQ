"""Well Operations module — persistence models.

Isolated from costing: no FK to any afe* or daily_cost* table, and vice versa.
Every business table is organization_id-scoped, soft-deletable and auditable.
"""

from datetime import UTC, date, datetime
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

from app.core.precision import DECIMAL_PLACES
from app.core.database import Base


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


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
    auto_extract_on_upload: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    classification_confidence_high: Mapped[Decimal] = mapped_column(Numeric(28, DECIMAL_PLACES), default=Decimal("0.85"), nullable=False)
    classification_confidence_low: Mapped[Decimal] = mapped_column(Numeric(28, DECIMAL_PLACES), default=Decimal("0.60"), nullable=False)
    require_operations: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
class OpsOperation(Base):
    """Downtime / non-productive operation, configured in the Code Library.

    Replaces the former NPT code list: one *Operations* list describes the work
    that was not part of the programme. It is required only when the block's
    Activity type is NPT or UPA, which is why the old ``requires_npt_code`` flag
    and NPT-only pairing rules are gone with the NPT code family.
    """

    __tablename__ = "ops_operations"
    __table_args__ = (
        UniqueConstraint("organization_id", "operation_code", name="uq_ops_operations_org_code"),
        Index("ix_ops_operations_org_deleted", "organization_id", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_code: Mapped[str] = mapped_column(String(50), nullable=False)
    operation_name: Mapped[str] = mapped_column(String(150), nullable=False)
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
class OpsCodeRecord(Base):
    __abstract__ = True
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class OpsSubPhase(OpsCodeRecord):
    """Sub-phase of a Master Data Phase, configured in the Code Library.

    The Phase itself is a Master Data register; the sub-phase narrows it. A
    sub-phase belongs to one phase, so the daily report offers only the
    sub-phases of the phase the engineer selected.
    """

    __tablename__ = "ops_sub_phases"
    __table_args__ = (
        UniqueConstraint("organization_id", "phase_id", "sub_phase_code", name="uq_ops_sub_phase_code"),
    )
    phase_id: Mapped[str] = mapped_column(
        ForeignKey("phases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    phase_code_snapshot: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    phase_name_snapshot: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    sub_phase_code: Mapped[str] = mapped_column(String(50), nullable=False)
    sub_phase_name: Mapped[str] = mapped_column(String(150), nullable=False)


class OpsCodeCorrelation(Base):
    """Map one printed code from the reference catalogue to this workspace's criteria.

    A correlation is a *pre-selection*, never a saved value: extraction writes the
    correlated criteria onto the block as suggestions the engineer still has to
    accept. One printed token may only map once per workspace *and* family, so a
    summary can never claim an operation is an activity.

    ``kind`` names the criterion the printed token belongs to: ``operation``
    (the Code Library Operations list), ``cause``, ``sub-phase``,
    ``responsible-party``, or ``agency``. Hole Section, Phase and Activity are
    Master Data registers, so they are carried as companion criteria only.
    """

    __tablename__ = "ops_code_correlations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "kind", "source_code", name="uq_ops_correlation_org_kind_source"
        ),
        Index("ix_ops_code_correlations_org_deleted", "organization_id", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 'operation' | 'cause' | 'sub-phase' | 'responsible-party' | 'agency'
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_family: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    source_code: Mapped[str] = mapped_column(String(100), nullable=False)
    source_label: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    # Primary target is set according to ``kind``; the companion columns let one
    # correlation pre-select every other criterion in the same pass.
    # All foreign keys use RESTRICT so a correlated record can never be silently deleted.
    target_operation_id: Mapped[str | None] = mapped_column(
        ForeignKey("ops_operations.id", ondelete="RESTRICT"), nullable=True
    )
    target_cause_id: Mapped[str | None] = mapped_column(
        ForeignKey("ops_causes.id", ondelete="RESTRICT"), nullable=True
    )
    target_sub_phase_id: Mapped[str | None] = mapped_column(
        ForeignKey("ops_sub_phases.id", ondelete="RESTRICT"), nullable=True
    )
    target_responsible_agency_id: Mapped[str | None] = mapped_column(
        ForeignKey("ops_agencies.id", ondelete="RESTRICT"), nullable=True
    )
    target_vendor_id: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=True
    )
    target_hole_section_id: Mapped[str | None] = mapped_column(
        ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=True
    )
    target_phase_id: Mapped[str | None] = mapped_column(
        ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True
    )
    target_activity_id: Mapped[str | None] = mapped_column(
        ForeignKey("activities.id", ondelete="RESTRICT"), nullable=True
    )
    target_mark_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("ops_mark_rules.id", ondelete="RESTRICT"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(20), default="", server_default="", nullable=False)
    target_allocation: Mapped[str] = mapped_column(String(8), default="", server_default="", nullable=False)
    target_label: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    extra_criteria_summary: Mapped[str] = mapped_column(String(300), default="", server_default="", nullable=False)
    note: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    @property
    def target_id(self) -> str | None:
        col = {
            "operation": "target_operation_id",
            "cause": "target_cause_id",
            "sub-phase": "target_sub_phase_id",
            "agency": "target_vendor_id",
            "responsible-party": "target_responsible_agency_id",
            "mark": "target_mark_rule_id",
        }.get(self.kind or "")
        return getattr(self, col, None) if col else None


class OpsCodeLink(Base):
    """Multi-criteria relationship between two or more workspace records.

    Stores typed, column-wise links across the Master Data registers (Hole
    Section, Phase, Activity) and the Code Library lists (Operations, Sub-phase,
    Cause, Responsible agency, Agency/service vendor, Source mark), plus Scope
    and Allocation. One rule can carry as many criteria as the user needs, which
    is what lets ``DRLSUR`` say "this hole section, this phase, this sub-phase,
    this activity, this operation, this cause and this vendor" in a single row.
    Links feed the schematic tree, extraction co-selection and the report
    block review hints, and guard deletion: a linked record cannot be deleted
    until the rule that references it is removed.
    """

    __tablename__ = "ops_code_links"
    __table_args__ = (
        UniqueConstraint("organization_id", "rule_signature", name="uq_ops_code_links_org_signature"),
        Index("ix_ops_code_links_org_deleted", "organization_id", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_name: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)
    rule_signature: Mapped[str] = mapped_column(String(320), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), default="", server_default="", nullable=False)
    default_allocation: Mapped[str] = mapped_column(String(8), default="", server_default="", nullable=False)
    hole_section_id: Mapped[str | None] = mapped_column(
        ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=True
    )
    phase_id: Mapped[str | None] = mapped_column(
        ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True
    )
    sub_phase_id: Mapped[str | None] = mapped_column(
        ForeignKey("ops_sub_phases.id", ondelete="RESTRICT"), nullable=True
    )
    activity_id: Mapped[str | None] = mapped_column(
        ForeignKey("activities.id", ondelete="RESTRICT"), nullable=True
    )
    operation_id: Mapped[str | None] = mapped_column(
        ForeignKey("ops_operations.id", ondelete="RESTRICT"), nullable=True
    )
    cause_id: Mapped[str | None] = mapped_column(
        ForeignKey("ops_causes.id", ondelete="RESTRICT"), nullable=True
    )
    responsible_agency_id: Mapped[str | None] = mapped_column(
        ForeignKey("ops_agencies.id", ondelete="RESTRICT"), nullable=True
    )
    vendor_id: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=True
    )
    mark_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("ops_mark_rules.id", ondelete="RESTRICT"), nullable=True
    )
    criteria_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    summary_label: Mapped[str] = mapped_column(String(400), default="", server_default="", nullable=False)
    note: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)


class OpsMarkRule(OpsCodeRecord):
    __tablename__ = "ops_mark_rules"
    __table_args__ = (UniqueConstraint("organization_id", "mark_code", name="uq_ops_mark_code"),)
    mark_code: Mapped[str] = mapped_column(String(20), nullable=False)
    mark_name: Mapped[str] = mapped_column(String(150), nullable=False)
    default_classification: Mapped[str] = mapped_column(String(12), nullable=False)
    default_allocation: Mapped[str] = mapped_column(String(8), nullable=False)


class OpsDocumentType(Base):
    __tablename__ = "ops_document_types"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class OpsDocument(Base):
    __tablename__ = "ops_documents"
    __table_args__ = (
        Index("ix_ops_documents_org_well", "organization_id", "well_id"),
        Index("ix_ops_documents_org_status", "organization_id", "status"),
        Index("ix_ops_documents_org_deleted", "organization_id", "is_deleted"),
        Index("ix_ops_documents_checksum", "organization_id", "checksum_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    well_id: Mapped[str | None] = mapped_column(
        ForeignKey("wells.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    rig_id: Mapped[str | None] = mapped_column(ForeignKey("rigs.id", ondelete="RESTRICT"), nullable=True)
    scope: Mapped[str] = mapped_column(String(20), default="drilling", nullable=False)
    folder_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    document_type: Mapped[str] = mapped_column(String(20), default="DDR", nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), default="application/pdf", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    storage: Mapped[str] = mapped_column(String(20), default="database", nullable=False)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
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
    report_id: Mapped[str | None] = mapped_column(ForeignKey("ops_daily_reports.id", ondelete="SET NULL"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("ops_documents.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    report_type: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(28, DECIMAL_PLACES), default=Decimal(0), nullable=False)
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
    baseline_plan_id: Mapped[str | None] = mapped_column(ForeignKey("ops_plan_versions.id", ondelete="SET NULL"))
    completed_plan_item_id: Mapped[str | None] = mapped_column(ForeignKey("ops_plan_items.id", ondelete="SET NULL"))
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
    depth_start_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    depth_end_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    depth_unit: Mapped[str] = mapped_column(String(5), default="m", nullable=False)
    tvd_start_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    tvd_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    tvd_source: Mapped[str] = mapped_column(String(40), default="", server_default="", nullable=False)
    bit_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    progress_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    rotating_hours: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    cum_rotating_hours: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    spud_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dfs_days: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    est_days: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    md_auth_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    last_casing_size_in: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    last_casing_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    hole_section_text: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    hole_size_in: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    current_status: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    mud_type: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False)
    mud_weight_ppg: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    mud_viscosity_sec: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    mud_pv_cp: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    mud_yp_lbf: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    bha_summary: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    pob_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    reopen_reason: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
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
    source_activity_code: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False)
    source_operation_code: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False)
    source_cause_code: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    source_mark: Mapped[str] = mapped_column(String(30), default="", server_default="", nullable=False)
    # The engineer-facing criteria, in the order the review dialog lists them:
    # Hole Section -> Phase -> Sub-phase -> Activity -> Allocation -> Cause ->
    # Operations -> Agency / service vendor -> Responsible agency label.
    hole_section_id: Mapped[str | None] = mapped_column(ForeignKey("hole_sections.id", ondelete="SET NULL"), nullable=True)
    phase_id: Mapped[str | None] = mapped_column(ForeignKey("phases.id", ondelete="SET NULL"), nullable=True)
    sub_phase_id: Mapped[str | None] = mapped_column(ForeignKey("ops_sub_phases.id", ondelete="SET NULL"), nullable=True)
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("activities.id", ondelete="SET NULL"), nullable=True)
    # Derivable from ``activity_id``; kept as a column so historical days, totals
    # and filters never change when an activity's type is later corrected.
    classification: Mapped[str] = mapped_column(String(10), default="Planned", nullable=False)
    allocation: Mapped[str] = mapped_column(String(10), default="PT", nullable=False)
    is_productive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Engineer-facing mark: the system's own comparison of the block with the
    # saved baseline, still under review until the engineer confirms it, then
    # editable by hand with a recorded reason.
    # "on" is the honest default: no comparison exists until a baseline does.
    timeline_comparison: Mapped[str] = mapped_column(String(12), default="on", server_default="on", nullable=False)
    timeline_variance_days: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    timeline_planned_days: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    timeline_actual_days: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    timeline_basis: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    timeline_review_state: Mapped[str] = mapped_column(String(20), default="suggested", server_default="suggested", nullable=False)
    timeline_note: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    timeline_reviewed_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    timeline_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    classification_evidence: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    classification_source: Mapped[str] = mapped_column(String(20), default="keyword", nullable=False)
    operation_id: Mapped[str | None] = mapped_column(ForeignKey("ops_operations.id", ondelete="SET NULL"), nullable=True)
    operation_snapshot: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    cause_code: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    # The responsible agency label is this workspace's own Code Library list;
    # ``responsible_party`` keeps its text beside the link, exactly like the
    # vendor link keeps the vendor's name.
    responsible_agency_id: Mapped[str | None] = mapped_column(
        ForeignKey("ops_agencies.id", ondelete="SET NULL"), nullable=True
    )
    depth_from_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    depth_to_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    tvd_from_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    tvd_to_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    depth_unit: Mapped[str] = mapped_column(String(5), default="m", nullable=False)
    footage_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    bit_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    mud_weight_ppg: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    rotating_hours: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    rop_m_per_hr: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    rop_basis: Mapped[str] = mapped_column(String(20), default="rotating", nullable=False)
    responsible_party: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    vendor_id: Mapped[str | None] = mapped_column(ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    narrative: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_page: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_bbox: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(28, DECIMAL_PLACES), default=Decimal("0.50"), nullable=False)
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
    depth_end_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    footage_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    rop_m_per_hr: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    cum_days_from_spud: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    cum_footage_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    plan_cum_days_at_depth: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    lag_days: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    lag_basis: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    npt_block_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_confidence: Mapped[Decimal] = mapped_column(Numeric(28, DECIMAL_PLACES), default=Decimal(0), nullable=False)
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
    planned_days: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    prepared_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    approved_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    reopen_reason: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
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
    operation_id: Mapped[str | None] = mapped_column(ForeignKey("ops_operations.id", ondelete="SET NULL"), nullable=True)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    target_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    delta_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    planned_hours: Mapped[Decimal] = mapped_column(Numeric(28, DECIMAL_PLACES), default=Decimal(0), nullable=False)
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cum_planned_days: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    hours_source: Mapped[str] = mapped_column(String(20), default="rate", nullable=False)
    rate_basis: Mapped[str] = mapped_column(String(20), default="rop", nullable=False)
    rop_assumption_m_per_hr: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    trip_speed_m_per_hr: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    contingency_hours: Mapped[Decimal] = mapped_column(Numeric(28, DECIMAL_PLACES), default=Decimal(0), nullable=False)
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
    md_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    inc_deg: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    azi_deg: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    tvd_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    ns_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    ew_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    vsec_m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    dls_deg_per_30m: Mapped[Decimal | None] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=True)
    tool: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(28, DECIMAL_PLACES), default=Decimal("0.50"), nullable=False)
    survey_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
