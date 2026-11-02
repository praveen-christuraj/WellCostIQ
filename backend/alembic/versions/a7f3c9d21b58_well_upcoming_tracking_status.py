"""Upcoming / Active / Completed well tracking, per configuration scope.

Wells were flagged only as ``active`` or ``completed``. A well that has just
been created and is still being planned and costed therefore looked identical
to a well a rig is actually drilling, which is wrong for budget plotting and
MIS reporting. This revision widens both scope-level tracking columns
(``wells.status`` for Drilling, ``wells.completion_status`` for Completion) to
``upcoming | active | completed`` and makes ``upcoming`` the value a new well
starts with, so the plan (``config_status``) and the execution tracking stay
independent.

Existing wells are reclassified narrowly: a scope is only moved back to
``upcoming`` when its plan is still a draft, no section was ever saved for it,
no spud instant was recorded, and neither an AFE nor a daily-cost sheet exists
for it — in other words a well that was created but never actually planned or
started. Anything with a plan, a budget or a cost sheet keeps its ``active``
status, so no history is rewritten.

Revision ID: a7f3c9d21b58
Revises: b7c1d9e4f2a8
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7f3c9d21b58"
down_revision: Union[str, None] = "b7c1d9e4f2a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUS_CONSTRAINTS = {
    "drilling": ("status", "config_status", "ck_wells_status"),
    "completion": ("completion_status", "completion_config_status", "ck_wells_completion_status"),
}


WELLS = sa.table(
    "wells",
    sa.column("id", sa.String(36)),
    sa.column("organization_id", sa.String(36)),
    sa.column("status", sa.String(20)),
    sa.column("config_status", sa.String(20)),
    sa.column("completion_status", sa.String(20)),
    sa.column("completion_config_status", sa.String(20)),
    sa.column("drilling_spud_at", sa.DateTime()),
    sa.column("completion_spud_at", sa.DateTime()),
    sa.column("drilling_is_deleted", sa.Boolean()),
    sa.column("completion_is_deleted", sa.Boolean()),
)
SECTIONS = sa.table(
    "well_sections",
    sa.column("id", sa.String(36)),
    sa.column("well_id", sa.String(36)),
    sa.column("scope", sa.String(20)),
)
AFES = sa.table(
    "afes",
    sa.column("id", sa.String(36)),
    sa.column("well_id", sa.String(36)),
    sa.column("configuration_scope", sa.String(20)),
)
SHEETS = sa.table(
    "daily_cost_entries",
    sa.column("id", sa.String(36)),
    sa.column("afe_id", sa.String(36)),
    sa.column("is_deleted", sa.Boolean()),
)


def _started_clause(scope: str):
    """True when the scope has any evidence of planning, budget or execution.

    One shared ``wells`` table object keeps the correlated subqueries pointing at
    the row being updated, on PostgreSQL and SQLite alike.
    """
    has_section = sa.select(SECTIONS.c.id).where(
        SECTIONS.c.well_id == WELLS.c.id, SECTIONS.c.scope == scope
    ).exists()
    has_afe = sa.select(AFES.c.id).where(
        AFES.c.well_id == WELLS.c.id, AFES.c.configuration_scope == scope
    ).exists()
    has_sheet = (
        sa.select(SHEETS.c.id)
        .select_from(SHEETS.join(AFES, SHEETS.c.afe_id == AFES.c.id))
        .where(
            AFES.c.well_id == WELLS.c.id,
            AFES.c.configuration_scope == scope,
            SHEETS.c.is_deleted.is_(False),
        )
        .exists()
    )
    has_spud = WELLS.c[f"{scope}_spud_at"].isnot(None)
    return sa.or_(has_section, has_afe, has_sheet, has_spud)


def _backfill_upcoming() -> None:
    """Flag never-planned, never-started scopes as upcoming. Typed expressions keep
    PostgreSQL and SQLite on exactly the same statement."""
    bind = op.get_bind()
    for scope, (status_attr, config_attr, _constraint) in STATUS_CONSTRAINTS.items():
        bind.execute(
            WELLS.update()
            .where(
                WELLS.c[status_attr] == "active",
                WELLS.c[config_attr] == "draft",
                WELLS.c[f"{scope}_is_deleted"].is_(False),
                sa.not_(_started_clause(scope)),
            )
            .values({status_attr: "upcoming"})
        )


def upgrade() -> None:
    with op.batch_alter_table("wells") as batch:
        for _scope, (status_attr, _config_attr, constraint) in STATUS_CONSTRAINTS.items():
            batch.drop_constraint(constraint, type_="check")
        for _scope, (status_attr, _config_attr, constraint) in STATUS_CONSTRAINTS.items():
            batch.create_check_constraint(
                constraint, f"{status_attr} IN ('upcoming', 'active', 'completed')"
            )
            batch.alter_column(
                status_attr,
                existing_type=sa.String(length=20),
                existing_nullable=False,
                server_default="upcoming",
            )
    _backfill_upcoming()


def downgrade() -> None:
    bind = op.get_bind()
    for status_attr, _config_attr, _constraint in STATUS_CONSTRAINTS.values():
        bind.execute(
            WELLS.update().where(WELLS.c[status_attr] == "upcoming").values({status_attr: "active"})
        )
    with op.batch_alter_table("wells") as batch:
        for status_attr, _config_attr, constraint in STATUS_CONSTRAINTS.values():
            batch.drop_constraint(constraint, type_="check")
        for status_attr, _config_attr, constraint in STATUS_CONSTRAINTS.values():
            batch.create_check_constraint(constraint, f"{status_attr} IN ('active', 'completed')")
            batch.alter_column(
                status_attr,
                existing_type=sa.String(length=20),
                existing_nullable=False,
                server_default="active",
            )
