"""Add entry checks for daily cost sheets: reviews and workspace item profiles.

The entry checks compare a daily cost sheet with the other sheets of its AFE
and point out values that look mistyped. They are computed on demand from the
cost ledger, so this revision changes no existing table and moves no data. It
adds the two small typed tables the checks keep:

* ``daily_cost_check_reviews`` -- a user kept the value behind one finding as
  entered. One row per finding of a sheet, removed with the sheet.
* ``daily_cost_item_profiles`` -- what one item usually carries across a
  workspace's recent sheets. A summary of the ledger, rebuilt from it whenever
  it is stale; an empty table only means a new well is judged a little later.

No permission is added: reading the checks uses ``daily-cost:read`` and
reviewing them uses ``daily-cost:update``.

Revision ID: b7d3e9f25a41
Revises: a2c5d8f14b30
Create Date: 2026-11-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d3e9f25a41"  # pragma: allowlist secret - Alembic revision ID, not a credential.
down_revision: Union[str, None] = "a2c5d8f14b30"  # pragma: allowlist secret - Parent revision ID.
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_cost_check_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("entry_id", sa.String(36), sa.ForeignKey("daily_cost_entries.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("check_key", sa.String(240), nullable=False),
        sa.Column("check_code", sa.String(40), nullable=False),
        sa.Column("fingerprint", sa.String(80), nullable=False),
        sa.Column("subject_label", sa.String(255), nullable=False, server_default=""),
        sa.Column("value_label", sa.String(120), nullable=False, server_default=""),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("reviewed_by", sa.String(255), nullable=False, server_default=""),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entry_id", "check_key", name="uq_daily_cost_check_reviews_entry_key"),
    )
    op.create_table(
        "daily_cost_item_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("subject_kind", sa.String(20), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("variant", sa.String(120), nullable=False, server_default=""),
        sa.Column("metric", sa.String(20), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False, server_default=""),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("well_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("median_value", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("spread", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("low_value", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("high_value", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("common_value", sa.Numeric(28, 10), nullable=True),
        sa.Column("last_observed_on", sa.Date(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "subject_kind", "subject_id", "variant", "metric", "unit",
            name="uq_daily_cost_item_profiles_subject",
        ),
    )
    op.create_index(
        "ix_daily_cost_item_profiles_org_subject", "daily_cost_item_profiles", ["organization_id", "subject_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_cost_item_profiles_org_subject", table_name="daily_cost_item_profiles")
    op.drop_table("daily_cost_item_profiles")
    op.drop_table("daily_cost_check_reviews")
