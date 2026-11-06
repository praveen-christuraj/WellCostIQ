# IT Security observation remediation plan — 2026-11-06

## Objective and release constraints

Address the latest IT Security observations with the smallest reversible changes that fit the
current Compose, Render/Vercel/Supabase and FastAPI architecture. Preserve the existing UI,
routes, RBAC rules, tenant boundaries, business calculations and API contracts.

**UAT data safety is a hard release gate.** This work must not delete, rewrite, move or reseed
users, password hashes/history, sessions, organisations, audit entries or business records. No
volume is removed or replaced. The audit-table change is permission-only and leaves the existing
`public.audit_logs` table and every row in place. New-cluster role initialization is not replayed
against an existing cluster. Hosted dashboard changes, credential rotation and restore exercises
are operational tasks and must not be simulated in code.

The implementation is divided into repository changes that can be tested now and provider or
governance actions that require named owners, dashboards or production access. A checkbox in this
plan means repository implementation, not provider verification.

## Current-state corrections to the review

- Item 10 is already implemented by `security_headers` middleware in `backend/app/main.py`;
  regression coverage will be strengthened rather than adding duplicate middleware.
- Item 23 is correct as reviewed. `backend/start-hosted.sh` will be reused unchanged as the Docker
  entrypoint; its migration credential assignment and `unset` will not be altered.
- Item 25 is partially implemented: `docs/SECURITY_MANUAL.md` already exists and is linked. It
  needs the more specific proxy, ownership, monitoring, incident and rotation procedures.
- The audit table is `public.audit_logs`, not `public.audit_log`. It will remain in place to avoid
  breaking ORM queries and historic data. Append-only grants are the safe immediate control; an
  audit-schema move is not part of this release.
- Existing request budgets are database-backed in `core/request_security.py`, so process sleep does
  not erase their ledger. Account lockout is also persisted. Edge throttling remains necessary to
  stop abuse before it reaches the API.
- The report's suggested backup-import verification conflicts with `burst=2`: the queued retry is
  not necessarily the second immediate request. Implementation will test sustained over-budget
  traffic rather than claim that every second request receives 429.
- The existing 2048 MB backup-import application/nginx limit will be retained. Reducing it without
  the largest real archive size would break a supported recovery workflow.

## Workstreams and item disposition

### A. Edge and hosted request hardening (items 1–10, 17, 22b, 29)

1. **Nginx transport and response policy (1, 2.5).** Add the same one-year HSTS policy used by
   Vercel, without `preload`, and append `upgrade-insecure-requests` to both CSP definitions.
2. **Nginx request handling (2.1–2.4).** Reuse the shared proxy parameters for health; permit only
   GET/HEAD for assets and the SPA; allow only the API's existing GET/POST/PUT/PATCH/DELETE verbs;
   retain same-origin behaviour by denying OPTIONS at this layer.
3. **Real client address (3).** Pin `edge_net`, trust only that subnet for `X-Forwarded-For`, enable
   recursive resolution, and keep `WEB_BIND_ADDRESS=127.0.0.1` coupled to that trust. Preserve the
   existing overwrite—not append—proxy header behaviour.
4. **Backup-import throttle (4).** Add a dedicated 1 request/minute zone with burst 2 and the
   existing 600 second timeouts and 2048 MB limit. Keep the application limit aligned.
5. **Host allowlists (5, 7).** Make nginx's real server names an explicit Compose build setting,
   keep localhost/127.0.0.1 for health checks, and reject all unnamed hosts. Add optional
   application-layer `ALLOWED_HOSTS` enforcement and configure Render's actual hostname. Direct
   hosted requests with an unexpected Host must fail without changing normal Vercel rewrites.
6. **Controlled Render deployment (6).** Set `autoDeploy: false`; document deployment only after a
   passing Security workflow and review. GitHub required-check/branch-protection configuration is
   an administrator verification step, not something this file can prove.
7. **Hosted edge limitation (7).** Document that Compose nginx controls do not protect Render.
   Application Host enforcement is immediate; provider edge rate limiting/WAF remains a required
   hosted action. Prefer a paid always-on service for production and retain database-backed budgets.
8. **Hardened Render image (8).** Switch the Blueprint to Docker with `rootDir: backend` and
   `dockerfilePath: ./Dockerfile`. Reuse `start-hosted.sh` as entrypoint so `PORT`, migrations and
   credential removal behave exactly as they do today. Override that entrypoint explicitly in
   Compose migration/API services so their existing commands remain unchanged. Registry digest
   deployment is a later supply-chain improvement; no unverified digest claim will be made.
9. **Applied settings evidence (9).** Supply a redacted capture checklist. Actual Vercel, Render and
   Supabase dashboard captures remain pending because repository access does not provide them.
10. **API headers (10).** Keep the existing middleware and add assertions for health and 404/error
    responses, including CSP, nosniff, frame-deny and referrer policy.
11. **Pinned authentication policy (17).** Add token lifetime and all missing password policy keys
    to Render and Compose examples. Document disabling bootstrap and deleting the seed password
    after first successful setup; do not change current credentials or users.
12. **Database TLS (22b).** In staging/production, reject PostgreSQL URLs without an explicit secure
    `sslmode` (`require`, `verify-ca` or `verify-full`). Apply this to both runtime and migration
    startup through the existing Settings load. Local development/test behaviour is unchanged.
13. **Health documentation (29).** Remove stale `admin_seeded` statements and align the readiness
    list with the implemented liveness-only endpoint and remaining controls.

### B. Compose runtime containment (items 11–16, 18)

1. **Resource/process limits (11).** Add CPU/memory/PID limits to db/api/web; db receives PID 300
   for PostgreSQL workers. Add bounded JSON logs to every service, including one-shot migrations
   (15).
2. **Temporary filesystems (12).** Add 512 MB `rw,noexec,nosuid,nodev` tmpfs mounts. Disable nginx
   disk buffering of proxied responses so large exports are not truncated by the tmpfs cap. No
   application feature executes files from `/tmp`.
3. **Database capabilities (13).** Drop all capabilities and add only the official PostgreSQL
   entrypoint's CHOWN/DAC_OVERRIDE/FOWNER/SETGID/SETUID set.
4. **Network isolation (3, 14).** Make `backend_net` internal with its existing pinned subnet and
   pin `edge_net`; web retains egress through `edge_net`. Document that future SMTP or other API
   egress needs a deliberate separate network design.
5. **Credential files (16).** Add `.secrets/` to ignore rules and write a non-destructive migration
   procedure. Switching a live UAT stack to file secrets is deferred to an operator maintenance
   window: the same existing secret values must be copied into 0600 files and verified before env
   values are removed. Application `_FILE` support and Compose rewiring are not silently forced in
   this patch. Environment-based exposure remains an acknowledged residual risk.
6. **Ignore credential formats (18).** Add private-key, VPN, keystore, dump, cloud/Kubernetes and
   Terraform patterns. Do not ignore public keys/certificates. This supplements—not replaces—the
   full-history scanner.

### C. Database safeguards without business-data changes (items 19–22)

1. **Fresh-cluster roles (19).** Add application connection limit 20, 120 s statement timeout,
   60 s idle-in-transaction timeout and 10 s lock timeout. Preserve distinct passwords and existing
   role separation. Add audit-schema default SELECT/INSERT and sequence grants for future use.
2. **Existing application connections (19).** Apply the same safe statement/idle/lock timeouts on
   PostgreSQL connections in SQLAlchemy, avoiding an assumption that the migration role may ALTER
   another role on Supabase. Existing-role CONNECTION LIMIT remains a DBA runbook action because it
   requires administrator privilege and worker/pool capacity review.
3. **Existing audit grants (20).** Add one PostgreSQL-only Alembic revision after current head
   `f1d7a4c95b23`. It performs no INSERT/UPDATE/DELETE and no table move/copy; it only creates the
   optional audit schema/default grants where supported and revokes UPDATE/DELETE on the existing
   `public.audit_logs` from `wellcosting_app`. SELECT and INSERT continue unchanged. SQLite tests
   skip these PostgreSQL privilege statements.
4. **Backups and retention (21).** Record proposed RPO/RTO, provider PITR/snapshot requirements,
   retention/tenant-deletion decisions and a restore-rehearsal template. State that Render's local
   backup directory is ephemeral and is not a database backup. Actual provider setup and restore
   evidence are pending operator execution.
5. **Tenant isolation (22a).** Keep existing authorization semantics. PostgreSQL RLS or per-tenant
   roles require a dedicated design/migration/UAT release and are not folded into this patch.

### D. Pipeline, evidence and governance (items 24–28)

1. **Reproducible CI (24a,b,f,g).** Pin action commits with version comments, use Ubuntu 24.04,
   retain artifacts for 14 days, and add Dependabot for Actions/pip/npm.
2. **Secret and image scanning (24c,d).** Add a blocking full-history Gitleaks job and blocking
   high/critical Trivy scans of both built images. No auto-suppression baseline is introduced.
3. **Static analysis (24e).** Gate Bandit at low severity and above. Review any finding and fix or
   document it with exact line-scoped justification; retain an unsuppressed report and do not hide
   existing findings behind an unreviewed baseline.
4. **Security operations manual (25, 27).** Extend the existing manual with proxy/HSTS ownership,
   real-IP coupling, hosted log drains and alert cadence, incident first actions, audit
   preservation, responsibility assignments and credential rotation order/consequences. Named
   staff, notification delivery and rehearsal evidence must be supplied by the organisation.
5. **MFA risk acceptance (26).** Add a risk-register entry that accurately lists implemented
   compensating controls and residual exposure. Until an owner, expiry, approver and date are
   supplied it remains **pending acceptance**, never an asserted approval.
6. **Traceable evidence (28).** Enhance the collector with source commit, CI run ID, tool/version,
   per-command UTC timestamp/command/exit code, expected-file validation and a SHA-256 manifest
   written outside the evidence directory. Signing and live dashboard/restore evidence remain
   operational steps.

## Test and release plan

1. Run focused Settings, middleware, security and migration tests; then the complete backend suite.
2. Run frontend security tests and the production build even though no UI source is changing.
3. Validate nginx syntax and Compose configuration/image runtime where Docker is available. Check
   GET/HEAD success, unsupported methods, unknown Host rejection, HSTS/CSP on `/` and assets,
   health proxy headers and backup throttling. If Docker is unavailable, report that limitation.
4. Test Alembic upgrade from the previous head on a disposable database, including preservation of
   sentinel user/password/audit/business rows. Test downgrade only on that disposable database.
5. Run Gitleaks/Bandit/Trivy in CI and resolve findings without ignoring them silently.
6. Before UAT deployment: take a provider snapshot, set actual nginx/Render hostnames, confirm
   `ALLOWED_HOSTS`, preserve existing secret values, and confirm the migration role owns
   `public.audit_logs`. Deploy manually only after checks pass.
7. After UAT deployment: verify response headers/methods/Host handling, application login and audit
   writes, read-only audit history, imports/exports, existing user sign-in/password flows and a
   representative business read/write in a disposable UAT record. Do not run destructive restore
   tests against UAT.

## Repository implementation and validation record

Implemented in this branch: workstreams A1–A8 and A10–A13; B1–B4 and B6; C1–C5's
non-destructive repository/runbook controls; and D1–D6. Item 10 already existed and
now has explicit health/404 regression assertions. Item 16's live conversion and
all provider/named-owner actions remain pending as listed below.

Local validation completed on 2026-11-06:

- **361 backend tests passed**, including the new Host/TLS/security-header cases
  and the audit migration's user/password/audit data-preservation round trip.
- Frontend security checks, production build, npm audit (**0 vulnerabilities**)
  and **40 shared UI checks** passed. No UI source or design changed.
- `pip-audit` reported **no known vulnerabilities**. Bandit passes with 20 exact,
  line-scoped reviewed `nosec` justifications; a deliberately added new finding
  failed the gate and was removed. CI retains an `--ignore-nosec` report and the
  rationale is in `docs/SECURITY_STATIC_ANALYSIS.md`.
- Shell/Python/JSON/YAML syntax checks, Compose volume/bind invariants, nginx
  placeholder substitution, evidence provenance/expected-file/external-manifest
  smoke checks and `git diff --check` passed.
- Docker/nginx live runtime, real PostgreSQL privilege verification, Gitleaks and
  Trivy require the CI/container environment; local Docker is unavailable. Their
  successful execution must be confirmed from this branch's CI run before UAT.

## Deferred/operator-owned items (explicitly not claimed complete)

- Provider edge WAF/rate limiting, paid always-on hosting and image-by-digest deployment.
- Live Render/Vercel/Supabase settings capture and GitHub required-check settings.
- Live file-secret migration using unchanged existing values; no forced rotation in this release.
- Managed PITR/snapshot configuration, retention approval and timed disposable restore rehearsal.
- Named monitoring owner/deputy, functioning alerts/log drain, incident and rotation rehearsals.
- Signed MFA risk acceptance with owner/expiry and native MFA/SSO implementation.
- PostgreSQL RLS/per-tenant roles and any optional audit-schema data migration (Phase 2 design).
