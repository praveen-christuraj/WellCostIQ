"""Make existing audit history append-only without moving or changing rows.

Revision ID: f2a6c8d41e07
Revises: f1d7a4c95b23
Create Date: 2026-11-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f2a6c8d41e07"  # pragma: allowlist secret - Alembic revision ID, not a credential.
down_revision: Union[str, None] = "f1d7a4c95b23"  # pragma: allowlist secret - Parent revision ID.
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # This migration intentionally contains no data DML and no table move. The
    # migration role owns public.audit_logs in the supported deployment. Hosted
    # databases with differently named roles are left for their DBA runbook.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.audit_logs') IS NOT NULL
               AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wellcosting_app') THEN
                REVOKE UPDATE, DELETE ON TABLE public.audit_logs FROM wellcosting_app;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wellcosting_app')
               AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wellcosting_migrator') THEN
                CREATE SCHEMA IF NOT EXISTS audit;
                GRANT USAGE, CREATE ON SCHEMA audit TO wellcosting_migrator;
                GRANT USAGE ON SCHEMA audit TO wellcosting_app;
                ALTER DEFAULT PRIVILEGES FOR ROLE wellcosting_migrator IN SCHEMA audit
                    GRANT SELECT, INSERT ON TABLES TO wellcosting_app;
                ALTER DEFAULT PRIVILEGES FOR ROLE wellcosting_migrator IN SCHEMA audit
                    GRANT USAGE, SELECT ON SEQUENCES TO wellcosting_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # Restore only the former table grants. Never drop the audit schema: a later
    # migration may have placed data there, and downgrade must not destroy it.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.audit_logs') IS NOT NULL
               AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wellcosting_app') THEN
                GRANT UPDATE, DELETE ON TABLE public.audit_logs TO wellcosting_app;
            END IF;
        END
        $$;
        """
    )
