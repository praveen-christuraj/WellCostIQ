"""Streamline the Well Operations code library into Master Data + Code Library criteria.

Replaces the seven parallel operations code lists with the criteria the daily
report and the Code Library actually use:

* **Master Data** supplies Hole Section, Phase, Activity and vendors. ``activities``
  gains ``activity_type`` (Planned / UPA / NPT), which is what the daily report
  reads as a block's Activity.
* **Code Library** supplies Operations (the former NPT code list, renamed),
  Sub-phases (children of a Master Data Phase), Causes, Responsible agency labels
  and Source marks.
* The printed-code correlation and multi-criteria code link tables are rebuilt
  column-wise against the new criteria: hole section, phase, sub-phase, activity,
  operations, cause, responsible agency label and agency / service vendor.

Retired: ``ops_operation_codes``, ``ops_activity_codes``, ``ops_npt_codes``,
``ops_phase_codes``. Correlation and link rows that pointed at a retired list are
removed with the list they pointed at, so no rule can reference a record that no
longer exists. Daily blocks keep their printed source text and their
classification; only the retired foreign keys are dropped.

Revision ID: b7e2f4a91c38
Revises: e8b4c1d92f30
Create Date: 2026-11-19 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2f4a91c38"
down_revision: Union[str, None] = "e8b4c1d92f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RETIRED_TABLES = ("ops_operation_codes", "ops_activity_codes", "ops_npt_codes", "ops_phase_codes")

# Correlation columns that pointed at a retired table.
RETIRED_CORRELATION_COLUMNS = (
    "target_operation_code_id",
    "target_activity_code_id",
    "target_npt_code_id",
    "target_phase_code_id",
    "target_classification",
)

# Link columns that pointed at a retired table.
RETIRED_LINK_COLUMNS = (
    "operation_code_id",
    "activity_code_id",
    "npt_code_id",
    "phase_code_id",
    "default_classification",
)


def _is_pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _drop_fks(table: str, column_names: tuple[str, ...]) -> None:
    """Drop every foreign key that covers one of ``column_names``.

    PostgreSQL needs the constraint dropped by name before the column; SQLite is
    rebuilt by Alembic's batch mode, which does the same through the reflection
    of the table definition. Both paths are handled here so the two dialects run
    the identical logical steps.
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        inspector = sa.inspect(bind)
        for fk in inspector.get_foreign_keys(table):
            if set(fk["constrained_columns"]) & set(column_names):
                op.drop_constraint(fk["name"], table, type_="foreignkey")


def _add_activity_type() -> None:
    with op.batch_alter_table("activities") as batch:
        batch.add_column(
            sa.Column("activity_type", sa.String(10), nullable=False, server_default="Planned")
        )
        batch.create_check_constraint(
            "ck_activities_type", "activity_type IN ('Planned', 'UPA', 'NPT')"
        )
    # Existing activities keep working: they are planned drilling work until a
    # user says otherwise. Nothing is inferred from a code or a name.


def _create_operations_table() -> None:
    op.create_table(
        "ops_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation_code", sa.String(50), nullable=False),
        sa.Column("operation_name", sa.String(150), nullable=False),
        sa.Column("family", sa.String(30), nullable=False, server_default="other"),
        sa.Column("category", sa.String(50), nullable=False, server_default="other"),
        sa.Column("default_responsible_party", sa.String(200), nullable=False, server_default=""),
        sa.Column("is_chargeable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_company_caused", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_contractor_caused", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "operation_code", name="uq_ops_operations_org_code"),
    )
    op.create_index("ix_ops_operations_organization_id", "ops_operations", ["organization_id"])
    op.create_index("ix_ops_operations_org_deleted", "ops_operations", ["organization_id", "is_deleted"])


def _create_sub_phases_table() -> None:
    op.create_table(
        "ops_sub_phases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phase_id", sa.String(36), sa.ForeignKey("phases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("phase_code_snapshot", sa.String(50), nullable=False, server_default=""),
        sa.Column("phase_name_snapshot", sa.String(150), nullable=False, server_default=""),
        sa.Column("sub_phase_code", sa.String(50), nullable=False),
        sa.Column("sub_phase_name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "phase_id", "sub_phase_code", name="uq_ops_sub_phase_code"),
    )
    op.create_index("ix_ops_sub_phases_organization_id", "ops_sub_phases", ["organization_id"])
    op.create_index("ix_ops_sub_phases_org_deleted", "ops_sub_phases", ["organization_id", "is_deleted"])
    op.create_index("ix_ops_sub_phases_phase_id", "ops_sub_phases", ["phase_id"])


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = _is_pg()

    _add_activity_type()
    _create_operations_table()
    _create_sub_phases_table()

    # ---------------------------------------------------------------- correlations
    _drop_fks(
        "ops_code_correlations",
        (
            "target_operation_code_id",
            "target_activity_code_id",
            "target_npt_code_id",
            "target_phase_code_id",
            "target_classification",
        ),
    )
    with op.batch_alter_table("ops_code_correlations") as batch:
        for column in (*RETIRED_CORRELATION_COLUMNS, "target_agency_id"):
            batch.drop_column(column)
        batch.add_column(sa.Column("target_operation_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("target_sub_phase_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("target_hole_section_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("target_phase_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("target_activity_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("target_responsible_agency_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("target_vendor_id", sa.String(36), nullable=True))

    # ---------------------------------------------------------------- code links
    _drop_fks(
        "ops_code_links",
        ("operation_code_id", "activity_code_id", "npt_code_id", "phase_code_id", "default_classification"),
    )
    with op.batch_alter_table("ops_code_links") as batch:
        for column in (*RETIRED_LINK_COLUMNS, "agency_id"):
            batch.drop_column(column)
        batch.add_column(sa.Column("hole_section_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("phase_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("sub_phase_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("activity_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("operation_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("responsible_agency_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("vendor_id", sa.String(36), nullable=True))

    # ---------------------------------------------------------------- daily blocks
    # Add the Operations snapshot and copy the printed NPT token into it *before*
    # the retired columns go: a reviewed day keeps the token it was saved with.
    op.add_column(
        "ops_activity_blocks",
        sa.Column("operation_snapshot", sa.String(50), nullable=False, server_default=""),
    )
    bind.execute(
        sa.text(
            "UPDATE ops_activity_blocks SET operation_snapshot = COALESCE(npt_code_snapshot, '')"
        )
    )

    _drop_fks("ops_activity_blocks", ("operation_code_id", "activity_code_id", "npt_code_id", "agency_id"))
    with op.batch_alter_table("ops_activity_blocks") as batch:
        batch.drop_column("operation_code_id")
        batch.drop_column("activity_code_id")
        batch.drop_column("npt_code_id")
        # ``agency_id`` was the old free-text agency link; the responsible agency
        # label and the agency / service vendor are now separate criteria.
        batch.drop_column("agency_id")
        batch.drop_column("npt_code_snapshot")
        batch.add_column(sa.Column("sub_phase_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("operation_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("responsible_agency_id", sa.String(36), nullable=True))

    # ---------------------------------------------------------------- plan items
    _drop_fks("ops_plan_items", ("operation_code_id",))
    with op.batch_alter_table("ops_plan_items") as batch:
        batch.drop_column("operation_code_id")
        batch.add_column(sa.Column("operation_id", sa.String(36), nullable=True))

    # ---------------------------------------------------------------- settings
    with op.batch_alter_table("ops_settings") as batch:
        batch.alter_column("require_npt_code", new_column_name="require_operations")

    if is_pg:
        _add_postgres_foreign_keys()

    # ------------------------------------------------------------------ retire lists
    for table in RETIRED_TABLES:
        op.drop_table(table)

    _seed_operations(bind)


def _add_postgres_foreign_keys() -> None:
    """PostgreSQL enforces the new FKs; SQLite keeps SQLAlchemy's declaration."""
    with op.batch_alter_table("ops_code_correlations") as batch:
        batch.create_foreign_key(
            "fk_ops_corr_operation", "ops_operations", ["target_operation_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key(
            "fk_ops_corr_sub_phase", "ops_sub_phases", ["target_sub_phase_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key(
            "fk_ops_corr_section", "hole_sections", ["target_hole_section_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key(
            "fk_ops_corr_phase", "phases", ["target_phase_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key(
            "fk_ops_corr_activity", "activities", ["target_activity_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key(
            "fk_ops_corr_resp_agency",
            "ops_agencies",
            ["target_responsible_agency_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_ops_corr_vendor", "vendors", ["target_vendor_id"], ["id"], ondelete="RESTRICT"
        )

    with op.batch_alter_table("ops_code_links") as batch:
        batch.create_foreign_key(
            "fk_ops_link_section", "hole_sections", ["hole_section_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key("fk_ops_link_phase", "phases", ["phase_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key(
            "fk_ops_link_sub_phase", "ops_sub_phases", ["sub_phase_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key("fk_ops_link_activity", "activities", ["activity_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key(
            "fk_ops_link_operation", "ops_operations", ["operation_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key(
            "fk_ops_link_resp_agency",
            "ops_agencies",
            ["responsible_agency_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key("fk_ops_link_vendor", "vendors", ["vendor_id"], ["id"], ondelete="RESTRICT")

    for table, columns in (
        (
            "ops_activity_blocks",
            (("fk_ops_blocks_sub_phase", "ops_sub_phases", "sub_phase_id"), ("fk_ops_blocks_operation", "ops_operations", "operation_id"), ("fk_ops_blocks_resp_agency", "ops_agencies", "responsible_agency_id")),
        ),
        ("ops_plan_items", (("fk_ops_plan_items_operation", "ops_operations", "operation_id"),)),
    ):
        with op.batch_alter_table(table) as batch:
            for name, ref, column in columns:
                batch.create_foreign_key(name, ref, [column], ["id"], ondelete="SET NULL")


def _seed_operations(bind) -> None:
    """Seed the built-in downturn operations from the printed reference catalogue.

    These are the trouble/NPT tokens the organisation's own workbooks use
    (TP01, TR02, TD01, TW01 …). They are a starting list a workspace may edit,
    never a second source of truth: the code and its name come from
    ``default_codes.py``.
    """
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.domain.operations.default_codes import catalogue_rows

    rows = [row for row in catalogue_rows() if row["family"] == "Trouble / NPT"]
    if not rows:
        return
    now = datetime.now(UTC)
    for org in bind.execute(sa.text("SELECT id FROM organizations")).scalars():
        for sort_order, row in enumerate(rows):
            exists = bind.execute(
                sa.text(
                    "SELECT id FROM ops_operations WHERE organization_id=:org AND operation_code=:code"
                ),
                {"org": org, "code": row["code"]},
            ).scalar()
            if exists:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO ops_operations (id, organization_id, operation_code, operation_name,"
                    " family, category, default_responsible_party, is_chargeable, is_company_caused,"
                    " is_contractor_caused, description, sort_order, is_active, is_deleted,"
                    " created_at, updated_at)"
                    " VALUES (:id,:org,:code,:name,'trouble','other','',:chargeable,false,false,"
                    ":description,:sort_order,true,false,:now,:now)"
                ),
                {
                    "id": str(uuid4()),
                    "org": org,
                    "code": row["code"],
                    "name": row["name"][:150],
                    "chargeable": bool(row.get("is_chargeable")),
                    "description": (row.get("description") or "")[:500],
                    "sort_order": sort_order,
                    "now": now,
                },
            )


def downgrade() -> None:
    """Recreate the retired lists empty, so the older code runs on the same data.

    The dropped lists are not repopulated from the new criteria: their original
    identities are gone and inventing them back would silently change a
    historical report. Blocks keep their printed source text and classification.
    """
    is_pg = _is_pg()

    op.create_table(
        "ops_operation_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_code", sa.String(50), nullable=False),
        sa.Column("operation_name", sa.String(150), nullable=False),
        sa.Column("category", sa.String(50), nullable=False, server_default="other"),
        sa.Column("default_classification", sa.String(10), nullable=False, server_default="Planned"),
        sa.Column("is_productive_default", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("counts_as_on_bottom", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("requires_npt_code", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("phase_applicable", sa.String(20), nullable=False, server_default="both"),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "operation_code", name="uq_ops_operation_codes_org_code"),
    )
    op.create_index("ix_ops_operation_codes_org_deleted", "ops_operation_codes", ["organization_id", "is_deleted"])

    op.create_table(
        "ops_activity_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_code", sa.String(50), nullable=False),
        sa.Column("activity_name", sa.String(150), nullable=False),
        sa.Column("default_allocation", sa.String(10), nullable=False, server_default="PT"),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "activity_code", name="uq_ops_activity_codes_org_code"),
    )
    op.create_index("ix_ops_activity_codes_org_deleted", "ops_activity_codes", ["organization_id", "is_deleted"])

    op.create_table(
        "ops_npt_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("npt_code", sa.String(50), nullable=False),
        sa.Column("npt_name", sa.String(150), nullable=False),
        sa.Column("family", sa.String(30), nullable=False, server_default="other"),
        sa.Column("category", sa.String(50), nullable=False, server_default="other"),
        sa.Column("default_responsible_party", sa.String(200), nullable=False, server_default=""),
        sa.Column("is_chargeable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_company_caused", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_contractor_caused", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "npt_code", name="uq_ops_npt_codes_org_code"),
    )
    op.create_index("ix_ops_npt_codes_org_deleted", "ops_npt_codes", ["organization_id", "is_deleted"])

    op.create_table(
        "ops_phase_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phase_code", sa.String(20), nullable=False),
        sa.Column("phase_name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "phase_code", name="uq_ops_phase_code"),
    )

    with op.batch_alter_table("ops_settings") as batch:
        batch.alter_column("require_operations", new_column_name="require_npt_code")

    _drop_fks("ops_plan_items", ("operation_id",))
    with op.batch_alter_table("ops_plan_items") as batch:
        batch.drop_column("operation_id")
        batch.add_column(sa.Column("operation_code_id", sa.String(36), nullable=True))

    _drop_fks("ops_activity_blocks", ("sub_phase_id", "operation_id", "responsible_agency_id"))
    with op.batch_alter_table("ops_activity_blocks") as batch:
        batch.drop_column("sub_phase_id")
        batch.drop_column("operation_id")
        batch.drop_column("operation_snapshot")
        batch.drop_column("responsible_agency_id")
        batch.add_column(sa.Column("operation_code_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("activity_code_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("npt_code_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("agency_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column("npt_code_snapshot", sa.String(50), nullable=False, server_default="")
        )

    _drop_fks(
        "ops_code_links",
        ("hole_section_id", "phase_id", "sub_phase_id", "activity_id", "operation_id", "responsible_agency_id", "vendor_id"),
    )
    with op.batch_alter_table("ops_code_links") as batch:
        for column in (
            "hole_section_id",
            "phase_id",
            "sub_phase_id",
            "activity_id",
            "operation_id",
            "responsible_agency_id",
            "vendor_id",
        ):
            batch.drop_column(column)
        batch.add_column(sa.Column("agency_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("phase_code_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("operation_code_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("activity_code_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("npt_code_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column("default_classification", sa.String(12), nullable=False, server_default="")
        )

    _drop_fks(
        "ops_code_correlations",
        (
            "target_operation_id",
            "target_sub_phase_id",
            "target_hole_section_id",
            "target_phase_id",
            "target_activity_id",
            "target_responsible_agency_id",
            "target_vendor_id",
        ),
    )
    with op.batch_alter_table("ops_code_correlations") as batch:
        for column in (
            "target_operation_id",
            "target_sub_phase_id",
            "target_hole_section_id",
            "target_phase_id",
            "target_activity_id",
            "target_responsible_agency_id",
            "target_vendor_id",
        ):
            batch.drop_column(column)
        batch.add_column(sa.Column("target_agency_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("target_operation_code_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("target_activity_code_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("target_npt_code_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("target_phase_code_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column("target_classification", sa.String(12), nullable=False, server_default="")
        )

    op.drop_table("ops_sub_phases")
    op.drop_table("ops_operations")

    with op.batch_alter_table("activities") as batch:
        batch.drop_constraint("ck_activities_type", type_="check")
        batch.drop_column("activity_type")
