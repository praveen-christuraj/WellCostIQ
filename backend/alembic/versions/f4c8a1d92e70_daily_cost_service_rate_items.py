"""Store multiple priced AFE cost items under one daily service row.

Revision ID: f4c8a1d92e70
Revises: c4a7e1b93d52
Create Date: 2026-11-21
"""

from alembic import op
import sqlalchemy as sa

revision = "f4c8a1d92e70"
down_revision = "c4a7e1b93d52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_cost_service_rate_items",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("service_line_id", sa.String(length=36), sa.ForeignKey("daily_cost_service_lines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("baseline_service_rate_id", sa.String(length=36), sa.ForeignKey("daily_cost_baseline_service_rates.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("charge_category", sa.String(length=40), nullable=False),
        sa.Column("charging_basis", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 10), nullable=False),
        sa.Column("quantity_unit", sa.String(length=20), nullable=False),
        sa.Column("captured_rate", sa.Numeric(28, 10), nullable=False),
        sa.Column("override_rate", sa.Numeric(28, 10), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(28, 10), nullable=False),
        sa.Column("amount", sa.Numeric(28, 10), nullable=False),
        sa.Column("standard_amount", sa.Numeric(28, 10), nullable=False),
        sa.Column("usd_exchange_rate", sa.Numeric(28, 10), nullable=False),
        sa.Column("usd_amount", sa.Numeric(28, 10), nullable=False),
        sa.Column("rate_source", sa.String(length=30), nullable=False),
        sa.Column("baseline_budget_line_id", sa.String(length=36), sa.ForeignKey("daily_cost_baseline_budget_lines.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("budget_key", sa.String(length=100), nullable=False),
        sa.Column("override_reason", sa.String(length=500), server_default="", nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("charge_category IN ('Mobilization', 'Demobilization', 'Operation', 'Standby', 'Personnel-Operation', 'Personnel-Standby', 'Fixed Charge', 'Others')", name="ck_daily_cost_service_rate_item_category"),
        sa.CheckConstraint("charging_basis IN ('Day Rate', 'Per Service Rate', 'Per Section Rate')", name="ck_daily_cost_service_rate_item_basis"),
        sa.CheckConstraint("quantity >= 0 AND captured_rate >= 0 AND amount >= 0 AND standard_amount >= 0 AND usd_amount >= 0", name="ck_daily_cost_service_rate_item_amounts"),
    )
    op.create_index("ix_daily_cost_service_rate_items_service_line_id", "daily_cost_service_rate_items", ["service_line_id"])
    op.create_index("ix_daily_cost_service_rate_items_baseline_service_rate_id", "daily_cost_service_rate_items", ["baseline_service_rate_id"])
    op.create_index("ix_daily_cost_service_rate_items_baseline_budget_line_id", "daily_cost_service_rate_items", ["baseline_budget_line_id"])
    op.create_index("ix_daily_cost_service_rate_items_budget_key", "daily_cost_service_rate_items", ["budget_key"])
    op.create_index("ix_daily_cost_service_rate_item_line_order", "daily_cost_service_rate_items", ["service_line_id", "sort_order"])


def downgrade() -> None:
    op.drop_index("ix_daily_cost_service_rate_item_line_order", table_name="daily_cost_service_rate_items")
    op.drop_index("ix_daily_cost_service_rate_items_budget_key", table_name="daily_cost_service_rate_items")
    op.drop_index("ix_daily_cost_service_rate_items_baseline_budget_line_id", table_name="daily_cost_service_rate_items")
    op.drop_index("ix_daily_cost_service_rate_items_baseline_service_rate_id", table_name="daily_cost_service_rate_items")
    op.drop_index("ix_daily_cost_service_rate_items_service_line_id", table_name="daily_cost_service_rate_items")
    op.drop_table("daily_cost_service_rate_items")
