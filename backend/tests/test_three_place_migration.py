"""Exercise an actual Alembic transition with legacy costing data on SQLite."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

PREVIOUS = 'b4d621f389aa'
REVISION = 'c1d9e5a4f702'


def test_legacy_rounding_positive_preflight_and_downgrade(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{path}'}

    def migrate(action, target):
        return subprocess.run(
            [sys.executable, '-m', 'alembic', action, target],
            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=90,
        )

    result = migrate('upgrade', PREVIOUS)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute("INSERT INTO organizations (id,name,slug,created_at) VALUES ('org','Legacy','legacy',CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO rigs (id,organization_id,rig_code,rig_name,created_at,updated_at) VALUES ('rig','org','R','Rig',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO blocks (id,organization_id,block_code,block_name,created_at,updated_at) VALUES ('block','org','B','Block',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO wells (id,organization_id,rig_id,well_code,well_name,well_location,block_id,objective,created_at,updated_at) VALUES ('well','org','rig','W','Well','Location','block','Objective',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO afes (id,organization_id,rig_id,well_id,afe_code,afe_name,afe_type,created_at,updated_at) VALUES ('afe','org','rig','well','AFE','Estimate','Drilling',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO afe_exchange_rates (id,organization_id,afe_id,currency_code,rate,created_at,updated_at) VALUES ('fx','org','afe','EUR',0.0004,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO services (id,organization_id,service_code,service_name,service_category,provider_type,created_at,updated_at) VALUES ('svc','org','SVC','Mud Logging','Drilling Services','In House Services',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO ops_plan_versions (id,organization_id,well_id,scope,version_no,label,basis,status,planned_days,prepared_by,approved_by,notes,is_deleted,created_at,updated_at,created_by,updated_by) VALUES ('plan','org','well','drilling',1,'Programme','engineer','draft',1.2345,'','','',false,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'','')")
        # Second programme whose ten-place value must NOT round up, and a whole
        # number that must stay an integer rather than become a float.
        db.execute("INSERT INTO ops_plan_versions (id,organization_id,well_id,scope,version_no,label,basis,status,planned_days,prepared_by,approved_by,notes,is_deleted,created_at,updated_at,created_by,updated_by) VALUES ('plan-hold','org','well','drilling',2,'Programme','engineer','draft',1.2344,'','','',false,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'','')")
        db.execute("INSERT INTO ops_plan_versions (id,organization_id,well_id,scope,version_no,label,basis,status,planned_days,prepared_by,approved_by,notes,is_deleted,created_at,updated_at,created_by,updated_by) VALUES ('plan-int','org','well','drilling',3,'Programme','engineer','draft',7,'','','',false,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'','')")
    rejected = migrate('upgrade', REVISION)
    assert rejected.returncode != 0 and 'FX rate that would round to zero' in rejected.stderr
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == (PREVIOUS,)
        assert db.execute("SELECT planned_days FROM ops_plan_versions WHERE id='plan'").fetchone() == (1.2345,)
        db.execute("UPDATE afe_exchange_rates SET rate=0.0005 WHERE id='fx'")

        db.execute("INSERT INTO invoice_payment_terms (id,organization_id,term_code,term_name,created_at,updated_at) VALUES ('term','org','TERM','Payment term',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO invoice_payment_term_splits (id,organization_id,term_id,currency_code,percentage) VALUES ('split','org','term','USD',0.0004)")
        db.execute("INSERT INTO invoice_payment_term_splits (id,organization_id,term_id,currency_code,percentage) VALUES ('split-rest','org','term','NGN',99.9996)")

    rejected = migrate('upgrade', REVISION)
    assert rejected.returncode != 0 and 'payment split that would round to zero' in rejected.stderr
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == (PREVIOUS,)
        assert db.execute("SELECT rate FROM afe_exchange_rates WHERE id='fx'").fetchone() == (0.0005,)
        db.execute("UPDATE invoice_payment_term_splits SET percentage=0.001 WHERE id='split'")
        db.execute("UPDATE invoice_payment_term_splits SET percentage=99.999 WHERE id='split-rest'")

    applied = migrate('upgrade', 'head')
    assert applied.returncode == 0, applied.stderr
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute("SELECT rate FROM afe_exchange_rates WHERE id='fx'").fetchone() == (0.001,)
        # Half away from zero, decided by the stored value and not by the SQLite
        # build: round(1.2345, 3) is 1.235 before SQLite 3.43 and 1.234 from 3.43
        # because the double sits just under the half.  The ledger must not differ
        # between the two.
        assert db.execute("SELECT planned_days FROM ops_plan_versions WHERE id='plan'").fetchone() == (1.235,)
        assert db.execute("SELECT planned_days FROM ops_plan_versions WHERE id='plan-hold'").fetchone() == (1.234,)
        assert db.execute("SELECT planned_days FROM ops_plan_versions WHERE id='plan-int'").fetchone() == (7,)
        assert db.execute("SELECT typeof(planned_days) FROM ops_plan_versions WHERE id='plan-int'").fetchone() == ('integer',)
        assert dict((name, sql_type) for _, name, sql_type, *_ in db.execute('PRAGMA table_info(afe_exchange_rates)'))['rate'] == 'NUMERIC(28, 3)'
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO services (id,organization_id,service_code,service_name,service_category,provider_type,created_at,updated_at) VALUES ('second','org','SVC2','mud logging','Drilling Services','In House Services',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        assert 'source_activity_code' in {row[1] for row in db.execute('PRAGMA table_info(ops_activity_blocks)')}

    undone = migrate('downgrade', PREVIOUS)
    assert undone.returncode == 0, undone.stderr
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute("SELECT planned_days FROM ops_plan_versions WHERE id='plan'").fetchone() == (1.235,)
        assert db.execute("SELECT planned_days FROM ops_plan_versions WHERE id='plan-int'").fetchone() == (7,)
        assert 'source_activity_code' not in {row[1] for row in db.execute('PRAGMA table_info(ops_activity_blocks)')}
