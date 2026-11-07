"""add IDVS report/register tax switches, net payable amount and signing space

Revision ID: c1d2e3f4a5b6
Revises: b3c4d5e6f7a8
Create Date: 2026-11-07 15:00:00.000000

Adds, column-wise and without touching any existing business row's meaning:

* ``invoice_tax_configurations.is_report_visible`` - whether a tax is printed on
  the IDVS report and therefore changes its invoice/verified total.
* ``invoice_tax_configurations.is_net_payable`` - whether a tax changes the
  register's Net payable amount. A tax may be report-only, register-only, both
  or neither.
* ``invoice_idvs_taxes.is_report_visible`` / ``is_net_payable`` - the
  configuration switches snapshotted onto each saved IDVS tax row, so a later
  configuration change never rewrites a stored sheet.
* ``invoice_idvs.net_payable_amount`` - the register amount: verified total with
  every net-payable tax applied, less disallowed and advance amounts. It equals
  the existing adjusted verified amount unless register-only taxes exist.
* ``invoice_idvs.signature_space_mm`` - the blank signing space printed above
  the Prepared By/Checked By/Verified By/Approved By names on the IDVS report.

Every new switch defaults to true and the net payable amount is backfilled from
the existing adjusted verified amount, so existing IDVS records print and total
exactly as before.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("invoice_tax_configurations") as batch:
        batch.add_column(sa.Column("is_report_visible", sa.Boolean(), server_default="true", nullable=False))
        batch.add_column(sa.Column("is_net_payable", sa.Boolean(), server_default="true", nullable=False))

    with op.batch_alter_table("invoice_idvs_taxes") as batch:
        batch.add_column(sa.Column("is_report_visible", sa.Boolean(), server_default="true", nullable=False))
        batch.add_column(sa.Column("is_net_payable", sa.Boolean(), server_default="true", nullable=False))

    with op.batch_alter_table("invoice_idvs") as batch:
        batch.add_column(sa.Column("net_payable_amount", sa.Numeric(28, 10), server_default="0", nullable=False))
        batch.add_column(sa.Column("signature_space_mm", sa.Integer(), server_default="15", nullable=False))
        batch.create_check_constraint(
            "ck_invoice_idvs_signature_space", "signature_space_mm >= 0 AND signature_space_mm <= 60"
        )

    # Existing sheets keep one net payable amount: the stored adjusted verified amount.
    op.execute("UPDATE invoice_idvs SET net_payable_amount = adjusted_verified_amount")


def downgrade() -> None:
    with op.batch_alter_table("invoice_idvs") as batch:
        batch.drop_constraint("ck_invoice_idvs_signature_space", type_="check")
        batch.drop_column("signature_space_mm")
        batch.drop_column("net_payable_amount")

    with op.batch_alter_table("invoice_idvs_taxes") as batch:
        batch.drop_column("is_net_payable")
        batch.drop_column("is_report_visible")

    with op.batch_alter_table("invoice_tax_configurations") as batch:
        batch.drop_column("is_net_payable")
        batch.drop_column("is_report_visible")
