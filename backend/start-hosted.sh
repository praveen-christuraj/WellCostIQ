#!/bin/sh
# Render/hosted startup: migrate before starting the API and drop the DDL credential.
set -eu
: "${DATABASE_URL:?Set DATABASE_URL to the restricted application role}"
: "${MIGRATION_DATABASE_URL:?Set MIGRATION_DATABASE_URL to the migration role}"
if [ "$DATABASE_URL" = "$MIGRATION_DATABASE_URL" ]; then
  echo 'Application and migration database connections must use distinct roles.' >&2
  exit 1
fi
DATABASE_URL="$MIGRATION_DATABASE_URL" alembic upgrade head
unset MIGRATION_DATABASE_URL
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --no-server-header
