"""add IDVS day counts and sign-off signatories

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-11-07 09:00:00.000000

Adds, column-wise and without touching existing business rows:

* ``invoice_idvs.day_count_enabled`` - whether the IDVS shows the
  "No. of days" column for services and rental tools (default off).
* ``invoice_idvs_lines.invoice_days`` and ``verified_days`` - per-line day
  multipliers. Existing lines receive ``1``, so every stored total is unchanged.
* ``invoice_signatories`` - configured Prepared / Checked / Verified / Approved
  names and designations maintained in Invoice Configuration.
* ``invoice_idvs_signatures`` - the name and designation chosen for each
  sign-off role on an IDVS, snapshotted at save time.

No permission is added: sign-off configuration uses ``invoice-processing:configure``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SIGNATURE_ROLE_SQL = "'prepared', 'checked', 'verified', 'approved'"


def upgrade() -> None:
    with op.batch_alter_table("invoice_idvs") as batch:
        batch.add_column(sa.Column("day_count_enabled", sa.Boolean(), server_default="false", nullable=False))

    with op.batch_alter_table("invoice_idvs_lines") as batch:
        batch.add_column(sa.Column("invoice_days", sa.Numeric(28, 10), server_default="1", nullable=False))
        batch.add_column(sa.Column("verified_days", sa.Numeric(28, 10), server_default="1", nullable=False))
        batch.create_check_constraint("ck_invoice_idvs_lines_invoice_days", "invoice_days > 0")
        batch.create_check_constraint("ck_invoice_idvs_lines_verified_days", "verified_days >= 0")

    op.create_table(
        "invoice_signatories",
        sa.Column("signatory_role", sa.String(length=20), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("designation", sa.String(length=150), server_default="", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"signatory_role IN ({SIGNATURE_ROLE_SQL})", name="ck_invoice_signatories_role"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "signatory_role", "full_name", name="uq_invoice_signatories_org_role_name"),
    )
    op.create_index("ix_invoice_signatories_org_deleted", "invoice_signatories", ["organization_id", "is_deleted"], unique=False)
    op.create_index(op.f("ix_invoice_signatories_organization_id"), "invoice_signatories", ["organization_id"], unique=False)

    op.create_table(
        "invoice_idvs_signatures",
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("signature_role", sa.String(length=20), nullable=False),
        sa.Column("signatory_id", sa.String(length=36), nullable=True),
        sa.Column("signatory_name", sa.String(length=150), server_default="", nullable=False),
        sa.Column("designation", sa.String(length=150), server_default="", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(f"signature_role IN ({SIGNATURE_ROLE_SQL})", name="ck_invoice_idvs_signatures_role"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoice_idvs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["signatory_id"], ["invoice_signatories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_id", "signature_role", name="uq_invoice_idvs_signatures_role"),
    )
    op.create_index("ix_invoice_idvs_signatures_invoice_order", "invoice_idvs_signatures", ["invoice_id", "sort_order"], unique=False)
    op.create_index(op.f("ix_invoice_idvs_signatures_organization_id"), "invoice_idvs_signatures", ["organization_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_invoice_idvs_signatures_organization_id"), table_name="invoice_idvs_signatures")
    op.drop_index("ix_invoice_idvs_signatures_invoice_order", table_name="invoice_idvs_signatures")
    op.drop_table("invoice_idvs_signatures")
    op.drop_index(op.f("ix_invoice_signatories_organization_id"), table_name="invoice_signatories")
    op.drop_index("ix_invoice_signatories_org_deleted", table_name="invoice_signatories")
    op.drop_table("invoice_signatories")

    with op.batch_alter_table("invoice_idvs_lines") as batch:
        batch.drop_constraint("ck_invoice_idvs_lines_verified_days", type_="check")
        batch.drop_constraint("ck_invoice_idvs_lines_invoice_days", type_="check")
        batch.drop_column("verified_days")
        batch.drop_column("invoice_days")

    with op.batch_alter_table("invoice_idvs") as batch:
        batch.drop_column("day_count_enabled")
