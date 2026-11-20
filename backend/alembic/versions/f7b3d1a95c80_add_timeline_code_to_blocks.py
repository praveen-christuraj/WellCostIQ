"""Add the per-line sequence code that links a daily-report line to a programme activity.

Revision ID: f7b3d1a95c80
Revises: e2f4c9b71a38
Create Date: 2026-11-20 00:00:00.000000

Lead/lag is correlated by sequence code, not by description text. Each line of a
baseline programme already carries ``ops_plan_items.sequence_no``; the daily
report line stores that code in ``ops_activity_blocks.timeline_code`` and the
comparison sums the hours of every line sharing the code.

Existing links are preserved: blocks already tied to a programme row
(``timeline_plan_item_id``) inherit that row's sequence number as their code.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7b3d1a95c80"
down_revision: Union[str, None] = "e2f4c9b71a38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ops_activity_blocks",
        sa.Column("timeline_code", sa.String(20), nullable=True),
    )
    op.create_index(
        "ix_ops_blocks_org_timeline_code",
        "ops_activity_blocks",
        ["organization_id", "timeline_code"],
    )
    op.execute(
        sa.text(
            "UPDATE ops_activity_blocks "
            "SET timeline_code = ("
            "  SELECT CAST(sequence_no AS VARCHAR(20)) FROM ops_plan_items "
            "  WHERE ops_plan_items.id = ops_activity_blocks.timeline_plan_item_id"
            ") "
            "WHERE timeline_plan_item_id IS NOT NULL AND timeline_code IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_ops_blocks_org_timeline_code", table_name="ops_activity_blocks")
    op.drop_column("ops_activity_blocks", "timeline_code")
