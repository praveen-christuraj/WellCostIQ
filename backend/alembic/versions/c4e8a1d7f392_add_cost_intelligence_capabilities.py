"""Add the Cost Intelligence capabilities.

Cost Intelligence is a read-only analysis of figures a role can already see, so
``cost-intelligence:read`` is granted to every existing role that holds
``daily-cost:read`` or ``afe:read`` (the figures themselves stay behind those
source capabilities). ``cost-intelligence:export`` goes to roles that can
already export one of those modules. No table is created: the module stores
nothing.

Revision ID: c4e8a1d7f392
Revises: b7d3e9f25a41
Create Date: 2026-11-14
"""

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a1d7f392"  # pragma: allowlist secret - Revision ID.
down_revision: Union[str, None] = "b7d3e9f25a41"  # pragma: allowlist secret - Parent revision ID.
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSIONS = sa.table(
    "permissions",
    sa.column("id", sa.String(36)),
    sa.column("organization_id", sa.String(36)),
    sa.column("key", sa.String(100)),
    sa.column("description", sa.String(500)),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
ROLES = sa.table(
    "roles",
    sa.column("id", sa.String(36)),
    sa.column("organization_id", sa.String(36)),
    sa.column("is_owner", sa.Boolean()),
)
ROLE_PERMISSIONS = sa.table(
    "role_permissions",
    sa.column("role_id", sa.String(36)),
    sa.column("permission_id", sa.String(36)),
)
ORGANIZATIONS = sa.table("organizations", sa.column("id", sa.String(36)))

NEW = {
    "cost-intelligence:read": ("Open Cost Intelligence: automated cost analysis and suggestions",
                               ("daily-cost:read", "afe:read")),
    "cost-intelligence:export": ("Export the Cost Intelligence report",
                                 ("daily-cost:export", "afe:export")),
}


def upgrade() -> None:
    bind = op.get_bind()
    for organization_id in bind.execute(sa.select(ORGANIZATIONS.c.id)).scalars().all():
        existing = dict(bind.execute(
            sa.select(PERMISSIONS.c.key, PERMISSIONS.c.id).where(PERMISSIONS.c.organization_id == organization_id)
        ).all())
        roles = bind.execute(
            sa.select(ROLES.c.id, ROLES.c.is_owner).where(ROLES.c.organization_id == organization_id)
        ).all()
        for key, (description, sources) in NEW.items():
            if key in existing:
                continue
            permission_id = str(uuid4())
            bind.execute(PERMISSIONS.insert(), [{
                "id": permission_id, "organization_id": organization_id, "key": key,
                "description": description, "created_at": datetime.now(timezone.utc),
            }])
            source_ids = [existing[item] for item in sources if item in existing]
            holders = set(bind.execute(
                sa.select(ROLE_PERMISSIONS.c.role_id).where(ROLE_PERMISSIONS.c.permission_id.in_(source_ids))
            ).scalars().all()) if source_ids else set()
            grants = [
                {"role_id": role_id, "permission_id": permission_id}
                for role_id, is_owner in roles if is_owner or role_id in holders
            ]
            if grants:
                bind.execute(ROLE_PERMISSIONS.insert(), grants)


def downgrade() -> None:
    bind = op.get_bind()
    ids = bind.execute(sa.select(PERMISSIONS.c.id).where(PERMISSIONS.c.key.in_(tuple(NEW)))).scalars().all()
    if ids:
        bind.execute(ROLE_PERMISSIONS.delete().where(ROLE_PERMISSIONS.c.permission_id.in_(ids)))
        bind.execute(PERMISSIONS.delete().where(PERMISSIONS.c.id.in_(ids)))
