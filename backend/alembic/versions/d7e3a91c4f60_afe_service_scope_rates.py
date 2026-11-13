"""Configure one Day Rate service across every section and phase in one dialog.

A Day Rate service used to hold one set of unit rates per service line, so a
service with three different section rates had to be entered three times. The
estimate now keeps four new column-wise tables:

* ``afe_service_scope_rates`` — the unit rate for one (section, optional phase)
  and charge category, overriding the shared rate for that scope;
* ``afe_service_scope_days`` — explicit days (or hours) for one (section,
  optional phase) and charge category;
* ``afe_sow_service_scope_rates`` / ``afe_sow_service_scope_days`` — the same
  two shapes on the two-sided SOW revision lines, so a revision mirrors the
  estimate exactly.

Nothing existing is rewritten: stored shared rates, charges and section rates
keep their meaning, and every row gains no new nullable column. The report
totals a service once per (section, phase, activity, sub activity) in code, so
the change is additive.

Revision ID: d7e3a91c4f60
Revises: c4d5e6f7a8b9
Create Date: 2026-11-12 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd7e3a91c4f60'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORG = sa.String(36)
CHARGE_CATEGORIES_SQL = (
    "'Mobilization', 'Demobilization', 'Operation', 'Standby', "
    "'Personnel-Operation', 'Personnel-Standby', 'Fixed Charge', 'Others'"
)

def _org_column() -> sa.Column:
    return sa.Column('organization_id', ORG, sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)


def _child_header_columns() -> list[sa.Column]:
    """The columns every AFE/SOW child row carries, in model order."""
    return [
        sa.Column('id', sa.String(36), primary_key=True),
        _org_column(),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'afe_service_scope_rates',
        *_child_header_columns(),
        sa.Column('line_id', sa.String(36), sa.ForeignKey('afe_service_lines.id', ondelete='CASCADE'), nullable=False),
        sa.Column('hole_section_id', sa.String(36), sa.ForeignKey('hole_sections.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('phases.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('charge_category', sa.String(40), nullable=False),
        sa.Column('unit_rate', sa.Numeric(28, 10), server_default='0', nullable=False),
        sa.UniqueConstraint(
            'line_id', 'hole_section_id', 'phase_id', 'charge_category', name='uq_afe_service_scope_rates_scope'
        ),
        sa.CheckConstraint(f'charge_category IN ({CHARGE_CATEGORIES_SQL})', name='ck_afe_service_scope_rates_category'),
        sa.CheckConstraint('unit_rate >= 0', name='ck_afe_service_scope_rates_rate'),
    )
    op.create_index('ix_afe_service_scope_rates_line_id', 'afe_service_scope_rates', ['line_id'])
    op.create_index('ix_afe_service_scope_rates_org', 'afe_service_scope_rates', ['organization_id'])
    op.create_index('ix_afe_service_scope_rates_section', 'afe_service_scope_rates', ['hole_section_id'])
    op.create_index('ix_afe_service_scope_rates_phase', 'afe_service_scope_rates', ['phase_id'])
    
    op.create_table(
        'afe_service_scope_days',
        *_child_header_columns(),
        sa.Column('line_id', sa.String(36), sa.ForeignKey('afe_service_lines.id', ondelete='CASCADE'), nullable=False),
        sa.Column('charge_category', sa.String(40), nullable=False),
        sa.Column('hole_section_id', sa.String(36), sa.ForeignKey('hole_sections.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('phases.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('quantity', sa.Numeric(28, 10), server_default='0', nullable=False),
        sa.Column('quantity_unit', sa.String(10), server_default='days', nullable=False),
        sa.CheckConstraint(f'charge_category IN ({CHARGE_CATEGORIES_SQL})', name='ck_afe_service_scope_days_category'),
        sa.CheckConstraint("quantity_unit IN ('days', 'hours')", name='ck_afe_service_scope_days_unit'),
        sa.CheckConstraint('quantity >= 0', name='ck_afe_service_scope_days_qty'),
    )
    op.create_index('ix_afe_service_scope_days_line_id', 'afe_service_scope_days', ['line_id'])
    op.create_index('ix_afe_service_scope_days_org', 'afe_service_scope_days', ['organization_id'])
    op.create_index('ix_afe_service_scope_days_section', 'afe_service_scope_days', ['hole_section_id'])
    op.create_index('ix_afe_service_scope_days_phase', 'afe_service_scope_days', ['phase_id'])
    
    op.create_table(
        'afe_sow_service_scope_rates',
        *_child_header_columns(),
        sa.Column(
            'line_id', sa.String(36), sa.ForeignKey('afe_sow_service_lines.id', ondelete='CASCADE'), nullable=False
        ),
        sa.Column('hole_section_id', sa.String(36), sa.ForeignKey('hole_sections.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('phases.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('charge_category', sa.String(40), nullable=False),
        sa.Column('unit_rate', sa.Numeric(28, 10), server_default='0', nullable=False),
        sa.UniqueConstraint(
            'line_id', 'hole_section_id', 'phase_id', 'charge_category', name='uq_afe_sow_scope_rates_scope'
        ),
        sa.CheckConstraint(f'charge_category IN ({CHARGE_CATEGORIES_SQL})', name='ck_afe_sow_scope_rates_category'),
        sa.CheckConstraint('unit_rate >= 0', name='ck_afe_sow_scope_rates_rate'),
    )
    op.create_index('ix_afe_sow_service_scope_rates_line_id', 'afe_sow_service_scope_rates', ['line_id'])
    op.create_index('ix_afe_sow_service_scope_rates_org', 'afe_sow_service_scope_rates', ['organization_id'])
    op.create_index('ix_afe_sow_service_scope_rates_section', 'afe_sow_service_scope_rates', ['hole_section_id'])
    op.create_index('ix_afe_sow_service_scope_rates_phase', 'afe_sow_service_scope_rates', ['phase_id'])

    op.create_table(
        'afe_sow_service_scope_days',
        *_child_header_columns(),
        sa.Column(
            'line_id', sa.String(36), sa.ForeignKey('afe_sow_service_lines.id', ondelete='CASCADE'), nullable=False
        ),
        sa.Column('charge_category', sa.String(40), nullable=False),
        sa.Column('hole_section_id', sa.String(36), sa.ForeignKey('hole_sections.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('phases.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('quantity', sa.Numeric(28, 10), server_default='0', nullable=False),
        sa.Column('quantity_unit', sa.String(10), server_default='days', nullable=False),
        sa.CheckConstraint(f'charge_category IN ({CHARGE_CATEGORIES_SQL})', name='ck_afe_sow_scope_days_category'),
        sa.CheckConstraint("quantity_unit IN ('days', 'hours')", name='ck_afe_sow_scope_days_unit'),
        sa.CheckConstraint('quantity >= 0', name='ck_afe_sow_scope_days_qty'),
    )
    op.create_index('ix_afe_sow_service_scope_days_line_id', 'afe_sow_service_scope_days', ['line_id'])
    op.create_index('ix_afe_sow_service_scope_days_org', 'afe_sow_service_scope_days', ['organization_id'])
    op.create_index('ix_afe_sow_service_scope_days_section', 'afe_sow_service_scope_days', ['hole_section_id'])
    op.create_index('ix_afe_sow_service_scope_days_phase', 'afe_sow_service_scope_days', ['phase_id'])


def downgrade() -> None:
    op.drop_table('afe_sow_service_scope_days')
    op.drop_table('afe_sow_service_scope_rates')
    op.drop_table('afe_service_scope_days')
    op.drop_table('afe_service_scope_rates')
