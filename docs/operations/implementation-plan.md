# Well Operations module — implementation plan v2

**Status:** historical design proposal (the code families it names — `ops_operation_codes`, `ops_activity_codes`, `ops_npt_codes`, `ops_phase_codes` — were retired 2026-11-19; Activities now carry an Activity type in Master Data and the Code Library holds Operations, Sub-Phases, Cause Codes, Responsible Agency labels and source marks). For the implemented workflow, permissions, calculation bases and limits, see [Well Operations: daily workflow](daily-workflow.md). The sections below describe the proposal, not a release checklist with every item completed.
**Date:** 2026-11-17
**Branch:** `arena/10241b7b-wellcostiq`
**Supersedes:** `docs/operations-implementation-plan.md` (v1) — v1 covered only the DDR spine.
v2 keeps v1's spine and adds the report-extraction engine, the document vault, the configurable
code library, the Excel family, DMR/RMR, the plan/timeline and lead/lag engine, ROP, KPI dashboards
and the interactive charts that the requirements ask for.
**Read with:** `docs/operations/report-study.md` (the evidence), `docs/operations-module-plan.md`
(the architecture decision: one workspace, one database, RBAC not tenancy) and
`docs/operations-costing-decoupling.md` (operations and costing run independently).

---

## 0. The requirement, restated as a contract

| # | Requirement | Where it is delivered |
| --- | --- | --- |
| 1 | Break down DDR, DCR, DMR, RMR (and any report) | §5 extraction engine, report families §5.3 |
| 2 | Allocate Planned / NPT / UPA hours and days from any report | §6 classification engine (`classification` + `allocation` + `is_productive`) |
| 3 | Summarise uploads briefly | §6.6 deterministic brief + optional local-AI polish |
| 4 | Time vs Depth chart, actual vs predicted | §7 timeline engine, §9.4 chart |
| 5 | Everything user-verified; draft until verified | §4.4 review workflow, §5.2 stage 9 |
| 6 | Dashboard with the important KPIs | §9 |
| 7 | Well position, depth, direction from the report | §8 geometry (surveys, trajectory, position) |
| 8 | Timeline as the base for the graph and for lead/lag days | §7 |
| 9 | ROP, needed for lead/lag | §7.5 |
| 10 | Interactive dashboard; intelligent extraction engine | §9, §5 |
| 11 | Study the model reports and operation summaries | `docs/operations/report-study.md` |
| 12 | Take workflow/features from the four reference repos | §11 (verdicts in the study §8) |
| 13 | Must not interfere or correlate with the existing costing modules | §2 boundaries, §12 FK-assertion test |
| 14 | Only Users, Rigs, Wells shared; complete RBAC separation | §2, §10 |
| 15 | Rig-scoped, well-scoped, drilling/completion-scoped | §3.1 scope model, every table and query |
| 16 | A directory per well and per scope for documents; PDF and Excel | §4 document vault, §5.4 Excel path |
| — | Codes/categorisations user-configurable | §3.4 code library |
| — | Correlation of the timeline must be "kept in memory" and reusable | §7.6 correlation store |

---

## 1. What this module is, in one paragraph

A **Well Operations** module, inside the existing workspace and database, that receives the daily
drilling/completion/mud/rig-move reports as uploaded documents, **extracts** them into a structured,
tenant-scoped record with a confidence score and field-level provenance, lets the drilling engineer
**review and correct** that record in a purpose-built workspace, and then keeps it as the authoritative
**time record** from which the module produces a brief, a plan-versus-actual **timeline**, a
**time-vs-depth** chart, **lead/lag**, **ROP**, NPT/UPA allocation, and the operations **KPI dashboard**.
It shares only users, rigs, wells and the depth/unit utilities with the costing modules, writes nothing to
them, reads nothing from them, and is invisible to a user who lacks its capabilities.

---

## 2. Boundaries (non-negotiable, testable)

### 2.1 What is shared

| Shared foundation (Layer 1) | Used as |
| --- | --- |
| `organizations` (tenant/workspace) | every row is `organization_id`-scoped |
| `users`, roles, permissions, audit, notifications, tasks | inherited unchanged |
| `blocks`, `rigs`, `wells`, `well_sections`, `well_phases`, `hole_sections`, `phases`, `vendors` | read by ID, snapshotted on write |
| `core/units.py` (`depth_to_meters`, `normalize_depth_unit`), `core/time.py`, `core/precision.py`, `core/spreadsheets.py` | reused verbatim |
| UI layer: `DataTable`, `FormDialog`, `PageHeading`, `SectionCard`, `ChartPanel`, `useUnsavedChangesGuard` | reused verbatim |

### 2.2 What is *not* shared and must stay disconnected

- No `ops_*` table has a foreign key to any `afe*` or `daily_cost*` table, and no costing table gains a
  foreign key to `ops_*`. Operations never reads AFE, Daily Cost, Mud Cost, LIH, Fuel, NDT or Invoice data;
  costing never reads `ops_*`.
- No service in `services/operations*` imports a costing service; no costing service reads an `ops_*` table.
- No cost figure appears anywhere in the operations module, its prints or its exports. NPT is **hours**,
  never money (decoupling §4.4).
- The existing regex classification in `services/daily_cost.py` is **not** touched. Operations stores its
  own classification explicitly; the two may disagree and that disagreement is future work, not a defect.
- The daily-cost 24-hour rule and the operations completeness rule are different rules over different
  objects; neither is changed by this module.

**Guard:** `backend/tests/test_operations_isolation.py` walks SQLAlchemy metadata, asserts no `ops_` FK
targets a costing table (and vice versa), asserts the costing services' import graph, and asserts every
new permission is namespaced `ops-*`. This test is a release gate, not an advisory.

### 2.3 Module entitlement (so nobody is confused)

`module_entitlements (organization_id, module_key, is_enabled, enabled_at, enabled_by)` with
`module_key ∈ {costing, operations, invoice-processing, …}` — additive, one row per module actually
enabled.

- The sidebar group **Well Operations** and every `/operations` route render only when the module is
  enabled **and** the user holds at least one `ops-*` capability.
- A costing-only workspace never sees the module; an operations-only workspace never sees AFE/Daily Cost.
- Enabling/disabling is an owner action, audited, and does not delete data.
- Default for existing workspaces: `operations = false` until the owner switches it on, so deploying this
  release changes no existing user's screen.

---

## 3. Domain model

Conventions applied to every table without repeating them: `organization_id` (FK, indexed, filtered on
every query), soft delete (`is_deleted`, `deleted_at`, restore + purge endpoints), audit row per mutation,
`created_at/updated_at/created_by/updated_by`, column-wise storage only (no JSON), `Numeric(28,10)` for
decimal measures, `Integer` minutes for durations, snapshots beside every FK, explicit Alembic revision.

### 3.1 Scope model — how rig / well / drilling-completion scoping is enforced

```
organization
└── block
    └── rig            (one rig, many wells over time)
        └── well
            ├── scope = drilling    → one document folder, one plan, one report series, one timeline
            └── scope = completion  → one document folder, one plan, one report series, one timeline
```

- `scope ∈ {drilling, completion}` on every report, block, plan, folder and metric. It is validated
  against `Well.sections_for_scope(scope)`.
- Every query is filtered by `organization_id` **and** (where the entity has one) `well_id` and `scope`.
- A rig may only be attached to a report whose well currently belongs to that rig; when a report's rig
  disagrees with the well's rig (historical moves), the report keeps the reported rig with a snapshot and
  a `rig_mismatch` finding rather than being rejected.
- Cross-scope access (completion user opening a drilling report) is denied by the same capability set,
  not by a separate table.

### 3.2 Documents and folders (requirement 16)

```
ops_well_folders        id, org, well_id, scope, folder_type ('reports'|'plans'|'programmes'|'certificates'|'other'),
                        year, month (nullable, for the date tree), label, sort_order
ops_documents           id, org, well_id, scope, folder_id (nullable),
                        document_type ('DDR'|'DCR'|'DMR'|'RMR'|'plan'|'programme'|'certificate'|'other'),
                        file_name, content_type, size_bytes, checksum_sha256,
                        source ('upload'|'import'|'api'), storage ('database'|'external'),
                        content LargeBinary (deferred), external_ref,
                        document_date, report_no_text, status
                        ('uploaded'|'extracting'|'extracted'|'extraction_failed'|'reviewed'|'archived'),
                        extraction_job_id, supersedes_id, version_no, is_current,
                        retention_until, legal_hold, notes, uploaded_by_*
ops_document_versions   id, org, document_id, version_no, checksum, size, replaced_by, replaced_at (audit trail of file replacement)
ops_document_links      id, org, document_id, entity_type ('report'|'mud_report'|'rig_move'|'plan'), entity_id
```

- The **directory** the user sees is `Well → Scope → Year → Month`, with the document. It is a query, not
  a filesystem: works in Docker, in Render, and in the backup archive with no volume to lose.
- **Dedupe**: `checksum_sha256` unique per organisation; re-uploading the same file returns the existing
  document and offers "view / re-extract / replace", never a duplicate.
- **Versions**: replacing a file creates a version row and keeps the old bytes until purge; the report it
  produced keeps its own immutable extraction snapshot.
- **Limits**: 25 MB/file (mirrors `invoice_attachments`), allowed types `pdf`, `xlsx`, `xlsm` (macro
  content rejected), `xls`, `csv`, plus `docx` for supporting documents; MIME sniffed, extension is not
  trusted. Per-workspace cap and per-well cap configurable.
- **Safety**: ZIP/PDF bomb guards (page count, compressed-size ratio, per-page word cap), parser run with
  a wall-clock timeout, workbook XML never evaluated, macros never executed, external links never
  resolved, no network access from the parser, formula-injection sanitising on every export.
- **Read-only source**: an uploaded workbook is stored byte-for-byte. Sheet protection is *read past*
  (it is a UI lock, not encryption); file-level encryption is detected and reported as "password
  required" with a guided action. The original is never rewritten.
- **Retention**: documents inherit `ops_settings.retention_years` (default 10), purge only through the
  existing Deleted Entries pattern with `ops-doc:permanent-delete`.

### 3.3 Reports, extraction and time blocks

```
ops_daily_reports        id, org, well_id, rig_id, scope, report_type ('DDR'|'DCR'),
                         report_date, report_no_text, report_no_seq, day_number, event_code,
                         period_start_at, period_end_at, period_timezone, period_minutes,
                         hole_section_id, phase_id, depth_start_m, depth_end_m, depth_unit,
                         tvd_m, progress_m, rotating_hours, dfs_days, est_days, md_auth_m,
                         last_casing_size_in, last_casing_depth_m,
                         customer, project, site, datum, supervisor, engineer, uwi, block_text,
                         status ('draft'|'in_review'|'submitted'|'approved'|'rejected'),
                         extraction_status ('none'|'running'|'needs_review'|'reviewed'|'failed'),
                         current_extraction_id, source_document_id,
                         operation_summary, forward_plan, hse_summary, remarks,
                         submitted_at/by, approved_at/by, rejection_reason,
                         supersedes_id, superseded_by_id, is_current, revision_no,
                         residency flags (`*_snapshot` columns for rig/well/section/phase names)
ops_activity_blocks      id, org, report_id, sequence_no,
                         started_at, ended_at, duration_minutes,          -- stored, always recomputed from timestamps
                         phase_raw ('DRLPRO'…), operation_code_id, activity_code_id, activity_id,
                         classification ('Planned'|'UPA'|'NPT'), allocation ('PT'|'NPT'|'UPA'|'SP'),
                         is_productive, classification_source ('explicit'|'code'|'keyword'|'timeline'|'reviewer'),
                         npt_code_id, npt_code_snapshot, agency_id, cause_code,
                         hole_section_id, phase_id,
                         depth_from_m, depth_to_m, depth_unit, footage_m, bit_depth_m,
                         rotating_hours, rop_m_per_hr, rop_basis ('rotating'|'drilling'|'none'),
                         responsible_party, vendor_id, reason, narrative,
                         source_page, source_bbox, confidence, review_state ('suggested'|'accepted'|'edited'|'rejected'),
                         reviewer_user_id, reviewed_at
ops_unaccounted_time     id, org, report_id, from_at, to_at, minutes, reason, source
ops_report_revisions     id, org, report_id, revision_no, changed_by, changed_at, summary, reason
ops_report_status_history id, org, report_id, from_status, to_status, actor, at, note
ops_daily_metrics        id, org, well_id, rig_id, scope, report_date, day_number,
                         logged_minutes, planned_minutes, upa_minutes, npt_minutes, pt_minutes, sp_minutes,
                         productive_minutes, unaccounted_minutes,
                         depth_end_m, footage_m, rop_m_per_hr, cum_days_from_spud, cum_footage_m,
                         plan_cum_days_at_depth, lag_days, lag_basis,
                         npt_block_count, avg_confidence, review_state, computed_at
```

Rules:

- `duration_minutes` is always recomputed from timestamps; the client value is only a cross-check.
- `classification` **and** `allocation` are stored: the organisation uses `P/U/NPT` marks and
  `NPT/PT/UPA/SP` allocation (study §3). They are not the same field.
- `is_productive` is derived from the activity/operation code by default, overridable with a reason;
  `NPT` can never be productive (DB check).
- `footage_m = depth_to_m − depth_from_m` when positive; `rop_m_per_hr = footage_m ÷ rotating_hours`
  (study S8). ROP is stored with its basis and never computed look-ahead.
- Approving a report freezes its blocks: later edits create a revision (PO/SO amendment pattern).

### 3.4 The configurable code library (requirement: "categorizations and codes… user configurable")

All registers share: `code`, `name`, `description`, `sort_order`, `is_active`, soft delete, import/export,
audit, and a **starter list** import (never seeded into the database by a migration).

| Table | Contents | Starter list |
| --- | --- | --- |
| `ops_phase_codes` | 10 phase codes (`DRILL`, `COMP`, `MOB`, `PREP`, `ABAN`, `W.O.`, `W.T.`, `SEC-WELL`, `RE-EN`, `PROD-MAN`) | from `Codes` sheet |
| `ops_operation_codes` | 20 operation codes A–T with names, `default_classification`, `is_productive_default`, `counts_as_on_bottom`, `requires_npt_code` | from `Codes` sheet |
| `ops_activity_codes` | the 37 numeric activity codes with names and default allocation | from `Codes` sheet |
| `ops_activities` | the 256 fine activities, each mapped to an operation code + activity code, with keyword aliases | from `Codes` sheet |
| `ops_npt_codes` | the 75 codes, with `family` (`well`/`rig`/`downhole`/`surface`/`waiting`/`other`), `is_planned_variant`, `default_agency`, `is_chargeable`, `is_company_caused`, `is_contractor_caused`, keywords | from `Codes` sheet |
| `ops_agencies` | 30 agencies + category (`operator`/`rig_contractor`/`service`) | from `Codes` sheet |
| `ops_causes` | 17 cause codes | from `Codes` sheet |
| `ops_phase_map` | mapping from OpenWells phase abbreviations (`DRLPRO`, `DRLSUR`, `CSGIN2`, `EVAL`, …) → hole section + operation code + activity code | derived from the 12 observed values, editable |
| `ops_rig_aliases`, `ops_well_aliases` | normalised alias → `rig_id`/`well_id` with confidence | seeded from existing rigs/wells + the observed spellings |
| `ops_activity_keywords` | activity/cause keyword → activity/cause/NPT code mapping used by the inference engine | starter ~200 phrases, editable, learns from corrections |
| `ops_settings` | one row per workspace (see §3.5) | defaults |

`ops_activities` references the existing Master Data `activities` **by nullable FK plus snapshot** — never
by replacement. If a client wants one list for both modules, they map them; otherwise operations owns its
own list without touching AFE/cost behaviour.

### 3.5 Settings

`ops_settings`: `day_boundary_hour` (default 0), `operating_timezone`, `tour_pattern`
(`single_24h`|`day_night_12h`), `require_review_before_submit` (default true),
`auto_extract_on_upload` (default true), `classification_confidence_high` (0.85),
`classification_confidence_low` (0.60), `require_npt_code`, `require_npt_agency`,
`require_npt_reason`, `max_daily_hours` (24), `completeness_tolerance_minutes` (2),
`allow_block_spill` (true, max 1 block), `default_depth_unit`, `default_rop_basis` (`rotating`),
`plan_contingency_hours` (2), `plan_trip_speed_m_per_hr`, `document_max_mb` (25), `retention_years` (10),
`extraction_timeout_seconds` (60), `ai_assist_enabled` (false).

---

## 4. The document vault and the review workspace

### 4.1 Upload flow

1. User drags files onto **Well → Scope → Documents** (or uses the global *Upload reports* screen, which
   asks for well/scope only when the report cannot be identified).
2. Server sniffs the type, computes SHA-256, checks dedupe and limits, stores the bytes, records the
   document, and (if `auto_extract_on_upload`) queues an extraction job.
3. The screen shows a live status per file: `uploaded → extracting → needs review → reviewed`, with the
   failure reason inline and a **Retry extraction** action.
4. Batch upload is supported; each file succeeds or fails on its own; nothing is silently dropped.

### 4.2 Directory view

`Well → Drilling / Completion → Years → Months → documents`, with counts, status chips, report-date and
report-no columns, filters (type, status, date range, uploaded by), search, and actions: view, download,
re-extract, replace version, link to report, delete. The same tree is exportable (XLSX index) and printable.

### 4.3 Review workspace (the heart of requirement 5)

Split screen, permission `ops-report:update`:

- **Left:** the source document — PDF pages rendered by the browser's own viewer for `pdf`, and for
  XLSX a server-rendered sheet grid preview (the workbook is never handed to a JS spreadsheet engine that
  could execute formulas). Page/sheet navigation; the block being reviewed is highlighted via its stored
  page + bounding box.
- **Right:** the parsed record in tabs — *Header*, *Time blocks*, *Depths & sections*, *Mud*, *Bit & ROP*,
  *Safety*, *Personnel*, *Materials*, *Narrative*, *Findings*.
- Every field carries a **provenance chip**: extracted (with confidence), computed, defaulted, or edited
  by *user* at *time*. Low-confidence fields are visibly flagged, not hidden.
- **Findings panel** lists every conflict and rule that fired: "block 7 overlaps block 8", "NPT code
  missing", "report no. 81 but DFS 76", "depth unit ft in a metric well", "well name matched by alias
  (0.72)", each with a one-click jump and a suggested fix.
- **Keyboard-first**: next/accept (`Enter`), edit (`E`), reject (`X`), next finding (`N`). "Accept all
  high-confidence" exists, but never accepts below the configured threshold and never submits.
- **Learning**: a correction is stored in `ops_extraction_overrides` (pattern → target, with a
  hit-count and the user who taught it) and `ops_activity_keywords`; the next extraction of similar text
  proposes the corrected mapping. Deterministic, inspectable, revocable — no opaque model.

### 4.4 Workflow and status

`draft → in_review → submitted → approved` (with `rejected` back to `draft`), plus revision on amendment.

- Only `draft`/`in_review` are editable. `submitted` needs `ops-report:submit`; `approved` needs
  `ops-report:approve` (a different person where the workspace requires it); amendment needs
  `ops-report:amend` and creates a revision, keeping the approved version and its audit trail.
- A report cannot be submitted while blocking findings remain (overlap, missing NPT code/agency/reason,
  block outside the period, unconfirmed low-confidence header identity). Non-blocking findings are listed
  and acknowledged.
- Nothing is ever submitted automatically, however confident the engine is.

---

## 5. The extraction engine (requirement 10: "more intelligent and capable")

### 5.1 Architecture

New package, following the repo's layering:

```
backend/app/models/operations.py            tables (§3)
backend/app/domain/operations/              pure functions, standard library only, no DB
    taxonomy.py                             code → classification/allocation/productivity mapping
    classify.py                             rule engine + confidence
    durations.py                            minutes, period resolution, completeness
    plan.py                                 rate-based planned hours, cumulative curves
    metrics.py                              ROP, lag/lead, coverage, Pareto, data-quality score
    normalise.py                            units, dates, names, amounts
backend/app/services/operations/            database + validation + orchestration
    documents.py                            vault, dedupe, versions, retention
    extraction.py                           job runner, stages, promotion to report
    extractors/base.py                      shared geometry helpers
    extractors/openwells_pdf.py             DDR/DCR/RMR family
    extractors/mud_excel.py                 DMR family
    extractors/ops_summary_excel.py         the engineers' Summary/Timeline workbooks
    extractors/generic_pdf.py               fallback (section titles + key/value + tables)
    review.py                               findings, overrides, accept/edit
    reports.py, plan.py, analytics.py, masters.py, settings.py
backend/app/api/operations.py               routers
backend/app/schemas/operations.py           typed DTOs
```

`domain/operations/*` is pure and unit-tested without a database (same discipline as
`domain/cost_intelligence.py`), so the classification and lag/lead rules are testable in isolation.

### 5.2 The nine stages of one extraction

| # | Stage | What it does | Stored as |
| --- | --- | --- | --- |
| 1 | **Intake** | type sniff, limits, checksum, encryption/macro detection, store bytes | `ops_documents` |
| 2 | **Identity** | report family from layout signature; well, rig, scope, report date/no, period; alias matching with confidence; duplicate/amendment detection | `ops_extraction_jobs`, findings |
| 3 | **Segment** | split into the known sections using titles **and** table header signatures (`From To Dur Phase Code Sub Class` is the time-log fingerprint) | job section map |
| 4 | **Extract** | typed extractors per section: header key/value, time-log rows by geometry, hole sections, mud, BHA/bit, pump, safety, personnel, materials, surveys, remarks | job payload rows |
| 5 | **Normalise** | units → metres, dates → ISO with ambiguity rules, `23:59` → 24:00 tolerance, names → canonical, amounts → Decimal | normalised draft |
| 6 | **Resolve taxonomy** | map the reported `Phase`/`Code`/`Sub Class` and narrative to the configured registers; unmatched values become **candidates**, never silent drops | findings + drafts |
| 7 | **Classify & correlate** | classification, allocation, NPT code, agency, cause, productivity — with rule trail and confidence (§6) | drafts + findings |
| 8 | **Validate** | completeness, overlaps, depth monotonicity, NPT completeness, cumulative-counter continuity against the previous report, unit sanity, identity consistency | findings (blocking/warning) |
| 9 | **Assemble draft** | create/refresh the draft report with blocks, metrics and provenance; compute ROP, lag/lead and the brief; put it in the review queue | `ops_daily_reports`, `ops_activity_blocks`, `ops_daily_metrics` |

Properties that matter:

- **Idempotent and re-runnable.** Re-running an extraction creates `ops_extraction_jobs` row *n+1*; the
  reviewer's accepted/edited values are preserved (they are keyed by sequence + start time + fingerprint),
  new findings are shown as a diff. A parser upgrade therefore never destroys work.
- **Never destructive.** A failed extraction leaves the document stored and readable; it never half-writes
  a report. Promotion to a report is one transaction.
- **Existing engineer workbooks are importable.** The four Operations Summary workbooks and the two DMR
  workbooks are first-class inputs (`ops_summary_excel`, `mud_excel`), including protected and hidden
  sheets, so the client's history can be loaded without re-typing — and the module becomes the system of
  record from then on.

### 5.3 Report families and signature detection

| Family | Signature | Parser |
| --- | --- | --- |
| OpenWells daily (DDR/DCR/RMR) | `OpenWells` footer, sections `1 General` … `2.1 Operation Summary`, time-log header | `openwells_pdf.py` |
| Mud report workbook (DMR) | sheets `OBM`/`WBM`, `DAILY MUD REPORT`, `Specifications IN OUT` | `mud_excel.py` |
| Operations summary workbook | sheets `Summary`, `Codes`, `Input-lookahead`, `PT-NPT DATASHEET` | `ops_summary_excel.py` |
| Generic PDF/CSV | none of the above | `generic_pdf.py` (section titles + key/value + tables) with lower confidence and a mandatory manual mapping step |
| Unknown | no match | stored, queued as `extraction_failed` with "unrecognised layout — map manually" |

RMR is handled as an OpenWells daily report with `report_type = RMR` and rig-move fields extracted into
`ops_rig_moves` when the narrative or a mover's layout provides them (move type, departure/arrival, distance,
planned vs actual duration).

### 5.4 Excel specifics

- Read with `openpyxl` in read-only/data-only mode; sheet protection ignored for reading, file-level
  encryption reported; hidden sheets skipped unless mapped; pivot/MS-Query targets detected (they carry
  headers but no rows) and the underlying sheet read instead.
- Table detection: locate the header row by matching the known column set (`Block`, `Field`, `Rig Name`,
  `Well Name`, `Start Time`, …), then read rows until a blank run. Column names are matched case- and
  whitespace-insensitively with an editable mapping table, because the engineers' headers contain line
  breaks and drift (`Depth End M)` vs `Depth End (m)` vs `Depth End (ft)`).
- Dates: Excel serial and text both handled; the ambiguous `mm/dd` vs `dd/mm` rule (§6.2) applies.
- Formulas: only cached values are read; nothing is recalculated; the **imported values are evidence**
  and every computed figure (ROP, cumulative days, lag/lead) is recomputed server-side so the workbook's
  known defects (study §1.8) cannot propagate.
- The import screen previews the mapping, the row count, the detected unit and the identity, and refuses
  the import if identity is unresolved.

### 5.5 Performance and limits

- One DDR: ≤ 8 s extraction on a 4-core container (measured target; 6 pages, ~15 blocks).
- One 900-row Summary workbook: ≤ 20 s.
- Jobs run in a bounded worker pool (`threading`, like `services/backup.py`), one job per document,
  timeout enforced, progress persisted. No external queue dependency.
- Uploads are processed off the request that stores them, so a 25 MB file never blocks the UI.

---

## 6. Classification and allocation engine

### 6.1 Two axes, stored separately (study S4)

| Field | Values | Meaning |
| --- | --- | --- |
| `classification` | `Planned`, `UPA`, `NPT` | the organisation's plan mark (their `Plan` column, their `P/U/NPT`) |
| `allocation` | `PT`, `NPT`, `UPA`, `SP` | the reporting allocation (their `Select PT/NPT Allocation` list) |
| `is_productive` | bool | forward progress; `NPT` can never be productive |

Mapping (editable): `Planned → PT`, `NPT → NPT`, `UPA → UPA`, and `SP` (slow progress) is a sub-case of
`Planned` that is flagged as low-productivity rather than non-productive. This keeps the three-way
requirement while preserving the four-way allocation the crews already use.

### 6.2 Evidence, precedence and confidence

| Rule | Evidence | Weight |
| --- | --- | --- |
| R1 explicit import | the engineers' `Plan`/`Agency`/`Cause` columns | 1.0 (authoritative when present) |
| R2 explicit mark | PDF `Sub/Class` `P`/`U`/`D` | 0.55 (`D` → NPT candidate, S3) |
| R3 NPT code | a trouble code (`T*`/`X*`) already chosen | 1.0 |
| R4 activity-code semantics | code 21–24 waiting, 25 maintenance, 26 strike, 29 fishing, 31 redress TSV ⇒ NPT/UPA | 0.45 |
| R5 keyword lexicon | `WAITING ON`, `LOST CIRCULATION`, `STUCK`, `FISHING`, `TRIPPED OFF`, `RIG REPAIR`, `WEATHER`, `HOLD`, `NO CIRCULATION`, `REDRESS`, `CREW` … (~200 entries, editable) | 0.3 each, capped |
| R6 timeline correlation | the block is not in the plan, or is > 1.5× the planned duration, or occurs while the plan expects on-bottom drilling | 0.35 |
| R7 history | the same activity on the same well was classified NPT/UPA before | 0.15 |
| R8 reviewer | a human decision | 1.0, final |

`confidence = 1 − Π(1 − w)` over the fired rules, clamped, and every fired rule is written to
`ops_extraction_findings` with its reason text so the number is explainable in one click. Bands:
`≥ high → pre-accepted suggestion`, `low…high → needs review`, `< low → flagged as unresolved`.
When `require_review_before_submit` is on (default) **nothing reaches a submitted report without a
reviewer's acceptance**; the bands only order the reviewer's work.

### 6.3 NPT completeness

`NPT` requires a code, an agency (responsible party) and a reason of ≥ 10 non-blank characters — enforced
in the schema, in the service and as DB checks (the API is not the only writer). `UPA` requires a reason.
The reviewer can pick from the 75-code list filtered by family and by the keywords that fired.

### 6.4 Period, durations and completeness

`resolve_period(report_date, scope)` → `[00:00, 24:00)` in the workspace timezone, converted to UTC for
storage and back for display. Completeness: `Σ duration_minutes` must equal `period_minutes` within
`completeness_tolerance_minutes` (default 2, because reports use 23:59) **or** the difference is recorded in
`ops_unaccounted_time` and surfaced as a warning. Overlaps are always blocking; a single spill block past
midnight is allowed and flagged (study Q10).

### 6.5 Deriving days

- **Campaign day** (`day_number`): from the scope's spud (`drilling_spud_at` / `completion_spud_at`),
  never from the report number; a future/absent spud yields a flagged null (Q6).
- **Logged time** (sum of blocks ÷ 24) and **DFS** (reported) are stored separately; the dashboard prints
  which basis a percentage uses.

### 6.6 The "brief" (requirement 3)

A deterministic composition, printed and exportable:

1. identity line (well, rig, scope, day N, report no., depth start→end, footage, ROP, cum. days);
2. the day in one paragraph: the top 3 blocks by duration, with their classification;
3. time split: planned / UPA / NPT / unaccounted hours and percentages, with the basis;
4. NPT list: code, hours, agency, cause, one-line reason each;
5. depth progress and section status against plan (lead/lag);
6. people/materials/HSE headlines (POB, mud weight, safety event);
7. forward plan (next 24 h) as extracted, unedited;
8. a "data quality" line: blocks reviewed, unresolved findings, confidence average.

An optional **AI polish** (workspace toggle, default off) may rewrite paragraphs 2–4 for readability using
the existing offline Ollama client. Facts, numbers and codes are injected by the server and the model is
never allowed to add or change a figure; the deterministic brief is always available beside it.

---

## 7. Timeline, lead/lag, ROP (requirements 4, 8, 9)

### 7.1 Plan model

```
ops_plan_versions   id, org, well_id, scope, version_no, label, basis ('programme'|'afpd'|'engineer'),
                    status ('draft'|'active'|'superseded'), planned_start_at, planned_days,
                    prepared_by, approved_by, notes
ops_plan_items      id, org, plan_version_id, sequence_no, hole_section_id, phase_id,
                    operation_code_id, activity_id, description, target_depth_m, delta_depth_m,
                    planned_hours, planned_start_at, planned_end_at, cum_planned_days,
                    hours_source ('rate'|'manual'), rate_basis ('rop'|'trip_speed'|'fixed'),
                    rop_assumption_m_per_hr, trip_speed_joints_per_hr, contingency_hours,
                    is_critical_path, notes
ops_plan_item_actuals id, org, plan_item_id, report_id, block_id, actual_hours, actual_start_at,
                    actual_end_at, mapping_source ('auto'|'manual'), confidence
ops_plan_assumptions id, org, well_id, scope, hole_section_id, rop_m_per_hr, trip_speed_joints_per_hr,
                    connection_minutes, contingency_hours, flat_time_hours
```

- The **plan builder** reproduces what the engineers do today with formulas (study §1.8): pick hole
  section and activity, give the target depth; planned hours are generated from ROP / trip speed /
  contingency assumptions, editable per item. No plan leaves the module unversioned; activating a new
  version keeps the old one for comparison.
- A plan can also be generated from the well plan already in the database
  (`well_sections` + `well_phases.days`) so the schedule baseline is not re-typed.

### 7.2 Actual mapping

Blocks map to plan items automatically by activity/depth/time-window with a confidence, and the reviewer
can fix the mapping in the timeline screen (drag a block onto a plan item). Unmapped blocks are visible,
not discarded; unplanned blocks are exactly the evidence for UPA/NPT.

### 7.3 Lead/lag definitions (printed next to every figure)

| Measure | Formula | Sign convention |
| --- | --- | --- |
| `lag_days(item)` | `actual_cum_days − planned_cum_days` at the item's completion | **positive = behind schedule (lag)**, negative = ahead (lead) |
| `lag_days(day)` | `actual_cum_days − planned_cum_days_at_actual_depth` | schedule variance against the plan curve at today's depth |
| `milestone_variance(days)` | `actual_date(section TD / casing point) − planned_date` | positive = late |
| `lead_credit(days)` | `max(0, −lag_days)` | reported separately, never netted away silently |

Computed per **well, scope, hole section, phase and plan item**, stored in `ops_daily_metrics` and
`ops_plan_item_actuals`, recomputed on report save/approve, never hand-typed. Current-workbook defects
(study §1.8) cannot recur because the server owns the arithmetic.

### 7.3a Hours, and the engineer's correction (the reference workbook's Input-lookahead sheet)

The workbook set the requirement: lead and lag are **hours**, not opinions. Each activity block carries:

| Column | Meaning | Who sets it |
| --- | --- | --- |
| `timeline_planned_hours` | the active programme's hours for the matched item | programme, read-only |
| `timeline_system_actual_hours` | the block's logged duration ÷ 60 at the time it was compared | the time log |
| `timeline_actual_hours` | the engineer's actual hours — the logged figure until edited | the engineer |
| `timeline_variance_hours` | `planned − actual`, lead positive | recomputed from the two rows above |

- `_match_plan_item` maps a block to a programme row by normalised description (Jaccard, exact match = 1.0,
  prefix ≥ 0.72, a −0.15 penalty for reusing an item already matched, threshold 0.5). No confident match is
  better than a wrong one: an unmatched block reports `no matching programme activity` and no variance.
- `POST /operations/reports/{id}/timeline-review` accepts `hours: [{block_id, actual_hours}]`.
  `null` clears a correction and restores the logged hours. `rejected` blanks the variance rather than
  zeroing it — "not comparable" and "on plan" are different statements.
- The **edited value is stored on the block**, so the next day, the dashboard, the charts and the guide all
  read it. A later re-suggest skips a block whose `timeline_actual_edited` is set, and a report save with an
  edited actual recomputes only the variance, never overwriting the engineer's figure.
- An edit needs a reason, recorded with the actor and the timestamp and written to the Audit Log, because the
  value now differs from the time log.
- `reports.review_timeline` returns the recomputed `variance_hours`, `total_variance_hours` and
  `corrected_blocks`; the report editor's **Review hours & lead / lag** dialog shows planned, system,
  editable actual, cumulative planned/actual and the variance per row, with the totals above the table.
- The `timeline_review_state` and `timeline_note` are **not** part of the bulk block save: a report save must
  not silently replace a human review decision.

### 7.4 Time vs depth curves

`GET /operations/analytics/time-depth` returns, for a well/scope (or several wells):

- `plan`: `[(cum_planned_days, depth_m, label)]` from the active plan version;
- `actual`: `[(cum_actual_days, depth_m, report_date, block_id)]` from the blocks (depth at block end);
- `actual_by_day`: last depth per report date (for a clean daily staircase);
- `sections`: hole-section boundaries with names and sizes;
- `npt_bands`: time intervals to shade on the time axis;
- `milestones`: spud, casing points, section TD, TD, rig release (planned vs actual);
- `lag_series`: the day-by-day lag in days.

Charts: time-vs-depth (default), depth-vs-time, plan-vs-actual cumulative days, lag/lead waterfall, ROP
vs depth, NPT bands. All are the standard `ChartPanel`/`InteractiveChart` with drill-through to the blocks
that produced a point (verified on the mounted page, per the cost-intelligence chart lesson).

### 7.5 ROP

| Measure | Definition |
| --- | --- |
| Block ROP | `footage_m ÷ rotating_hours` (basis stored; `drilling` basis available) |
| Day ROP | day footage ÷ day drilling hours |
| Section ROP | section footage ÷ section drilling hours |
| Bit-run ROP | footage between bit runs ÷ rotating hours (from `ops_bit_runs`) |
| Plan ROP | the assumption used to generate planned hours |
| ROP variance | actual − plan, and the footage it cost (input to lead/lag explanation) |

ROP only counts blocks whose activity code is on-bottom drilling (`counts_as_on_bottom` on the operation
code). Trips, casing and waiting never enter ROP. Footage is only counted when the bit advanced
(`depth_to > depth_from`), so reaming is excluded from ROP but included in time.

### 7.6 "Keep the timeline in memory" — correlation store

A per-well materialised view, recomputed on every report save/approve:

- `ops_timeline_state` (one row per well/scope): active plan version, current plan item, planned cum days,
  actual cum days, lag days, current section, current phase, last report date, expected next report date,
  open findings count, data-quality score.
- `resolver.expected_state(well, scope, at)` returns the planned `(item, depth, days)` at an instant;
  the classification engine, the dashboard, the "missing report" check and the brief all use it.
- Because it is a table (not a cache in memory), it survives a restart, is tenant-scoped and is auditable;
  "in memory" in the requirement is satisfied by *persisted, instantly available* state, not by a
  process-local cache.

---

## 8. Well geometry: depth, position, direction (requirement 7)

```
ops_surveys          id, org, well_id, scope, report_id, station_no, md_m, inc_deg, azi_deg,
                     tvd_m, ns_m, ew_m, vsec_m, dls_deg_per_30m, tool, source ('section'|'narrative'|'manual'),
                     confidence, survey_at
ops_well_headers     id, org, report_id, md_m, tvd_m, progress_m, rotating_hours, dfs_days, est_days,
                     md_auth_m, last_casing_size_in, last_casing_depth_m, datum, kb_elevation_m,
                     depth_unit_entered
ops_hole_sections_actual id, org, well_id, scope, hole_section_id, size_in, top_m, base_m,
                     started_at, ended_at, source_report_id, is_current
```

- Surveys come from section 7.1 when present and from narrative gyro/MWD lines
  (`MWD SURVEY @ 9784.87 FT, INC 26.28°, AZI 147.10°`) by a typed regex; both are stored with provenance
  and confidence, and nothing is fabricated when the table is partial (study Q20).
- Position (N/S, E/W, vertical section) is stored when reported; a minimum-curvature calculation fills
  TVD/NS/EW/DLS only when the module is asked to and the inputs are complete, and the calculated rows are
  marked `calculated` so a reported value always wins.
- **Implemented as a service, not a view.** `backend/app/domain/operations/trajectory.py` is a pure
  minimum-curvature engine (`integrate()`, `interpolate_tvd()`, `survey_azimuth_from_departure()`); it has no
  database or HTTP dependency and is unit-testable on its own. `backend/app/services/operations/well_path.py`
  assembles a single payload from the record:
  * `GET /operations/well-path?well_id&scope&vs_azimuth` — stations, summary, casing sections, open hole,
    planned curve, current depth with its basis, survey discrepancies, notes and one `assumption` sentence;
  * `GET /operations/well-diagram?scope&rig_id&well_id` — the same payload per configured well of a scope;
  * `OpsDashboardOut.well_visual` — schematic plus depth for a single-well filter (null for a multi-well
    filter, where one drawing would misrepresent the rest).
- **Provenance rules, each of which stops a plausible-but-wrong number:**
  * current MD = max(last survey station MD, latest report's closing depth). Verified (submitted/approved)
    reports beat drafts; the draft is used only when nothing is verified, and `depth_basis` says which;
  * current TVD = survey interpolation at the current MD; falls back to the report header TVD, then to MD with
    `assumed vertical (no surveys)` stated in words;
  * casing seats come from the report header pair (`last_casing_size_in`, `last_casing_depth_m`) first, then
    from configured `well_sections`; the deepest printed shoe wins for a given size; a size without a depth
    is not a seat;
  * a printed TVD that contradicts the integration beyond tolerance is **reported, not overwritten**
    (`survey_discrepancies`); the drawing uses the integrated value and the page shows both numbers;
  * the vertical-section plane is the well's own closure azimuth by default (two-pass integration); an
    explicit `vs_azimuth` rebuilds the curve in a reference plane;
  * surveys are de-duplicated by measured depth on `is_current`, so a re-extracted report cannot draw the same
    station twice.
- **Pages.** `/operations/well-path` (route guarded by `ops-dashboard:read` | `ops-report:read` |
  `ops-analytics:read`) draws the schematic + vertical section on one shared depth axis, a north/east plan
  view, inclination and dogleg, the station table and a provenance panel. The Operations Dashboard embeds the
  same panel for the selected well and scope, and its **Current depth** KPI card reads the same service, so the
  card and the drawing cannot disagree. The daily report dialog links straight to the well's own drawing.
- Casing sizes are parsed from either the imperial fraction the reports print (`13-3/8"`, `8 1/2"`) or the
  configuration's hole-section name; dogleg is normalised to degrees per 30 m from the printed per-100 ft
  value. 3-D remains optional and later: the two 2-D views answer the operational question without a
  WebGL dependency.

---

## 9. Dashboards and analytics (requirements 6, 10)

### 9.1 Operations dashboard (`/operations`)

Filters: date range (quick + advanced), rig, well, block, scope, hole section, phase, classification,
agency. Every KPI card prints its **basis** in the hint and drills through to records.

| KPI | Definition |
| --- | --- |
| Reporting coverage | wells with a reviewed report for the last operating day ÷ wells with an active scope |
| Missing reports | expected report days with no document (from the timeline resolver) |
| Logged hours | Σ block minutes ÷ 60 |
| Planned / UPA / NPT / SP hours and % | of **logged** time, basis printed |
| Productive % | productive minutes ÷ logged minutes |
| Unaccounted hours | Σ `ops_unaccounted_time` ÷ 60, with trend |
| NPT Pareto | hours by NPT code family, code and agency |
| Top causes | cause code × agency × well |
| ROP (avg, by section) | footage ÷ drilling hours, plan vs actual |
| Days vs plan | lag/lead at portfolio, rig and well level |
| Depth progress | current MD vs plan depth at today's plan day |
| Data quality score | 100 − penalties: unresolved findings, low-confidence fields, missing codes, unaccounted time |
| Review backlog | reports awaiting review, oldest first, by assignee |
| Recent activity | last uploads, submissions, approvals, rejections |

### 9.2 Other pages

| Page | Purpose |
| --- | --- |
| `/operations/rigs` | rig league table: productive %, NPT %, ROP, reports filed, lag |
| `/operations/wells` | well list with scope, status, day, depth, lag, open findings |
| `/operations/wells/:id` | well operations home: directory, reports, timeline, charts, briefs |
| `/operations/reports` | register (list, filters, bulk actions, import/export, print) |
| `/operations/reports/:id` | report editor / review workspace |
| `/operations/timeline` | plan versions, plan builder, actual mapping, lead/lag board |
| `/operations/analytics` | time-depth, ROP, NPT and data-quality analytics with export |
| `/operations/mud` | DMR register, mud property trends, losses, inventory |
| `/operations/rig-moves` | RMR register, move durations, planned vs actual |
| `/operations/documents` | global document browser (same tree, cross-well) |
| `/operations/library` | the configurable code library (all registers) |
| `/operations/settings` | workspace settings |
| `/operations/deleted` | Deleted Entries (restore/purge) |

### 9.3 Interaction rules

Filters persist per user; charts cross-filter the tables; drill-through opens the record that produced a
point; every export records an audit row; no animation, no emoji, Navy Blue & White enterprise theme with
the existing tokens; light/dark both verified.

### 9.4 Exports and print

- **DDR/DCR print** reproducing the paper form: header block, 24-hour table, narrative, forward plan,
  depth panel, signature block (supervisor / company man / toolpusher), then supporting panels
  (NPT by code/agency in hours, planned vs actual days and depth, detail log). Batch print of selected
  reports, one PDF, ordered well → date.
- **XLSX**: register export, block export, NPT analysis, time-depth series, plan vs actual, and the
  operations-summary layout the engineers already use (so their existing downstream files keep working).
- **CSV** for every table; **PDF** for the dashboard figures *and* charts, rendered from the same data
  the screen used (the standing convention from the costing dashboards).
- Formula-injection guards on every cell (`safe_csv_cell`), and a printed "figures as at" timestamp.

---

## 10. RBAC and tenancy

### 10.1 Capability namespaces

```python
"ops-report":   ("read","create","update","delete","restore","permanent-delete","import","export",
                 "submit","approve","amend","print","review"),
"ops-doc":      ("read","upload","update","delete","restore","permanent-delete","download","extract"),
"ops-master":   ("read","create","update","delete","import","export"),
"ops-plan":     ("read","create","update","delete","activate","export"),
"ops-analytics":("read","export"),
"ops-settings": ("read","update"),
```

No `ops-timelog` (blocks live inside a report and are governed by `ops-report`); no `ops-npt` separate
from `ops-report` at this stage — a redundant capability is a grant that looks meaningful and isn't.

### 10.2 Role templates (per workspace, editable)

| Role | Granted | Deliberately denied |
| --- | --- | --- |
| Drilling Supervisor | `ops-report:*` except approve/amend, `ops-doc:upload/read/download`, `ops-master:read`, `ops-analytics:read` | every costing capability |
| Night Company Man | `ops-report:read/create/update/review`, `ops-doc:read/upload` | submit, approve, analytics export, costing |
| Completion Supervisor | the same, completion scope | drilling-scope writes |
| Operations Manager | `ops-report:read/approve/amend/export/print`, `ops-plan:*`, `ops-analytics:*`, `ops-master:*` | data entry of blocks |
| Drilling Engineer (reviewer) | `ops-report:review/update`, `ops-doc:extract`, `ops-master:update`, `ops-analytics:read` | approve, delete, costing |
| HSE Officer | read-only across reports, `ops-doc:read` | any write, any cost |
| Executive / Analyst | `ops-report:read/export`, `ops-analytics:read/export` | any write |
| Administrator | `ops-settings:*` | — (still no costing unless granted) |

Every endpoint uses `Depends(require("ops-…"))`; every route is also gated by the module entitlement;
one test per capability asserts a `403` that names the missing key.

### 10.3 Tenancy

Every read filters `organization_id`; every write validates that the well, rig, section, phase, activity,
NPT code, agency and document belong to the caller's workspace and are not deleted. Tests mirror
`tests/test_daily_cost.py`'s cross-tenant battery for every endpoint and bulk action.

---

## 11. What we take from the reference repositories (requirement 12)

| Repo | Adopted | Rejected | Why |
| --- | --- | --- | --- |
| DrillDash | analytics vocabulary (days vs depth, footage/ROP per day, activity ribbon), whole-well overview beside a time axis, rule-based state as a second opinion | WITSML/parquet real-time stack, replay, vendored chart libs | no real-time feed here; the stack must stay this app's |
| drilling-report-database | layout-aware pdfplumber parsing, section/label dictionaries, child-table normalisation, duplicate detection by hash **and** identity, stored section text | SQLite/local-only architecture, free-text storage, AI-generated SQL | this repo already has PostgreSQL, typed columns and a governed assistant |
| DrillMind | 8-state activity state (drilling, reaming, circulating, connection, tripping in/out, washing, static) as an optional derived attribute, MSE/d-exponent as later KPIs | ML stack, PyTorch/scikit, vector store, alerts engine | no heavy dependencies; deterministic rules only |
| drilling-reports-ds-pipeline | table-type detection by header signature, dictionary-driven extraction from the client's own codes, problem-keyword → NPT cause mapping | notebooks as production code, transformer models | determinism, testability, offline |

The net effect: the *ideas* of four projects, implemented with this repository's layering and conventions
and **no new runtime dependency**.

---

## 12. Migrations, integration and non-regression

### 12.1 Migrations (one per phase, all additive)

Current head `d6a2b8c3e901`. Each revision: `create_table` + indexes + checks, permission backfill copied
structurally from `a9d4e2f7c138_add_afe_management.py` (idempotent, explicit `created_at`), module
entitlement row defaulted **off**, `downgrade()` dropping in reverse FK order and deleting only what it
created. **No business data is seeded in a migration** — starter code lists ship as import templates and
a "Load starter code list" action.

Gates for every revision: `alembic upgrade head` → `downgrade -1` → `upgrade head` on SQLite **and**
PostgreSQL, then `alembic check` on a fresh database, then the full suite in a fresh process (the
reflection-order flake documented in `.agent/memory/project.md` is fixed by making `_scope_for`
deterministic if the new `ops_` prefixes surface it — never by editing the assertion).

### 12.2 Cross-cutting integration (do not defer)

| Area | Work |
| --- | --- |
| Navigation | new **Well Operations** group after *Daily Cost Management*, permission- and entitlement-gated |
| API contract | bump `API_VERSION` and `REQUIRED_API_VERSION` together (0.15.0 for Phase 1) |
| Database Browser | `("ops_", "Well Operations")` in `MODULE_GROUPS`; hide sensitive columns (document bytes, `*_snapshot` noise) |
| Report Builder | ops tables selectable once browsable; human labels added to the catalogue |
| Assistant | ops facts inside `ai_context.py` under `ops-report:read` only; never cost figures |
| Retention / dependencies | register labels so purging a well/rig names the ops records that hold it instead of an opaque 500 |
| Backup | confirm round-trip of a document (bytes) and a report — a test, not an assumption |
| Audit | entity types `ops_report`, `ops_activity_block`, `ops_document`, `ops_plan`, `ops_*_code`; actions `create/update/delete/restore/submit/approve/reject/amend/import/export/extract/review` |
| Notifications / Task Manager | review assignments and rejected reports create a task through the existing engine |
| Deleted Entries | every register participates; purge only with `ops-…:permanent-delete` |

### 12.3 Non-regression

Existing AFE, Daily Cost, Mud Cost, Invoice, Report Builder, Cost Intelligence and Assistant suites must
pass unchanged. The isolation test (§2.2) is added and must pass. `make build`, `make ui-check`, and a new
`make operations-check` join the gate list.

---

## 13. Delivery plan

Sized for one senior full-stack engineer with a drilling-engineering SME available for review; parallel
work is noted. Estimates include tests and documentation, which are not optional in this repository.

| Phase | Deliverable | Exit criterion | Est. |
| --- | --- | --- | --- |
| **0. Foundations** | module entitlement, `ops_settings`, code library (all registers + import templates + alias tables), document vault, RBAC namespaces and role templates, nav/routes, audit, Deleted Entries, migration 1 | owner can enable the module, upload a PDF into a well/scope folder, manage codes; nothing visible to costing-only users | 3 wks |
| **1. Extraction engine v1** | OpenWells PDF parser (DDR/DCR/RMR), identity resolution, taxonomy resolution, classification engine, validation, draft assembly, review workspace with provenance and findings | the 21 sample reports extract to drafts with ≥ 95 % of blocks, ≥ 95 % of header fields, every block classified with a rule trail; engineer can review and save one report end-to-end | 5 wks |
| **2. Report lifecycle** | editable blocks, period/completeness rules, submit/approve/amend, print (paper form), register, imports/exports, brief | a supervisor files a DDR that replaces the paper form; 24 h reconciles; approved report is immutable | 3 wks |
| **3. Timeline, lead/lag, ROP** | plan versions, plan builder with rate assumptions, actual mapping, timeline state resolver, metrics, time-depth series | plan vs actual chart and lead/lag reconcile to the plan sheet for one real well; lag definition printed | 3 wks |
| **4. Dashboards & analytics** | operations dashboard, rig/well pages, analytics page, charts with drill-through, PDF/XLSX exports | every KPI traceable to records; a manager answers "where did the time go, and are we behind?" on one page | 3 wks |
| **5. Excel family + DMR + RMR** | Operations Summary workbook import (protected/hidden sheets, mapping preview), mud report register and trends, rig-move register | the client's existing workbooks import without re-typing; DMR trends render; moves planned vs actual | 3 wks |
| **6. Hardening & depth** | re-extraction diff, corrections learning, bulk backfill of history, surveys/trajectory panel, optional AI brief polish, performance tuning, handover docs and training guide | 12 months of history loaded; re-running a parser upgrade loses no reviewed work; extraction targets met | 3 wks |

**Total ≈ 23 weeks.** Phase 0 and Phase 5's Excel parser can be built in parallel with Phase 1 by a second
engineer. Phases 1–2 are the critical path; nothing after Phase 2 can start usefully before it lands.

---

## 14. Testing

### 14.1 Backend

1. **Domain unit tests** (`tests/test_operations_domain.py`): period resolution across timezones and a
   DST boundary, 23:59 tolerance, spill block, completeness, classification precedence and confidence
   arithmetic, plan rate generation, cumulative curves, lag/lead signs, ROP basis and exclusions.
2. **Parser tests** (`tests/test_operations_extraction.py`) against anonymised fixtures committed in
   `backend/tests/fixtures/operations/` (three reduced DDR PDFs — metric, imperial, completion — one DMR
   workbook, one protected Summary workbook): golden assertions on identity, block count, hours,
   classification, findings. Nothing else from the client's reports is committed.
3. **API tests**: lifecycle, draft-only editing, 409 on stale revision, bulk delete/restore/purge,
   amend, import/export, document upload limits/dedupe/versions, extraction retry, review actions.
4. **RBAC**: one test per capability (403 naming the key), entitlement-off yields 404/403 for every route.
5. **Tenant isolation**: every endpoint and bulk action, cross-workspace.
6. **Isolation guard** (§2.2) — FKs, imports, permission prefixes.
7. **Audit**: one row per mutation with the right entity/action.
8. **Security**: size/type/macro/zip-bomb/page-cap rejection, formula injection in exports,
   encrypted workbook handling, no network calls from the parser.
9. **Migration**: upgrade/downgrade/upgrade on SQLite and PostgreSQL, permissions backfilled, entitlement off.
10. **Backup round-trip**: document bytes and report survive export/import.

### 14.2 Frontend

`make operations-check` (jsdom, in the style of `.agent/tools/daily-cost-check.jsx`) asserting: the
directory tree groups by well/scope, a low-confidence field is visible, a blocking finding disables submit
with its reason, the unsaved-changes guard fires, the timeline chart plots plan and actual series and a
click opens the right block, the NPT Pareto drills through, the brief renders, and the print sheet repeats
table headers. Plus Chromium passes for both themes, table density and responsive layout.

### 14.3 Performance and quality budgets

| Budget | Target |
| --- | --- |
| DDR extraction | ≤ 8 s |
| 900-row workbook import | ≤ 20 s |
| Dashboard (20 rigs, 200 wells, 100k blocks) | ≤ 1.5 s p95 |
| Time-depth series (one well, full history) | ≤ 400 ms |
| Register page | 20/50/100 rows, ≤ 300 ms server time |
| Extraction recall on the 21 samples | ≥ 95 % of blocks, ≥ 95 % of header fields, 100 % of durations |

---

## 15. Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Report formats drift (new OpenWells template, a new contractor) | parser silently misses sections | signature detection, per-section "not found" findings, golden fixtures, generic fallback, re-run diff |
| `Sub/Class = D` or other marks are misinterpreted | wrong NPT split | treat as candidate, reviewer confirms, taxonomy editable, report the assumption |
| Date ambiguity (dd/mm vs mm/dd) | wrong day, wrong report identity | dual parse + validation against spud/DFS/sequence, confirm when ambiguous |
| Engineers reject the review workload | shelfware, back to Excel | keyboard-first review, accept-high-confidence, copy-from-previous, import of their existing workbooks, brief generated for free |
| Extraction "cleverness" erodes trust | users stop checking | every suggestion shows its rule and confidence; nothing auto-submits; corrections are inspectable and revocable |
| Decoupling erodes via a "temporary" FK | costs and operations drift together | isolation test is a release gate |
| Excel protection/encryption edge cases | uploads fail confusingly | read past sheet protection, detect file encryption, explicit message and guided action |
| Parser resource abuse (huge/pathological files) | outage | size/page/word caps, timeout, sandboxed worker, no network |
| Plan/timeline data not maintained | charts empty, lag meaningless | generate plan from `well_sections`/`well_phases`, rate-based builder, default assumptions per section, visible "no active plan" state |
| Scope creep into real-time WITSML / ML analytics | programme never ships | out of scope explicitly (§17); revisit only on a named request |
| Migration drift | production schema diverges | `alembic check` on a fresh DB is a gate, not advice |

---

## 16. Decisions needed from the client (blocking, cheap now, expensive later)

| ID | Question | Recommendation | Consequence if deferred |
| --- | --- | --- | --- |
| D1 | Confirm `Sub/Class = D` means NPT | yes, as a candidate | classification accuracy on 4/166 blocks now, more later |
| D2 | Is the report day 00:00–24:00 local (as the reports show) or a 06:00 boundary? | 00:00, configurable | uniqueness, day numbering, all day counts |
| D3 | Who may approve — Operations Manager only, or supervisor → manager? | two-step: submit (supervisor) → approve (manager) | permission model |
| D4 | Is `SP` (slow progress) reported separately or folded into `UPA`? | separately, folded only in the headline | KPI definitions |
| D5 | Which reports are in scope for v1: DDR/DCR only, or DMR/RMR too? | DDR/DCR v1, DMR/RMR Phase 5 | sequencing |
| D6 | Should historical workbooks be back-filled, and how far back? | import the current month + the wells in flight, then decide | data volume, effort |
| D7 | Retention period and legal hold for operational documents | 10 years, hold flag | purge design |
| D8 | May the optional offline AI rewrite be enabled for briefs? | off by default; enable after review | nothing (toggle) |
| D9 | Is the extracted time used for billing later (day-rate support)? | not in this module; hours only | keeps decoupling true |
| D10 | Unit default for the workspace | metres, with per-well override | display only |

---

## 17. Explicitly out of scope (so it does not creep in)

- Any cost, AFE, invoice, day-rate or billing figure; any correlation with Daily Cost (deferred Phase 5
  of the decoupling record, unscheduled).
- Real-time WITSML/RTOC streaming, replay and sensor analytics.
- Machine-learned anomaly detection, vector search and LLM-authored SQL.
- Mobile/offline field data capture.
- A second workspace or second database (already decided against, with reasons).
- Editing the client's workbooks in place or generating their exact macros.

---

## 18. Definition of done for the programme

A Drilling Manager opens one page and answers, for any well and any period, with every figure traceable
to a record:

1. Are our reports complete — every well, every day, reviewed?
2. How many days did this well take, against plan, per hole section?
3. Where did the time go — planned, UPA, NPT — and what caused it, and who owned it?
4. Are we ahead or behind, in days, and since when?
5. What is our ROP by section, against the plan assumption?
6. What did the day actually say, in one paragraph, with no re-typing?

And the drilling engineer opens one document and answers: *what did the engine read, how sure is it, what
do I need to fix before this becomes the record?* — in minutes, not the afternoon the spreadsheet costs.
