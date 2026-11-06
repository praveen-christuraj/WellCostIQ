"""The audit grant revision must preserve existing UAT-style data exactly."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys


PREVIOUS_HEAD = "f1d7a4c95b23"  # pragma: allowlist secret - Alembic parent revision ID.


def test_audit_grant_migration_preserves_users_passwords_and_audit_rows(tmp_path):
    database = tmp_path / "audit-grants.sqlite3"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    backend = Path(__file__).resolve().parents[1]

    def migrate(operation: str, target: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", operation, target],
            cwd=backend,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    migrate("upgrade", PREVIOUS_HEAD)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES ('org-preserved', 'Preserved workspace', 'preserved', '2026-01-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO users (id, organization_id, email, full_name, password_hash, is_active, "
            "token_version, failed_logins, must_change_password, created_at) "
            "VALUES ('user-preserved', 'org-preserved', 'owner@preserved.example', 'Owner', "
            "'existing-argon2-hash-not-a-password', 1, 7, 0, 0, '2026-01-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO audit_logs (id, organization_id, actor_user_id, actor_email, actor_name, action, "
            "entity_type, entity_id, entity_label, summary, ip_address, user_agent, created_at) "
            "VALUES ('audit-preserved', 'org-preserved', 'user-preserved', 'owner@preserved.example', "
            "'Owner', 'update', 'well', 'well-1', 'Historic well', 'Original audit summary', "
            "'192.0.2.1', 'historic-agent', '2026-01-02 00:00:00')"
        )
        before = connection.execute(
            "SELECT users.id, users.password_hash, users.token_version, audit_logs.summary "
            "FROM users JOIN audit_logs ON audit_logs.actor_user_id = users.id"
        ).fetchall()

    migrate("upgrade", "head")
    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT users.id, users.password_hash, users.token_version, audit_logs.summary "
            "FROM users JOIN audit_logs ON audit_logs.actor_user_id = users.id"
        ).fetchall()
        assert after == before
        assert connection.execute("SELECT COUNT(*) FROM organizations").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone() == (1,)

    migrate("downgrade", PREVIOUS_HEAD)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT users.id, users.password_hash, users.token_version, audit_logs.summary "
            "FROM users JOIN audit_logs ON audit_logs.actor_user_id = users.id"
        ).fetchall() == before
