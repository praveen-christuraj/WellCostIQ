# Well Operations: detailed implementation plan

**Status:** plan only, and **superseded** — see `docs/operations/implementation-plan.md` (v2) and, for what
ships, [docs/operations/daily-workflow.md](operations/daily-workflow.md). The code lists sketched below
(`ops_operation_codes`, `ops_activity_codes`, `ops_npt_codes`, `ops_phase_codes`) were retired on
2026-11-19 in favour of Master Data Activities carrying an Activity type plus four Code Library lists; the
nine review criteria are Hole Section, Phase, Sub-phase, Activity, Allocation, Cause, Operations, Agency /
service vendor and responsible Agency.
**Companion to:** `docs/operations-module-plan.md` (the architecture decision — read that first for *why*)
and `docs/operations-costing-decoupling.md` (the 2026-11-17 decision that operations and costing run
independently — read that second for *what is not being built*).
**Date:** 2026-11-17

This document answers *how*: the work breakdown, the exact tables and columns, the endpoints, the
validation rules, the frontend surfaces, the migrations, the tests and the acceptance criteria.

---

## 0. Ground rules this plan is bound by

Everything below is shaped by conventions the repository already enforces. Any implementation that
breaks one of these will be rejected in review, so they are stated up front rather than discovered
mid-build.

| Rule | Source | Consequence for this module |
| --- | --- | --- |
| Column-wise storage, never JSON | `AGENTS.md`, convention 4 | The activity log is one row per time block with typed columns. No `payload`, no `details` blob. |
| `organization_id` on every table, filtered on every query | `models/*`, 79 filters in `services/daily_cost.py` alone | Every ops table carries it; every read filters it; every write validates the parent belongs to the caller's tenant. |
| Soft delete first, purge only from Deleted Entries | convention 14 | `is_deleted` + `deleted_at` on every business table, restore/purge endpoints, audit on all three. |
| Audit every action in the same transaction | `services/audit.py`, convention 1 | `audit.record(...)` beside every mutation; caller commits. |
| RBAC via `require("module:action")` | `api/deps.py:70+` | New capability namespaces; no hard-coded role checks. |
| Explicit Alembic revisions, never `create_all` at runtime | `.agent/memory/project.md:336`, current head `d6a2b8c3e901` | One additive revision per phase, with upgrade **and** downgrade, verified by `alembic check`. |
| Pagination 20/50/100; quick + advanced + date-range filters | conventions 5, 6 | Every register uses shared `DataTable`. |
| Import xlsx/csv with preview; export xlsx/csv/PDF | convention 7 | Import + export on every register; preview before write. |
| Module dashboard per module | convention 8 | `/operations` overview with KPIs. |
| Unsaved-changes protection via shared primitives | convention 15 | `useUnsavedChangesGuard` on the DDR editor, `FormDialog` on all dialogs. |
| Cancel-only dialogs, no backdrop/Escape close | convention 12 | Reuse `FormDialog`/`PanelDialog`; never a raw MUI `Dialog`. |
| Depth in metres internally, unit-aware entry | `core/units.py` | `depth_to_meters()`, `normalize_depth_unit()`; store both entered and normalised. |
| Timestamps UTC-aware, comparisons via `as_utc` | `core/time.py` | Report windows are stored UTC but *interpreted* in the workspace's operating timezone (see D4). |
| Ten/fewer decimals via shared precision aliases | `core/precision.py` | `Decimal10` for metric values; `Integer` minutes for durations. |
| Spreadsheet formula injection guarded | `core/spreadsheets.py` | All exports pass through `safe_csv_cell`. |

One rule that needs explicit handling because it does **not** exist yet: **there is no scheduling or
job infrastructure.** `services/backup.py:1345` runs a daemon `threading.Thread` loop for backup
schedules only. Any "close the day at midnight" or "flag missing DDRs" feature in this module must
either reuse that pattern or be a request-time computation. **Plan: request-time computation only.**
No new scheduler in Phase 1-2; nightly notifications reuse the backup scheduler's loop only if a
phase explicitly needs it (it does not, in this plan).

---

## 1. Work breakdown at a glance

| Phase | Theme | Deliverable | Est. (1 senior full-stack) | Depends on |
| --- | --- | --- | --- | --- |
| **0** | Decisions & spec | Signed taxonomy, mapping table, spec doc, seeded code list | 1-2 weeks (mostly client time) | — |
| **1** | The time spine | NPT codes master data, DDR/DCR register, activity log, validations, submit/approve, dashboard, print, import/export | 7-9 weeks | Phase 0 |
| **3** | Registers | Rig moves & day types, bit/BHA, mud checks, surveys, pressure tests, POB, HSE | 8-10 weeks (parallelisable per register, ~1.5-2 wk each) | Phase 1 |
| **4a** | Ops-only MIS | Flat-time analysis, NPT hours by cause/party/rig, ROP benchmarks, planned-vs-actual days, rig performance | 3-4 weeks | Phase 1 (and ideally 3) |
| ~~2~~ | ~~The join~~ | ~~Time log authoritative; cost lines link to logs; NPT cost/duration from time~~ | **Deferred to Phase 5** | — |
| **5** | Correlation | Auto-extraction of Planned/UPA/NPT into costing; cost-of-NPT; cross-referenced prints | Unscheduled | Ops accepted in use |

> **Scope change 2026-11-17.** Operations and costing ship **independently, with no data flow between
> them**. The original Phase 2 (the join) is deferred to Phase 5 and appears below only as a record of
> what was deferred and why. See `docs/operations-costing-decoupling.md` for the decision, the
> three-layer model that defines "independent", and the C1-C7 compatibility contract that Phase 1 must
> honour so Phase 5 stays cheap. **Nothing below needs building now.**

Phase 1 is the only hard sequence. Phase 3 registers are independent of each other and can be built in
any order once Phase 1 lands. Phase 4a needs Phase 1 data only. Phase 5 is triggered by operational
acceptance, not by a date.

---

## 2. Phase 0 — decisions that shape the schema

Nothing is coded until these are answered, because each one changes a column, a constraint or a
uniqueness rule. Record the answers in `MODEL REPORTS/` as a signed spec and mirror them into
`.agent/memory/project.md` (the durable-decisions file).

### 2.1 Decision sheet to circulate

| ID | Question | Options | Recommended | Schema impact |
| --- | --- | --- | --- | --- |
| D1 | NPT taxonomy | Contract/IADC-style list vs custom | Adopt the contract list, extend with local codes | `ops_npt_codes.category` enum |
| D2 | Is `is_productive` derived or typed? | Derive from `ops_operation_codes.is_productive` vs per-row entry | **Derive** from the operation code, with a per-row override + reason column | Adds `productivity_source`, `productivity_override_reason` |
| ~~D3~~ | ~~Which module owns time?~~ **Settled 2026-11-17 — deferred.** The modules run independently; the DDR owns *operations* time from day one, costing keeps its own derivation until Phase 5 | — | No schema impact now | None |
| D4 | Report period definition | Calendar midnight / tour-based (12h) / 06:00-06:00 | **Configurable per workspace, default 06:00-06:00** (industry norm for offshore day boundaries) | `ops_settings.day_boundary_hour`, `tour_pattern` |
| ~~D5~~ | ~~DDR for an un-AFE'd well?~~ **Resolved by the decoupling** — operations no longer references AFEs, so there is nothing to block on | — | Yes, by construction | `afe_id` **removed** from `ops_daily_reports` |
| D6 | Approval chain & amendment | 1-step vs 2-step; amend-in-place vs versioned | 2-step (Supervisor submits → Company man approves), **versioned amendment** (`supersedes_id`), like PO/SO revisions | Status + supersedes columns |
| D7 | NPT responsible party | Vendor FK vs free text vs both | **Both**, reusing the existing pattern: `vendor_id` + `responsible_party` + `responsible_party_source` | Mirror `well_sub_activities` columns |
| D8 | Retention & legal hold | Ops records vs cost records | Ops retained longer (typically 7-10 yrs); implement via existing retention registry | `services/retention.py` entries |

### 2.2 Specifications to write before coding

1. **Time taxonomy sheet** — the full operation code list (Drilling, Tripping, Casing, Cementing,
   Logging, Testing, Completion, Workover, Fishing, Milling, …) with, per code: default
   `classification` (Planned/UPA/NPT), default `is_productive`, whether it needs an NPT code,
   whether it counts as "on bottom" for ROP purposes.
2. **NPT code list** — codes, names, categories, default responsible party, chargeable flag.
3. **Productive/non-productive mapping table** — the five valid combinations from the architecture
   doc §7.2, plus the one forbidden (NPT + productive).
4. **DDR/DCR field sheet** — every field the paper report carries today, marked mandatory/optional,
   with the print position, so the printed output matches what crews already sign.
5. **Tour/handover rules** — who writes which report, what carries forward, how the forward plan
   and handover notes flow.

Deliverable: `MODEL REPORTS/Well Operations Spec v1.0.md` (+ the code lists as CSV for seeding).

---

## 3. Phase 1 — the time spine

This is the phase that must be right. Everything else reads from it.

### 3.1 New tables (7)

New model file: `backend/app/models/operations.py`. Tables carry `ops_` prefix so the Database
Browser's `module_group()` can map them with a single prefix entry.

#### `ops_operation_codes` — the operation taxonomy (new master data)

```
id                    String(36) PK
organization_id       FK organizations CASCADE, indexed
operation_code        String(50)   -- unique per workspace, upper-cased on write
operation_name        String(150)
category              String(50)   -- drilling|tripping|casing|cementing|logging|testing|
                                  -- completion|workover|fishing|milling|support|other
default_classification String(10)  -- Planned|UPA|NPT
is_productive_default  Boolean
is_on_bottom          Boolean      -- feeds ROP / rotating-hours metrics
requires_npt_code     Boolean
phase_applicable      String(20)   -- drilling|completion|both
description           String(500)
is_deleted, deleted_at, created_at, updated_at
UNIQUE (organization_id, operation_code)
```

#### `ops_npt_codes` — the NPT reason taxonomy (**retired 2026-11-19**; downtime work now lives in `ops_operations`)

```
id, organization_id
npt_code              String(50)   -- unique per workspace
npt_name              String(150)
category              String(50)   -- equipment_failure|hole_problem|well_control|weather|
                                  -- third_party|logistics|personnel|waiting_on_orders|
                                  -- surface_equipment|subsurface|survey|testing|other
subcategory           String(80)
default_responsible_party String(200)
is_chargeable         Boolean      -- can the day be re-billed?
is_company_caused     Boolean
is_contractor_caused  Boolean
description           String(500)
is_deleted, deleted_at, created_at, updated_at
UNIQUE (organization_id, npt_code)
```

Both are modelled on `master_data.py`'s `MasterDataRecord` abstract base and reuse the same
soft-delete lifecycle and unique-code convention. **They are separate registers, not rows in
`activities`**, because `activities` is referenced by AFE lines and daily cost lines and must not
change shape.

#### `ops_settings` — one row per workspace (mirrors `backup_settings`)

```
id, organization_id (UNIQUE)
day_boundary_hour     Integer default 6      -- 0-23, local operating hour that starts a report day
operating_timezone    String(64)             -- IANA name, e.g. Africa/Lagos
tour_pattern          String(20)             -- single_24h | day_night_12h
require_npt_code      Boolean default true
require_npt_party     Boolean default true
allow_ddr_without_afe Boolean default true
max_daily_hours       Numeric(28,10) default 24
created_at, updated_at, updated_by
```

#### `ops_daily_reports` — the DDR / DCR header

```
id, organization_id
report_no             String(100)  -- server-generated, unique per org (see 3.4)
report_code           String(120)  -- human display code, e.g. WOC-01-DDR-0042
scope                 String(20)   -- drilling|completion   CHECK
report_date           Date         -- the operating day this report belongs to
day_number            Integer      -- 1-based from spud, computed and stored for reporting
tour                  String(10)   -- day|night|full   (CHECK)
period_start_at       DateTime(timezone=True)
period_end_at         DateTime(timezone=True)
period_minutes        Integer      -- derived, stored for validation speed
rig_id                FK rigs RESTRICT, indexed
rig_code_snapshot, rig_name_snapshot
well_id               FK wells RESTRICT, indexed
well_code_snapshot, well_name_snapshot
-- NO afe_id: operations does not reference costing (decoupling decision, 2026-11-17).
-- An AFE is layered on in Phase 5 if it proves useful; nothing else in this table changes.
hole_section_id       FK hole_sections RESTRICT NULL, indexed
phase_id              FK phases RESTRICT NULL, indexed
depth_start           Numeric(28,10) NULL
depth_end             Numeric(28,10) NULL
depth_unit            String(5) default 'm'        -- entered unit; metres also stored
depth_start_m, depth_end_m Numeric(28,10) NULL     -- normalised via depth_to_meters()
operation_summary     Text
forward_plan          Text
hse_summary           Text
handover_notes        Text
status                String(20) default 'draft'   -- draft|submitted|approved|rejected
submitted_at, submitted_by, approved_at, approved_by
rejection_reason      String(500) default ''
supersedes_id         FK ops_daily_reports SET NULL NULL
superseded_by_id      FK ops_daily_reports SET NULL NULL
is_current            Boolean default true
is_deleted, deleted_at, created_at, updated_at, created_by, updated_by

UNIQUE (organization_id, well_id, scope, report_date, tour)
CHECK  period_end_at > period_start_at
CHECK  status IN ('draft','submitted','approved','rejected')
CHECK  scope IN ('drilling','completion')
CHECK  depth_end_m IS NULL OR depth_start_m IS NULL OR depth_end_m >= depth_start_m
INDEX  (organization_id, report_date)
INDEX  (organization_id, well_id, report_date)
INDEX  (organization_id, status)
INDEX  (organization_id, is_deleted)
```

#### `ops_activity_logs` — the time record

```
id, organization_id
report_id             FK ops_daily_reports CASCADE, indexed
sequence_no           Integer
started_at            DateTime(timezone=True)
ended_at              DateTime(timezone=True) NULL     -- NULL = ongoing at period close
duration_minutes      Integer                          -- stored, validated against timestamps
activity_id           FK activities RESTRICT, indexed  -- existing Master Data Activity
activity_code_snapshot, activity_name_snapshot
operation_code_id     FK ops_operation_codes RESTRICT, indexed
operation_code_snapshot, operation_name_snapshot
classification        String(10)  -- Planned|UPA|NPT          CHECK
is_productive         Boolean                                  -- derived (D2) or overridden
productivity_source   String(10)  -- derived|override           CHECK
productivity_override_reason String(500) default ''
npt_code_id           FK ops_npt_codes RESTRICT NULL, indexed
npt_code_snapshot, npt_name_snapshot
phase_id              FK phases RESTRICT NULL, indexed
hole_section_id       FK hole_sections RESTRICT NULL, indexed
depth_from_m, depth_to_m Numeric(28,10) NULL
depth_unit            String(5) default 'm'
responsible_party      String(200) default ''
vendor_id              FK vendors SET NULL NULL, indexed
vendor_code_snapshot   String(50) default ''
responsible_party_source String(20) default 'manual'  -- vendor|manual|import  CHECK
reason                 String(500) default ''          -- mandatory for NPT/UPA
remarks                String(1000) default ''
is_deleted, deleted_at, created_at, updated_at, created_by, updated_by

CHECK  duration_minutes > 0
CHECK  ended_at IS NULL OR ended_at > started_at
CHECK  classification IN ('Planned','UPA','NPT')
CHECK  NOT (classification = 'NPT' AND is_productive)        -- the forbidden combination
CHECK  productivity_source IN ('derived','override')
CHECK  classification <> 'NPT' OR npt_code_id IS NOT NULL     -- when settings.require_npt_code
CHECK  classification = 'Planned' OR LENGTH(TRIM(reason)) > 0  -- UPA/NPT must explain itself
INDEX  (organization_id, report_id, sequence_no)
INDEX  (organization_id, started_at)
INDEX  (organization_id, classification)
INDEX  (organization_id, npt_code_id)
INDEX  (organization_id, is_deleted)
```

**Why `duration_minutes` is stored as well as the timestamps:** the sum-of-durations validation and
every MIS aggregate need it, and computing `EXTRACT(EPOCH FROM ended_at - started_at)` per row in
every report would be wasteful and would behave differently on SQLite (used by the test suite).
It is always recomputed from the timestamps on write, never trusted from input.

**Non-overlap enforcement — important detail.** PostgreSQL could use
`EXCLUDE USING gist (report_id WITH =, tstzrange(started_at, ended_at) WITH &&)` but that needs the
`btree_gist` extension and SQLite (which the test suite runs on) does not support exclusion
constraints at all. Plan:

1. **Service-layer check** (authoritative, portable): before commit, sort the report's blocks and
   reject any overlap with a specific `409` naming both conflicting rows. Same pattern as the
   existing "24 hours" guard in `services/daily_cost.py:2157-2180`.
2. **PostgreSQL-only exclusion constraint** added behind
   `if op.get_bind().dialect.name == "postgresql":` in the migration, as defence in depth for
   non-API writers. Document it as production-only in the model docstring so nobody wonders why
   the model does not declare it.

#### `ops_report_revisions` — amendment history

Mirrors the PO/SO revision-chain design (`vendor_master.py`): `report_id`, `revision_number`,
`changed_by`, `changed_at`, `summary`, `reason`. Written whenever a submitted/approved report is
amended. One row per amendment, never a JSON diff.

#### `ops_unaccounted_time` — optional but recommended

Rather than forcing every minute to be logged, allow gaps and *surface* them:
`report_id`, `from_at`, `to_at`, `minutes`, `reason`. Populated automatically at submit when
`sum(duration_minutes) < period_minutes`. This is the difference between a system crews fight and one
they use. **Decision to confirm in Phase 0**; the plan assumes yes.

### 3.2 Service layer

`backend/app/services/operations.py` — the only place business rules live. Functions:

| Function | Responsibility |
| --- | --- |
| `resolve_period(db, org, report_date, scope, tour)` | Turn a report date + tour into `period_start_at`/`period_end_at` using `ops_settings` (D4). Single definition, used by create and by every validation. |
| `compute_day_number(db, well, scope, report_date)` | Days since the scope's spud (`Well.drilling_spud_at` / `completion_spud_at`). Reuses the existing milestone, not a new one. |
| `next_report_no(db, org, well, scope)` | Sequential per well/scope, collision-safe under `_WRITE_LOCK`. |
| `validate_time_blocks(db, report, blocks)` | No overlaps, `duration = period`, ≤ `max_daily_hours`, NPT needs code + party + reason, depth monotonic within the day. Raises `409`/`422` with actionable messages naming the row. |
| `derive_productivity(operation_code, override, reason)` | D2 rule in one place. |
| `save_report(db, org, report_id, payload, user, request)` | Replace blocks under `_WRITE_LOCK`, recompute stored derivations, audit one row per changed block group. |
| `submit_report` / `approve_report` / `reject_report` / `amend_report` | Status machine, each its own permission. Mirrors `submit_entry`/`reopen_entry` in `services/daily_cost.py:3721-3770`. |
| `copy_previous_day(db, report)` | Pre-fill a new report from the last one on the same well/scope — the single biggest time-saver for crews. Mirrors "Copy previous day" in the daily cost sheet. |
| `operations_dashboard(db, org, filters)` | KPI aggregate (see 3.6). |
| `time_summary(db, org, well_id, from, to)` | Productive %, NPT %, hours by classification, NPT by code and party. Fully self-contained: reads operations rows only, no costing data. |
| `import_reports(db, org, payload)` / line import | Full validation before any write, row-level errors returned. |
| `delete_reports` / `restore_reports` / `purge_reports` | Soft-delete lifecycle. Nothing outside the module references a block, so purge is blocked only by an approved report's revision history. |

**Concurrency:** reuse the `_WRITE_LOCK` pattern (`threading.Lock` around the read-modify-write) plus
`SELECT ... FOR UPDATE` on the report row, exactly as `save_daily_cost` does. Two supervisors
editing the same report must not interleave.

### 3.3 API surface

`backend/app/api/operations.py`, mounted in `main.py` as
`app.include_router(operations.router, prefix="/api/v1")` next to line 185.

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/operations/reference` | `ops-report:read` — wells, rigs, sections, phases, activities, operation/npt codes, settings (one call, like `ndt/inspection/reference`) |
| GET | `/operations/dashboard` | `ops-report:read` |
| GET | `/operations/reports` | `ops-report:read` — filters: `well_id`, `rig_id`, `scope`, `status`, `from`, `to`, `tour` |
| GET | `/operations/reports/deleted` | `ops-report:read` |
| GET | `/operations/reports/{id}` | `ops-report:read` |
| POST | `/operations/reports` | `ops-report:create` |
| PUT | `/operations/reports/{id}` | `ops-report:update` (draft only) |
| POST | `/operations/reports/{id}/copy-previous` | `ops-report:create` |
| POST | `/operations/reports/{id}/submit` | `ops-report:submit` |
| POST | `/operations/reports/{id}/approve` | `ops-report:approve` |
| POST | `/operations/reports/{id}/reject` | `ops-report:approve` |
| POST | `/operations/reports/{id}/amend` | `ops-report:amend` |
| POST | `/operations/reports/bulk-delete` | `ops-report:delete` |
| POST | `/operations/reports/bulk-restore` | `ops-report:restore` |
| POST | `/operations/reports/bulk-permanent-delete` | `ops-report:permanent-delete` |
| POST | `/operations/reports/import` | `ops-report:import` |
| POST | `/operations/reports/export-audit` | `ops-report:export` |
| GET | `/operations/time-summary` | `ops-report:read` — the dashboard/report aggregate |
| GET | `/operations/npt-codes`, `/operations/operation-codes` | `ops-master:read` |
| POST/PATCH/DELETE | `/operations/npt-codes[/{id}]` etc. | `ops-master:create/update/delete` |
| GET/PUT | `/operations/settings` | read: `ops-report:read`; write: `ops-master:update` |

Every route is `Depends(require(...))`; every handler passes `user.organization_id` down. The
service — not the router — validates that the well, AFE, section, phase, activity, NPT code and
vendor all belong to that workspace and are not deleted. That is the pattern in
`services/daily_cost.py` and it is what keeps tenant isolation honest.

### 3.4 Report numbering

Follow `next_number()` in `services/backup.py:189`: scan `column LIKE 'stem%'`, take the max numeric
suffix, add one, zero-pad. Format
`{well_code}-{SCOPE_ABBR}-{report_date:%Y%m}-{seq:04d}`, e.g. `WOC-01-DDR-202611-0042`. Generated
server-side only; unique constraint is the backstop. Under `_WRITE_LOCK` to survive concurrent
creation.

### 3.5 Validation rules (all in `validate_time_blocks`, all with actionable messages)

1. **No overlaps.** "Block 3 (06:00-09:30) overlaps block 4 (09:00-11:00). Adjust one of them."
2. **Blocks fall inside the period.** A block may not start before `period_start_at` or end after
   `period_end_at` (+ a documented grace of, say, 0 — decided in Phase 0).
3. **Sum of durations.** Either equals `period_minutes`, or the difference is recorded in
   `ops_unaccounted_time` and surfaced as a warning on the report and dashboard — never silently
   accepted, never a hard block (a mid-report print is legitimate).
4. **NPT completeness.** `classification='NPT'` requires `npt_code_id`, a non-blank `reason` (≥ 10
   chars, matching the other-expenses remarks convention) and, if `settings.require_npt_party`, a
   responsible party. Enforced in Pydantic **and** as a `CHECK` constraint, because the API is not
   the only writer.
5. **Productivity.** `is_productive` may only be `true` for `Planned` or `UPA`. Derivation from the
   operation code is the default; an override needs a reason.
6. **Depth.** Within one report, depth must not run backwards for the current hole section
   (`depth_to >= depth_from`); compared in metres after `depth_to_meters()`.
7. **Scope.** A `completion` report may only reference the well's Completion sections/phases — reuse
   `Well.sections_for_scope(scope)` (`models/rig_well.py:262`), the helper added for exactly this
   bug class.
8. **Status.** Editing is draft-only (`409` otherwise), matching
   `services/daily_cost.py:6061`. Amending an approved report creates a new revision and requires
   `ops-report:amend`.
9. **Locked plan.** If the well's scope plan is `completed` (final review / completed), new reports
   are refused with the same wording style as `_require_scope_not_signed_off`.

### 3.6 Dashboard (`/operations`)

Convention 8 requires one. KPIs, each `StatCard`, each with a stated basis in `hint`:

- Wells with a report today / expected (the coverage gap — the number a Drilling Manager actually wants)
- Total reportable hours, productive hours, NPT hours, UPA hours (sum of `duration_minutes`)
- Productive % and NPT % — with the **basis printed** ("of logged time", "of period time")
- NPT hours by category (chart) and by responsible party (table, drill-through to reports)
- Unaccounted time total, flagged as a data-quality KPI
- Recent activity (last reports submitted/approved)

Charts reuse `ChartPanel` + `InteractiveChart`; the drill-through pattern is the one already used by
`BusinessDashboard`'s `DrillThroughPanel`.

### 3.7 Frontend

| Route | Page | Notes |
| --- | --- | --- |
| `/operations` | `pages/OperationsOverview.tsx` | Dashboard. Nav: new top-level **Well Operations** group in `Layout.tsx` after *Daily Cost Management*. |
| `/operations/reports` | `pages/OperationsReports.tsx` | List-only register, server-side filters, `DataTable`, bulk actions, import/export, print selection. |
| `/operations/reports/:id` | `pages/OperationsReport.tsx` | The DDR/DCR editor — full-page, `useUnsavedChangesGuard`. |
| `/operations/reports/deleted` | tab/page | Deleted Entries, restore/purge. |
| `/operations/npt-codes` | inside Master Data or its own register | Follow the `Services` register layout. |
| `/operations/settings` | `pages/OperationsSettings.tsx` | Day boundary, timezone, tour pattern, enforcement toggles. |

**The editor page** is the piece with real UX weight. Layout:

1. **Header band** — well, rig, scope, report date, day number, tour, period (read-only, derived), status chip, report code.
2. **Time block grid** (AG Grid) — one row per activity: start, end, duration, operation code, activity, classification chip (Planned/UPA/NPT colour-coded by theme token), NPT code, responsible party, depth from/to, reason, remarks.
   - Row actions: edit (opens `FormDialog`), delete (confirm), **insert above/below**, **split at time**.
   - A persistent **time ruler** above the grid showing the 24h period with logged/unaccounted gaps — the one visual that makes a missing hour obvious.
   - Footer: logged / unaccounted / over-24 totals, live as rows change (mirrors the daily cost sheet's live preview).
3. **Narrative panels** — operation summary, forward plan, HSE summary, handover notes (`SectionCard`, plain textareas).
4. **Depth panel** — start/end depth with unit picker, metres shown underneath.
5. **Action bar** — Save draft, Submit, Print, Copy previous day, Import lines. Permission-gated; submit disabled until validations pass, with the blocking reason inline.

Dialogs (`components/operations/`): `TimeBlockDialog.tsx`, `SubmitReportDialog.tsx`,
`AmendReportDialog.tsx`, `RejectReportDialog.tsx`, `NptCodeFormDialog.tsx`,
`OperationCodeFormDialog.tsx`. All built on shared `FormDialog` — Cancel-only, unsaved-guard,
inline field errors, persistent error pop-up on API failure.

Types in `frontend/src/lib/operations.ts` (the module's own lib file, matching
`lib/dailyCost.ts`/`lib/ndt*.ts`); shared `api()` for calls.

### 3.8 Print

`components/operations/OperationsReportPrintSheet.tsx` + `@media print` rules in `styles.css`,
scoped under `.ops-report-print-sheet` exactly as `.afe-cost-print-sheet` is.

- **Page 1: the DDR/DCR cover** in the classic 24-hour table form: header block (well, rig, report
  no, date, day number, tour, depth start/end), the time breakdown table, then the operation
  summary, forward plan, HSE summary, handover, and the signature block (supervisor / company man /
  toolpusher).
- **Page 2+: supporting panels** — productive/non-productive pie, NPT by code with responsible
  party and **hours** (cost belongs to Phase 5), planned-vs-actual days and depth per section, and
  the detail log.
- A4 portrait or landscape decided in Phase 0 against the paper form crews use.
- Every printed decimal to two places; stored ten-decimal precision unchanged (the repo's rule).
- Batch print: "print selected reports" produces one PDF of the cover pages, ordered well then
  date — the pattern already implemented for daily sheets.

### 3.9 RBAC, migration and seed

**Capabilities** appended to `CAPABILITIES` in `services/provisioning.py`:

```python
"ops-report": ("read", "create", "update", "delete", "restore", "permanent-delete",
               "import", "export", "submit", "approve", "amend"),
"ops-master": ("read", "create", "update", "delete"),
"ops-hse":    ("read", "create", "update"),          # Phase 3
"ops-timelog":("read", "create", "update", "delete"),# reserved, see note
```

Note on `ops-timelog`: the time blocks live *inside* a report and are governed by `ops-report`. Do
**not** create a separate timelog permission unless the Phase 0 decision says blocks are edited
independently of the report. A redundant capability is a grant that looks meaningful and isn't.

**Migration** `backend/alembic/versions/<new>_add_well_operations.py`, `down_revision = "d6a2b8c3e901"`:

1. `create_table` × 7 (+ indexes, in the same order the existing revisions use).
2. `_backfill_capabilities()` — copied structurally from `a9d4e2f7c138_add_afe_management.py:33`:
   for every organisation, insert the new `permissions` rows and grant them to the owner role.
   Idempotent (skip keys that already exist), so a re-run does not duplicate.
3. Seed the two code registers for existing workspaces from the Phase 0 CSVs? **No** — seeding
   business data in a migration is the thing this repo deliberately avoids (`project.md:337`,
   never write to an existing tenant's business data). Instead: ship an **import template** and a
   "Load starter code list" button in the register that creates rows through the normal audited API.
4. `downgrade()` drops tables in reverse FK order and deletes only the permissions it created,
   with the `role_permissions` rows first.
5. PostgreSQL-only branch adds the btree_gist exclusion constraint; guarded by dialect check.

Verify with: `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head`, then
`alembic check` on a **fresh** SQLite DB. `.agent/memory/project.md` warns explicitly that
`Base.metadata.create_all` (used by the tests) will **not** catch model/migration drift — the
`alembic check` run is the real gate.

### 3.10 Cross-cutting integration (do not defer these)

| Area | Work | File |
| --- | --- | --- |
| Database Browser | Add `("ops_", "Well Operations")` to `MODULE_GROUPS` so all ops tables appear grouped. | `services/database_browser.py:51` |
| Report Builder | New tables become selectable automatically once browsable; verify joins to `wells`/`rigs` resolve through `_scope_for`. Add human labels. | `services/report_catalog.py` |
| Retention / purge | Add ops entries to the reference-label map so purging a well or rig names what still holds it instead of returning an opaque 500. | `services/dependencies.py:20`, `services/retention.py` |
| Backup | Nothing to add — the backup plan reflects tables automatically. **Confirm** a workspace archive round-trips an ops report (test it, do not assume). | `services/backup.py` |
| Assistant | Add a Well Operations paragraph to the grounding text and a few `AssistantFact`s (wells without a report today, NPT hours this week). Permission-gated with `ops-report:read`. | `services/ai_context.py:51` |
| Audit | `entity_type` values: `ops_report`, `ops_activity_log`, `ops_npt_code`, `ops_operation_code`. Actions reuse `create|update|delete|restore|submit|approve|reject|amend|import|export`. | `services/audit.py` |
| Import/export | Every register: xlsx/csv import with preview and row errors; xlsx/csv/PDF export through `safe_csv_cell`. Export audits recorded. | shared frontend + `core/spreadsheets.py` |
| Cost Intelligence | No rules yet (Phase 4), but register the module so the panel can grow. | `services/cost_intelligence.py` |

### 3.11 Tests — `backend/tests/test_operations.py`

Follow the shape of `tests/test_daily_cost.py` and `test_rig_well.py`. Required coverage:

1. **Tenant isolation** — a report/block/code from workspace A is invisible and unwritable from B (every endpoint and every bulk action).
2. **Lifecycle** — draft → submitted → approved; reject; amend creates a revision; rollback paths; `409` on editing a non-draft.
3. **Time validation** — overlap rejected with both rows named; block outside period rejected; sum < period records unaccounted; sum > period rejected; `max_daily_hours` respected.
4. **NPT rules** — NPT without code rejected; NPT without reason rejected; NPT + productive rejected by the `CHECK`; UPA with productive allowed.
5. **Derivation** — `is_productive` follows the operation code; override without reason rejected.
6. **Period resolution** — day boundary 06:00 gives the right UTC window across a DST-free and a DST-observing timezone; a report date at 03:00 local belongs to the previous operating day.
7. **Day number** — computed from the scope's spud; completion and drilling counts are independent.
8. **Depth** — ft entry stored as metres correctly; backwards depth rejected; scope-appropriate section required.
9. **Soft delete → restore → purge**, with purge blocked only by the report's own revision history.
9a. **Decoupling guard** — a test that walks the `ops_*` foreign keys and asserts none targets an
   `afe*` or `daily_cost_*` table, and the reverse. This is the assertion that keeps the
   2026-11-17 independence decision true; see `docs/operations-costing-decoupling.md` §3.
10. **RBAC** — one test per new capability key, asserting `403` and the message naming the key.
11. **Audit** — every mutation writes one row with the right `action`/`entity_type`.
12. **Import** — valid file, row-level errors, formula-injection cell, duplicate report rejected.
13. **Compensating test for the pre-existing flake**: `test_database_browser.py::test_child_tables_are_scoped_through_their_foreign_keys` is order-dependent (documented in `project.md:371`). The new `ops_` prefixes change reflection ordering — **run the full suite in a fresh process** and, if it now fails, fix the *ordering determinism* in `_scope_for`, not the assertion.

Frontend gates: `make build`, `make ui-check`, and a new `make operations-check` in the style of
`.agent/tools/daily-cost-check.jsx` asserting: the time ruler shows a gap, NPT chip colour in both
themes, the submit button disables with the blocking reason, the unsaved guard fires on navigation,
and the print sheet renders every block with repeated table headers.

### 3.12 Definition of done for Phase 1

- A supervisor can file a complete DDR for a live well and it replaces the paper form, with the
  printed output signed by the same three roles.
- The 24 hours of the operating period reconcile: logged + unaccounted = period, always.
- Every NPT minute carries a cause and a responsible party.
- Dashboard shows coverage, productive % and NPT % with stated bases.
- Import/export/print/audit/RBAC/soft-delete all present and tested.
- The decoupling holds: the FK-assertion test passes, no `ops_*` table references a costing table.
- Compatibility contract C1-C7 honoured (IDs kept beside snapshots, exact period instants stored,
  the same three classification literals, minutes not decimal hours, shared depth normalisation).
- Operations is usable with the costing modules untouched and unchanged — verified by running the
  existing daily-cost and AFE test suites against the new migration.
- `alembic check` clean on a fresh DB; full suite green in a fresh process.
- `.agent/memory/project.md` updated with the durable decisions; `make graph` regenerated.

---

## 4. Phase 5 (formerly Phase 2) — the join — DEFERRED, DO NOT BUILD

> **This entire section is deferred and unscheduled.** It is kept because it is the design record for
> what correlation will involve, and because it explains why nothing in Phase 1 needs to change to
> accommodate it later. Read it as an appendix, not as work. The decision and its trigger conditions
> are in `docs/operations-costing-decoupling.md`.
>
> The two things that make deferral safe: every column below is **nullable and additive**, and the
> compatibility contract C1-C7 is already satisfied by the Phase 1 design. Deferring costs nothing.

This phase changes existing code, so it needs the most care. It is also the phase that makes the
whole programme worth doing.

### 4.1 Schema changes (additive, reversible)

**`daily_cost_service_lines`** (and, where a charge is genuinely tied to a block, the other three line
tables) gain:

```
ops_activity_log_id   FK ops_activity_logs SET NULL NULL, indexed
```

`SET NULL`, not `CASCADE`: purging an operation must never silently delete a booked cost. The link
is optional — legacy sheets have none, and a charge may legitimately not correspond to one block.

**`wells`** — no change needed. Spud timestamps, sections, phases and planned days already exist.

**New** `ops_cost_links` is **not** needed in Phase 2. One charge belongs to at most one block. If a
charge must be split across blocks, that is a Phase 4 refinement with its own table and its own
decision.

### 4.2 Behaviour changes

| Change | From | To |
| --- | --- | --- |
| NPT/UPA **duration** | `services/operational_time.py` — dedupe explicit `hours` cost allocations, ÷24 | Read `ops_activity_logs.duration_minutes` for reports that have one; fall back to the existing rule **only** for legacy sheets with no linked log. |
| NPT/UPA **cost** | Sum of cost lines whose `classification` matches | Sum of cost lines **linked to NPT blocks**; unlinked NPT-classified lines reported separately as "unattributed NPT cost" rather than silently counted. |
| Classification | Regex on activity name (`classify_activity`, `services/daily_cost.py:265`) | Read from the linked block. Regex remains as the fallback for manual lines, clearly labelled in the UI as "inferred". |
| 24-hour rule | Cost sheet's dedup rule (`services/daily_cost.py:2157`) | The DDR's completeness rule is authoritative. The cost rule stays as a compatibility guard for sheets that have no DDR, but **the API tells the user which rule applied** — never two contradictory errors for one day. |
| Printed daily cost "Time Position" | Hours derived from cost quantities | Reads the linked DDR; prints the DDR report number beside the figures so the two documents cross-reference. |
| Planned vs actual days | Planned from `well_phases.days`; actual from spud→completion | Same, plus **actual days per section/phase** computed from the time log — the flat-time analysis crews actually ask for. |

### 4.3 Migration and dual-run

1. Add the nullable column. **No backfill** — there is nothing meaningful to guess.
2. Ship a **linking helper** in the daily cost sheet: rows with an activity/section/phase/date
   matching exactly one DDR block offer a one-click link, with a bulk "link all matching" action
   that requires `daily-cost:update` and reports what it could not resolve. This is a convenience,
   not a migration.
3. **Dual-run for one full reporting period**: both the old derivation and the new one are computed
   and the difference is surfaced in the report ("time basis: DDR" / "time basis: derived") so the
   client can UAT the change on real data before the old rule is demoted.
4. Only after sign-off: mark the cost-derived duration as legacy in the docs and the print, and
   update `docs/daily-cost-management.md` and the BRD's OD-02 entry from "open" to "decided".

### 4.4 Tests

- Link survives report amendment (revision creates new blocks — decide whether links follow; plan:
  amendment creates new block rows and the service **re-points** links, writing an audit row, because
  losing a cost-to-time link on amendment is data loss).
- Purging an operation does not delete the charge (`SET NULL` verified).
- Duration parity test: for a legacy sheet with no DDR, the number is byte-identical to today's.
- A sheet with a DDR uses DDR duration, and the printed figure matches the DDR print.
- NPT cost = linked lines only; unattributed NPT cost appears separately and the totals still reconcile.

---

## 5. Phase 3 — the operational registers

Each register is a self-contained slice (model → schema → service → api → page → tests → migration)
and follows the `ndt_inspection` module as the smallest complete template (46/172/53/139 lines —
model, service, api, schema). Estimate ~1.5-2 weeks each at this codebase's conventions.

| Register | Key tables | Notes |
| --- | --- | --- |
| **Rig moves & day types** | `ops_rig_moves`, `ops_day_type_log` | Day type (operating / standby / force majeure / repair / reduced rate) feeds day-rate billing and directly explains a cost variance. Approve step separate from entry. |
| **Bit & BHA records** | `ops_bit_records`, `ops_bha_components` | Bit, IADC dull grade, metres, rotating hours, ROP computed and stored. Feeds the existing drill-bits usage report rather than duplicating it. |
| **Mud checks** | `ops_mud_checks`, `ops_mud_check_readings` | Interval readings (density, funnel viscosity, filtrate, chlorides, solids…). Explicitly **not** the same thing as `mud_cost_entries` (which is material balance and cost); they must never be merged. |
| **Surveys** | `ops_surveys` | MD/INC/AZI/TVD/DLS, tool, run number. TVD is computed and stored. |
| **Pressure tests** | `ops_pressure_tests` | BOP, leak-off/FIT, casing, wellhead; pressure, duration, result, witness. Compliance-flavoured, so `ops-hse` permissions. |
| **POB & personnel** | `ops_personnel_onboard` | Rotation register, headcount, medivac events. Sensitive: needs its own read capability and a documented retention stance. |
| **HSE** | `ops_hse_observations`, `ops_incidents` | Observation and incident registers with corrective-action tracking reusing `workflow_tasks` (`models/security.py:125`) rather than inventing a task engine. |

Every one: soft delete, audit, import/export, 20/50/100 paging, quick + advanced + date filters,
module-grouped in the Database Browser, and reachable from the DDR editor as a linked panel where
that saves re-typing (e.g. today's bit run and mud check attach to the day).

---

## 6. Phase 4a — operations-only MIS (the financial half is deferred to Phase 5)

Everything here reads operations rows only. No costing data is joined, which is exactly why it can
be built immediately after Phase 1.

1. **Flat-time / time-distribution analysis** — hours by operation, by section, by phase; planned vs
   actual days per phase from `well_phases`; days-per-1000 m/ft benchmarks by hole section.
2. **NPT analysis in hours** — by cause, by responsible party, by well, by rig, trended; mean time
   between failures by equipment. *(The cost dimension — hours × day rate plus linked charges — is
   Phase 5. Until then the report shows hours and states plainly that no cost is attributed.)*
3. **Rig performance** — productive %, NPT %, MTBF, rig league table. Every percentage states its
   basis: "of logged time" versus "of period time" are different numbers and are never mixed.
4. **Data-quality panel** — reports filed versus expected, unaccounted time trend, NPT records missing
   a cause or a party. This is the panel that tells you whether the workflow is ready for Phase 5.
5. **Assistant grounding** — extend `ai_context.py` with ops facts (wells without a report today, NPT
   hours this week), permission-gated with `ops-report:read`, same "never assert a figure the caller
   cannot see" discipline. No cost figures.
6. **Report Builder** — publish a starter set of ops reports through the existing builder rather
   than hard-coding them, so the client can extend them without a release.

**Deferred to Phase 5:** cost of NPT; variance explained by flat time; cost per metre by section;
day-rate burn against operating day type; any Cost Intelligence rule that crosses into costing.

---

## 7. Sequencing, dependencies and risks

### 7.1 Critical path

```
Phase 0 decisions
    └─▶ Phase 1 (spine)  ──▶  Phase 4a (ops-only MIS)
              │                      │
              └─▶ Phase 3 registers ─┘
                                     │
                     (deferred, trigger-gated)
                                     ▼
                             Phase 5 (correlation)
```

Phase 1 is independently deployable and delivers a working operations module with no dependency on
costing at all. Phase 3 and 4a can proceed in parallel with a second engineer and touch only new
files. Phase 5 starts only when operations has been accepted in production use and someone asks for
the cost of NPT — the three signals are in `docs/operations-costing-decoupling.md` §9.

### 7.2 Risks specific to implementation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| **Double entry of hours during the interim** (the real cost of decoupling) | Crews type the day's hours twice: once in the DDR, once on the cost sheet | Make the DDR the one place time is typed from day one, even though costing does not consume it yet. Cost-hour entry is then transcribed from the DDR by a clerk. When Phase 5 arrives, costing *consumes* what was already being typed — a consumption change, not a data-entry project. |
| **Decoupling erodes silently** | A future change adds an `afe_id` "just for reporting" and the independence claim becomes fiction | The FK assertion test (3.11 §9a) plus contract C6; both are required gates, not advisory. |
| **Crews reject data entry** | Module becomes shelfware | Copy-previous-day, the time ruler showing only gaps, unaccounted time instead of hard blocks, import from the existing spreadsheet. |
| **Report period ambiguity (D4)** | Every day count is off by hours | Decide in Phase 0, store the timezone per workspace, test across a DST boundary and a 03:00-local case. |
| **Non-overlap constraint not portable** | Silent double-count in production if only the service checks | Service check is authoritative and always runs; PG exclusion constraint added as defence in depth. |
| **Exact time instants not stored** (contract C2) | Correlation later degrades to date matching and mismatches the operating day | Store `period_start_at`/`period_end_at` and block `started_at`/`ended_at` in Phase 1 regardless of whether anything reads them yet. Cheap now, impossible to reconstruct later. |
| **Reflection-order flake in the existing suite** | CI noise that hides real failures | Fix the ordering determinism in `_scope_for` if the new prefixes surface it; do not edit the assertion. |
| **Migration drift** | Production schema diverges from models | `alembic upgrade/downgrade/upgrade` + `alembic check` on a fresh DB is a required gate, not optional. |
| **Scope creep into a full drilling engineering suite** | Programme never ships | Phase 3 registers are optional; sequence them by what the client actually asks for twice. |
| **Correlation started too early** | Built on a workflow that is still changing, so it must be rebuilt | Phase 5 is trigger-gated, not date-gated. See §9 of the decoupling record before commissioning it. |

### 7.3 What "done" means overall

**Done for this programme (Phases 1, 3, 4a)** is when a Drilling Manager can open one page and answer,
for any well and any period, *with every figure traceable to a record*:

- How many days did this well take, against plan, per hole section?
- Where did the time go, and what was productive versus not?
- Which NPT causes hurt us most, and who owned them?
- Are our DDRs complete, and is unaccounted time falling?

**Done for Phase 5** adds the financial question: *what did that time cost, and does the operational
story agree with the financial one to the currency unit?*

The second question is the one only a single database can answer. That is why the architecture
recommendation stands even though the modules are, for now, deliberately unconnected: the join is
available to build whenever it is wanted, and it is a join rather than a data pipeline precisely
because the decision was one workspace and one database.
