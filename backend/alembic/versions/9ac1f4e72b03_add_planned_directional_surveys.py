"""Store planned directional survey stations on plan versions."""

from alembic import op
import sqlalchemy as sa

revision = "9ac1f4e72b03"
down_revision = "f7b3d1a95c80"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ops_plan_versions", sa.Column(
        "survey_shared_reference", sa.Boolean(), server_default=sa.false(), nullable=False,
    ))
    op.create_table(
        "ops_plan_survey_stations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_version_id", sa.String(36), sa.ForeignKey("ops_plan_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("md_m", sa.Numeric(28, 3), nullable=False),
        sa.Column("inc_deg", sa.Numeric(28, 3), nullable=False),
        *(sa.Column(name, sa.Numeric(28, 3)) for name in (
            "azi_deg", "tvd_m", "ns_m", "ew_m", "vsec_m", "dls_deg_per_30m",
        )),
        sa.Column("tool", sa.String(100), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("source_file", sa.String(255), nullable=False),
        sa.Column("source_sheet", sa.String(100), nullable=False),
        sa.Column("survey_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("plan_version_id", "md_m", name="uq_ops_plan_survey_md"),
    )
    op.create_index("ix_ops_plan_survey_org_plan", "ops_plan_survey_stations", ["organization_id", "plan_version_id"])


def downgrade() -> None:
    op.drop_table("ops_plan_survey_stations")
    op.drop_column("ops_plan_versions", "survey_shared_reference")
