"""Add the in-application guide: its memory, transcript and capabilities.

The guide reasons only from durable, curated memory plus the caller's own
workspace figures. This creates the two typed tables behind that promise —
``assistant_memory`` (shipped entries plus per-workspace additions) and
``assistant_conversations`` (the caller's own short question history) — and
grants ``assistant:read`` to every existing role so every user keeps the help
they already had, while ``assistant:manage`` goes to owners only.

Revision ID: a2c5d8f14b30
Revises: e1b4f7a92c35
Create Date: 2026-11-13
"""

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "a2c5d8f14b30"
down_revision: Union[str, None] = "e1b4f7a92c35"
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
ORGANIZATIONS = sa.table(
    "organizations",
    sa.column("id", sa.String(36)),
)


def upgrade() -> None:
    op.create_table(
        "assistant_memory",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("memory_key", sa.String(80), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("category", sa.String(20), nullable=False, server_default="faq"),
        sa.Column("keywords", sa.String(400), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("steps", sa.Text(), nullable=False, server_default=""),
        sa.Column("route", sa.String(200), nullable=False, server_default=""),
        sa.Column("permission", sa.String(80), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_by_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "memory_key", name="uq_assistant_memory_key"),
    )
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("intent", sa.String(60), nullable=False, server_default=""),
        sa.Column("memory_key", sa.String(80), nullable=False, server_default=""),
        sa.Column("route", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    bind = op.get_bind()
    organizations = bind.execute(sa.select(ORGANIZATIONS.c.id)).scalars().all()
    for organization_id in organizations:
        read_id = str(uuid4())
        manage_id = str(uuid4())
        created_at = datetime.now(timezone.utc)
        bind.execute(PERMISSIONS.insert(), [
            {"id": read_id, "organization_id": organization_id, "key": "assistant:read",
             "description": "Ask the in-application guide", "created_at": created_at},
            {"id": manage_id, "organization_id": organization_id, "key": "assistant:manage",
             "description": "Record workspace memory for the in-application guide", "created_at": created_at},
        ])
        roles = bind.execute(
            sa.select(ROLES.c.id, ROLES.c.is_owner).where(ROLES.c.organization_id == organization_id)
        ).all()
        grants = []
        for role_id, is_owner in roles:
            grants.append({"role_id": role_id, "permission_id": read_id})
            if is_owner:
                grants.append({"role_id": role_id, "permission_id": manage_id})
        if grants:
            bind.execute(ROLE_PERMISSIONS.insert(), grants)


def downgrade() -> None:
    bind = op.get_bind()
    keys = ("assistant:read", "assistant:manage")
    permission_ids = bind.execute(
        sa.select(PERMISSIONS.c.id).where(PERMISSIONS.c.key.in_(keys))
    ).scalars().all()
    if permission_ids:
        bind.execute(ROLE_PERMISSIONS.delete().where(ROLE_PERMISSIONS.c.permission_id.in_(permission_ids)))
        bind.execute(PERMISSIONS.delete().where(PERMISSIONS.c.id.in_(permission_ids)))
    op.drop_table("assistant_conversations")
    op.drop_table("assistant_memory")
