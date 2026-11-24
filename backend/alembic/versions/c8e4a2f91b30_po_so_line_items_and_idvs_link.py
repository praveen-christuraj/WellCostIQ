"""Add PO/SO line items, line-item revision history, and optional IDVS line link.

Revision ID: c8e4a2f91b30
Revises: b4f8c2d91a07, f4c8a1d92e70
Create Date: 2026-11-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8e4a2f91b30"
down_revision: Union[str, Sequence[str], None] = ("b4f8c2d91a07", "f4c8a1d92e70")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NUM3 = sa.Numeric(28, 3)

SERVICE_RATE_ITEM_DECIMALS = (
    "quantity",
    "captured_rate",
    "override_rate",
    "exchange_rate",
    "amount",
    "standard_amount",
    "usd_exchange_rate",
    "usd_amount",
)


def upgrade() -> None:
    # Align the merged daily_cost_service_rate_items branch to the workspace 3-decimal contract.
    with op.batch_alter_table("daily_cost_service_rate_items") as batch:
        for column_name in SERVICE_RATE_ITEM_DECIMALS:
            batch.alter_column(
                column_name,
                existing_type=sa.Numeric(28, 10),
                type_=NUM3,
            )

    op.create_table(
        "po_so_line_items",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.String(length=36),
            sa.ForeignKey("po_so_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_line_item_id",
            sa.String(length=36),
            sa.ForeignKey("po_so_line_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("line_item_code", sa.String(length=80), nullable=False),
        sa.Column("vendor_code", sa.String(length=80), server_default="", nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("unit_rate", NUM3, server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("current_revision_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("added_in_order_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", "line_item_code", name="uq_po_so_line_items_order_code"),
        sa.CheckConstraint("unit_rate >= 0", name="ck_po_so_line_items_rate_non_negative"),
        sa.CheckConstraint("current_revision_number >= 1", name="ck_po_so_line_items_rev_positive"),
    )
    op.create_index("ix_po_so_line_items_organization_id", "po_so_line_items", ["organization_id"])
    op.create_index("ix_po_so_line_items_order_id", "po_so_line_items", ["order_id"])
    op.create_index(
        "ix_po_so_line_items_parent_line_item_id",
        "po_so_line_items",
        ["parent_line_item_id"],
    )
    op.create_index(
        "ix_po_so_line_items_org_order",
        "po_so_line_items",
        ["organization_id", "order_id", "is_deleted"],
    )

    op.create_table(
        "po_so_line_item_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "line_item_id",
            sa.String(length=36),
            sa.ForeignKey("po_so_line_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(length=24), server_default="initial", nullable=False),
        sa.Column("unit_rate", NUM3, nullable=False),
        sa.Column("previous_unit_rate", NUM3, nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("previous_currency", sa.String(length=10), nullable=False),
        sa.Column("vendor_code", sa.String(length=80), server_default="", nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("previous_description", sa.String(length=2000), server_default="", nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=500), server_default="", nullable=False),
        sa.Column("recorded_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("line_item_id", "revision_number", name="uq_po_so_line_item_rev_number"),
        sa.CheckConstraint(
            "unit_rate >= 0 AND previous_unit_rate >= 0",
            name="ck_po_so_line_item_rev_rates",
        ),
        sa.CheckConstraint(
            "change_type IN ('initial', 'price_revision', 'detail_amendment', 'order_amendment_copy')",
            name="ck_po_so_line_item_rev_type",
        ),
    )
    op.create_index(
        "ix_po_so_line_item_revisions_organization_id",
        "po_so_line_item_revisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_po_so_line_item_revisions_line_item_id",
        "po_so_line_item_revisions",
        ["line_item_id"],
    )

    with op.batch_alter_table("invoice_idvs_lines") as batch:
        batch.add_column(sa.Column("po_line_item_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column("po_line_code_snapshot", sa.String(length=80), server_default="", nullable=False)
        )
        batch.add_column(
            sa.Column("po_vendor_code_snapshot", sa.String(length=80), server_default="", nullable=False)
        )
        batch.add_column(sa.Column("po_unit_rate_snapshot", NUM3, nullable=True))
        batch.add_column(
            sa.Column("po_currency_snapshot", sa.String(length=10), server_default="", nullable=False)
        )
        batch.create_foreign_key(
            "fk_invoice_idvs_lines_po_line_item_id",
            "po_so_line_items",
            ["po_line_item_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_invoice_idvs_lines_po_line_item_id", ["po_line_item_id"])


def downgrade() -> None:
    with op.batch_alter_table("invoice_idvs_lines") as batch:
        batch.drop_index("ix_invoice_idvs_lines_po_line_item_id")
        batch.drop_constraint("fk_invoice_idvs_lines_po_line_item_id", type_="foreignkey")
        batch.drop_column("po_currency_snapshot")
        batch.drop_column("po_unit_rate_snapshot")
        batch.drop_column("po_vendor_code_snapshot")
        batch.drop_column("po_line_code_snapshot")
        batch.drop_column("po_line_item_id")

    op.drop_index("ix_po_so_line_item_revisions_line_item_id", table_name="po_so_line_item_revisions")
    op.drop_index("ix_po_so_line_item_revisions_organization_id", table_name="po_so_line_item_revisions")
    op.drop_table("po_so_line_item_revisions")

    op.drop_index("ix_po_so_line_items_org_order", table_name="po_so_line_items")
    op.drop_index("ix_po_so_line_items_parent_line_item_id", table_name="po_so_line_items")
    op.drop_index("ix_po_so_line_items_order_id", table_name="po_so_line_items")
    op.drop_index("ix_po_so_line_items_organization_id", table_name="po_so_line_items")
    op.drop_table("po_so_line_items")

    with op.batch_alter_table("daily_cost_service_rate_items") as batch:
        for column_name in SERVICE_RATE_ITEM_DECIMALS:
            batch.alter_column(
                column_name,
                existing_type=NUM3,
                type_=sa.Numeric(28, 10),
            )
