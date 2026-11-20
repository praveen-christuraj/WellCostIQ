"""Plan-vs-timeline review in hours, and the survey stations the well diagram reads.

Two changes, both additive.

**Plan vs timeline (lead / lag).** The daily-report review used to compare a
block with the elapsed calendar days of the programme and ask for a note. The
organisation compares *hours*: the same job's planned hours against the hours it
actually took, variance = planned − actual, positive = lead. The block now stores
that comparison:

* ``timeline_plan_item_id`` / ``timeline_plan_step_no`` / ``timeline_plan_label``
  — the programme row being compared;
* ``timeline_planned_hours`` / ``timeline_actual_hours`` /
  ``timeline_system_actual_hours`` — the two sides, and the log's own figure
  before an engineer correction;
* ``timeline_variance_hours`` / ``timeline_cum_planned_days`` — the result;
* ``timeline_actual_edited`` / ``timeline_edited_by`` / ``timeline_edited_at``
  — who corrected the actual hours and when.

Existing rows keep exactly what they had: the new columns are nullable or
defaulted, and no historical value is recomputed by the migration. A re-suggest
on the next save fills them from the active programme, which is why the backfill
is deliberately absent — rewriting a reviewed report during a schema upgrade
would change a submitted day.

**Survey quality flags.** ``ops_surveys`` gains ``is_current`` and
``source_page`` so a re-extracted station can supersede an earlier one without
deleting the evidence, and the diagram can say which page printed it. Every
existing station is current, which is what it already meant.
"""

import sqlalchemy as sa
from alembic import op

revision = "e2f4c9b71a38"
down_revision = "b7e2f4a91c38"
branch_labels = None
depends_on = None

NUM3 = sa.Numeric(28, 3)

BLOCK_COLUMNS = (
    sa.Column("timeline_plan_item_id", sa.String(36), nullable=True),
    sa.Column("timeline_plan_step_no", sa.Integer(), nullable=True),
    sa.Column("timeline_plan_label", sa.String(500), nullable=False, server_default=""),
    sa.Column("timeline_planned_hours", NUM3, nullable=True),
    sa.Column("timeline_actual_hours", NUM3, nullable=True),
    sa.Column("timeline_system_actual_hours", NUM3, nullable=True),
    sa.Column("timeline_variance_hours", NUM3, nullable=True),
    sa.Column("timeline_cum_planned_days", NUM3, nullable=True),
    sa.Column("timeline_actual_edited", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("timeline_edited_by", sa.String(255), nullable=False, server_default=""),
    sa.Column("timeline_edited_at", sa.DateTime(timezone=True), nullable=True),
)

SURVEY_COLUMNS = (
    sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("source_page", sa.Integer(), nullable=True),
)


def upgrade() -> None:
    for column in BLOCK_COLUMNS:
        op.add_column("ops_activity_blocks", column)
    # An existing station is the current one; a superseded station would have been
    # deleted before this revision, so `true` states the record honestly.
    for column in SURVEY_COLUMNS:
        op.add_column("ops_surveys", column)
    with op.batch_alter_table("ops_activity_blocks") as batch:
        batch.create_foreign_key(
            "fk_ops_blocks_timeline_plan_item",
            "ops_plan_items",
            ["timeline_plan_item_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_ops_blocks_timeline_plan_item", ["timeline_plan_item_id"])
    # Planning a programme row is what a review points at, so the FK is useful for
    # lookups but must never block deleting an unactivated draft programme row.
    op.execute(
        sa.text(
            "UPDATE ops_activity_blocks SET timeline_system_actual_hours = ROUND(duration_minutes / 60.0, 3) "
            "WHERE timeline_actual_edited = false AND duration_minutes > 0"
        )
    )
    # The review reuses ``ops-report:update``, the capability that already governs
    # editing a draft report. No new key is inserted, so no role silently gains or
    # loses a grant: a user who cannot edit a draft still cannot correct its hours.


def downgrade() -> None:
    with op.batch_alter_table("ops_activity_blocks") as batch:
        batch.drop_index("ix_ops_blocks_timeline_plan_item")
        batch.drop_constraint("fk_ops_blocks_timeline_plan_item", type_="foreignkey")
    for column in reversed(BLOCK_COLUMNS):
        op.drop_column("ops_activity_blocks", column.name)
    for column in reversed(SURVEY_COLUMNS):
        op.drop_column("ops_surveys", column.name)
