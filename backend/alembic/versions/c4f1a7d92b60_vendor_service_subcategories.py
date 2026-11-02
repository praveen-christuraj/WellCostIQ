"""Link well sub activities to Master Data vendors and their service subcategories.

Adds the ``vendor_service_subcategories`` register (one row per service line a
vendor provides, e.g. Halliburton — Liner Service) and points well sub
activities at a vendor plus, optionally, one of that vendor's service lines.
Existing free-text ``responsible_party`` values are matched to an existing
vendor by code or exact name; only unambiguous matches are linked, everything
else stays free text so no historical register changes meaning.

Revision ID: c4f1a7d92b60
Revises: b7c1d9e4f2a8
"""

from alembic import op
import sqlalchemy as sa

revision = "c4f1a7d92b60"
down_revision = "b7c1d9e4f2a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_service_subcategories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), nullable=False),
        sa.Column("subcategory_code", sa.String(length=50), nullable=False),
        sa.Column("subcategory_name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "vendor_id",
            "subcategory_code",
            name="uq_vendor_service_subcategories_org_vendor_code",
        ),
    )
    op.create_index(
        "ix_vendor_service_subcategories_organization_id",
        "vendor_service_subcategories",
        ["organization_id"],
    )
    op.create_index(
        "ix_vendor_service_subcategories_vendor_id",
        "vendor_service_subcategories",
        ["vendor_id"],
    )
    op.create_index(
        "ix_vendor_service_subcategories_org_vendor",
        "vendor_service_subcategories",
        ["organization_id", "vendor_id"],
    )

    with op.batch_alter_table("well_sub_activities") as batch:
        batch.add_column(sa.Column("vendor_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("vendor_subcategory_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_well_sub_activities_vendor_id",
            "vendors",
            ["vendor_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_well_sub_activities_vendor_subcategory_id",
            "vendor_service_subcategories",
            ["vendor_subcategory_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_well_sub_activities_vendor_id", "well_sub_activities", ["vendor_id"]
    )
    op.create_index(
        "ix_well_sub_activities_vendor_subcategory_id",
        "well_sub_activities",
        ["vendor_subcategory_id"],
    )
    op.create_index(
        "ix_well_sub_activities_org_vendor",
        "well_sub_activities",
        ["organization_id", "vendor_id"],
    )

    # Backfill: link a sub activity whose free-text party names exactly one
    # active vendor (by code, or by exact case-insensitive name).
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT sa.id AS sub_activity_id,
                   sa.organization_id AS organization_id,
                   sa.responsible_party AS responsible_party
            FROM well_sub_activities AS sa
            WHERE sa.vendor_id IS NULL
              AND sa.responsible_party IS NOT NULL
              AND TRIM(sa.responsible_party) <> ''
            """
        )
    ).fetchall()
    for row in rows:
        party = (row.responsible_party or "").strip()
        if not party or party.lower() in {"-", "n/a", "na", "none", "not applicable"}:
            continue
        matches = connection.execute(
            sa.text(
                """
                SELECT v.id AS id, v.vendor_name AS vendor_name
                FROM vendors AS v
                WHERE v.organization_id = :organization_id
                  AND v.is_deleted = :not_deleted
                  AND (UPPER(v.vendor_code) = :upper_party OR LOWER(v.vendor_name) = :lower_party)
                """
            ),
            {
                "organization_id": row.organization_id,
                "not_deleted": False,
                "upper_party": party.upper(),
                "lower_party": party.lower(),
            },
        ).fetchall()
        vendor_ids = {match.id for match in matches}
        if len(vendor_ids) != 1:
            continue
        matched = matches[0]
        connection.execute(
            sa.text(
                """
                UPDATE well_sub_activities
                SET vendor_id = :vendor_id, responsible_party = :vendor_name
                WHERE id = :sub_activity_id
                """
            ),
            {
                "vendor_id": matched.id,
                "vendor_name": matched.vendor_name,
                "sub_activity_id": row.sub_activity_id,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_well_sub_activities_org_vendor", table_name="well_sub_activities")
    op.drop_index(
        "ix_well_sub_activities_vendor_subcategory_id", table_name="well_sub_activities"
    )
    op.drop_index("ix_well_sub_activities_vendor_id", table_name="well_sub_activities")
    with op.batch_alter_table("well_sub_activities") as batch:
        batch.drop_constraint("fk_well_sub_activities_vendor_subcategory_id", type_="foreignkey")
        batch.drop_constraint("fk_well_sub_activities_vendor_id", type_="foreignkey")
        batch.drop_column("vendor_subcategory_id")
        batch.drop_column("vendor_id")
    op.drop_index(
        "ix_vendor_service_subcategories_org_vendor",
        table_name="vendor_service_subcategories",
    )
    op.drop_index(
        "ix_vendor_service_subcategories_vendor_id",
        table_name="vendor_service_subcategories",
    )
    op.drop_index(
        "ix_vendor_service_subcategories_organization_id",
        table_name="vendor_service_subcategories",
    )
    op.drop_table("vendor_service_subcategories")
