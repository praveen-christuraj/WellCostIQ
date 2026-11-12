"""Add reusable record templates (AFE estimate, well plan, daily sheet).

Every value is stored column-wise; a template holds no JSON. Catalogue and plan
references are plain ids so Master Data cleanup never deletes a template.

Existing workspaces also receive the five new permission records, granted to
their owner role; other roles stay unchanged until an administrator assigns
them, exactly as the earlier capability migrations do.

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-11-12 09:00:00.000000
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORG = sa.String(36)

# Read is enough to pick a template and apply it; the rest gate authoring.
TEMPLATE_CAPABILITIES = {
    'template:read': 'Browse and apply reusable templates',
    'template:create': 'Save a new reusable template',
    'template:update': 'Edit or duplicate a reusable template',
    'template:delete': 'Delete a reusable template',
    'template:export': 'Export reusable templates and their usage audit',
}


def _org_column() -> sa.Column:
    return sa.Column('organization_id', ORG, sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)


def upgrade():
    op.create_table(
        'record_templates',
        sa.Column('id', sa.String(36), primary_key=True),
        _org_column(),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('template_kind', sa.String(20), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('name_key', sa.String(120), nullable=False),
        sa.Column('description', sa.String(500), server_default='', nullable=False),
        sa.Column('scope', sa.String(60), server_default='General', nullable=False),
        sa.Column('afe_type', sa.String(20), server_default='Drilling', nullable=False),
        sa.Column('standard_currency', sa.String(10), server_default='', nullable=False),
        sa.Column('is_shared', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('use_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(120), server_default='', nullable=False),
        sa.Column('updated_by', sa.String(120), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_by', sa.String(120), server_default='', nullable=False),
        sa.UniqueConstraint('organization_id', 'user_id', 'template_kind', 'name_key', name='uq_record_templates_owner_name'),
        sa.CheckConstraint("template_kind IN ('afe', 'well', 'daily-cost')", name='ck_record_templates_kind'),
    )
    op.create_index('ix_record_templates_organization_id', 'record_templates', ['organization_id'])
    op.create_index('ix_record_templates_user_id', 'record_templates', ['user_id'])
    op.create_index('ix_record_templates_org_kind_scope', 'record_templates', ['organization_id', 'template_kind', 'scope'])

    op.create_table(
        'record_template_services',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('template_id', sa.String(36), sa.ForeignKey('record_templates.id', ondelete='CASCADE'), nullable=False),
        _org_column(),
        sa.Column('service_id', sa.String(36), nullable=False),
        sa.Column('service_code', sa.String(60), server_default='', nullable=False),
        sa.Column('service_name', sa.String(200), server_default='', nullable=False),
        sa.Column('charging_basis', sa.String(30), server_default='Day Rate', nullable=False),
        sa.Column('section_code', sa.String(60), server_default='', nullable=False),
        sa.Column('phase_code', sa.String(60), server_default='', nullable=False),
        sa.Column('currency', sa.String(10), server_default='', nullable=False),
        sa.Column('service_amount', sa.String(40), server_default='0', nullable=False),
        sa.Column('operation_rate', sa.String(40), nullable=True),
        sa.Column('standby_rate', sa.String(40), nullable=True),
        sa.Column('repair_rate', sa.String(40), nullable=True),
        sa.Column('operation_days', sa.String(40), nullable=True),
        sa.Column('standby_days', sa.String(40), nullable=True),
        sa.Column('repair_days', sa.String(40), nullable=True),
        sa.Column('quantity_unit', sa.String(10), server_default='days', nullable=False),
        sa.Column('remarks', sa.String(500), server_default='', nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    )
    op.create_index('ix_record_template_services_template_id', 'record_template_services', ['template_id'])
    op.create_index('ix_record_template_services_organization_id', 'record_template_services', ['organization_id'])
    op.create_index('ix_record_template_services_template', 'record_template_services', ['template_id', 'sort_order'])

    op.create_table(
        'record_template_consumables',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('template_id', sa.String(36), sa.ForeignKey('record_templates.id', ondelete='CASCADE'), nullable=False),
        _org_column(),
        sa.Column('category', sa.String(30), nullable=False),
        sa.Column('section_code', sa.String(60), server_default='', nullable=False),
        sa.Column('phase_code', sa.String(60), server_default='', nullable=False),
        sa.Column('drill_bit_id', sa.String(36), nullable=True),
        sa.Column('drill_bit_code', sa.String(60), server_default='', nullable=False),
        sa.Column('drill_bit_name', sa.String(200), server_default='', nullable=False),
        sa.Column('quantity', sa.String(40), server_default='1', nullable=False),
        sa.Column('estimated_amount', sa.String(40), nullable=True),
        sa.Column('currency', sa.String(10), server_default='', nullable=False),
        sa.Column('remarks', sa.String(500), server_default='', nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    )
    op.create_index('ix_record_template_consumables_template_id', 'record_template_consumables', ['template_id'])
    op.create_index('ix_record_template_consumables_organization_id', 'record_template_consumables', ['organization_id'])
    op.create_index('ix_record_template_consumables_template', 'record_template_consumables', ['template_id', 'sort_order'])

    op.create_table(
        'record_template_tangibles',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('template_id', sa.String(36), sa.ForeignKey('record_templates.id', ondelete='CASCADE'), nullable=False),
        _org_column(),
        sa.Column('tangible_id', sa.String(36), nullable=False),
        sa.Column('tangible_code', sa.String(60), server_default='', nullable=False),
        sa.Column('tangible_name', sa.String(200), server_default='', nullable=False),
        sa.Column('quantity', sa.String(40), server_default='1', nullable=False),
        sa.Column('remarks', sa.String(500), server_default='', nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    )
    op.create_index('ix_record_template_tangibles_template_id', 'record_template_tangibles', ['template_id'])
    op.create_index('ix_record_template_tangibles_organization_id', 'record_template_tangibles', ['organization_id'])
    op.create_index('ix_record_template_tangibles_template', 'record_template_tangibles', ['template_id', 'sort_order'])

    op.create_table(
        'record_template_well_sections',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('template_id', sa.String(36), sa.ForeignKey('record_templates.id', ondelete='CASCADE'), nullable=False),
        _org_column(),
        sa.Column('hole_section_id', sa.String(36), nullable=False),
        sa.Column('section_code', sa.String(60), server_default='', nullable=False),
        sa.Column('section_name', sa.String(200), server_default='', nullable=False),
        sa.Column('from_depth', sa.Numeric(28, 10), server_default='0', nullable=False),
        sa.Column('to_depth', sa.Numeric(28, 10), server_default='0', nullable=False),
        sa.Column('depth_unit', sa.String(4), server_default='m', nullable=False),
        sa.Column('remarks', sa.String(500), server_default='', nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    )
    op.create_index('ix_record_template_well_sections_template_id', 'record_template_well_sections', ['template_id'])
    op.create_index('ix_record_template_well_sections_organization_id', 'record_template_well_sections', ['organization_id'])
    op.create_index('ix_record_template_well_sections_template', 'record_template_well_sections', ['template_id', 'sort_order'])

    op.create_table(
        'record_template_well_phases',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('section_id', sa.String(36), sa.ForeignKey('record_template_well_sections.id', ondelete='CASCADE'), nullable=False),
        _org_column(),
        sa.Column('phase_id', sa.String(36), nullable=False),
        sa.Column('phase_code', sa.String(60), server_default='', nullable=False),
        sa.Column('phase_name', sa.String(200), server_default='', nullable=False),
        sa.Column('days', sa.Numeric(28, 10), server_default='0', nullable=False),
        sa.Column('remarks', sa.String(500), server_default='', nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    )
    op.create_index('ix_record_template_well_phases_section_id', 'record_template_well_phases', ['section_id'])
    op.create_index('ix_record_template_well_phases_organization_id', 'record_template_well_phases', ['organization_id'])
    op.create_index('ix_record_template_well_phases_section', 'record_template_well_phases', ['section_id', 'sort_order'])

    _grant_capabilities()


def _grant_capabilities() -> None:
    bind = op.get_bind()
    organizations = sa.table('organizations', sa.column('id', sa.String(36)))
    permissions = sa.table(
        'permissions',
        sa.column('id', sa.String(36)),
        sa.column('organization_id', sa.String(36)),
        sa.column('key', sa.String(100)),
        sa.column('description', sa.String(500)),
        sa.column('created_at', sa.DateTime(timezone=True)),
    )
    roles = sa.table('roles', sa.column('id', sa.String(36)), sa.column('organization_id', sa.String(36)), sa.column('is_owner', sa.Boolean()))
    role_permissions = sa.table('role_permissions', sa.column('role_id', sa.String(36)), sa.column('permission_id', sa.String(36)))

    for (organization_id,) in bind.execute(sa.select(organizations.c.id)):
        owner_role_id = bind.execute(
            sa.select(roles.c.id).where(roles.c.organization_id == organization_id, roles.c.is_owner.is_(True))
        ).scalar_one_or_none()
        for key, description in TEMPLATE_CAPABILITIES.items():
            permission_id = bind.execute(
                sa.select(permissions.c.id).where(permissions.c.organization_id == organization_id, permissions.c.key == key)
            ).scalar_one_or_none()
            if permission_id is None:
                permission_id = str(uuid4())
                bind.execute(permissions.insert().values(
                    id=permission_id,
                    organization_id=organization_id,
                    key=key,
                    description=description,
                    created_at=datetime.now(timezone.utc),
                ))
            if owner_role_id:
                assigned = bind.execute(
                    sa.select(role_permissions.c.role_id).where(
                        role_permissions.c.role_id == owner_role_id,
                        role_permissions.c.permission_id == permission_id,
                    )
                ).first()
                if assigned is None:
                    bind.execute(role_permissions.insert().values(role_id=owner_role_id, permission_id=permission_id))


def downgrade():
    keys = tuple(TEMPLATE_CAPABILITIES)
    # Remove assignments before the permission rows they reference.
    op.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key IN :keys)").bindparams(sa.bindparam('keys', expanding=True, value=keys)))
    op.execute(sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(sa.bindparam('keys', expanding=True, value=keys)))
    op.drop_table('record_template_well_phases')
    op.drop_table('record_template_well_sections')
    op.drop_table('record_template_tangibles')
    op.drop_table('record_template_consumables')
    op.drop_table('record_template_services')
    op.drop_table('record_templates')
