"""Operations reopen workflow, expanded MD/TVD/report prefill columns, and WAT timezone default."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "d4f7a2c81e90"
down_revision = "c1d9e5a4f702"
branch_labels = None
depends_on = None

NUM3 = sa.Numeric(28, 3)

PERMISSIONS = (
    ("ops-plan:reopen", "Reopen active or superseded operation timelines to draft"),
    ("ops-report:reopen", "Reopen submitted or approved daily operation reports to draft"),
)

REPORT_COLUMNS = (
    sa.Column("tvd_start_m", NUM3, nullable=True),
    sa.Column("tvd_source", sa.String(40), nullable=False, server_default=""),
    sa.Column("bit_depth_m", NUM3, nullable=True),
    sa.Column("cum_rotating_hours", NUM3, nullable=True),
    sa.Column("spud_date", sa.Date(), nullable=True),
    sa.Column("hole_section_text", sa.String(120), nullable=False, server_default=""),
    sa.Column("hole_size_in", NUM3, nullable=True),
    sa.Column("current_status", sa.String(500), nullable=False, server_default=""),
    sa.Column("mud_type", sa.String(100), nullable=False, server_default=""),
    sa.Column("mud_weight_ppg", NUM3, nullable=True),
    sa.Column("mud_viscosity_sec", NUM3, nullable=True),
    sa.Column("mud_pv_cp", NUM3, nullable=True),
    sa.Column("mud_yp_lbf", NUM3, nullable=True),
    sa.Column("bha_summary", sa.String(500), nullable=False, server_default=""),
    sa.Column("pob_count", sa.Integer(), nullable=True),
    sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("reopened_by", sa.String(255), nullable=False, server_default=""),
    sa.Column("reopen_reason", sa.String(500), nullable=False, server_default=""),
)

BLOCK_COLUMNS = (
    sa.Column("tvd_from_m", NUM3, nullable=True),
    sa.Column("tvd_to_m", NUM3, nullable=True),
    sa.Column("mud_weight_ppg", NUM3, nullable=True),
)

PLAN_COLUMNS = (
    sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("reopened_by", sa.String(255), nullable=False, server_default=""),
    sa.Column("reopen_reason", sa.String(500), nullable=False, server_default=""),
)


def upgrade() -> None:
    for col in REPORT_COLUMNS:
        op.add_column("ops_daily_reports", col)
    for col in BLOCK_COLUMNS:
        op.add_column("ops_activity_blocks", col)
    for col in PLAN_COLUMNS:
        op.add_column("ops_plan_versions", col)

    op.execute(
        sa.text(
            "UPDATE ops_settings SET operating_timezone = 'Africa/Lagos' "
            "WHERE operating_timezone IN ('UTC', 'Etc/UTC', 'GMT')"
        )
    )

    bind = op.get_bind()
    for org in bind.execute(sa.text("SELECT id FROM organizations")).scalars():
        for key, description in PERMISSIONS:
            params = {
                "org": org,
                "key": key,
                "description": description,
                "id": str(uuid4()),
                "now": datetime.now(UTC),
            }
            existing = bind.execute(
                sa.text("SELECT id FROM permissions WHERE organization_id=:org AND key=:key"),
                params,
            ).scalar()
            if existing:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO permissions (id, organization_id, key, description, created_at) "
                    "VALUES (:id, :org, :key, :description, :now)"
                ),
                params,
            )
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT id, :id FROM roles WHERE organization_id=:org AND is_owner=true"
                ),
                params,
            )


def downgrade() -> None:
    keys = sa.bindparam("keys", expanding=True, value=[key for key, _ in PERMISSIONS])
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE key IN :keys)"
        ).bindparams(keys)
    )
    op.execute(sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(keys))

    with op.batch_alter_table("ops_plan_versions") as batch:
        for col in reversed(PLAN_COLUMNS):
            batch.drop_column(col.name)
    with op.batch_alter_table("ops_activity_blocks") as batch:
        for col in reversed(BLOCK_COLUMNS):
            batch.drop_column(col.name)
    with op.batch_alter_table("ops_daily_reports") as batch:
        for col in reversed(REPORT_COLUMNS):
            batch.drop_column(col.name)
