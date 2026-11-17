"""Merge operations

Revision ID: 830ae530918e
Revises: a1b2c3d4e5f7, d6a2b8c3e901
Create Date: 2026-11-17 17:57:19.058844
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '830ae530918e'
down_revision: Union[str, None] = ('a1b2c3d4e5f7', 'd6a2b8c3e901')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
