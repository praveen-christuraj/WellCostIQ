# Files for CyberSec final review

Send the supplied review ZIP. It preserves these repository paths and includes fresh scan/build/test evidence. It contains no real `.env`, passwords, database dumps, private keys, dependencies or virtual environments.

## Manifests and runtime versions

- `frontend/package.json`
- `frontend/package-lock.json`
- `backend/requirements.in`
- `backend/requirements.txt` — canonical hashed production lock
- `backend/requirements-dev.in`
- `backend/requirements-dev.txt` — hashed test lock
- `backend/requirements-tools.in`
- `backend/requirements-tools.txt` — hashed compiler/scanner lock
- `backend/requirements.lock` — compatibility include
- `backend/pyproject.toml`
- `.python-version`, `.node-version`, `.nvmrc`
- `.npmrc`, `frontend/.npmrc`

## Build, deployment and security controls

- `backend/Dockerfile`, `frontend/Dockerfile`
- `.dockerignore`, `backend/.dockerignore`, `frontend/.dockerignore`
- `docker-compose.yml`
- `frontend/nginx.conf`, `frontend/proxy_params_wcp.conf`
- `frontend/vercel.json`, `render.yaml`, `backend/start-hosted.sh`
- `.github/workflows/security.yml`, `Makefile`, `docs/ci-template.yml`
- `.gitignore`, `.env.example`, `backend/.env.example` — examples only
- `.githooks/pre-commit`, `scripts/check-staged-secrets.py`
- `scripts/postgres-init-roles.sh`, `scripts/postgres-inventory.sql`
- `scripts/collect-cybersec-evidence.py`
- `docs/vscode-user-settings.example.json` — apply at user/application level after review

## Explanation and executed evidence

- `README.md`, `docs/deployment.md`
- `docs/CYBERSEC_BASELINE.md`
- `docs/CYBERSEC_VALIDATION_2026-11-02.md`
- `docs/CYBERSEC_REVIEW_FILES.md` (this checklist)
- `evidence/npm-audit-report.json`
- `evidence/pip-audit-report.json`
- `evidence/bandit-report.json`
- `evidence/secret-scan.json` — potential matches left visible for triage; reviewers need repository access for referenced application/test files outside this configuration bundle
- `evidence/api-image-identifier.txt`, `evidence/web-image-identifier.txt`
- `evidence/api-image-packages.txt`, `evidence/web-image-packages.txt`
- `evidence/image-pins.json` — upstream base-image tags and manifest digests
- `evidence/database-role-validation.json`
- `evidence/postgresql-test-inventory.txt`, `evidence/postgresql-test-volume.txt` — disposable test deployment only
- `evidence/web-runtime-validation.json`, `evidence/hosted-startup-validation.json`
- Build/test/clean-install logs and `evidence/collection-status.json`
- `SHA256SUMS` — checksums of the review snapshot

## Still required from your actual workstation and deployment

These cannot be substituted with cloud-test inventories:

1. The actual VS Code/Docker Desktop versions, confirmation of VS Code automatic updates, and `code --list-extensions --show-versions > vscode-extensions.txt`. Review extension publishers and remove unused extensions on the real workstation.
2. Production PostgreSQL deployment method and version, actual volume/storage information when containerized, and the output of `scripts/postgres-inventory.sql` on that database. The managed provider must confirm its own PostgreSQL upgrade/extension availability.
3. Live role/grant verification, configured Render/Vercel runtime/build settings, and final deployed image IDs/digests. The locally built review images were not pushed to a registry.
4. CyberSec triage of secret-scan matches and any required OS/container vulnerability scan. No suppression baseline or risk exception has been accepted automatically.
5. Approval and a tested backup/restore cutover before an existing PostgreSQL 16/17 database is moved to the new PostgreSQL 18 volume. Before Render deployment, provision the two database roles and both connection secrets and apply the new startup command.

Never attach real connection credentials, private keys, `.env` files or production data. Generated quarterly snapshots belong outside the repository; the evidence collector enforces that output location.
