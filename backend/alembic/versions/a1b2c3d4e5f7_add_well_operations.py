"""Add Well Operations module — document vault, reports, analytics.

Revision ID: a1b2c3d4e5f7
Revises: f9a2c7d4e611
Create Date: 2026-11-17 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "f9a2c7d4e611"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CAPABILITIES = [
    ("ops-doc", "read"), ("ops-doc", "upload"), ("ops-doc", "update"), ("ops-doc", "delete"), ("ops-doc", "restore"), ("ops-doc", "permanent-delete"), ("ops-doc", "download"), ("ops-doc", "extract"),
    ("ops-report", "read"), ("ops-report", "create"), ("ops-report", "update"), ("ops-report", "delete"), ("ops-report", "restore"), ("ops-report", "permanent-delete"), ("ops-report", "import"), ("ops-report", "export"), ("ops-report", "submit"), ("ops-report", "approve"), ("ops-report", "amend"), ("ops-report", "print"), ("ops-report", "review"),
    ("ops-master", "read"), ("ops-master", "create"), ("ops-master", "update"), ("ops-master", "delete"), ("ops-master", "import"), ("ops-master", "export"),
    ("ops-plan", "read"), ("ops-plan", "create"), ("ops-plan", "update"), ("ops-plan", "delete"), ("ops-plan", "activate"), ("ops-plan", "export"),
    ("ops-analytics", "read"), ("ops-analytics", "export"),
    ("ops-settings", "read"), ("ops-settings", "update"),
]


def _backfill_capabilities():
    conn = op.get_bind()
    # Fetch organizations
    org_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM organizations")).fetchall()]
    for org_id in org_ids:
        for resource, action in CAPABILITIES:
            key = f"{resource}:{action}"
            exists = conn.execute(sa.text("SELECT id FROM permissions WHERE organization_id = :org AND key = :key"), {"org": org_id, "key": key}).first()
            if exists:
                continue
            import uuid as _uuid
            pid = str(_uuid.uuid4())
            from datetime import datetime, timezone as _tz
            now = datetime.now(_tz.utc)
            conn.execute(sa.text("INSERT INTO permissions (id, organization_id, key, description, created_at) VALUES (:id, :org, :key, :desc, :now)"), {"id": pid, "org": org_id, "key": key, "desc": f"{action.title()} {resource}", "now": now})
        # Grant to owner role
        owner = conn.execute(sa.text("SELECT id FROM roles WHERE organization_id = :org AND is_owner = true"), {"org": org_id}).first()
        if owner:
            owner_id = owner[0]
            for resource, action in CAPABILITIES:
                key = f"{resource}:{action}"
                perm = conn.execute(sa.text("SELECT id FROM permissions WHERE organization_id = :org AND key = :key"), {"org": org_id, "key": key}).first()
                if perm:
                    exists_link = conn.execute(sa.text("SELECT 1 FROM role_permissions WHERE role_id = :rid AND permission_id = :pid"), {"rid": owner_id, "pid": perm[0]}).first()
                    if not exists_link:
                        conn.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid)"), {"rid": owner_id, "pid": perm[0]})


def upgrade() -> None:
    # ops_settings
    op.create_table(
        "ops_settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("day_boundary_hour", sa.Integer(), nullable=False),
        sa.Column("operating_timezone", sa.String(length=64), nullable=False),
        sa.Column("tour_pattern", sa.String(length=20), nullable=False),
        sa.Column("require_review_before_submit", sa.Boolean(), nullable=False),
        sa.Column("auto_extract_on_upload", sa.Boolean(), nullable=False),
        sa.Column("classification_confidence_high", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("classification_confidence_low", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("require_npt_code", sa.Boolean(), nullable=False),
        sa.Column("require_npt_agency", sa.Boolean(), nullable=False),
        sa.Column("require_npt_reason", sa.Boolean(), nullable=False),
        sa.Column("max_daily_hours", sa.Integer(), nullable=False),
        sa.Column("completeness_tolerance_minutes", sa.Integer(), nullable=False),
        sa.Column("allow_block_spill", sa.Boolean(), nullable=False),
        sa.Column("default_depth_unit", sa.String(length=5), nullable=False),
        sa.Column("default_rop_basis", sa.String(length=20), nullable=False),
        sa.Column("plan_contingency_hours", sa.Integer(), nullable=False),
        sa.Column("document_max_mb", sa.Integer(), nullable=False),
        sa.Column("retention_years", sa.Integer(), nullable=False),
        sa.Column("extraction_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_ops_settings_org"),
    )
    op.create_index(op.f("ix_ops_settings_organization_id"), "ops_settings", ["organization_id"], unique=False)

    # ops_operation_codes
    op.create_table(
        "ops_operation_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("operation_code", sa.String(length=50), nullable=False),
        sa.Column("operation_name", sa.String(length=150), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("default_classification", sa.String(length=10), nullable=False),
        sa.Column("is_productive_default", sa.Boolean(), nullable=False),
        sa.Column("counts_as_on_bottom", sa.Boolean(), nullable=False),
        sa.Column("requires_npt_code", sa.Boolean(), nullable=False),
        sa.Column("phase_applicable", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "operation_code", name="uq_ops_operation_codes_org_code"),
    )
    op.create_index(op.f("ix_ops_operation_codes_organization_id"), "ops_operation_codes", ["organization_id"], unique=False)
    op.create_index("ix_ops_operation_codes_org_deleted", "ops_operation_codes", ["organization_id", "is_deleted"], unique=False)

    # ops_activity_codes
    op.create_table(
        "ops_activity_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("activity_code", sa.String(length=50), nullable=False),
        sa.Column("activity_name", sa.String(length=150), nullable=False),
        sa.Column("default_allocation", sa.String(length=10), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "activity_code", name="uq_ops_activity_codes_org_code"),
    )
    op.create_index(op.f("ix_ops_activity_codes_organization_id"), "ops_activity_codes", ["organization_id"], unique=False)
    op.create_index("ix_ops_activity_codes_org_deleted", "ops_activity_codes", ["organization_id", "is_deleted"], unique=False)

    # ops_npt_codes
    op.create_table(
        "ops_npt_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("npt_code", sa.String(length=50), nullable=False),
        sa.Column("npt_name", sa.String(length=150), nullable=False),
        sa.Column("family", sa.String(length=30), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("default_responsible_party", sa.String(length=200), nullable=False),
        sa.Column("is_chargeable", sa.Boolean(), nullable=False),
        sa.Column("is_company_caused", sa.Boolean(), nullable=False),
        sa.Column("is_contractor_caused", sa.Boolean(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "npt_code", name="uq_ops_npt_codes_org_code"),
    )
    op.create_index(op.f("ix_ops_npt_codes_organization_id"), "ops_npt_codes", ["organization_id"], unique=False)
    op.create_index("ix_ops_npt_codes_org_deleted", "ops_npt_codes", ["organization_id", "is_deleted"], unique=False)

    # ops_agencies
    op.create_table(
        "ops_agencies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("agency_code", sa.String(length=50), nullable=False),
        sa.Column("agency_name", sa.String(length=150), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "agency_code", name="uq_ops_agencies_org_code"),
    )
    op.create_index(op.f("ix_ops_agencies_organization_id"), "ops_agencies", ["organization_id"], unique=False)
    op.create_index("ix_ops_agencies_org_deleted", "ops_agencies", ["organization_id", "is_deleted"], unique=False)

    # ops_causes
    op.create_table(
        "ops_causes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("cause_code", sa.String(length=50), nullable=False),
        sa.Column("cause_name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "cause_code", name="uq_ops_causes_org_code"),
    )
    op.create_index(op.f("ix_ops_causes_organization_id"), "ops_causes", ["organization_id"], unique=False)
    op.create_index("ix_ops_causes_org_deleted", "ops_causes", ["organization_id", "is_deleted"], unique=False)

    # ops_documents
    op.create_table(
        "ops_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("well_id", sa.String(length=36), nullable=True),
        sa.Column("rig_id", sa.String(length=36), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("folder_id", sa.String(length=36), nullable=True),
        sa.Column("document_type", sa.String(length=20), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage", sa.String(length=20), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("external_ref", sa.String(length=500), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("report_no_text", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("extraction_job_id", sa.String(length=36), nullable=True),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legal_hold", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.String(length=1000), nullable=False),
        sa.Column("well_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("well_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("rig_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("rig_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column("uploaded_by_name", sa.String(length=160), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rig_id"], ["rigs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["well_id"], ["wells.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ops_documents_organization_id"), "ops_documents", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ops_documents_well_id"), "ops_documents", ["well_id"], unique=False)
    op.create_index("ix_ops_documents_org_well", "ops_documents", ["organization_id", "well_id"], unique=False)
    op.create_index("ix_ops_documents_org_status", "ops_documents", ["organization_id", "status"], unique=False)
    op.create_index("ix_ops_documents_org_deleted", "ops_documents", ["organization_id", "is_deleted"], unique=False)
    op.create_index("ix_ops_documents_checksum", "ops_documents", ["organization_id", "checksum_sha256"], unique=False)

    # ops_extraction_jobs
    op.create_table(
        "ops_extraction_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("report_type", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("findings", sa.Text(), nullable=False),
        sa.Column("payload_summary", sa.Text(), nullable=False),
        sa.Column("error_message", sa.String(length=2000), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["ops_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ops_extraction_jobs_organization_id"), "ops_extraction_jobs", ["organization_id"], unique=False)
    op.create_index("ix_ops_extraction_jobs_org_doc", "ops_extraction_jobs", ["organization_id", "document_id"], unique=False)
    op.create_index("ix_ops_extraction_jobs_org_status", "ops_extraction_jobs", ["organization_id", "status"], unique=False)

    # ops_daily_reports
    op.create_table(
        "ops_daily_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("rig_id", sa.String(length=36), nullable=True),
        sa.Column("rig_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("rig_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("well_id", sa.String(length=36), nullable=False),
        sa.Column("well_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("well_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("report_type", sa.String(length=10), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("report_no_text", sa.String(length=50), nullable=False),
        sa.Column("report_no_seq", sa.Integer(), nullable=True),
        sa.Column("day_number", sa.Integer(), nullable=True),
        sa.Column("event_code", sa.String(length=50), nullable=False),
        sa.Column("period_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_minutes", sa.Integer(), nullable=False),
        sa.Column("hole_section_id", sa.String(length=36), nullable=True),
        sa.Column("phase_id", sa.String(length=36), nullable=True),
        sa.Column("depth_start_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("depth_end_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("depth_unit", sa.String(length=5), nullable=False),
        sa.Column("tvd_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("progress_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("rotating_hours", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("dfs_days", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("est_days", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("md_auth_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("last_casing_size_in", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("last_casing_depth_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("customer", sa.String(length=200), nullable=False),
        sa.Column("project", sa.String(length=200), nullable=False),
        sa.Column("site", sa.String(length=200), nullable=False),
        sa.Column("datum", sa.String(length=100), nullable=False),
        sa.Column("supervisor", sa.String(length=200), nullable=False),
        sa.Column("engineer", sa.String(length=200), nullable=False),
        sa.Column("uwi", sa.String(length=100), nullable=False),
        sa.Column("block_text", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("extraction_status", sa.String(length=20), nullable=False),
        sa.Column("current_extraction_id", sa.String(length=36), nullable=True),
        sa.Column("source_document_id", sa.String(length=36), nullable=True),
        sa.Column("operation_summary", sa.Text(), nullable=False),
        sa.Column("forward_plan", sa.Text(), nullable=False),
        sa.Column("hse_summary", sa.Text(), nullable=False),
        sa.Column("remarks", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by", sa.String(length=255), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=False),
        sa.Column("rejection_reason", sa.String(length=500), nullable=False),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
        sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.CheckConstraint("extraction_status IN ('none', 'running', 'needs_review', 'reviewed', 'failed')", name="ck_ops_reports_extraction_status"),
        sa.CheckConstraint("scope IN ('drilling', 'completion')", name="ck_ops_reports_scope"),
        sa.CheckConstraint("status IN ('draft', 'in_review', 'submitted', 'approved', 'rejected')", name="ck_ops_reports_status"),
        sa.ForeignKeyConstraint(["hole_section_id"], ["hole_sections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rig_id"], ["rigs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_document_id"], ["ops_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["well_id"], ["wells.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "well_id", "scope", "report_date", name="uq_ops_reports_org_well_scope_date"),
    )
    op.create_index(op.f("ix_ops_daily_reports_organization_id"), "ops_daily_reports", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ops_daily_reports_rig_id"), "ops_daily_reports", ["rig_id"], unique=False)
    op.create_index(op.f("ix_ops_daily_reports_well_id"), "ops_daily_reports", ["well_id"], unique=False)
    op.create_index("ix_ops_reports_org_deleted", "ops_daily_reports", ["organization_id", "is_deleted"], unique=False)
    op.create_index("ix_ops_reports_org_rig", "ops_daily_reports", ["organization_id", "rig_id"], unique=False)
    op.create_index("ix_ops_reports_org_status", "ops_daily_reports", ["organization_id", "status"], unique=False)
    op.create_index("ix_ops_reports_org_well_date", "ops_daily_reports", ["organization_id", "well_id", "report_date"], unique=False)

    # ops_activity_blocks
    op.create_table(
        "ops_activity_blocks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("phase_raw", sa.String(length=20), nullable=False),
        sa.Column("operation_code_id", sa.String(length=36), nullable=True),
        sa.Column("activity_code_id", sa.String(length=36), nullable=True),
        sa.Column("activity_id", sa.String(length=36), nullable=True),
        sa.Column("classification", sa.String(length=10), nullable=False),
        sa.Column("allocation", sa.String(length=10), nullable=False),
        sa.Column("is_productive", sa.Boolean(), nullable=False),
        sa.Column("classification_source", sa.String(length=20), nullable=False),
        sa.Column("npt_code_id", sa.String(length=36), nullable=True),
        sa.Column("npt_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("agency_id", sa.String(length=36), nullable=True),
        sa.Column("cause_code", sa.String(length=50), nullable=False),
        sa.Column("hole_section_id", sa.String(length=36), nullable=True),
        sa.Column("phase_id", sa.String(length=36), nullable=True),
        sa.Column("depth_from_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("depth_to_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("depth_unit", sa.String(length=5), nullable=False),
        sa.Column("footage_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("bit_depth_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("rotating_hours", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("rop_m_per_hr", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("rop_basis", sa.String(length=20), nullable=False),
        sa.Column("responsible_party", sa.String(length=200), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("source_bbox", sa.String(length=200), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("review_state", sa.String(length=20), nullable=False),
        sa.Column("reviewer_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("allocation IN ('PT', 'NPT', 'UPA', 'SP')", name="ck_ops_blocks_allocation"),
        sa.CheckConstraint("classification IN ('Planned', 'UPA', 'NPT')", name="ck_ops_blocks_classification"),
        sa.CheckConstraint("NOT (classification = 'NPT' AND is_productive = true)", name="ck_ops_blocks_npt_productive"),
        sa.CheckConstraint("review_state IN ('suggested', 'accepted', 'edited', 'rejected')", name="ck_ops_blocks_review_state"),
        sa.ForeignKeyConstraint(["activity_code_id"], ["ops_activity_codes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agency_id"], ["ops_agencies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["hole_section_id"], ["hole_sections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["npt_code_id"], ["ops_npt_codes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["operation_code_id"], ["ops_operation_codes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["report_id"], ["ops_daily_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ops_activity_blocks_organization_id"), "ops_activity_blocks", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ops_activity_blocks_report_id"), "ops_activity_blocks", ["report_id"], unique=False)
    op.create_index("ix_ops_blocks_org_classification", "ops_activity_blocks", ["organization_id", "classification"], unique=False)
    op.create_index("ix_ops_blocks_org_report", "ops_activity_blocks", ["organization_id", "report_id"], unique=False)
    op.create_index("ix_ops_blocks_org_report_seq", "ops_activity_blocks", ["organization_id", "report_id", "sequence_no"], unique=False)

    # ops_unaccounted_time
    op.create_table(
        "ops_unaccounted_time",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("from_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["ops_daily_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ops_unaccounted_time_organization_id"), "ops_unaccounted_time", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ops_unaccounted_time_report_id"), "ops_unaccounted_time", ["report_id"], unique=False)
    op.create_index("ix_ops_unaccounted_org_report", "ops_unaccounted_time", ["organization_id", "report_id"], unique=False)

    # ops_daily_metrics
    op.create_table(
        "ops_daily_metrics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("well_id", sa.String(length=36), nullable=False),
        sa.Column("rig_id", sa.String(length=36), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=True),
        sa.Column("logged_minutes", sa.Integer(), nullable=False),
        sa.Column("planned_minutes", sa.Integer(), nullable=False),
        sa.Column("upa_minutes", sa.Integer(), nullable=False),
        sa.Column("npt_minutes", sa.Integer(), nullable=False),
        sa.Column("pt_minutes", sa.Integer(), nullable=False),
        sa.Column("sp_minutes", sa.Integer(), nullable=False),
        sa.Column("productive_minutes", sa.Integer(), nullable=False),
        sa.Column("unaccounted_minutes", sa.Integer(), nullable=False),
        sa.Column("depth_end_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("footage_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("rop_m_per_hr", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("cum_days_from_spud", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("cum_footage_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("plan_cum_days_at_depth", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("lag_days", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("lag_basis", sa.String(length=50), nullable=False),
        sa.Column("npt_block_count", sa.Integer(), nullable=False),
        sa.Column("avg_confidence", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("review_state", sa.String(length=20), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rig_id"], ["rigs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["well_id"], ["wells.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "well_id", "scope", "report_date", name="uq_ops_metrics_org_well_scope_date"),
    )
    op.create_index(op.f("ix_ops_daily_metrics_organization_id"), "ops_daily_metrics", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ops_daily_metrics_well_id"), "ops_daily_metrics", ["well_id"], unique=False)
    op.create_index("ix_ops_metrics_org_well_date", "ops_daily_metrics", ["organization_id", "well_id", "report_date"], unique=False)

    # ops_plan_versions
    op.create_table(
        "ops_plan_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("well_id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("basis", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_days", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("prepared_by", sa.String(length=255), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["well_id"], ["wells.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ops_plan_versions_organization_id"), "ops_plan_versions", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ops_plan_versions_well_id"), "ops_plan_versions", ["well_id"], unique=False)
    op.create_index("ix_ops_plan_versions_org_well_scope", "ops_plan_versions", ["organization_id", "well_id", "scope"], unique=False)

    # ops_plan_items
    op.create_table(
        "ops_plan_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("plan_version_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("hole_section_id", sa.String(length=36), nullable=True),
        sa.Column("phase_id", sa.String(length=36), nullable=True),
        sa.Column("operation_code_id", sa.String(length=36), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("target_depth_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("delta_depth_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("planned_hours", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cum_planned_days", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("hours_source", sa.String(length=20), nullable=False),
        sa.Column("rate_basis", sa.String(length=20), nullable=False),
        sa.Column("rop_assumption_m_per_hr", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("trip_speed_m_per_hr", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("contingency_hours", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("is_critical_path", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["hole_section_id"], ["hole_sections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["operation_code_id"], ["ops_operation_codes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plan_version_id"], ["ops_plan_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ops_plan_items_organization_id"), "ops_plan_items", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ops_plan_items_plan_version_id"), "ops_plan_items", ["plan_version_id"], unique=False)
    op.create_index("ix_ops_plan_items_org_plan", "ops_plan_items", ["organization_id", "plan_version_id"], unique=False)

    # ops_surveys
    op.create_table(
        "ops_surveys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("well_id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=True),
        sa.Column("station_no", sa.Integer(), nullable=True),
        sa.Column("md_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("inc_deg", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("azi_deg", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("tvd_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("ns_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("ew_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("vsec_m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("dls_deg_per_30m", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("tool", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("survey_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["ops_daily_reports.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["well_id"], ["wells.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ops_surveys_organization_id"), "ops_surveys", ["organization_id"], unique=False)
    op.create_index(op.f("ix_ops_surveys_well_id"), "ops_surveys", ["well_id"], unique=False)
    op.create_index("ix_ops_surveys_org_report", "ops_surveys", ["organization_id", "report_id"], unique=False)
    op.create_index("ix_ops_surveys_org_well", "ops_surveys", ["organization_id", "well_id"], unique=False)

    _backfill_capabilities()


def downgrade() -> None:
    # Drop in reverse FK order
    op.drop_table("ops_surveys")
    op.drop_table("ops_plan_items")
    op.drop_table("ops_plan_versions")
    op.drop_table("ops_daily_metrics")
    op.drop_table("ops_unaccounted_time")
    op.drop_table("ops_activity_blocks")
    op.drop_table("ops_daily_reports")
    op.drop_table("ops_extraction_jobs")
    op.drop_table("ops_documents")
    op.drop_table("ops_causes")
    op.drop_table("ops_agencies")
    op.drop_table("ops_npt_codes")
    op.drop_table("ops_activity_codes")
    op.drop_table("ops_operation_codes")
    op.drop_table("ops_settings")

    # Remove permissions
    conn = op.get_bind()
    for resource, action in CAPABILITIES:
        key = f"{resource}:{action}"
        conn.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key = :key)"), {"key": key})
        conn.execute(sa.text("DELETE FROM permissions WHERE key = :key"), {"key": key})
