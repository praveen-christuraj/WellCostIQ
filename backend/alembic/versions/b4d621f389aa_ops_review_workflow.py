"""Operations-only review metadata, document types and independently assignable grants."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "b4d621f389aa"
down_revision = "830ae530918e"
branch_labels = depends_on = None
KEYS = ("ops-dashboard:read", "ops-doc:export", "ops-plan:import", "ops-plan:restore", "ops-master:restore")


CONFIDENCES = {
    "ops_settings": ("classification_confidence_high", "classification_confidence_low"),
    "ops_activity_blocks": ("confidence",),
    "ops_daily_metrics": ("avg_confidence",),
    "ops_surveys": ("confidence",),
    "ops_extraction_jobs": ("confidence",),
}


def resize_confidence(old, new):
    # All six are leaf-table measurements. Match the shared 10-decimal contract.
    for table, columns in CONFIDENCES.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.alter_column(column, existing_type=old, type_=new, existing_nullable=False)


def upgrade():
    for table, prefix in [("ops_phase_codes", "phase"), ("ops_mark_rules", "mark")]:
        op.create_table(
            table,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(f"{prefix}_code", sa.String(20), nullable=False),
            sa.Column(f"{prefix}_name", sa.String(150), nullable=False),
            sa.Column("description", sa.String(500), nullable=False),
            sa.Column("sort_order", sa.Integer, nullable=False),
            sa.Column("is_active", sa.Boolean, nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            *(
                [
                    sa.Column("default_classification", sa.String(12), nullable=False),
                    sa.Column("default_allocation", sa.String(8), nullable=False),
                ]
                if prefix == "mark"
                else []
            ),
            sa.UniqueConstraint("organization_id", f"{prefix}_code", name=f"uq_ops_{prefix}_code"),
        )
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])

    op.create_table(
        "ops_document_types",
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("code", sa.String(20), primary_key=True),
        sa.Column("sort_order", sa.Integer, nullable=False),
    )
    # Nullable inline FK works on both SQLite and PostgreSQL without rebuilding the populated report table.
    resize_confidence(sa.Numeric(5, 2), sa.Numeric(28, 10))
    op.execute(
        "ALTER TABLE ops_daily_reports ADD COLUMN baseline_plan_id VARCHAR(36) REFERENCES ops_plan_versions(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE ops_daily_reports ADD COLUMN completed_plan_item_id VARCHAR(36) REFERENCES ops_plan_items(id) ON DELETE SET NULL"
    )
    op.add_column(
        "ops_activity_blocks",
        sa.Column("classification_evidence", sa.String(500), nullable=False, server_default=""),
    )
    with op.batch_alter_table("ops_extraction_jobs") as b:
        b.add_column(sa.Column("report_id", sa.String(36)))
        b.create_foreign_key("fk_ops_job_report", "ops_daily_reports", ["report_id"], ["id"], ondelete="SET NULL")
        b.create_index("ix_ops_extraction_jobs_report_id", ["report_id"])
    # Preserve a pre-upgrade draft's job/source association without guessing at a
    # programme version or inferring a relationship merely from a well and date.
    op.execute("""UPDATE ops_extraction_jobs SET report_id=(
        SELECT r.id FROM ops_daily_reports r WHERE r.organization_id=ops_extraction_jobs.organization_id
        AND r.current_extraction_id=ops_extraction_jobs.id
        ORDER BY r.created_at DESC, r.id LIMIT 1)""")
    bind = op.get_bind()
    for org in bind.execute(sa.text("SELECT id FROM organizations")).scalars():
        for key in KEYS:
            params = {"org": org, "key": key, "id": str(uuid4()), "now": datetime.now(UTC)}
            existing = bind.execute(
                sa.text("SELECT id FROM permissions WHERE organization_id=:org AND key=:key"), params
            ).scalar()
            if existing:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO permissions (id,organization_id,key,description,created_at) VALUES (:id,:org,:key,:key,:now)"
                ),
                params,
            )
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id,permission_id) SELECT id,:id FROM roles WHERE organization_id=:org AND is_owner=true"
                ),
                params,
            )


def downgrade():
    keys = sa.bindparam("keys", expanding=True, value=KEYS)
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key IN :keys)"
        ).bindparams(keys)
    )
    op.execute(sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(keys))
    with op.batch_alter_table("ops_extraction_jobs") as b:
        b.drop_index("ix_ops_extraction_jobs_report_id")
        b.drop_constraint("fk_ops_job_report", type_="foreignkey")
        b.drop_column("report_id")
    resize_confidence(sa.Numeric(28, 10), sa.Numeric(5, 2))
    op.drop_column("ops_daily_reports", "baseline_plan_id")
    op.drop_column("ops_daily_reports", "completed_plan_item_id")
    op.drop_column("ops_activity_blocks", "classification_evidence")
    op.drop_table("ops_document_types")
    op.drop_table("ops_mark_rules")
    op.drop_table("ops_phase_codes")
