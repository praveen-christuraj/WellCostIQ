"""Remarks on the fuel list, so a user-managed fuel matches every other consumable.

Fuel used to be a fixed list written in code, so ``fuel_types`` never needed the
free-text notes column the tangibles, drill bits, mud chemicals and cement
additives each carry. Now that the workspace creates its own fuels — and the
shared import sheet has a remarks column for every register — the fuel list is
brought in line with them.

Revision ID: f1d7a4c95b23
Revises: e2b6d0c84a17
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f1d7a4c95b23"
down_revision: Union[str, None] = "e2b6d0c84a17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("fuel_types") as batch:
        batch.add_column(
            sa.Column("remarks", sa.String(500), nullable=False, server_default="", default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("fuel_types") as batch:
        batch.drop_column("remarks")
