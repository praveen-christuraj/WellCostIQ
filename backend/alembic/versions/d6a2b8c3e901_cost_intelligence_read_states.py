"""Personal Cost Intelligence finding read states.

Revision ID: d6a2b8c3e901
Revises: c4e8a1d7f392
"""
from alembic import op
import sqlalchemy as sa

revision = "d6a2b8c3e901"
down_revision = "c4e8a1d7f392"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cost_intelligence_read_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", "finding_id", name="uq_ci_read_state_user_finding"),
    )
    op.create_index("ix_cost_intelligence_read_states_organization_id", "cost_intelligence_read_states", ["organization_id"])


def downgrade():
    op.drop_index("ix_cost_intelligence_read_states_organization_id", table_name="cost_intelligence_read_states")
    op.drop_table("cost_intelligence_read_states")
