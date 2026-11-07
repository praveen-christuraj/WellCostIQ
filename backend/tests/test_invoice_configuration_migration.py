"""The configuration extension preserves existing business and identity rows."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_invoice_configuration_migration_preserves_existing_rows(tmp_path):
    database = tmp_path / 'configuration.sqlite3'
    environment = {**os.environ, 'DATABASE_URL': f'sqlite:///{database}'}
    backend = Path(__file__).resolve().parents[1]

    def migrate(operation, target):
        result = subprocess.run([sys.executable, '-m', 'alembic', operation, target], cwd=backend,
                                env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    migrate('upgrade', 'c1d2e3f4a5b6')
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO invoice_locations (id, organization_id, location_name, created_at, updated_at) VALUES ('existing', 'org', 'Existing base', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        original = db.execute('SELECT * FROM invoice_locations').fetchall()
    migrate('upgrade', 'head')
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT * FROM invoice_locations').fetchall() == original
        assert db.execute('SELECT count(*) FROM invoice_descriptions').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM invoice_signatories').fetchone() == (0,)
    migrate('downgrade', 'c1d2e3f4a5b6')
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT * FROM invoice_locations').fetchall() == original
