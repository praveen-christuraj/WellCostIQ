# Executed CyberSec baseline validation — 2026-11-02

Scope: repository build/deployment configuration, isolated cloud builds, a disposable PostgreSQL 18.6 Compose deployment, and temporary test environments. No production deployment, database upgrade, registry push, workstation upgrade or quarterly automation was performed.

| Check | Executed result |
|---|---|
| Recommended releases and Docker references | Node release metadata confirmed 22.23.4. Official Docker image metadata/registry manifests confirmed Python 3.12.16, Node 22.23.4, PostgreSQL 18.6 and Nginx stable 1.30.6. Exact tags/digests are in the Dockerfiles, Compose and `evidence/image-pins.json`. |
| Node clean install | `npm ci` succeeded using the committed manifests on Node 22.23.4. jsdom is now a locked development dependency. |
| Frontend dependency audit | `npm audit --json`: **0 known advisories**, including development dependencies. |
| Frontend security checks | `npm run test:security` passed (CSV/XLSX formula neutralization, limits, quoting and XLSX text round trip). |
| Frontend build | TypeScript and Vite production build passed on Node 22.23.4. Existing chunk-size performance warnings remain. |
| Shared UI checks | **33 passed** in light/dark modes using the locked jsdom dependency. |
| Production Python audit | `pip-audit -r backend/requirements.txt`: **0 known advisories** across **36** pinned production dependencies. |
| Python locks | Canonical production lock generated with hashes; dev/test has **44** dependencies and exactly matches all production pins; isolated tools has **39** fully pinned/hashed dependencies, including pip/setuptools. Production versions were retained rather than broadly upgrading unrelated libraries. |
| Hash-verified clean Python install | Fresh Python **3.12.16** container installed `requirements-dev.txt` with `--require-hashes`; `pip check` reported no broken requirements. |
| Backend full regression | **326 passed**, 282 warnings, **902.96 seconds**, Python **3.12.16**, disposable SQLite test databases. |
| Hash-verified tools install | Fresh isolated virtualenv installed `requirements-tools.txt` using `--require-hashes`; `pip check` passed. Compiler/scanner host uses Python 3.12.14; application validation used the pinned 3.12.16 image. |
| Static analysis | Bandit high-severity gate passed. The full JSON report includes all severities for review; no blanket ignore was added. |
| PostgreSQL 18.6 deployment | Fresh named test volume initialized successfully; Alembic reached `b7c1d9e4f2a8` using the dedicated migration role. No database host port is published. |
| Database permissions | The running API authenticated as `wellcosting_app`; DML and serial sequence use succeeded on a synthetic migration-owned table; application table creation and role creation by either non-superuser role were refused. Probe changes were rolled back. |
| API image/runtime | Full production Dockerfile built successfully; runtime UID is non-root; root-owned application source is not writable by that UID. Hash-verified production dependencies only. |
| Web image/runtime | Final full production Dockerfile built successfully. Nginx 1.30.6 runs non-root with a read-only root filesystem/dropped capabilities, passes `nginx -t`, serves the application and security headers, and reports **healthy**. Node is absent from the runtime image. |
| Nginx configuration fixes | Removed duplicate proxy timeout directives by making defaults inherit from server scope. Updated PID/temp paths for the new image and made the loopback health probe independent of an injected outbound HTTP proxy. |
| Hosted startup | Isolated fake-command checks confirm migrations use the separate connection, the API process does not receive `MIGRATION_DATABASE_URL`, failed migrations prevent API startup, and identical connections are rejected. No live Render deployment was exercised. |
| Secret hook | A synthetic staged credential was detected even after the working copy was changed to harmless text, proving that the hook examines staged bytes. Full scan matches remain visible in the supplied JSON; no automatic suppression/acceptance baseline was created. |
| Configuration / collector | Workflow and Compose YAML parsed; private database and migration dependency assertions passed; shell/Python syntax checks passed. Collector rejects evidence output paths inside the repository. |
| Image/package evidence | API and final web image IDs and installed package inventories captured. These were local review builds, **not pushed**; no registry digest for the custom application images is claimed. |
| Repository checks | Import graph regenerated; `git diff --check` passed. |

An early attempt exhausted this cloud workspace's 8 GB filesystem while Docker's VFS build layers and compiler caches coexisted. Its test failures were environmental (SQLite reported a full disk). Disposable caches/test images were cleaned, and the **fresh final full backend run above passed**. Earlier failed logs are not presented as passing evidence. Source files in this checkout also had owner-only permissions; image COPY permissions now explicitly allow the non-root runtime to read them.

## Limits and required review

- The full backend suite ran on SQLite. PostgreSQL evidence proves fresh-cluster migration and the tested role/sequence privileges; it does not prove PostgreSQL concurrency or every application workflow on PostgreSQL.
- Python locks target the Linux/Python 3.12 deployment platform. Native Windows requires separately generated/reviewed platform locks; Docker/WSL uses the canonical Linux environment.
- The supplied PostgreSQL extension/version/volume snapshots describe **only the disposable test deployment**. Actual production/managed versions, extensions, storage and grants are still required.
- Actual VS Code/Docker Desktop versions and extension inventory must come from the workstation being reviewed. Repository examples cannot enforce application-level workstation settings.
- Secret-scan potential matches require triage with repository access; a pattern match is not automatically a verified leaked credential. No exception or risk acceptance has been made on CyberSec's behalf.
- Package audits are advisory-service snapshots, not a complete OS/container CVE scan or penetration test. Installed OS package inventories are supplied for that review.
- Existing PostgreSQL 16/17 data must follow the tested-backup/restore cutover procedure before the new Compose volume is used in production. Managed deployments must provision and verify separate roles/secrets and apply the new start command before redeploying.

The configuration snapshot and generated evidence are intended for final CyberSec review, not as an assertion that the live environment has already been changed or certified.
