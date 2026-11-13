"""Separate the well-status ladder from the plan-status ladder, with rollback.

Until now "final review" was a *plan* status while "completed" was a *well*
status, so the two vocabularies overlapped and a well in final review still read
as Active. Each configuration scope now carries two clean ladders:

    well status  upcoming -> active -> final_review -> completed
    plan status  draft -> configured -> completed

coupled by one rule that the database enforces itself: a scope in final review
or completed has a completed plan, and a scope that is upcoming or active never
does.

Existing rows move without losing meaning:

* a scope that was Completed keeps that well status and gets a completed plan;
* an Active scope whose plan was "final review" becomes well status Final
  review with a completed plan;
* an Upcoming scope whose plan was "final review" (signed off but never
  started) keeps Upcoming with a configured plan;
* everything else is untouched.

The revision also adds the ``rig-well:rollback`` capability, which every
one-step rollback (Configured -> Draft, Active -> Upcoming, Final review ->
Active, Completed -> Final review) now needs. It is granted to the owner role
and to every role that already holds ``rig-well:update``: those roles could
reopen a plan, defer a well and reactivate a completed well before this
revision, so nobody loses authority they had. Administrators can then remove it
from the roles that should only move wells forward.

Revision ID: e1b4f7a92c35
Revises: d7e3a91c4f60
Create Date: 2026-11-13
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "e1b4f7a92c35"
down_revision: Union[str, None] = "d7e3a91c4f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLLBACK_KEY = "rig-well:rollback"
ROLLBACK_DESCRIPTION = "Roll a well scope or its plan back one step to the previous status"
UPDATE_KEY = "rig-well:update"

# (well status column, plan status column, status CHECK, plan CHECK, coupling CHECK)
SCOPES = (
    ("status", "config_status", "ck_wells_status", "ck_wells_config_status", "ck_wells_status_plan"),
    (
        "completion_status", "completion_config_status",
        "ck_wells_completion_status", "ck_wells_completion_config_status", "ck_wells_completion_status_plan",
    ),
)

NEW_STATUSES = "('upcoming', 'active', 'final_review', 'completed')"
NEW_PLANS = "('draft', 'configured', 'completed')"
OLD_STATUSES = "('upcoming', 'active', 'completed')"
OLD_PLANS = "('draft', 'configured', 'final_review')"

WELLS = sa.table(
    "wells",
    sa.column("status", sa.String(20)),
    sa.column("config_status", sa.String(20)),
    sa.column("completion_status", sa.String(20)),
    sa.column("completion_config_status", sa.String(20)),
)


def _drop_checks(coupling: bool) -> None:
    with op.batch_alter_table("wells") as batch:
        for _status, _plan, status_check, plan_check, coupling_check in SCOPES:
            batch.drop_constraint(status_check, type_="check")
            batch.drop_constraint(plan_check, type_="check")
            if coupling:
                batch.drop_constraint(coupling_check, type_="check")


def _grant_rollback() -> None:
    bind = op.get_bind()
    organizations = sa.table("organizations", sa.column("id", sa.String(36)))
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String(36)),
        sa.column("organization_id", sa.String(36)),
        sa.column("key", sa.String(100)),
        sa.column("description", sa.String(500)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.String(36)),
        sa.column("organization_id", sa.String(36)),
        sa.column("is_owner", sa.Boolean()),
    )
    role_permissions = sa.table(
        "role_permissions", sa.column("role_id", sa.String(36)), sa.column("permission_id", sa.String(36))
    )

    for (organization_id,) in bind.execute(sa.select(organizations.c.id)).all():
        permission_id = bind.execute(
            sa.select(permissions.c.id).where(
                permissions.c.organization_id == organization_id, permissions.c.key == ROLLBACK_KEY
            )
        ).scalar_one_or_none()
        if permission_id is None:
            permission_id = str(uuid4())
            bind.execute(
                permissions.insert().values(
                    id=permission_id,
                    organization_id=organization_id,
                    key=ROLLBACK_KEY,
                    description=ROLLBACK_DESCRIPTION,
                    created_at=datetime.now(timezone.utc),
                )
            )
        # The owner role, plus every role of this workspace that can already
        # update wells (and so could already reopen, defer and reactivate them).
        holders = {
            role_id
            for (role_id,) in bind.execute(
                sa.select(roles.c.id).where(roles.c.organization_id == organization_id, roles.c.is_owner.is_(True))
            ).all()
        }
        holders.update(
            role_id
            for (role_id,) in bind.execute(
                sa.select(role_permissions.c.role_id)
                .select_from(
                    role_permissions
                    .join(permissions, permissions.c.id == role_permissions.c.permission_id)
                    .join(roles, roles.c.id == role_permissions.c.role_id)
                )
                .where(
                    permissions.c.organization_id == organization_id,
                    permissions.c.key == UPDATE_KEY,
                    roles.c.organization_id == organization_id,
                )
            ).all()
        )
        assigned = {
            role_id
            for (role_id,) in bind.execute(
                sa.select(role_permissions.c.role_id).where(role_permissions.c.permission_id == permission_id)
            ).all()
        }
        for role_id in sorted(holders - assigned):
            bind.execute(role_permissions.insert().values(role_id=role_id, permission_id=permission_id))


def upgrade() -> None:
    # The old CHECKs reject the new vocabulary, so they go first; the new ones
    # are created only after every row has been moved onto it.
    _drop_checks(coupling=False)

    bind = op.get_bind()
    for status_name, plan_name, *_checks in SCOPES:
        status = WELLS.c[status_name]
        plan = WELLS.c[plan_name]
        # Signed off but never started: the plan was at least configured.
        bind.execute(
            sa.update(WELLS).where(status == "upcoming", plan == "final_review").values({plan_name: "configured"})
        )
        # Operations ended and the plan was sent for final review.
        bind.execute(
            sa.update(WELLS)
            .where(status == "active", plan == "final_review")
            .values({status_name: "final_review", plan_name: "completed"})
        )
        # A completed scope always carries a completed plan.
        bind.execute(sa.update(WELLS).where(status == "completed").values({plan_name: "completed"}))
        # Defensive: no value outside the new vocabularies may survive.
        bind.execute(
            sa.update(WELLS)
            .where(plan.notin_(("draft", "configured", "completed")))
            .values({plan_name: "draft"})
        )

    with op.batch_alter_table("wells") as batch:
        for status_name, plan_name, status_check, plan_check, coupling_check in SCOPES:
            batch.create_check_constraint(status_check, f"{status_name} IN {NEW_STATUSES}")
            batch.create_check_constraint(plan_check, f"{plan_name} IN {NEW_PLANS}")
            batch.create_check_constraint(
                coupling_check,
                f"({status_name} IN ('final_review', 'completed')) = ({plan_name} = 'completed')",
            )

    _grant_rollback()


def downgrade() -> None:
    _drop_checks(coupling=True)

    bind = op.get_bind()
    for status_name, plan_name, *_checks in SCOPES:
        status = WELLS.c[status_name]
        # Final review was a plan status on an active well.
        bind.execute(
            sa.update(WELLS)
            .where(status == "final_review")
            .values({status_name: "active", plan_name: "final_review"})
        )
        # A well could only be completed from a plan in final review.
        bind.execute(sa.update(WELLS).where(status == "completed").values({plan_name: "final_review"}))

    with op.batch_alter_table("wells") as batch:
        for status_name, plan_name, status_check, plan_check, _coupling_check in SCOPES:
            batch.create_check_constraint(status_check, f"{status_name} IN {OLD_STATUSES}")
            batch.create_check_constraint(plan_check, f"{plan_name} IN {OLD_PLANS}")

    # Remove assignments before the permission rows they reference.
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE key = 'rig-well:rollback')"
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE key = 'rig-well:rollback'"))
