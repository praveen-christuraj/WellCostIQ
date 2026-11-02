-- Run with psql -X -v ON_ERROR_STOP=1 -f scripts/postgres-inventory.sql.
-- Contains no connection string or password; save output outside the repository.
SELECT version();
SELECT * FROM pg_available_extensions ORDER BY name;
SELECT extname, extversion FROM pg_extension ORDER BY extname;
SELECT current_user, current_database();
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication
FROM pg_roles WHERE rolname IN ('wellcosting_app', 'wellcosting_migrator');
