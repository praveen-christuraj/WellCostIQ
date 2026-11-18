"""Operations code correlations and engineer-reviewed timeline comparison.

Additive only: a new correlation table plus per-block comparison columns, and two
grants for owners. No existing row is rewritten, no code is seeded and no saved
report value changes.
"""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "a7c3e91d5b64"
down_revision = "d4f7a2c81e90"
branch_labels = None
depends_on = None

NUM3 = sa.Numeric(28, 3)
PERMISSIONS = (
    ("ops-master:correlate", "Correlate printed default codes with workspace codes"),
    ("ops-plan:permanent-delete", "Permanently remove a deleted timeline"),
)

BLOCK_COLUMNS = (
    sa.Column("timeline_comparison", sa.String(12), nullable=False, server_default="on"),
    sa.Column("timeline_variance_days", NUM3, nullable=True),
    sa.Column("timeline_planned_days", NUM3, nullable=True),
    sa.Column("timeline_actual_days", NUM3, nullable=True),
    sa.Column("timeline_basis", sa.String(50), nullable=False, server_default=""),
    sa.Column("timeline_review_state", sa.String(20), nullable=False, server_default="suggested"),
    sa.Column("timeline_note", sa.String(500), nullable=False, server_default=""),
    sa.Column("timeline_reviewed_by", sa.String(255), nullable=False, server_default=""),
    sa.Column("timeline_reviewed_at", sa.DateTime(timezone=True), nullable=True),
)


def upgrade() -> None:
    op.create_table(
        "ops_code_correlations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("source_family", sa.String(60), nullable=False, server_default=""),
        sa.Column("source_code", sa.String(100), nullable=False),
        sa.Column("source_label", sa.String(200), nullable=False, server_default=""),
        sa.Column("target_operation_code_id", sa.String(36), nullable=True),
        sa.Column("target_activity_code_id", sa.String(36), nullable=True),
        sa.Column("target_npt_code_id", sa.String(36), nullable=True),
        sa.Column("target_cause_id", sa.String(36), nullable=True),
        sa.Column("target_phase_code_id", sa.String(36), nullable=True),
        sa.Column("target_agency_id", sa.String(36), nullable=True),
        sa.Column("target_label", sa.String(200), nullable=False, server_default=""),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(255), nullable=False, server_default=""),
        sa.UniqueConstraint(
            "organization_id", "kind", "source_code", name="uq_ops_correlation_org_kind_source"
        ),
    )
    op.create_index(
        "ix_ops_code_correlations_organization_id", "ops_code_correlations", ["organization_id"]
    )
    op.create_index(
        "ix_ops_code_correlations_org_deleted", "ops_code_correlations", ["organization_id", "is_deleted"]
    )
    # SQLite cannot add a foreign key in place, so the null-safe targets are declared
    # in the table above as plain columns and validated by the service. PostgreSQL
    # gets the real constraints through a batch alter.
    if op.get_bind().dialect.name == "postgresql":
        with op.batch_alter_table("ops_code_correlations") as batch:
            batch.create_foreign_key(
                "fk_ops_corr_operation", "ops_operation_codes", ["target_operation_code_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_foreign_key(
                "fk_ops_corr_activity", "ops_activity_codes", ["target_activity_code_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_foreign_key(
                "fk_ops_corr_npt", "ops_npt_codes", ["target_npt_code_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_foreign_key(
                "fk_ops_corr_cause", "ops_causes", ["target_cause_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_foreign_key(
                "fk_ops_corr_phase", "ops_phase_codes", ["target_phase_code_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_foreign_key(
                "fk_ops_corr_agency", "ops_agencies", ["target_agency_id"], ["id"], ondelete="CASCADE"
            )
    for column in BLOCK_COLUMNS:
        op.add_column("ops_activity_blocks", column)

    bind = op.get_bind()
    for org in bind.execute(sa.text("SELECT id FROM organizations")).scalars():
        for key, description in PERMISSIONS:
            params = {"org": org, "key": key, "description": description, "id": str(uuid4()), "now": datetime.now(UTC)}
            exists = bind.execute(
                sa.text("SELECT id FROM permissions WHERE organization_id=:org AND key=:key"), params
            ).scalar()
            if exists:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO permissions (id,organization_id,key,description,created_at)"
                    " VALUES (:id,:org,:key,:description,:now)"
                ),
                params,
            )
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id,permission_id)"
                    " SELECT id,:id FROM roles WHERE organization_id=:org AND is_owner=true"
                ),
                params,
            )


def downgrade() -> None:
    for column in (
        "timeline_reviewed_at",
        "timeline_reviewed_by",
        "timeline_note",
        "timeline_review_state",
        "timeline_basis",
        "timeline_actual_days",
        "timeline_planned_days",
        "timeline_variance_days",
        "timeline_comparison",
    ):
        with op.batch_alter_table("ops_activity_blocks") as batch:
            batch.drop_column(column)
    bind = op.get_bind()
    for key, _description in PERMISSIONS:
        bind.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE permission_id IN"
                " (SELECT id FROM permissions WHERE key=:key)"
            ),
            {"key": key},
        )
        bind.execute(sa.text("DELETE FROM permissions WHERE key=:key"), {"key": key})
    op.drop_index("ix_ops_code_correlations_org_deleted", table_name="ops_code_correlations")
    op.drop_index("ix_ops_code_correlations_organization_id", table_name="ops_code_correlations")
    op.drop_table("ops_code_correlations")
