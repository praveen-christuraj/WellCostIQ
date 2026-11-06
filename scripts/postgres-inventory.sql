-- Run with psql -X -v ON_ERROR_STOP=1 -f scripts/postgres-inventory.sql.
-- Contains no connection string or password; save output outside the repository.
SELECT version();
SELECT * FROM pg_available_extensions ORDER BY name;
SELECT extname, extversion FROM pg_extension ORDER BY extname;
SELECT current_user, current_database();
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolconnlimit, rolconfig
FROM pg_roles WHERE rolname IN ('wellcosting_app', 'wellcosting_migrator');

-- Expected application audit privileges: SELECT and INSERT only. Historic rows
-- remain in public.audit_logs; no table move or data rewrite is required.
SELECT grantee, table_schema, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE table_name = 'audit_logs' AND grantee IN ('wellcosting_app', 'wellcosting_migrator')
ORDER BY grantee, privilege_type;

-- Session values are collected for the current connection. Application runtime
-- connections set statement_timeout=120s, idle_in_transaction=60s, lock=10s.
SELECT name, setting, unit FROM pg_settings
WHERE name IN ('statement_timeout', 'idle_in_transaction_session_timeout', 'lock_timeout', 'max_connections')
ORDER BY name;

SELECT nspname AS schema_name,
       has_schema_privilege('wellcosting_app', nspname, 'USAGE') AS app_usage,
       has_schema_privilege('wellcosting_migrator', nspname, 'CREATE') AS migrator_create
FROM pg_namespace WHERE nspname IN ('public', 'audit') ORDER BY nspname;
