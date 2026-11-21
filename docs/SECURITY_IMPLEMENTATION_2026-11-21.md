# Security remediation implementation — 2026-11-21

Baseline: `099b2330b1e956ed76adb6deb793a52321628700`.
Plan: `SECURITY_REMEDIATION_PLAN_2026-11-21.md`. This record supersedes no historical audit or test result.

Reference reviewed: https://github.com/0sec-labs/0security.git at
`e22240d82f0127424916a42892562dfb0697f24c`, specifically the Python web
and variant-hunting checklists. Used as source-review methodology, not executed
as an agent or a security scanner. The local reference checkout is not shipped.

## Implemented in source

### F-01 — actual request bytes

`BodySizeLimitMiddleware` counts ASGI bytes without accumulating another body
copy. It rejects malformed, signed, duplicate, negative and oversized declared
lengths; a smaller declared length or no length cannot bypass the receive cap.
It covers safe methods too. Disconnect messages pass through unchanged.
Multipart is bounded **before** Starlette parses/spools it, not only when route
code eventually reads UploadFile. Parser error translation cannot downgrade a
size rejection from 413 to 400.

- `MAX_JSON_BODY_MB`: 10 default, startup bounds 1–128.
- `MAX_MULTIPART_BODY_MB`: 128 default, startup bounds 1–4096; aggregate files,
  boundaries and form fields, not a per-file allowance.
- Only POST `/api/v1/backup/jobs/import` receives the larger allowance:
  `BACKUP_MAX_UPLOAD_MB` (2048 default, startup bounds 1–4096) plus 1 MiB framing.
  Its existing streamed file cap still applies. Other content types do not get
  this larger allowance.
- Existing per-file/workspace limits are retained. Large bulk attachment requests
  may need splitting to respect the new aggregate cap; do not raise it without
  sizing temporary disk and reverse-proxy limits.

Multipart source inventory (all are under `/api/v1`):

| Handler/family | Existing downstream bound | New pre-parser aggregate bound |
|---|---|---|
| `backup.import_archive` | 2048 MiB default, counted while copying | configured upload + 1 MiB |
| `operations.upload_document` | workspace setting, 1–100 MiB | 128 MiB default |
| `operations.preview_surveys` | workspace setting, 1–100 MiB | 128 MiB default |
| `operations.preview_planned_survey` | shared survey reader, workspace limit | 128 MiB default |
| `operations.preview_timeline` | 10 MiB bounded read | 128 MiB default |
| `vendor_master.bulk_upload_documents` | configured per-file document bounded reader | 128 MiB default |
| `vendor_master.upload_documents` (PO/SO revision attachments) | shared document reader | 128 MiB default |
| `invoice_processing.upload_attachments` | attachment service per-file limits | 128 MiB default |

Nginx limits remain defense in depth. Direct ASGI/Render traffic now has byte
caps too. Do not interpret source changes as proof of provider edge settings.

### F-02 — archive validation

All manifest, validation and restore readers share a binary, bounded-line gzip
reader. Explicit `ArchivePolicy` ceilings:

| Resource | Ceiling |
|---|---:|
| Compressed archive | 4 GiB (unchanged) |
| Expanded bytes | 32 GiB |
| Expansion ratio | 1000:1, additionally subject to absolute expanded limit |
| Manifest line | 4 MiB |
| Other line | 64 MiB |
| JSONL records, including metadata | 2,000,000 |
| Declared tables / columns per table | 2048 / 2048 |
| Rows per record | 500 (writer's existing batch size) |
| Rows per table / total | 10,000,000 / 50,000,000 |

These are explicit source policy defaults, **not measurements of UAT archives**.
The 2048 MiB upload allowance was not reduced. Before release, compare the
expanded/record/row policy against real supported backups and size worker memory,
CPU and temporary storage. Adjust deliberately if legitimate archives need more.

Validation rejects non-object JSON records, duplicate JSON keys and table/column
declarations, invalid identifiers, credential tables, unknown record types,
unknown row columns, malformed binary wrappers, nested payloads, non-finite
numbers, contradictory/incomplete trailer counts, and data after the trailer.
Gzip/UTF-8/JSON errors and exceeded budgets become generic 422 BackupError values.
Table/column membership is checked against the current reflected backup plan
before import registration and before restore deletes. Restore rescans completely
before issuing its first delete and uses the bounded reader again on insert.
Credential/audit preservation and transactional restore behavior are retained.
Private upload temporary files are closed and removed on every exit. Imported
archives are created exclusively with private permissions and path containment
checks. These checks are not race-free protection against a hostile local
filesystem owner; private backup storage remains required.

### F-03 — serialized shared request ledger

The existing rolling-window ledger is retained without a schema/data migration.
PostgreSQL obtains a transaction-scoped advisory lock keyed by the private client
HMAC before counting and recording an attempt. SQLite obtains a write reservation
with BEGIN IMMEDIATE before reading the count. Each budget is spent in a separate
short-lived Session; caller business state is no longer implicitly committed.
429 and Retry-After are retained. Trusted proxy identity handling is unchanged.
Login additionally spends an account/workspace-keyed HMAC budget, including for
nonexistent accounts, to constrain distributed guessing without storing email.

Production workers must share the same PostgreSQL database, secret and window
configuration. PostgreSQL concurrency, pool capacity and caller transaction
behavior still require runtime validation. SQLite serializes all ledger writers
and is not the target for horizontally scaled production. Call throttling before
business writes to avoid SQLite writer contention. This does not replace WAF or
volumetric-abuse controls.

### F-04 — mounted authentication inventory foundation

`python -m app.core.route_inventory` (from backend) traverses mounted effective
FastAPI routes/dependencies, including lazy/dynamic routers and inherited
permissions. `require` and `require_any` expose metadata without changing their
permission semantics. New anonymous API paths fail the explicit method/path
allowlist; framework docs are separately classified and remain configuration-gated.

Generated `SECURITY_ROUTE_INVENTORY.json`: **649 method/path entries**, seven
public entries (five auth/recovery plus root/health), **zero missing-auth policy
violations**. The inventory records dependency capabilities and handler source
locations, and deliberately marks object ownership, tenant predicates and audit
behavior as requiring manual review. Conditional permission calls inside handler
bodies are not automatically proven by this report.

### Additional source-level remediations (follow-up pass)

- **CSV formula-injection escaping (`catalogue_items.py`, `record_templates.py`)**:
  wrapped all exported cell values in `safe_csv_cell` (`app/core/spreadsheets.py`)
  for the price-revision template CSV and record-template library CSV exports,
  matching `database_browser` and `report_engine`.
- **F-07 scheduler cross-process coordination (`app/services/backup.py`)**:
  hardened `run_due_backups()` with a PostgreSQL transaction-scoped advisory lock
  (`pg_try_advisory_xact_lock(hashtext('wellcostiq:backup_scheduler'))`) and
  SQLite `BEGIN IMMEDIATE` serialization, and advanced `next_run_at` atomically
  in the same transaction as `create_job(...)` so concurrent workers cannot
  double-claim the same scheduled run.
- **F-04 & F-06 source review**:
  verified `db.get(...)` and bulk-ID (`.in_(...)`) handlers across `app/api` and
  `app/services` are preceded by or paired with `organization_id` scoping; verified
  Ollama client (`app/services/ollama.py`), context assembly (`app/services/ai_context.py`,
  `app/services/cost_intelligence_ai.py`), and assistant routes (`app/api/assistant.py`)
  enforce fixed-target configuration, no redirects, bounded inputs/outputs,
  grounding rules, and capability-gated data loading.

## Validation actually performed

- Imported the app to generate the mounted dependency inventory, without entering
  application lifespan, running bootstrap, starting a scheduler, or accessing a
  production database.
- Compiled changed Python sources for syntax (`python -m py_compile`).
- Reviewed the diff and whitespace (`git diff --check`).

**No pytest, other test execution, GitHub checks, live exploit, provider inspection,
secret/dependency/image scan, or restore execution was performed.** New regression
cases are checked in but unexecuted. No customer data or schema was migrated.

## Remaining gates — do not describe the entire plan as complete

- Run approved regression/concurrency tests, disconnect/multipart cleanup cases,
  direct/proxied chunked requests, archive compatibility and non-destructive
  data-preservation fixtures in a disposable environment.
- Execute cross-tenant/privilege-transition negative cases to complement the
  source-level tenant-scoping review.
- Verify hosted WAF, direct-origin behavior, proxy identity and 429 behavior with
  provider evidence and a named owner (risk R-2026-002 remains OPEN).
- MFA/SSO and RLS require the plan's separate design, migration/UAT and named,
  expiring acceptance/approval. No owner or approval has been invented.
- Configure durable off-host backup storage, managed PITR, retention, and a timed
  disposable restore rehearsal.
- Complete Ollama egress policy verification and prompt-injection negative tests.
- Obtain authorized full-history secret/dependency/image scan results and patch
  artifact disposition. The tracked patch was not removed or claimed secret-free.
