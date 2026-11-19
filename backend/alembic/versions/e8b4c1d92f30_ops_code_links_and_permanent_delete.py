"""Multi-criteria operations code links, RESTRICT correlation FKs, and permanent-delete grants.

Additive, column-wise schema migration (no JSON columns):
- Extends ``ops_code_correlations`` with companion multi-criteria fields
  (``target_mark_rule_id``, ``scope``, ``target_classification``, ``target_allocation``,
  ``extra_criteria_summary``) and converts target FKs on PostgreSQL from CASCADE to
  RESTRICT so correlated codes can never be silently deleted.
- Creates ``ops_code_links`` for typed multi-criteria relationships among workspace
  codes across Phase, Operation, Activity, NPT, Cause, Agency, and Source Mark.
- Grants ``ops-master:permanent-delete``, ``template:restore``, and
  ``template:permanent-delete`` to every workspace's Owner role.
"""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "e8b4c1d92f30"
down_revision = "a7c3e91d5b64"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("ops-master:permanent-delete", "Permanently remove deleted operations codes and correlations"),
    ("template:restore", "Restore deleted reusable templates"),
    ("template:permanent-delete", "Permanently remove deleted reusable templates"),
)

CORRELATION_COLUMNS = (
    sa.Column("target_mark_rule_id", sa.String(36), nullable=True),
    sa.Column("scope", sa.String(20), nullable=False, server_default=""),
    sa.Column("target_classification", sa.String(12), nullable=False, server_default=""),
    sa.Column("target_allocation", sa.String(8), nullable=False, server_default=""),
    sa.Column("extra_criteria_summary", sa.String(300), nullable=False, server_default=""),
)

CORRELATION_FKS = (
    ("fk_ops_corr_operation", "ops_operation_codes", "target_operation_code_id"),
    ("fk_ops_corr_activity", "ops_activity_codes", "target_activity_code_id"),
    ("fk_ops_corr_npt", "ops_npt_codes", "target_npt_code_id"),
    ("fk_ops_corr_cause", "ops_causes", "target_cause_id"),
    ("fk_ops_corr_phase", "ops_phase_codes", "target_phase_code_id"),
    ("fk_ops_corr_agency", "ops_agencies", "target_agency_id"),
)

LINK_FKS = (
    ("fk_ops_link_phase", "ops_phase_codes", "phase_code_id"),
    ("fk_ops_link_operation", "ops_operation_codes", "operation_code_id"),
    ("fk_ops_link_activity", "ops_activity_codes", "activity_code_id"),
    ("fk_ops_link_npt", "ops_npt_codes", "npt_code_id"),
    ("fk_ops_link_cause", "ops_causes", "cause_id"),
    ("fk_ops_link_agency", "ops_agencies", "agency_id"),
    ("fk_ops_link_mark", "ops_mark_rules", "mark_rule_id"),
)


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    for column in CORRELATION_COLUMNS:
        op.add_column("ops_code_correlations", column)

    if is_pg:
        with op.batch_alter_table("ops_code_correlations") as batch:
            for fk_name, ref_table, col_name in CORRELATION_FKS:
                batch.drop_constraint(fk_name, type_="foreignkey")
                batch.create_foreign_key(fk_name, ref_table, [col_name], ["id"], ondelete="RESTRICT")
            batch.create_foreign_key(
                "fk_ops_corr_mark", "ops_mark_rules", ["target_mark_rule_id"], ["id"], ondelete="RESTRICT"
            )

    op.create_table(
        "ops_code_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("rule_signature", sa.String(320), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False, server_default=""),
        sa.Column("default_classification", sa.String(12), nullable=False, server_default=""),
        sa.Column("default_allocation", sa.String(8), nullable=False, server_default=""),
        sa.Column("phase_code_id", sa.String(36), nullable=True),
        sa.Column("operation_code_id", sa.String(36), nullable=True),
        sa.Column("activity_code_id", sa.String(36), nullable=True),
        sa.Column("npt_code_id", sa.String(36), nullable=True),
        sa.Column("cause_id", sa.String(36), nullable=True),
        sa.Column("agency_id", sa.String(36), nullable=True),
        sa.Column("mark_rule_id", sa.String(36), nullable=True),
        sa.Column("criteria_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("summary_label", sa.String(400), nullable=False, server_default=""),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(255), nullable=False, server_default=""),
        sa.UniqueConstraint("organization_id", "rule_signature", name="uq_ops_code_links_org_signature"),
    )
    op.create_index("ix_ops_code_links_organization_id", "ops_code_links", ["organization_id"])
    op.create_index("ix_ops_code_links_org_deleted", "ops_code_links", ["organization_id", "is_deleted"])

    if is_pg:
        with op.batch_alter_table("ops_code_links") as batch:
            for fk_name, ref_table, col_name in LINK_FKS:
                batch.create_foreign_key(fk_name, ref_table, [col_name], ["id"], ondelete="RESTRICT")

    for org in bind.execute(sa.text("SELECT id FROM organizations")).scalars():
        for key, description in PERMISSIONS:
            params = {
                "org": org,
                "key": key,
                "description": description,
                "id": str(uuid4()),
                "now": datetime.now(UTC),
            }
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
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    for key, _description in PERMISSIONS:
        bind.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE permission_id IN"
                " (SELECT id FROM permissions WHERE key=:key)"
            ),
            {"key": key},
        )
        bind.execute(sa.text("DELETE FROM permissions WHERE key=:key"), {"key": key})

    op.drop_index("ix_ops_code_links_org_deleted", table_name="ops_code_links")
    op.drop_index("ix_ops_code_links_organization_id", table_name="ops_code_links")
    op.drop_table("ops_code_links")

    if is_pg:
        with op.batch_alter_table("ops_code_correlations") as batch:
            batch.drop_constraint("fk_ops_corr_mark", type_="foreignkey")
            for fk_name, ref_table, col_name in CORRELATION_FKS:
                batch.drop_constraint(fk_name, type_="foreignkey")
                batch.create_foreign_key(fk_name, ref_table, [col_name], ["id"], ondelete="CASCADE")

    for col_name in (
        "extra_criteria_summary",
        "target_allocation",
        "target_classification",
        "scope",
        "target_mark_rule_id",
    ):
        with op.batch_alter_table("ops_code_correlations") as batch:
            batch.drop_column(col_name)
