"""Link a well sub activity's responsible party to the Master Data vendor register.

The responsible party used to be free text, so the same company could be spelled
three ways and nothing joined the sub activity back to the vendor it was bought
from. This adds the vendor key plus the code snapshot and the party's source
(vendor / manual / import) to ``well_sub_activities``, and links existing rows
whose typed name resolves to exactly one vendor in the same workspace. The typed
``responsible_party`` text is never rewritten by the backfill: reports, search
and daily-cost drill-through keep reading it.

Revision ID: c4e8b7a20d51
Revises: a7f3c9d21b58
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4e8b7a20d51"
down_revision: Union[str, None] = "a7f3c9d21b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SUB_ACTIVITIES = sa.table(
    "well_sub_activities",
    sa.column("id", sa.String(36)),
    sa.column("organization_id", sa.String(36)),
    sa.column("responsible_party", sa.String(200)),
    sa.column("vendor_id", sa.String(36)),
    sa.column("vendor_code_snapshot", sa.String(50)),
    sa.column("responsible_party_source", sa.String(20)),
)

VENDORS = sa.table(
    "vendors",
    sa.column("id", sa.String(36)),
    sa.column("organization_id", sa.String(36)),
    sa.column("vendor_code", sa.String(50)),
    sa.column("vendor_name", sa.String(200)),
    sa.column("is_deleted", sa.Boolean()),
)


def _link_existing_vendors() -> None:
    """Point a sub activity at its vendor when the typed name resolves to exactly one."""
    bind = op.get_bind()
    vendors = bind.execute(
        sa.select(
            VENDORS.c.id,
            VENDORS.c.organization_id,
            VENDORS.c.vendor_code,
            VENDORS.c.vendor_name,
        ).where(VENDORS.c.is_deleted.is_(False))
    ).all()
    # (organization, folded text) -> [vendor]. A name or code used by two vendors
    # is left untouched rather than guessed.
    index: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for vendor_id, organization_id, vendor_code, vendor_name in vendors:
        for text in (vendor_name, vendor_code):
            key = (organization_id, (text or "").strip().casefold())
            if not key[1]:
                continue
            bucket = index.setdefault(key, [])
            if (vendor_id, vendor_code) not in bucket:
                bucket.append((vendor_id, vendor_code))

    rows = bind.execute(
        sa.select(
            SUB_ACTIVITIES.c.id,
            SUB_ACTIVITIES.c.organization_id,
            SUB_ACTIVITIES.c.responsible_party,
        ).where(SUB_ACTIVITIES.c.vendor_id.is_(None))
    ).all()
    for record_id, organization_id, party in rows:
        matches = index.get((organization_id, (party or "").strip().casefold()), [])
        if len(matches) != 1:
            continue
        vendor_id, vendor_code = matches[0]
        bind.execute(
            SUB_ACTIVITIES.update()
            .where(SUB_ACTIVITIES.c.id == record_id)
            .values(
                vendor_id=vendor_id,
                vendor_code_snapshot=vendor_code or "",
                responsible_party_source="vendor",
            )
        )


def upgrade() -> None:
    with op.batch_alter_table("well_sub_activities") as batch:
        batch.add_column(sa.Column("vendor_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column("vendor_code_snapshot", sa.String(length=50), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column(
                "responsible_party_source",
                sa.String(length=20),
                nullable=False,
                server_default="manual",
            )
        )
        batch.create_check_constraint(
            "ck_well_sub_activities_party_source",
            "responsible_party_source IN ('vendor', 'manual', 'import')",
        )
        # Inside the batch block: SQLite has no ALTER for constraints, so the key
        # is added while the table is copied.
        batch.create_foreign_key(
            "fk_well_sub_activities_vendor_id_vendors",
            "vendors",
            ["vendor_id"],
            ["id"],
            ondelete="SET NULL",
        )
    # Matches the index the model declares for the vendor FK, the same shape as
    # the activity link: enough for tenant-scoped vendor drill-through and for
    # the ON DELETE SET NULL check the database performs on the vendor row.
    op.create_index("ix_well_sub_activities_vendor_id", "well_sub_activities", ["vendor_id"])
    _link_existing_vendors()


def downgrade() -> None:
    op.drop_index("ix_well_sub_activities_vendor_id", table_name="well_sub_activities")
    with op.batch_alter_table("well_sub_activities") as batch:
        batch.drop_constraint("fk_well_sub_activities_vendor_id_vendors", type_="foreignkey")
        batch.drop_constraint("ck_well_sub_activities_party_source", type_="check")
        batch.drop_column("responsible_party_source")
        batch.drop_column("vendor_code_snapshot")
        batch.drop_column("vendor_id")
