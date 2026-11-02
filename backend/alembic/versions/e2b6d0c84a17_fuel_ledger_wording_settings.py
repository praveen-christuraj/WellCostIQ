"""Fuel ledger wording settings — the register's fuel is data, not a constant.

Creates ``fuel_ledger_settings`` (one row per workspace): an optional link to a
Master Data fuel plus two label overrides. The Fuel Cost Register printed every
heading with a fuel name written into the code; from here the wording is read
from the workspace's own fuel list, so a site counting Diesel or a bio-blend
says so without a deployment. No row exists until a workspace says something,
and the resolver falls back to its single configured fuel and then to the
generic word "Fuel".

Revision ID: e2b6d0c84a17
Revises: c4e8b7a20d51
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e2b6d0c84a17"
down_revision: Union[str, None] = "c4e8b7a20d51"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fuel_ledger_settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("fuel_type_id", sa.String(length=36), nullable=True),
        sa.Column("fuel_label", sa.String(length=40), server_default="", nullable=False),
        sa.Column("saving_label", sa.String(length=40), server_default="", nullable=False),
        sa.Column("remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column("created_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fuel_type_id"], ["fuel_types.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_fuel_ledger_settings_org"),
    )
    op.create_index(
        "ix_fuel_ledger_settings_organization_id", "fuel_ledger_settings", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_fuel_ledger_settings_organization_id", table_name="fuel_ledger_settings")
    op.drop_table("fuel_ledger_settings")
