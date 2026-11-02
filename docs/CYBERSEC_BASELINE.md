# CyberSec baseline and final-review handover

This implements the repository controls requested in the supplied baseline review. It changes application build/deployment files; it does not change anyone's installed VS Code, Docker Desktop, or managed database. No production database has been upgraded.

## Selected versions

| Component | Repository baseline | Rationale |
|---|---|---|
| Python | 3.12.16 | Recommended patch within the existing 3.12 series; avoid an unnecessary 3.15 migration. `.python-version`, Render, CI and the backend image agree. |
| Node.js | 22.23.4 | Recommended patch within the existing Node 22 series; avoid an unnecessary Node 26 migration. `.node-version`, `.nvmrc`, frontend engines, Docker and CI agree. |
| PostgreSQL in Compose | 18.6, Alpine 3.24 | Exact upstream tag and manifest digest. See the required major-version migration below. |
| Nginx | 1.30.6, Alpine 3.24 | Replace the old 1.27 image with the verified stable image and run without root on port 8080. |
| VS Code / Docker Desktop | Retain the reviewed workstation versions | Keep VS Code automatic updates enabled and Docker Desktop current. `docs/vscode-user-settings.example.json` provides the user-level settings for normal updates and Workspace Trust; workspace settings cannot enforce these application-level controls. Their actual installed versions and extensions must be collected on the workstation. |

Docker base images use exact tags plus verified upstream multi-platform manifest digests. A base-image digest differs from a locally built application's image ID. Regenerate both image references and the evidence after an approved base-image update. A mutable tag such as `latest` is not a baseline.

## Dependencies and clean installs

- `frontend/package-lock.json` is the committed Node resolution. Run `npm ci` in `frontend`; changing dependencies intentionally requires updating both manifests and repeating the audit/build. Vercel also explicitly uses `npm ci` via `frontend/vercel.json`; select Node 22.x in the project settings and verify its actual patch meets the package engine requirement. The shared DOM checks now use a locked **development** dependency for jsdom instead of installing it ad hoc.
- `backend/requirements.in` lists direct production dependencies. `backend/requirements.txt` is the fully pinned, SHA-256-hashed production lock generated with pip-compile. Test libraries are in `requirements-dev.in` / `requirements-dev.txt`; compilers and scanners are in `requirements-tools.in` / `requirements-tools.txt`. `requirements.lock` is a compatibility include of the canonical production lock, not a second resolution.
- Install with `python -m pip install --require-hashes -r backend/requirements.txt` for production, or `--require-hashes -r backend/requirements-dev.txt` for tests. Create an isolated tools virtualenv and install `--require-hashes -r backend/requirements-tools.txt` there. Scanners and test tools are not shipped in the API image.
- The frontend runtime is static Nginx: it contains the compiled assets and **no Node, npm or node_modules**. `npm ci` includes development tools in the discarded build stage because Vite and TypeScript are required to build. `npm ci --omit=dev` is appropriate for a Node runtime, not for this build stage.
- `.npmrc` pins the public registry with strict TLS. It is also present in `frontend` because npm uses that project's configuration. No internal scope or private registry has been supplied; do not invent one. If internal packages are introduced, bind their actual scopes to the approved private registry (or use it as the default for unscoped internal packages). Keep authentication in user/CI secret configuration. For Python use an **exclusive** approved index and never `--extra-index-url`.

The committed Python locks target Python 3.12 on Linux (the production container/CI platform). Use Docker or WSL for the same reviewed environment on Windows; native Windows needs its own generated/reviewed platform lock because uvicorn standard extras differ by platform.

Regenerate locks using the pinned tools environment on Python 3.12:

```sh
.security-tools/bin/pip-compile --generate-hashes --strip-extras --index-url=https://pypi.org/simple --output-file=backend/requirements.txt backend/requirements.in
.security-tools/bin/pip-compile --generate-hashes --strip-extras --index-url=https://pypi.org/simple --output-file=backend/requirements-dev.txt backend/requirements-dev.in
.security-tools/bin/pip-compile --generate-hashes --allow-unsafe --strip-extras --index-url=https://pypi.org/simple --output-file=backend/requirements-tools.txt backend/requirements-tools.in
```

`--allow-unsafe` here tells pip-compile to pin and hash its own pip/setuptools dependencies; it does not disable installation hash checks.

Keep existing pins when no advisory requires a change. To update a particular dependency, use `pip-compile --upgrade-package PACKAGE` with the same output/inputs, regenerate the dependent dev lock, audit, clean-install and test. Do not use forced npm fixes, legacy peer dependency flags, unhashed freeze output, or `pip install --no-deps`.

## Container and PostgreSQL deployment

The API and frontend build/runtime stages declare non-root users before copying application code. Production API files are root-owned and read-only to the API account. Both application services use read-only root filesystems, temporary writable storage, dropped Linux capabilities, and `no-new-privileges`. The images accept an optional BuildKit `proxy_ca` secret for environments with a corporate CA; it exists only during dependency installation and is not copied into image layers. TLS verification stays enabled.

Compose uses Docker PostgreSQL, not a local database installation:

- Volume: `<compose-project>_postgres18_data`, mounted at `/var/lib/postgresql`; upstream PostgreSQL 18 stores PGDATA in its versioned subdirectory. Inspect the actual volume mount with `docker volume inspect <compose-project>_postgres18_data`; do not assume a particular host storage-driver path.
- PostgreSQL has **no host port mapping**. Only services on the Compose backend network can reach it. If a temporary administrator port is necessary, bind it explicitly to `127.0.0.1`, never all interfaces.
- `postgres` is the cluster administrator. The application never receives its password. Supply three **different**, strong passwords in an uncommitted `.env`: `POSTGRES_PASSWORD`, `DB_MIGRATION_PASSWORD`, and `DB_APP_PASSWORD`. Hex passwords generated independently with `openssl rand -hex 32` are URL-safe; URL-encode other passwords used inside database URLs.
- `scripts/postgres-init-roles.sh` creates `wellcosting_migrator` (schema creation/ownership) and `wellcosting_app` (connection, schema usage, table DML and sequence access). Neither may create databases/roles, replicate, or act as a superuser. Objects created by the migration role automatically grant the API its required DML rights.
- The one-shot `migrate` service runs Alembic with the migration credential. The API starts only after that service exits successfully and uses the application credential. It does not run migrations with runtime credentials.
- Web traffic binds to `127.0.0.1:8080` by default. Put the approved HTTPS reverse proxy in front of it; for a remote/container edge, deliberately configure `WEB_BIND_ADDRESS` and the firewall for that topology. Existing secure-cookie, HTTPS CORS and trusted-proxy production controls still apply.

### Existing PostgreSQL 16/17 databases: operator migration required

Do **not** delete the old volume, run `down -v`, or reuse its data directory with PostgreSQL 18. The new volume name protects the old files; it does **not** migrate their contents. Existing deployments must not be restarted with this new Compose file until this procedure is planned:

1. Record the old image/version, database size, extensions and actual volume mounts. Take a database backup with the old, working deployment and prove that it restores. Stop application writes during the final cutover; retain the old stack and volume for recovery.
2. Start PostgreSQL 18.6 on a fresh volume in an isolated migration environment and create the two roles. Review extension availability/compatibility before restoring. Use a logical dump of the application database with `--no-owner --no-acl`; restore it as `wellcosting_migrator` so tables/sequences belong to the migration role. Do not restore the old cluster superuser roles wholesale.
3. Grant the application `SELECT, INSERT, UPDATE, DELETE` on **all existing tables** and `USAGE, SELECT` on **all existing sequences** in `public`; default privileges only apply to future objects. Run Alembic as the migration role. Confirm row counts, application sign-in, read/write/export/backup workflows and role restrictions in staging.
4. Update the production secrets and connection URLs, cut over deliberately, and retain the old volume and backup according to the approved retention policy. Changing database passwords in `.env` alone does not rotate passwords in an existing cluster.

The hosted Render/Supabase path is separate: its actual PostgreSQL version and extensions are controlled by the provider. This repository cannot upgrade that service. Before deploying the updated Blueprint, have the database administrator create equivalent migration and restricted application roles for the provider's actual database, assign existing object privileges, and set **both** `MIGRATION_DATABASE_URL` and `DATABASE_URL` as Render secrets. `backend/start-hosted.sh` runs Alembic with the migration connection, removes that variable, then execs Uvicorn using only the application connection. It rejects missing or identical connections. Different URLs alone do not prove different roles: the provider-side grants and resulting roles still require live verification. Do not place the cluster administrator credential in either URL. Existing Render services must update their start command to `sh start-hosted.sh`; changing the Blueprint file alone does not guarantee the service settings were reapplied.

## Evidence to send for final review

Send the review ZIP prepared with this change, or collect these files while preserving their paths:

1. **Node:** `frontend/package.json`, `frontend/package-lock.json`, root and frontend `.npmrc`, `.node-version`, `.nvmrc`.
2. **Python:** all `backend/requirements*.in` / `backend/requirements*.txt`, the compatibility `backend/requirements.lock`, `.python-version`, and `backend/pyproject.toml`.
3. **Deployment/security configuration:** both Dockerfiles and per-service `.dockerignore` files, root `.dockerignore`, `docker-compose.yml`, `frontend/nginx.conf`, `frontend/proxy_params_wcp.conf`, `frontend/vercel.json`, `render.yaml`, `.github/workflows/security.yml`, `.gitignore`, and **only the redacted `.env.example` files**. Never attach real `.env`, keys, certificates containing private keys, connection credentials, or database dumps.
4. **Operational review:** this document, the fresh validation results, role-initialization and PostgreSQL-inventory scripts, `backend/start-hosted.sh`, the collection script, optional hook scripts, VS Code user-settings example, and updated deployment instructions.
5. **Generated evidence:** `npm-audit-report.json`, `pip-audit-report.json`, secret-scan results for triage, each built application's image ID (plus a registry digest only if pushed), and package inventories. Reports describe the date and environment scanned, not a permanent guarantee.
6. **Required from the real deployment/workstation:** PostgreSQL `SELECT version()`, `SELECT * FROM pg_available_extensions`, `SELECT extname, extversion FROM pg_extension`; actual database deployment/volume information; `code --list-extensions --show-versions`; actual VS Code and Docker Desktop versions. Disposable test-database inventories are labelled as test evidence and must not be presented as production inventory.

Run the collector on the machine being reviewed with the pinned Node/tools environment on PATH:

```sh
python scripts/collect-cybersec-evidence.py --output /path/outside/repo/review-evidence \
  --tools-bin /path/to/security-tools/bin \
  --image wellcostiq-api:YOUR-IMMUTABLE-TAG \
  --image wellcostiq-web:YOUR-IMMUTABLE-TAG \
  --pg-service YOUR_APPROVED_SERVICE_NAME
```

The collector records missing tools, unavailable inventories and scan exit codes in `collection-status.json`; missing evidence is not a clean scan. PostgreSQL credentials belong in the operator's secure PostgreSQL service/pass configuration. The collector never dumps Docker container environment variables.

Build local images with an immutable release/git tag, then record their IDs:

```sh
docker build -t wellcostiq-api:RELEASE-GITSHA backend
docker build -t wellcostiq-web:RELEASE-GITSHA frontend
docker image inspect --format '{{.Id}} {{json .RepoDigests}}' wellcostiq-api:RELEASE-GITSHA
```

A locally built image may have no RepoDigests; report its image ID and do not invent a registry digest. The review build tag in the supplied evidence is a disposable test tag; use a release/git tag for a real deployment.

## Secrets, scans and quarterly checks

`.gitignore` and Docker ignore files exclude environments, virtualenvs, dependencies, private keys and local evidence. A native opt-in pre-commit hook checks the **staged bytes** with the pinned detect-secrets tool; activate with `git config core.hooksPath .githooks` after putting the tools environment on PATH. It does not suppress findings or automatically create an acceptance baseline. Legacy scan matches (including example/test credentials and revision identifiers) remain visible for triage; a scan match is not automatically a confirmed leaked credential. Confirmed secrets require removal and rotation. Exceptions with actual residual risk require CyberSec ownership and expiry, never developer-only acceptance.

CI uses clean lockfile installs and runs dependency scans, backend tests, frontend security tests and a production build. It uploads audit JSON even on failure. npm audit covers registry advisories and pip-audit covers its selected advisory service; neither replaces OS/container scans, secret-history scanning or penetration testing.

Each quarter, run the collector again, then capture `python -m pip list --outdated` **in the relevant application environment** (not the scanner tools environment) to `pip-outdated-q.txt`. Save everything outside the repository and forward the snapshots for correlation. Install only needed VS Code extensions from verified publishers; the supplied workstation extension list requires reviewer approval. No quarterly automation or messages have been enabled by this change.
