#!/bin/sh
# Fresh-cluster initialization only. Existing databases need the migration runbook.
set -eu
: "${DB_APP_PASSWORD:?DB_APP_PASSWORD must be set}"
: "${DB_MIGRATION_PASSWORD:?DB_MIGRATION_PASSWORD must be set}"
if [ "$DB_APP_PASSWORD" = "$DB_MIGRATION_PASSWORD" ] || [ "$DB_APP_PASSWORD" = "$POSTGRES_PASSWORD" ] || [ "$DB_MIGRATION_PASSWORD" = "$POSTGRES_PASSWORD" ]; then
  echo "Database administrator, migrator and application passwords must be distinct." >&2
  exit 1
fi
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
BEGIN;
\getenv app_password DB_APP_PASSWORD
\getenv migration_password DB_MIGRATION_PASSWORD
CREATE ROLE wellcosting_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'migration_password';
CREATE ROLE wellcosting_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
REVOKE ALL ON DATABASE wellcosting FROM PUBLIC;
GRANT CONNECT ON DATABASE wellcosting TO wellcosting_app, wellcosting_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO wellcosting_migrator;
GRANT USAGE ON SCHEMA public TO wellcosting_app;
ALTER DEFAULT PRIVILEGES FOR ROLE wellcosting_migrator IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO wellcosting_app;
ALTER DEFAULT PRIVILEGES FOR ROLE wellcosting_migrator IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO wellcosting_app;
COMMIT;
SQL
