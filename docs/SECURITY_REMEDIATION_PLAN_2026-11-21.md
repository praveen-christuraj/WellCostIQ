# WellCostIQ security remediation plan

**Prepared:** 2026-11-21  
**Review type:** source-based security review and implementation plan  
**Branch reviewed:** `arena/ca62cbbb-wellcostiq` at `82dd43db46482f3c8072d6ce29b19f03cc0c7506`  
**Constraint:** read-only review. No implementation changes, pytest, or GitHub CLI checks were performed for this plan.

## 1. Executive summary

WellCostIQ already has substantial security engineering in place. The review found implemented JWT claim enforcement, Argon2 password hashing and lifecycle rules, refresh-token rotation/reuse detection, tenant-scoped RBAC conventions, database-backed request budgets, exact-origin CORS, production configuration validation, security headers, controlled backup/restore workflows, SQLAlchemy-bound queries, dependency/container scanning in CI, non-root/read-only containers, and extensive security documentation.

This plan therefore does **not** recommend replacing those controls or treating historical issues in older audit documents as current findings. The codebase’s own later remediation documents record that many earlier high-impact findings were addressed. The immediate source-level fixes to prioritize are narrower:

1. **P1 — Make the JSON request-body limit apply to actual bytes, not just a declared `Content-Length`.** `backend/app/main.py` currently treats a missing or malformed length as zero; this makes the application-layer cap bypassable by a request without a trustworthy length unless every deployment edge independently enforces a body limit.
2. **P1 — Bound decompressed backup archive parsing.** `backend/app/services/backup.py` checks the compressed file size and parses the gzip JSONL archive line-by-line, but does not impose a total expanded-byte, per-record-line, total-row, or expansion-ratio ceiling. A user with `backup:create` can submit a small or valid-size compressed archive that consumes disproportionate CPU/memory during validation. Parsing also assumes archive records are JSON objects in several places.
3. **P1/P2 — Close the hosted rate-limit gap operationally and make request-budget increments concurrency-safe.** `backend/app/core/request_security.py` documents the DB ledger as non-atomic under heavy concurrency, and `docs/SECURITY_RISK_REGISTER.md` already records that Compose nginx controls do not protect Render. The hosted edge limit/WAF and shared budget need deployment evidence; do not claim either exists based on repository configuration alone.

The next code work should be an exhaustive authorization/tenant-variant pass across the API, with automated route-registry coverage to prevent regressions. This is a high-value assurance task, not a claim that the current review demonstrated an exploitable IDOR. For a public multi-tenant SaaS launch, the deferred PostgreSQL RLS/per-tenant-role design and administrator MFA/SSO remain material residual risks and should be closed or formally accepted by named owners.

No confirmed committed plaintext production credential was established during this source review. The root-level tracked `01a1af5e-ba20-750c-9ef0-c89acbe06e47.patch` is an unusual 128 KB artifact and should be included in a full-history secrets scan and release-artifact review; keyword matches in a patch are not proof of a credential. The existing security workflow already runs a full-history Gitleaks job, but its result was not inspected here.

## 2. Method used (0security skills applied as methodology)

The 0security clone’s skills were used as review checklists, not invoked as runtime agents (their `load_skill` / `spawn_agent` tools belong to 0security’s own agent runtime). The review follows these specific methods:

- **`techniques/scan` + `frameworks/python-web`:** map application entry points, enumerate routes and trust boundaries, check authorization and data access, and retain only evidence-based findings with concrete replacement guidance.
- **`techniques/variant-hunting` + `techniques/assumption-mining`:** after identifying body-size and archive-parser boundaries, search their shared callers and siblings rather than fixing one route in isolation; verify authorization at both the helper and caller boundaries.
- **`vulnerabilities/sqli-advanced`:** search raw SQL, dynamic identifiers, and execution sinks; distinguish SQLAlchemy expression construction from interpolated SQL.
- **`vulnerabilities/path-traversal`:** inspect archive/path writes and confirm resolve-then-containment behavior, symlink checks, and the limits of those checks.
- **`vulnerabilities/ssrf-bypass`:** assess the Ollama client’s fixed configured target, redirects, credentials, URL parsing, and network boundary; a deployment-operator-controlled URL is not treated as attacker-controlled input.
- **`techniques/secrets-hunting`:** do not print secrets; assess tracked env/key-like files and ensure the full history scanner remains a blocking release gate. Any confirmed leak requires rotation, not just deletion.
- **`techniques/jwt-attacks`:** inspect algorithm allowlisting, required claims, issuer/type validation, session versioning, refresh rotation, replay handling, and invalidation.
- **`techniques/llm-prompt-injection`, `llm-excessive-agency`, `llm-insecure-output-handling`:** assess the assistant and Ollama boundary for untrusted context, data disclosure, output rendering, and ability to perform writes.
- **`techniques/workflow-hardening` + `cloud-iac-review`:** review Actions permissions/pinning, container privilege, networking, runtime secrets and provider-only controls.
- **`techniques/seedless-depth-review` + `attack-surface-diff`:** use read-only source inventory and repo evidence; no live exploit, destructive restore, test execution, or production access was attempted.

### Review coverage and limits

- FastAPI application bootstrap, middleware and router registration: `backend/app/main.py`.
- API routes: **551 statically decorated route declarations** were counted across `backend/app/api`; this includes router families whose routes are generated dynamically (notably `catalogue_items.py`). An AST spot-check found five intentionally unauthenticated router handlers: login, refresh, logout, forgot-password, and reset-password. Root and health routes are separate. That spot-check is not a substitute for the route-by-route authorization verification in Phase 2.
- Authentication/RBAC/request identity, representative schemas/models, backup and database-browser services, Ollama client, AI context/assistant, logging, request-size guard, CSV escaping and spreadsheet/workbook upload paths were inspected.
- Frontend sources were searched for dangerous HTML/eval sinks, browser token persistence, external opening and import/export boundaries. No `dangerouslySetInnerHTML`, `innerHTML`, `eval`, or `new Function` use was found in `frontend/src`; access tokens are held in module memory while refresh uses an HttpOnly cookie.
- Deployment and supply chain: `.env.example`, `backend/.env.example`, `render.yaml`, Compose and overlays, both Dockerfiles, Nginx, `.dockerignore`, `.gitignore`, Actions, Dependabot, staged-secret hook/scripts, database role initialization and deployment/evidence docs were examined.
- The repository is large (731 files excluding `.git` and `node_modules`, with major business modules thousands of lines long). This plan is a structured source review, not a penetration test, runtime validation, provider audit, or proof that every business-flow query is tenant-safe. The 0security principle “prove from code; do not infer a control from documentation” is retained for implementation and release sign-off.

## 3. Entry-point and trust-boundary inventory

### 3.1 Public and framework-level endpoints

- `backend/app/main.py`: `/`, `/api/health`, FastAPI docs/OpenAPI when configured, error handlers, CORS, Host check, cookie-origin guard, request-size guard and security headers.
- Auth router (`backend/app/api/auth.py`): public `/login`, `/refresh`, `/logout`; authenticated `/logout-all`, `/me`, `/change-password`.
- Password recovery (`backend/app/api/security.py`): public `/auth/forgot-password` and `/auth/reset-password`; all review/issue/force/revoke/lock administrative routes are permission-gated.
- Unauthenticated does not mean uncontrolled: verify public endpoint parity, generic response behavior, rate limits, CSRF behavior for refresh-cookie operations, and abuse resistance. Preserve public error uniformity and avoid returning account existence.

### 3.2 API route families to audit route-by-route

Every family below is part of the implementation’s actual entry-point inventory. For **every read, write, bulk, import, export, restore, and state-transition route**, record the permission key, workspace predicate, resource-owner rule, audit event, and input/resource limits. Check router-level and function-level dependencies, including dynamically generated routes.

| Family | Main source files |
|---|---|
| Authentication, recovery, security centre, notifications and tasks | `backend/app/api/auth.py`, `security.py` |
| Identity and access administration | `backend/app/api/rbac.py`, `deps.py` |
| Backup, import, restore, validation and download | `backend/app/api/backup.py`, `backend/app/services/backup.py` |
| Generic reflected database browser | `backend/app/api/database_browser.py`, `backend/app/services/database_browser.py` |
| Assistant, AI status/review, cost intelligence | `backend/app/api/assistant.py`, `cost_intelligence.py`; `backend/app/services/{assistant,ai_context,ollama,cost_intelligence_ai}.py` |
| Dashboard and audit/export surfaces | `backend/app/api/{business_dashboard,audit,usage_reports,report_builder}.py` |
| AFE, cost registers and SOW | `afe.py`, `daily_cost.py`, `fuel_cost.py`, `lih_cost.py`, `mud_cost.py`, `ndt_inspection.py`, `invoice_processing.py`, `sow_adjustment.py` |
| Wells, rigs, operations and document/survey uploads | `rig_well.py`, `operations.py`; `backend/app/services/operations/*` |
| Master data, catalogues, services, vendors and purchase/service orders | `master_data.py`, `catalogue_items.py`, `catalogue_options.py`, `service_master.py`, `vendor_master.py` |
| User-specific and reusable data | `costing_sets.py`, `record_templates.py` |

### 3.3 Persistence and supply-chain boundary

- ORM models and organization-scoped rows: `backend/app/models/*`; schemas: `backend/app/schemas/*`; Alembic: `backend/alembic/versions/*`.
- Database permissions/connection roles: `backend/app/core/database.py`, `backend/app/core/migrations.py`, `scripts/postgres-init-roles.sh`, `scripts/postgres-inventory.sql`, migration revisions and deployment secrets.
- Inbound requests cross Nginx/Render into FastAPI; proxy IP headers are trusted only for configured proxy networks. Browser access tokens are memory-only; refresh is cookie-based. Ollama is a separately configured network service; it is disabled by default in the hosted Render blueprint.
- The backend backup volume and hosted Render filesystem have different durability properties. `docs/SECURITY_RISK_REGISTER.md` explicitly notes Render’s `/app/backups` is ephemeral; it is not a substitute for managed database backup/PITR.

## 4. Evidence-based findings and implementation work

Severity is a prioritization label, not a calculated CVSS score. Findings below distinguish a source-level weakness from a provider-dependent residual risk. Existing controls in §5 must not be removed while fixing these.

### F-01 — Enforce request size on received JSON bytes (P1, application fix)

**Evidence:** `backend/app/main.py`, `body_size_guard` (near `MAX_JSON_BODY`). The middleware converts a missing or non-numeric `Content-Length` to zero and only rejects when the declared length exceeds the configured maximum. It does not count bytes delivered through ASGI. A direct API caller using a request without a reliable length can therefore bypass this particular cap. Nginx’s `client_max_body_size` is valuable but cannot be assumed to protect direct hosted API access or every deployment topology.

**Implementation:**
1. Replace the header-only check with a bounded ASGI receive wrapper that counts bytes as the application consumes the body and aborts with 413 once the configured limit is crossed. Reject invalid/negative `Content-Length`; if present, reject an over-limit declaration early, but still enforce the streamed byte count.
2. Keep multipart out of the generic JSON allowance only where its route has an explicit streaming byte limit. Build a route inventory of every `UploadFile`/multipart handler; route-specific limits must be applied while streaming, not after full buffering. Retain the larger, explicit backup archive allowance and its Nginx alignment.
3. Avoid a second unbounded buffer in middleware. Preserve request replay semantics needed by FastAPI/Pydantic and ensure the wrapper works for chunked ASGI messages and disconnects.
4. Align configuration validation for `MAX_JSON_BODY_MB` (positive, bounded, sane integer) and document that edge limits are defense in depth, not the application’s only byte cap.

**Acceptance evidence (when implementation is authorized):** 413 for over-limit declared bodies and for streamed/chunked bodies without a usable length; requests just below the cap pass; multipart endpoints retain their route-specific limits; no body content or credentials appear in logs. Verify both behind Nginx and against a direct API deployment in an isolated environment.

### F-02 — Bound backup archive expansion and validate each JSONL record (P1, application fix)

**Evidence:** `backend/app/services/backup.py`: `MAX_ARCHIVE_BYTES`, `read_manifest`, `scan_archive`, `_replace_workspace_rows`; upload route in `backend/app/api/backup.py`. The compressed archive file is capped (4 GiB in the service; the upload setting is 2048 MiB by default), but `gzip.open()` streams expanded data without an aggregate uncompressed-byte limit, expansion-ratio budget, maximum line length, or total row count. `read_manifest.readline()` and `scan_archive`’s per-line parse can allocate a very large JSON line. Several accesses assume the decoded JSON value is a dict, and row entries are later assumed to be dicts. This is a resource-exhaustion and malformed-input handling gap reachable by a caller with `backup:create`, not evidence of arbitrary file extraction (the format is gzip JSONL, not ZIP/TAR).

**Implementation:**
1. Add an explicit archive policy object with independently configured/constant ceilings for compressed bytes, total decompressed bytes, maximum manifest bytes, maximum record bytes, records, tables, columns/table, and rows/table/total. Choose ceilings from real supported archive sizes and UAT data; do not silently lower the current 2048 MiB supported upload without an archive-size review.
2. Count decompressed bytes while reading and stop immediately at the limit. Set a defensible compression-ratio ceiling as an additional guard, not the sole guard. Bound individual line reads before decoding/JSON parsing. Avoid `readline()` that may allocate an unbounded line.
3. Validate exact JSON shapes and primitive types: manifest dict/version/schema, table records as dicts, table names in the reflected/allowed table plan, rows as a bounded list of dicts, only known columns, and trailer/count consistency. Reject duplicate or contradictory table declarations and invalid identifiers before any DB mutation.
4. Keep a strict two-stage lifecycle: upload to a private temporary file with streaming size cap; scan/validate completely before registering or restoring; restore stays transactional and uses the existing preserve/exclude rules. Ensure temporary source and partial files are removed on every failure path.
5. Convert malformed gzip, UTF-8, JSON and schema errors to a stable 422-style `BackupError`; keep unexpected implementation failures generic and logged without echoing archive contents. Ensure failed validation cannot leave a registered completed job or partially replaced business data.
6. Audit stored archive paths both before reads and before writes/deletes. Preserve the existing `ensure_within_root()` resolve/containment/symlink check and private directory modes. If backup storage can be modified by an untrusted local actor, consider directory-descriptor/no-follow operations to narrow TOCTOU exposure; do not represent the present check as race-free against a hostile filesystem writer.

**Acceptance evidence:** synthetic gzip-bomb/large-line/malformed-record cases stop within a deterministic resource budget; no restore begins before all validation passes; existing archives within the agreed limits still validate; a failed archive leaves DB business rows, audit rows and credentials unchanged.

### F-03 — Make request budgets effective under concurrency and close hosted edge gap (P1/P2, code + operator action)

**Evidence:** `backend/app/core/request_security.py` explicitly says the database-backed `throttle()` is not an atomic edge limiter under heavy concurrency. It counts rows then inserts/commits, so simultaneous attempts can all observe a below-limit count. The existing limiter keys by trusted client identity and action; it does not by itself establish a distributed/provider-edge policy. `frontend/nginx.conf` implements local Compose nginx zones; `docs/SECURITY_RISK_REGISTER.md` correctly states they do not protect the direct Render origin and marks provider WAF/rate limiting as open.

**Implementation:**
1. Keep the transport peer as the default identity and trust forwarded client IP only from exact, configured proxy CIDRs. Do not accept caller-provided `X-Forwarded-For` as a rate-limit key or audit fact.
2. Change the persistent budget to an atomic operation (for example a row keyed by action, keyed client digest and window, incremented under a database lock/upsert with the configured limit checked atomically) or add a shared rate-limit service. Preserve privacy by storing keyed IP digests, not raw addresses. Add account/email-keyed protection for credential guessing without exposing account existence.
3. Preserve Nginx route-specific login/recovery/import limits. Configure and verify an equivalent provider edge throttle/WAF in front of hosted Render, including direct-origin behavior; the source YAML cannot prove that dashboard setting. Keep limits generous enough for legitimate office NAT and document 429/Retry-After behavior.
4. Consider whether `throttle()` should commit its own ledger transaction. If retained, document and test transaction boundaries; avoid surprising callers that expect their business work to be atomic with throttle state.

**Operator evidence required:** redacted provider setting, edge test showing sustained over-budget traffic is blocked before FastAPI, correct client-address behavior, and a named owner. This risk remains open until this evidence exists.

### F-04 — Exhaustive route authorization and cross-workspace variant audit (P1 assurance work)

**Evidence:** `backend/app/api/deps.py` centralizes current-user and permission checks. Many routers use `Depends(require(...))`; `operations.py` sometimes invokes a permission check inside the route body; `cost_intelligence.py` has a router-level dependency; dynamic catalogue routes are generated. The static AST spot-check only confirmed that the five public handlers lack `Current` by design. This is a review coverage gap, not a confirmed IDOR.

**Implementation:**
1. Generate a route inventory from the mounted FastAPI app, not grep alone. For each method/path, record whether it is public, authenticated, required capability, workspace-scoped lookup, owner-only rule, audit behavior, and request/resource limits.
2. Require each anonymous route to appear on a small explicit allowlist (`login`, `refresh`, `logout`, recovery request and code redemption, root/health as appropriate). Fail a security test or static check when a new route lacks the expected auth policy. Be careful with FastAPI dependency inheritance and dynamically included routers.
3. Review every `db.get(Model, id)`, model lookup, bulk ID list, import reference resolution, download and action route. Prove organization equality in the query or an immediately shared scoped helper before access/mutation. Check caller-specific data (assistant history, read states, costing sets, task comments, notifications) for both organization and user identity constraints.
4. Review privilege transitions: user create/update/delete, role/permission assignment, owner-account protection, password reset, lock/unlock, backup restore approve/execute, bulk actions and permanent delete. Test actor/target pairs across owner, delegated admin and ordinary roles.
5. Review API response models to prevent ORM serialization of password hashes, refresh/reset material, private session data or internal fields. Keep the database browser’s table allowlist/scope derivation and hidden credential columns.
6. Maintain service-level authorization when a service is callable from more than one route; do not rely on UI visibility or route order for access control.

**Acceptance evidence:** generated route inventory checked into security evidence; explicit anonymous allowlist; automated cross-tenant negative cases for every route family and representative bulk/import/export flows; exact permission matrix reviewed by the product owner. No destructive tests on UAT data.

### F-05 — Administrator identity assurance and tenant isolation (P1 before SaaS / design gate)

**Evidence:** `docs/SECURITY_RISK_REGISTER.md` identifies MFA/SSO as pending formal acceptance and PostgreSQL RLS/per-tenant roles as deferred. API-level workspace scoping is the current isolation layer; the application DB role has access to data across organizations. A stolen Owner password can sign in absent MFA. These are documented residual risks, not secret source vulnerabilities.

**Implementation sequence:**
1. Prefer MFA/SSO through a supported identity provider for owners and privileged operators; define account recovery and break-glass procedures before rollout. Until done, obtain a named approver, expiry date, compensating control test and alert ownership for MFA risk acceptance. A risk register with blank owner/expiry/approver is not accepted risk.
2. Develop a separate PostgreSQL RLS/per-tenant-role design: tenant context propagation, connection-pool reset/transaction safety, privileged jobs and backup/restore bypass, migrations, query performance and compatibility with SQLite developer/test mode. Do not bolt RLS onto the current system without a migration and cross-tenant verification plan.
3. Rehearse tenant isolation against a disposable multi-tenant PostgreSQL database; prove missing tenant context fails closed, pool reuse does not cross tenants, and admin/background tasks use deliberate elevated roles.
4. Preserve compatibility and all existing customer data during migration. RLS is a separate design/UAT phase, not part of a quick permission patch.

### F-06 — Ollama/assistant: preserve fixed-target boundary and prove no agency (P2 hardening)

**Evidence:** Ollama is disabled in the hosted Render config by default. `backend/app/core/config.py` validates scheme/host/path, rejects embedded URL credentials/query/fragment and path traversal; `backend/app/services/ollama.py` constructs requests to a configured endpoint, enforces timeouts and response bounds, does not follow redirects, uses TLS validation, and sanitizes text. Assistant and cost-intelligence AI routes require authenticated capability; there is no application-exposed arbitrary URL or generic tool executor observed in the reviewed routes. React rendering has no dangerous raw HTML sink in `frontend/src`.

**Implementation:**
1. Keep the endpoint deployment-controlled, never user- or model-controlled. Do not add URL-fetch, arbitrary tools, SQL execution or write actions to the assistant without a separate authorization/tool policy.
2. Treat workspace records, uploaded documents, memory entries and model output as untrusted prompt content. Bound question/context/output, separate system instructions from retrieved context, and test prompt-injection attempts for data exfiltration and unauthorized actions.
3. Keep model responses as text rendered through ordinary React escaping. If adding rich text/Markdown, use a vetted sanitizer with an allowlist and prohibit dangerous protocols/HTML; do not pass model content to `dangerouslySetInnerHTML`.
4. Where Ollama is enabled, restrict egress/firewall to the approved host/port; use HTTPS and credentials when crossing a trusted LAN. Consider explicit allowed-host/CIDR policy and DNS-rebinding protection if configuration can be influenced by a less-trusted actor. A settings-controlled fixed target is not equivalent to an attacker-supplied SSRF primitive.
5. Verify AI prompts avoid credentials, unnecessary PII and unrestricted cross-module records; retain audit records for AI use without storing raw secrets/questions unless a retention/privacy decision approves it.

### F-07 — Backup restore scheduling and deployment durability (P2, code/design + operator)

**Evidence:** the backup service’s scheduler is in-process and comments specify single-instance operation. `docs/SECURITY_RISK_REGISTER.md` says Render local backup storage is ephemeral and provider PITR/snapshots and a timed restore rehearsal are open. Multi-replica deployment could duplicate in-process scheduled work unless deployment is constrained.

**Implementation:** make the one-instance assumption an enforced deployment constraint or replace the local scheduler with a distributed lease/queue; ensure only one worker can create a scheduled backup per workspace. Move hosted backup artifacts to durable, access-controlled storage if retained across deploys. Configure managed DB snapshots/PITR, retention, encryption and restoration procedures outside the application repo. Rehearse restores into a disposable database and capture elapsed time/RPO/RTO.

### F-08 — Secret hygiene and supply-chain evidence (P2 ongoing)

**Evidence:** `.env.example` and `backend/.env.example` use placeholders; `.gitignore` excludes local secrets and key formats; the pre-commit hook checks staged bytes; `.github/workflows/security.yml` uses read-only top-level permissions, pinned action SHAs, full-history checkout/Gitleaks, Bandit, pip-audit, npm audit, Trivy scans and container runtime checks. These are strong repository controls, but this review did not run scanners or inspect CI execution results.

**Implementation:**
1. Preserve the blocking Gitleaks full-history scan and ensure its token stays least-privilege. Investigate all findings rather than introducing an unreviewed baseline. If a real credential was ever committed, revoke/rotate it and assess exposure/history; deleting a file is not remediation.
2. Scan `01a1af5e-ba20-750c-9ef0-c89acbe06e47.patch` and the full Git history with the approved secret scanner; classify whether the tracked patch belongs in the repository/release. Keep findings redacted in this plan and evidence.
3. Keep dependencies lockfile-based/hash-verified and container bases pinned to immutable digests. Review dependency scanner output and image CVEs on each release; document justified exceptions with owner/expiry.
4. Retain action SHA pinning, least-privilege workflow permissions, artifact retention and no event-context interpolation into shell. Review workflow changes with the workflow-hardening checklist.
5. Avoid claiming secrets are absent until the full-history scan and provider secret inventory have been reviewed.

## 5. Verified controls to preserve (do not regress)

These controls were visible in the inspected source/config and should be treated as invariants during remediation. Their **deployed** effectiveness still requires provider/runtime evidence.

- **JWT/session:** `backend/app/core/security.py` uses a fixed HS256 algorithm, requires expiry/issued/not-before/subject/org/type/version/issuer claims and checks token type; `deps.py` verifies active user, organization and token version. Refresh tokens are opaque, stored as hashes, rotated, and replay of a revoked token revokes sessions and increments token version. Browser access token is held in memory, refresh cookie is HttpOnly/SameSite Lax with configurable Secure.
- **Password/recovery:** centralized policy and history; generic public recovery response; request throttles; reset code hashes/expiry/one-time completion; sessions revoked on reset/change; owner targets receive extra protection in administrative actions.
- **RBAC/tenant:** `require()`/`require_any()` and `Current` dependencies; owners; organization predicates; non-owner role assignment constrained; data-owning services usually receive the authenticated `organization_id`. Route-level verification remains required.
- **Origin and browser:** production exact HTTPS CORS and host configuration; cookie-write Origin/Referer/Sec-Fetch-Site guard; CSP and security headers; API no-store; production docs disabled; Nginx rejects unknown Host and restricts verbs.
- **SQL and data output:** inspected SQL execution uses SQLAlchemy expressions or fixed constant SQL statements, not an observed user-interpolated SQL sink. Database-browser identifiers are matched against reflected allowlisted tables. CSV escaping helper handles formula-leading values; verify every exporter uses it when changing export code.
- **Files/uploads:** backup paths are resolved within the configured root and symlink paths rejected; backup imports stream to temporary files with an upload cap; document/survey paths have explicit limits; spreadsheet import readers bound row/column counts. Preserve these limits while expanding the central request-body guard.
- **Backup integrity/privacy:** archive format is gzip JSONL, with hash, manifest/trailer, credential tables excluded, organizations/audit/credentials preserved on restore, restore validation/dry run, two-person approval and pre-restore safety backup. Add resource bounds without weakening these data-preservation rules.
- **Logging:** `backend/app/core/logging.py` redacts common credential patterns and keeps SQL engine logging below INFO; validation errors omit rejected input; HTTP error handlers avoid exposing database internals. Continue treating logs and exception messages as sensitive.
- **Runtime/supply chain:** backend and frontend images use pinned base digests and non-root users; Compose API is read-only/capability-dropped with tmpfs, private DB network and resource/log limits; DB roles separate app from migration; locks are hash-verified; Actions are commit-pinned and permission-limited.

## 6. Prioritized implementation and release plan

### Phase 0 — Preserve evidence and establish the baseline

1. Freeze the reviewed source commit and attach the commit/tree hash to the remediation issue.
2. Run approved full-history secrets and dependency/image scanners in the authorized CI environment; do not put raw secret findings in tickets or chat. Do not change or delete customer data.
3. Resolve the tracked patch artifact’s purpose and scan it. Do not remove it without repository-owner approval.
4. Reconcile `docs/SECURITY_AUDIT_FINAL.md`, the 2026-11-06 remediation plan, risk register and this plan. Older documents describe prior defects and historical test runs; label dates and do not treat those as current validation.

### Phase 1 — Fix the two source-level availability gaps

1. Implement F-01 streaming actual-byte request cap, with multipart route-by-route exceptions.
2. Implement F-02 bounded archive decompression and strict schema validation before any DB write.
3. Add focused automated abuse cases and non-destructive data-preservation fixtures. **These tests are a future implementation gate only; none were run for this planning task.**
4. Review configuration defaults and deployment edge/body limits for parity across Compose, Render and direct ASGI operation.

### Phase 2 — Authorization and tenant boundary assurance

1. Generate the mounted route/dependency inventory and review every route family in §3.2.
2. Complete cross-workspace and privilege-transition variant checks using two organizations and realistic role matrices.
3. Add route-registry allowlist tests and service-layer scope assertions where there are multiple callers.
4. Verify CSV/XLSX/PDF exports, downloads, previews, audit actions, task/notification and assistant-history scope. Treat browser UI permissions as display only.
5. Do not make schema or business-data changes without a migration plan, backup, rollback and explicit UAT data-preservation check.

### Phase 3 — Operational and architecture risks

1. Implement atomic/shared request budgets and verify actual Render/provider edge settings (F-03).
2. Decide MFA/SSO and document named risk owner, expiry and compensating-monitoring evidence (F-05).
3. Start separate RLS/per-tenant-role design and multi-tenant PostgreSQL verification before public SaaS expansion (F-05).
4. Enforce single scheduler instance or distributed lease and finalize durable backup/PITR/restore runbook (F-07).
5. Complete Ollama threat model, egress restrictions, prompt injection tests and output rendering invariants (F-06).
6. Close secret-scan/patch artifact disposition and release supply-chain evidence (F-08).

### Phase 4 — Release verification (not performed in this review)

After implementation approval, use focused security tests, full application suites, static/dependency/image scans, Compose/nginx validation and a disposable PostgreSQL environment. Test direct-host and reverse-proxy deployments, chunked oversized bodies, archive bombs/malformed JSONL, route authentication, cross-tenant ID manipulation, refresh replay, password recovery, audit permissions, CSV formula injection, AI prompt injection and backup/restore preservation. Verify provider WAF, host/CORS, DB grants, secret inventory, monitoring and durable backups with redacted evidence. Run destructive restore tests only in a disposable environment, never on live/UAT data.

This section is a proposed gate, not a record of tests run. In this task, **pytest and GitHub CLI checks were not run**, per instruction.

## 7. Definition of done

- Actual received request bytes are bounded independent of `Content-Length`; all multipart routes have explicit streaming caps.
- Backup archive validation has bounded compressed and expanded input, per-line/schema/row ceilings, typed rejection errors and no partial writes on malformed input.
- A generated route inventory has an explicit unauthenticated allowlist and every business/data operation has documented capability, tenant scope and audit expectation.
- Cross-tenant access attempts fail consistently for reads, mutation, export/import, bulk operations and workflow state transitions.
- Rate budgets are atomic/shared at the layer appropriate for the deployment; hosted edge configuration is verified from provider evidence.
- MFA/SSO and RLS risks are implemented or have approved, named, time-bounded acceptance before the associated production release.
- Backup durability, scheduler cardinality, restore rehearsal and recovery objectives are evidenced operationally.
- Full-history secret scan, dependency scan, image scan and pinned workflow review are clean or have explicit, time-bounded exceptions; any exposed credential is rotated.
- Existing users, password hashes/history, sessions, organizations, audit entries and business rows are preserved unless a separately approved migration explicitly specifies otherwise.
- No remediation is described as complete based solely on documentation, a local pass, or the absence of a scanner match.

## 8. Files expected to change during implementation

Initial source fixes:

- `backend/app/main.py` — robust receive-byte body guard and configuration use.
- `backend/app/core/config.py` — validate and document request/backup limits if new settings are introduced.
- `backend/app/api/backup.py` — bounded upload lifecycle and errors.
- `backend/app/services/backup.py` — bounded archive parser, schema validation and pre-write checks.
- `backend/tests/` — focused security regression cases (only after implementation is authorized; no tests were run for this plan).

Authorization/operations assurance, subject to findings from the route-by-route pass:

- `backend/app/api/*.py`, shared scoped helpers/services, and applicable `backend/app/schemas/*` / `backend/app/models/*` / Alembic revisions.
- `backend/app/core/request_security.py`, deployment edge configuration and `docs/SECURITY_RISK_REGISTER.md`.
- `docker-compose*.yml`, `render.yaml`, `frontend/nginx.conf`, GitHub workflow and deployment/security docs only where evidence supports a concrete gap.

Avoid broad rewrites, unneeded migrations, speculative package upgrades, changing JWT issuer/audience, changing public API contracts, lowering supported backup limits without data, or making operator-only facts appear satisfied in source code.
