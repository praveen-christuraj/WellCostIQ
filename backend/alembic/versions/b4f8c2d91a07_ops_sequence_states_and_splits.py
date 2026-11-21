"""Sequence-code state, splits, and the workspace policy that reads them.

Lead and lag are hours compared per sequence code. That arithmetic was only half
the answer: a plan of 100 h with 12 h logged read as an 88 h lead, hours against
no code were dropped, and an activity that will never be done had nowhere to go.
This revision adds the stored facts the honest arithmetic needs. Additive and
column-wise — no JSON columns, no value is rewritten.

``ops_plan_items``
    * ``state`` (``planned`` | ``skipped``) plus who/why/when. A skipped activity
      releases its planned hours and stops counting in the cumulative curve;
    * ``closed_at`` / ``closed_by`` / ``close_source`` / ``close_note`` and
      ``closed_actual_hours``. Only a closed activity is a lead or a lag. Closing
      is an explicit act, so completion is never inferred from hours alone.

``ops_activity_blocks``
    * ``timeline_sequence_state`` — the code's state as the last recompute read it,
      so the register can say "in progress" without re-deriving the ledger;
    * ``timeline_split_state`` — ``split`` / ``remainder`` for a line whose hours
      are shared between codes;
    * ``timeline_basis`` widens 50 → 120 so a basis is never silently truncated.

``ops_settings``
    * ``sequence_uncoded_policy``, ``sequence_npt_policy``,
      ``sequence_skipped_credit``, ``sequence_auto_close_tolerance_pct``,
      ``sequence_auto_close``, ``sequence_require_code_on_submit`` and
      ``sequence_current_run_only``. Every default is the requested behaviour, so a
      workspace that never opens the new screen gets the corrected arithmetic.

``ops_activity_block_codes`` (new)
    * one line's hours against one sequence code, with a unique (block, item) key.

**Backfill, deliberately conservative.** Every plan row is ``planned`` (a skip is
never inferred); every block's ``timeline_sequence_state`` is empty and is filled
by the next recompute — a schema upgrade must not recompute a submitted day. The
one repair performed is for blocks whose programme link was nulled by an earlier
positional renumbering (``plans.replace_items`` used to delete and re-create every
item): where ``timeline_plan_item_id`` is NULL and the stored ``timeline_code``
matches **exactly one** row of that report's baseline programme, the link is
restored. An ambiguous match is left NULL and logged, never guessed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4f8c2d91a07"
down_revision: Union[str, None] = "9ac1f4e72b03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NUM3 = sa.Numeric(28, 3)


def upgrade() -> None:
    bind = op.get_bind()

    # ---------------------------------------------------------------- plan items
    op.add_column(
        "ops_plan_items",
        sa.Column("state", sa.String(16), nullable=False, server_default="planned"),
    )
    op.add_column("ops_plan_items", sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ops_plan_items", sa.Column("skipped_by", sa.String(255), nullable=False, server_default="")
    )
    op.add_column(
        "ops_plan_items", sa.Column("skip_reason", sa.String(500), nullable=False, server_default="")
    )
    op.add_column("ops_plan_items", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ops_plan_items", sa.Column("closed_by", sa.String(255), nullable=False, server_default="")
    )
    op.add_column(
        "ops_plan_items", sa.Column("close_source", sa.String(12), nullable=False, server_default="")
    )
    op.add_column(
        "ops_plan_items", sa.Column("close_note", sa.String(500), nullable=False, server_default="")
    )
    op.add_column("ops_plan_items", sa.Column("closed_actual_hours", NUM3, nullable=True))

    # ------------------------------------------------------------ activity blocks
    op.add_column(
        "ops_activity_blocks",
        sa.Column("timeline_sequence_state", sa.String(16), nullable=False, server_default=""),
    )
    op.add_column(
        "ops_activity_blocks",
        sa.Column("timeline_split_state", sa.String(12), nullable=False, server_default=""),
    )
    # 120 characters: a basis names the programme and the rule, and 50 truncated it.
    with op.batch_alter_table("ops_activity_blocks") as batch:
        batch.alter_column(
            "timeline_basis",
            existing_type=sa.String(50),
            type_=sa.String(120),
            existing_nullable=False,
            existing_server_default="",
        )

    # -------------------------------------------------------------------- settings
    op.add_column(
        "ops_settings",
        sa.Column("sequence_uncoded_policy", sa.String(12), nullable=False, server_default="lag"),
    )
    op.add_column(
        "ops_settings",
        sa.Column("sequence_npt_policy", sa.String(12), nullable=False, server_default="include"),
    )
    op.add_column(
        "ops_settings",
        sa.Column("sequence_skipped_credit", sa.String(12), nullable=False, server_default="separate"),
    )
    op.add_column(
        "ops_settings",
        sa.Column(
            "sequence_auto_close_tolerance_pct",
            sa.Numeric(28, 3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "ops_settings",
        sa.Column(
            "sequence_auto_close", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "ops_settings",
        sa.Column(
            "sequence_require_code_on_submit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "ops_settings",
        sa.Column(
            "sequence_current_run_only", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )

    # ------------------------------------------------------------ block ↔ code rows
    op.create_table(
        "ops_activity_block_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "block_id",
            sa.String(36),
            sa.ForeignKey("ops_activity_blocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_item_id",
            sa.String(36),
            sa.ForeignKey("ops_plan_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sequence_no_snapshot", sa.Integer(), nullable=False),
        sa.Column("hours", NUM3, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False, server_default=""),
        sa.UniqueConstraint("block_id", "plan_item_id", name="uq_ops_block_codes_block_item"),
    )
    op.create_index(
        "ix_ops_block_codes_org_item",
        "ops_activity_block_codes",
        ["organization_id", "plan_item_id"],
    )
    op.create_index(
        "ix_ops_activity_block_codes_block_id", "ops_activity_block_codes", ["block_id"]
    )
    op.create_index(
        "ix_ops_activity_block_codes_plan_item_id", "ops_activity_block_codes", ["plan_item_id"]
    )
    op.create_index(
        "ix_ops_activity_block_codes_organization_id",
        "ops_activity_block_codes",
        ["organization_id"],
    )

    _repair_nulled_plan_links(bind)


def _repair_nulled_plan_links(bind) -> None:
    """Restore programme links lost to the old positional renumbering.

    ``plans.replace_items`` used to delete every item and re-create it with a fresh
    primary key, which nulled ``timeline_plan_item_id`` on every block that pointed
    at one. The code text survived, so an unambiguous match restores the link. An
    ambiguous match is reported and left alone: a wrong link is worse than none.
    """
    rows = bind.execute(
        sa.text(
            """
            SELECT b.id             AS block_id,
                   b.report_id      AS report_id,
                   b.timeline_code  AS code,
                   r.well_id        AS well_id,
                   r.scope          AS scope,
                   r.baseline_plan_id AS plan_id,
                   b.organization_id AS org
              FROM ops_activity_blocks b
              JOIN ops_daily_reports r ON r.id = b.report_id
             WHERE b.timeline_plan_item_id IS NULL
               AND b.timeline_code IS NOT NULL
               AND b.is_deleted = :no
               AND r.is_deleted = :no
            """
        ),
        {"no": False},
    ).mappings().all()

    repaired = 0
    ambiguous = 0
    for row in rows:
        plan_id = row["plan_id"]
        if not plan_id:
            # The report pinned no baseline: fall back to the well/scope's active
            # version, never to any other well's programme.
            plan_id = bind.execute(
                sa.text(
                    """
                    SELECT p.id
                      FROM ops_plan_versions p
                     WHERE p.organization_id = :org
                       AND p.well_id = :well_id
                       AND p.scope = :scope
                       AND p.status = 'active'
                       AND p.is_deleted = :no
                    """
                ),
                {"org": row["org"], "well_id": row["well_id"], "scope": row["scope"], "no": False},
            ).scalar()
        if not plan_id:
            continue
        candidates = bind.execute(
            sa.text(
                """
                SELECT id, CAST(sequence_no AS VARCHAR(20)) AS code
                  FROM ops_plan_items
                 WHERE plan_version_id = :plan_id
                """
            ),
            {"plan_id": plan_id},
        ).mappings().all()
        matches = [c for c in candidates if (c["code"] or "").strip() == (row["code"] or "").strip()]
        if len(matches) == 1:
            bind.execute(
                sa.text(
                    "UPDATE ops_activity_blocks SET timeline_plan_item_id = :item WHERE id = :block"
                ),
                {"item": matches[0]["id"], "block": row["block_id"]},
            )
            repaired += 1
        elif len(matches) > 1:
            ambiguous += 1
    if repaired or ambiguous:
        print(  # noqa: T201 - migration log, the only channel at this point
            f"sequence codes: restored {repaired} programme link(s); "
            f"{ambiguous} block(s) left unlinked because the code matched more than one row"
        )


def downgrade() -> None:
    """Drop the new columns and table.

    The repair performed in :func:`_repair_nulled_plan_links` is **not** reversed:
    restoring a link to NULL would throw away a recovered fact, and the old code
    would null it again on the next save. The derived ``timeline_sequence_state``,
    ``timeline_split_state`` and split rows are dropped with their columns.
    """
    op.drop_index("ix_ops_activity_block_codes_organization_id", table_name="ops_activity_block_codes")
    op.drop_index("ix_ops_activity_block_codes_plan_item_id", table_name="ops_activity_block_codes")
    op.drop_index("ix_ops_activity_block_codes_block_id", table_name="ops_activity_block_codes")
    op.drop_index("ix_ops_block_codes_org_item", table_name="ops_activity_block_codes")
    op.drop_table("ops_activity_block_codes")

    for column in (
        "sequence_current_run_only",
        "sequence_require_code_on_submit",
        "sequence_auto_close",
        "sequence_auto_close_tolerance_pct",
        "sequence_skipped_credit",
        "sequence_npt_policy",
        "sequence_uncoded_policy",
    ):
        op.drop_column("ops_settings", column)

    with op.batch_alter_table("ops_activity_blocks") as batch:
        batch.alter_column(
            "timeline_basis",
            existing_type=sa.String(120),
            type_=sa.String(50),
            existing_nullable=False,
            existing_server_default="",
        )
    op.drop_column("ops_activity_blocks", "timeline_split_state")
    op.drop_column("ops_activity_blocks", "timeline_sequence_state")

    for column in (
        "closed_actual_hours",
        "close_note",
        "close_source",
        "closed_by",
        "closed_at",
        "skip_reason",
        "skipped_by",
        "skipped_at",
        "state",
    ):
        op.drop_column("ops_plan_items", column)
