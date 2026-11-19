# Well Operations: architecture decision and plan

**Status:** proposal only. No code, schema, migration or configuration has been changed. The NPT-code list
and the operations/activity/phase code families named below were superseded on 2026-11-19: Activities
live in Master Data with an Activity type (Planned / UPA / NPT), and the Code Library holds Operations,
Sub-Phases, Cause Codes, Responsible Agency labels and source marks. See
[docs/operations/daily-workflow.md](operations/daily-workflow.md).
**Date:** 2026-11-17
**Question asked:** should drilling/completion operations (DDR, DCR, rig operations and
activities, NPT/UPA, productive vs non-productive time) live in a *separate workspace* or in
*this* workspace as new modules behind RBAC — and should the data sit in one database or two?

---

## 1. Bottom line

| Question | Recommendation |
| --- | --- |
| Separate workspace, or new modules in this one? | **New modules in this workspace.** Do not create a second workspace. |
| Single database or separate database? | **Single database, single schema, same tenant.** |
| Can I extract data from one workspace to another? | **Not today** — and that is the strongest argument against splitting. |
| How do I get the separation I actually want? | **RBAC capability namespaces + module entitlements**, not a tenant boundary. |
| What is the one architectural change that matters most? | **Time becomes the primary record; cost derives from time** — inverting today's direction. |

The short version: a "workspace" in this codebase is not a folder — it is a **tenant**. It is
the authentication boundary, the data boundary, the RBAC boundary, the audit boundary and the
backup boundary. Using it to separate two halves of the *same* well's lifecycle would duplicate
one company's identity, one company's master data and one company's well, and would make the
single most valuable join in the product — *operations time to operations cost* — impossible.

---

## 2. What in your codebase drives this answer

This is not a generic opinion; these are the constraints already built into the repository.

| # | Fact | Where | Consequence for the decision |
| --- | --- | --- | --- |
| 1 | A `User` belongs to **exactly one** organisation (`users.organization_id`, unique on `(organization_id, email)`), and the access token carries one `org` claim that must match the user's row. | `backend/app/models/entities.py:36-57`, `backend/app/api/deps.py:44` | A second workspace means **every driller, supervisor and cost engineer needs a second login**. There is no membership table to switch between. |
| 2 | Permissions are **seeded tenant data** and the capability map is already `module:action` granular (`daily-cost` has 11 actions, `afe` has 12, `rig-well` has 10). | `backend/app/services/provisioning.py:19-100` | Granular separation is a **configuration exercise**, not a new tenancy model. This is precisely what RBAC is for. |
| 3 | Restore **refuses** an archive whose organisation differs from the target. | `backend/app/services/backup.py:706-708` | There is no supported path to move data between workspaces. "Extract from one workspace to another" would be a new feature you'd have to build and maintain. |
| 4 | Every one of ~134 tables is `organization_id`-scoped, and queries filter on it explicitly (79 occurrences in `services/daily_cost.py` alone). | `backend/app/models/*`, `services/*` | A new module inherits tenant isolation for free *inside* the workspace. A second workspace would need a **duplicate** rig/well/master-data set kept in sync by hand. |
| 5 | Cost lines already carry the operational keys: `activity_id`, `hole_section_id`, `phase_id`, `sub_activity_id`, `vendor_id`, `party_name`, `actual_depth`, plus `*_snapshot` copies. | `backend/app/models/daily_cost.py:458-520` | A DDR is the natural **parent** of a daily cost sheet — same well, same date, same rig, same activity. In one database this is an FK join. Across databases it is ETL. |
| 6 | Planned/UPA/NPT is **derived by regex** from the free-typed Master Data Activity code and name. | `backend/app/services/daily_cost.py:265-280` | Fragile for costing; unusable as the backbone of an operations MIS. Needs a real NPT taxonomy — a reason to build the module properly, not to split the tenant. |
| 7 | NPT/UPA **duration** is currently computed *from cost line hours* (explicit `hours` allocations, deduplicated, ÷24). | `backend/app/services/operational_time.py`, `services/daily_cost.py:2140-2190` | In a real operations module **time is the record and cost is the consequence**. This inversion is the highest-value change in the whole programme. |
| 8 | There is **no** time log, activity log, NPT event, bit record, mud check, survey, BOP/pressure test, rig-move or POB table anywhere in the 134 tables. | `grep __tablename__` across `models/` | Operations is genuinely greenfield — you are free to design the domain properly. Nothing forces it into a new tenant. |
| 9 | The Database Browser and Report Builder **auto-discover** tables via reflection, grouped by `module_group()`. | `services/database_browser.py:51-122`, `services/report_catalog.py` | New operations tables become browsable *and* reportable by adding one prefix mapping. A second database would be invisible to both. |
| 10 | Well plans already hold hole sections, phases **with planned days**, spud timestamps per scope, and the two status ladders. | `backend/app/models/rig_well.py`, `services/well_lifecycle.py` | The schedule baseline a DDR must be measured against (planned vs actual days, depth vs plan) **already exists here**. |

Fact 10 deserves emphasis: the operations module's most important comparison — *planned days
versus actual days, planned depth versus actual depth* — is already loaded in this schema. In a
second workspace you would either duplicate `well_sections`/`well_phases` or lose the comparison.

---

## 3. The three options, compared honestly

### Option A — New modules in this workspace, same tenant, same database *(recommended)*

```
Organisation (tenant, workspace, one login, one backup, one audit trail)
├── Master Data ............ activities, NPT codes, vendors, sections, phases, units
├── Rig & Well ............. rigs, wells, plans, sections, phases, planned days   [exists]
├── AFE .................... what we budgeted                                    [exists]
├── Well Operations ........ DDR, DCR, time log, rig ops, NPT/UPA, productive time  [new]
├── Daily Cost ............. what we spent                                       [exists]
├── Invoice Processing ..... what we were billed                                 [exists]
└── Reports / Intelligence . joins all of the above                              [exists]
```

- **Separation is achieved by capability, not by tenant.** A `Drilling Supervisor` role gets
  `ops-report:read/create/update` and `daily-cost:read` and nothing else. A `Night Company Man`
  gets create-only. A `Cost Engineer` gets `ops-report:read` + `daily-cost:read/update`. A
  `Drilling Manager` gets `ops-report:approve`. None of them can see AFE estimating, invoicing or
  user administration. That is a stronger separation than a second workspace gives you, because
  it is enforceable per action and auditable per row.
- **One login, one audit trail, one backup, one report catalog.**
- **The reconciliation join exists natively:** `ops_activity_log → daily_cost_service_line`, so
  NPT hours and NPT cost are the same object, not a nightly reconciliation.
- **Product packaging is solved with module entitlements**, not tenancy (see §4.2).

### Option B — Second workspace (new organisation) in the same database

This is the middle option people usually argue for. In *this* codebase it is the weakest:

| Cost | Detail |
| --- | --- |
| Duplicate identities | Every user needs a second account in a second workspace (fact 1). Off-boarding becomes two actions; a resigned engineer keeps access to one. |
| Duplicate master data | Rigs, wells, blocks, activities, sections, phases, vendors and NPT codes would exist twice, maintained twice, drifting silently. A well renamed in one is wrong in the other. |
| No shared well | The same physical well becomes two rows with two IDs. Depth, spud date, plan and status diverge. |
| No cross-tenant join | "NPT cost as a percentage of AFE spend" becomes an ETL job across tenants. Your Business Dashboard, Cost Intelligence, Assistant and Report Builder all assume one `organization_id` per request. |
| Backup ambiguity | Two archives that must be restored consistently — and restore already refuses foreign archives. Point-in-time recovery of "the truth" now spans two tenant scopes. |
| Auth work | Multi-tenant membership would need: a membership table, token `org` switching, refresh-session rework, `_session_facts` changes, per-org permission resolution, and a re-audit of every tenant-boundary test. This is a security-sensitive change in code the repo explicitly marks as not-to-be-changed casually (see `AGENTS.md`: *"Do not silently change authorization semantics or tenant boundaries"*). |

You would pay all of that to obtain a boundary you can already get with one `require()` call.

### Option C — Second workspace **and** second database

Everything in Option B, plus: no referential integrity across the split, two migration chains, two
backup schedules, two restore procedures, distributed-consistency problems for the AFE-versus-actual
position, duplicated users/roles/permissions seeding, and a second set of connection pools and
credential rotation. It is the worst of the three for a system whose entire value proposition is
*one operational truth feeding one financial truth*.

---

## 4. What to do instead of a second workspace

### 4.1 Capability namespaces (the RBAC answer)

Add namespaces following the existing convention in `provisioning.py`:

```
ops-report      read, create, update, delete, submit, approve, reopen, export, import, print
ops-timelog     read, create, update, delete
ops-npt         read, classify, approve        # separate hands: typing NPT vs ruling on it
ops-rigmove     read, create, update, approve
ops-master      read, create, update, delete   # NPT codes, operation codes, downtime categories
ops-hse         read, create, update
```

Every new endpoint uses `Depends(require("ops-report:update"))` exactly as `daily-cost` does, every
frontend route uses the existing `<Guard>`/`<GuardAny>` pattern, and every mutation calls the
existing audit service. You inherit soft delete, import/export, PDF print, pagination, filters and
module dashboards because they are standing conventions, not new work.

**Role templates to seed (per workspace, editable):**

| Role | Grant | Deliberately denied |
| --- | --- | --- |
| Drilling Supervisor | `ops-report:*` except approve, `ops-timelog:*`, `daily-cost:read`, `rig-well:read` | `afe:*`, `invoice-processing:*`, `users:*`, `backup:*` |
| Night Company Man | `ops-report:read/create`, `ops-timelog:read/create` | update after submit, approve, cost |
| Completion Supervisor | same, completion-scoped | drilling scope |
| Operations Manager | `ops-report:read/approve/reopen/export`, `ops-npt:approve` | data entry |
| Cost Engineer | `daily-cost:*`, `ops-report:read`, `afe:read` | `ops-report:create`, `ops-npt:approve` |
| HSE Officer | `ops-hse:*`, `ops-report:read` | cost and AFE |
| Executive / Analyst | read-only across `ops-report`, `daily-cost`, `afe`, `business-dashboard` | any write |

That table *is* the "separate workspace" the user is imagining — and it costs one role screen.

### 4.2 Module entitlement (the product-packaging answer)

If the real goal is *"I want to sell/licence operations separately from costing"*, that is a
**commercial** boundary, not a data boundary. Solve it with an entitlement record per workspace:

```
module_entitlements: id, organization_id, module_key, is_enabled, enabled_at, enabled_by
```

Sidebar groups, routes and API routers mount on entitlement + permission. A costing-only customer
never sees Operations; an operations-only customer never sees AFE; a customer with both gets the
joined dashboards. Same tenant, same login, same database — three SKUs.

This is strictly more flexible than a second workspace, because it can be changed with a checkbox
instead of an account migration.

---

## 5. Can I extract data from one workspace to another?

**Today: not supported, by design.**

- `restore_archive()` raises `403` when the archive's organisation differs from the target
  (`services/backup.py:706-708`). There is no "copy workspace" or "move rows" path.
- The archive writer (`write_archive`) *can* produce a JSON manifest of one tenant's rows, so the
  raw material for a transfer exists — but there is no importer that **remaps organisation IDs and
  every foreign key** into a different tenant, and no conflict resolution, ID-collision handling or
  master-data deduplication.
- Even if you built it, you would hit the identity problem: `(organization_id, email)` is unique, so
  users do not transfer cleanly, and refresh sessions, role assignments and audit history do not
  transfer at all.

**If you nonetheless choose a second workspace,** budget this as its own project (realistically
multi-week, and a permanent maintenance surface):

1. `workspace_transfer` export of ops rows with a *logical* key for every reference
   (`well_code`, `rig_code`, `activity_code`, `npt_code`) rather than raw UUIDs.
2. An importer that resolves each logical key in the target tenant, creates what is missing, and
   reports unmapped rows rather than inventing them.
3. Deliberate policy for: same well code existing in both, soft-deleted rows, submitted/approved
   documents, and snapshots (which must **not** be re-resolved — a snapshot is history).
4. A dry-run mode that prints what it would create, mirroring the restore dry-run pattern already
   in `backup.py`.
5. Audit of every transfer with both workspace IDs.

Note that this machinery is only ever needed because of the split. In Option A, "extraction" is a
`SELECT` with a join.

---

## 6. Single database or separate database?

**Recommendation: single PostgreSQL database, single schema, same tenant.**

Reasoning, specific to what you have:

1. **Integrity.** The AFE position is `AFE total − services − consumables − tangibles − other
   expenses`. If NPT hours live elsewhere, that equation cannot be enforced by a constraint, and a
   failed sync silently misstates the financial position. That is an audit finding, not a bug.
2. **Atomicity.** Submitting a DDR and rolling its time into cost must be one transaction. Across
   databases it is a saga, and every existing guarantee in `services/daily_cost.py` (row locks,
   deduplication, the 24-hour validation, baseline locking) becomes unenforceable.
3. **Identity.** One well, one ID, one lifecycle. `Well.tracking_status`, the status ladders, spud
   timestamps and plan days are already the shared truth. Splitting creates two answers to "is this
   well active?"
4. **Scale.** An operations time log is the highest-volume table in the app: roughly 24 hours/well/day
   even at 15-minute granularity, i.e. ~100 rows per well-day. For a 20-rig portfolio at full
   granularity that is ~700k rows/year — unremarkable for PostgreSQL, and easy to index
   `(organization_id, well_id, occurred_at)`. Volume is **not** a reason to split.
5. **Operations.** One migration chain (you have 59 revisions), one backup regime, one restore drill,
   one credential set, one set of connection pools. The repo's security baseline already assumes
   exactly one of each.
6. **Everything already built assumes it.** Database Browser, Report Builder reflection, Cost
   Intelligence, the Assistant's grounding, Business Dashboard and audit are all single-tenant-per-
   request. A second database is invisible to all six.

**When to reconsider — and it is a deployment question, not a module question:** if a future
customer must be physically isolated (data-residency, regulator, on-prem), the answer is
*schema-per-tenant* or *database-per-tenant for the whole product*, with the same single-schema
design and the same `organization_id` columns. That preserves every join. Do not split
operations from costing — split tenants from each other, if and when a contract demands it. The
codebase is already shaped for that: every table carries `organization_id` and RLS is listed as a
future phase in `.agent/memory/project.md`.

---

## 7. Target domain model for the operations modules

Design for the existing conventions: column-wise only (no JSON), `organization_id` on every table,
soft delete, `*_snapshot` columns for anything that must not drift, audit on every mutation.

### 7.1 Phase 1 — the time spine and the daily reports

**`ops_daily_reports`** — one per well, scope and report date (DDR for `drilling`, DCR for `completion`)

```
id, organization_id, report_no (unique per org), rig_id + snapshots, well_id + snapshots,
scope ('drilling'|'completion'), report_date, day_number, tour ('day'|'night'),
period_start_at, period_end_at,           -- the 24h window this report covers
hole_section_id, phase_id,                -- current section/phase
depth_at_period_start, depth_at_period_end, depth_unit,
operation_summary, forward_plan, hse_summary, handover_notes,
status ('draft'|'submitted'|'approved'|'rejected'), submitted_at/by, approved_at/by,
supersedes_id, superseded_by_id,          -- amendment chain, like PO/SO revisions
is_deleted, deleted_at, created_at, updated_at, created_by, updated_by
UNIQUE (organization_id, well_id, scope, report_date, tour)
```

**`ops_activity_logs`** — the time record. This is the table the whole programme hangs on.

```
id, organization_id, report_id,
sequence_no,
started_at, ended_at, duration_minutes,   -- nullable end = ongoing at report close
activity_id, activity_code_snapshot, activity_name_snapshot,   -- Master Data Activity
operation_code_id,                        -- new ops master data: drilling operations taxonomy
classification ('Planned'|'UPA'|'NPT'),   -- explicit this time, not regex-derived
npt_code_id, npt_code_snapshot,           -- required when classification = NPT
is_productive,                            -- derived and stored, see §7.2
phase_id, hole_section_id,
depth_from, depth_to, depth_unit,
responsible_party, vendor_id,             -- who owns the time
reason, remark                          -- mandatory for NPT/UPA, like other-expense remarks
```

Constraints to plan for (and test):
- `ended_at > started_at`, `duration_minutes > 0`.
- **No overlaps** within one report (exclusion constraint on the time range, or a service-level check).
- **Sum of durations = the report's period length**, or an explicit, surfaced *unaccounted time*
  figure — mirroring how the daily cost sheet refuses >24 deduplicated hours.
- `classification = 'NPT'` implies `npt_code_id IS NOT NULL` and a non-blank `reason`.

**`ops_npt_codes`** — new master data register (replaces the regex heuristic for operations)

```
code, name, category (equipment_failure, hole_problem, well_control, weather, third_party,
                      logistics, personnel, waiting_on_orders, surface_equipment, subsurface,
                      survey, testing, other), subcategory, default_responsible_party,
is_chargeable, is_company_caused, is_contractor_caused, description, soft delete
```

Seed from your drilling contract / IADC-style downtime categories. Every NPT minute becomes
attributable, which is what makes the NPT-versus-cost report defensible to a partner or a regulator.

### 7.2 The two axes: Planned/UPA/NPT and Productive/Non-productive

The request names both a three-way classification (Planned, UPA, NPT) and a two-way timing split
(productive, non-productive). Keep them as **two separate columns with an explicit mapping**, never
one enum, or every report will argue about what "UPA" means:

| classification | is_productive | Meaning |
| --- | --- | --- |
| Planned | true | Scheduled operation executed as planned (drilling, tripping, casing). |
| Planned | false | *Planned* non-productive time: planned cement wait, planned logging, planned rig move, planned maintenance. |
| UPA | true | Unplanned but still productive/necessary work (e.g. an unplanned wiper trip that made progress). |
| UPA | false | Unplanned off-plan work with no forward progress. |
| NPT | false | Non-productive; must carry an NPT code and a responsible party. |
| NPT | true | Should be rejected by a constraint — NPT is non-productive by definition. |

Rules to lock with the client before building: whether `is_productive` is derived from the
operation code (recommended — one source) or typed per row (flexible, but invites inconsistency);
and whether UPA counts inside NPT in any MIS percentage (it must **not** — they overlap in today's
cost-derived reporting, which is exactly the ambiguity flagged in
`MODEL REPORTS/WellCosting_Pro_BRD_v1.0.md` OD-02).

### 7.3 The inversion that makes the modules worth building — DEFERRED

> **Scope change (2026-11-17).** This section is no longer part of the initial delivery. Operations
> and costing ship **independently, with no data flow between them**. The inversion below becomes
> Phase 5, unscheduled. See `docs/operations-costing-decoupling.md` — it records the decision, the
> three-layer model that defines "independent", and the C1-C7 compatibility contract that must be
> honoured now so this section stays cheap to build later. Nothing below requires a schema change
> today; every column it needs is nullable and additive.

Today: *cost line has `quantity_unit = 'hours'` → hours become operational time → ÷24 → NPT days*
(`services/operational_time.py`). That is backwards for operations, and it is why the BRD carries
open decision OD-02.

Target (Phase 5): **`ops_activity_logs` is the sole authority on time.** Then:

- cost lines carry a nullable `ops_activity_log_id` (FK) — "this charge is for that hour block";
- NPT/UPA **hours** come straight from the time log, with no deduplication heuristics;
- NPT/UPA **cost** is the sum of the linked cost lines — so "cost of NPT" becomes a real number
  rather than a proportion of a day rate;
- the existing daily-cost 24-hour rule is **retired in favour of** the DDR's completeness rule,
  otherwise you will double-enter time and the two validations will contradict each other
  (a genuine, planned-for conflict — see §9, decision D3);
- the printed daily cost report's "Time Position" panel reads from the time log and finally agrees
  with the DDR.

This single change is the reason one database wins. It is a join in Option A and a data pipeline in
Option C — and because Option A was chosen, it remains a join whenever it is eventually built.

### 7.4 Phases 2-4 tables (sketch, not committed scope)

| Cluster | Tables |
| --- | --- |
| Rig operations | `ops_rig_moves` (departure/arrival, distance, cost, contract day type), `ops_rig_crews` (tour pattern, headcount), `ops_day_type_log` (operating / standby / force majeure / repair — feeds day-rate billing) |
| Drilling mechanics | `ops_bit_records` + `ops_bha_components` (bit, IADC dull grade, metres, hours, ROP), `ops_mud_checks` (interval readings: density, viscosity, filtrate, chlorides…), `ops_surveys` (MD/INC/AZI/TVD/DLS), `ops_pressure_tests` (BOP, leak-off/FIT, casing test), `ops_casing_cement` (shoes, cement tops, volumes) |
| Completion | `ops_completion_events` (perforations, packers, screens, gravel pack, stimulation stages, wellhead/tree), `ops_well_tests`, `ops_coiled_tubing_runs` |
| People & HSE | `ops_personnel_onboard` (POB register, rotation, medivac), `ops_hse_observations`, `ops_incidents`, `ops_permits_to_work`, `ops_handovers` |
| Integration | `ops_cost_links` (if a charge must be split across several activity logs), `ops_afe_progress` (actual vs planned days per section/phase) |

Every one of these benefits from the same tenant, the same wells and the same vendors already in
this database.

---

## 8. Suggested delivery order

**Phase 0 — decisions (do not skip; 1-2 weeks of alignment, no code)**
Lock: NPT taxonomy and code list; the productive/non-productive mapping table; the report period
convention (midnight-to-midnight vs tour-based vs 06:00-to-06:00); approval workflow and who may
approve; whether time-log granularity is per-activity or fixed-interval; retention. Each of these is
cheaper to decide than to retrofit. (The "DDR without an AFE" question is moot after the decoupling
decision: operations does not reference AFEs at all.)

**Phase 1 — the spine (MVP that stands alone)**
`ops_npt_codes` master data, `ops_daily_reports`, `ops_activity_logs`, the 24-hour/no-overlap
validations, the DDR/DCR entry screen, submit/approve, the module dashboard (productive %, NPT %,
NPT hours by code and responsible party), print/PDF, import/export, audit, RBAC namespaces.
*Exit criterion:* a supervisor can replace the paper DDR and the numbers reconcile to 24 hours.

**Phase 2 — the join — DEFERRED to Phase 5 (decision of 2026-11-17)**
Operations and costing ship independently. When correlation is eventually built: `ops_activity_log_id`
on cost lines; NPT/UPA duration read from the time log; NPT cost from linked charges; retire the
cost-derived duration rule; update the printed daily report's Time Position panel. See
`docs/operations-costing-decoupling.md`. Nothing in Phases 1/3/4a depends on it.

**Phase 3 — rig operations and the operational registers**
Rig moves and day-type log, bit/BHA records, mud checks, surveys, pressure tests, POB, HSE.
Each as its own register with the standard conventions; each feeding the ops dashboard.

**Phase 4 — MIS and intelligence (split by the decoupling decision)**
**4a, buildable immediately:** flat-time analysis, productive/NPT/UPA percentages, NPT hours by
cause, party, rig and well, ROP and days-per-1000 m/ft benchmarks, planned-versus-actual days per
phase, rig performance league tables. All of this reads operations data alone.
**4b, deferred to Phase 5:** cost-of-NPT by cause and party, and Cost Intelligence rules that explain
a financial variance from an operational cause. These are the only figures that need the join.

---

## 9. Decisions to lock before Phase 1

| ID | Decision | Why it is blocking |
| --- | --- | --- |
| D1 | NPT taxonomy — adopt the contract/IADC list, or your own? | Determines the master data, the reporting dimensions and every partner report. |
| D2 | Is `is_productive` derived from the operation code, or entered per row? | Two sources of truth for the same minute is the classic ops-software defect. |
| ~~D3~~ | ~~Does the DDR become the authority for time?~~ **Settled 2026-11-17:** both modules run independently; the DDR is the sole authority for *operations* time from day one, and costing keeps its own derivation until Phase 5. See `docs/operations-costing-decoupling.md`. | No longer blocking — the two modules validate different objects over different windows (a cost sheet vs a report period), so they cannot contradict each other. |
| D4 | Report period: calendar midnight, tour-based, or a 06:00 boundary? | Changes the uniqueness constraint, the day-number calculation and every day count. Also the seam that makes future correlation possible, so store the exact period timestamps (contract C2). |
| D5 | Can a DDR be filed for a well with no AFE / no configured plan? | **Simplified by the decoupling:** operations no longer references AFEs at all, so the answer is yes by construction. Only the well must exist and be in an open scope. |
| D6 | Approval chain: supervisor → company man → ops manager? And can a submitted DDR be amended, and how is the amendment versioned? | Determines status model, permission split and the supersedes chain. |
| D7 | Does NPT require a responsible party from the vendor register, free text, or both? | Matches the existing sub-activity convention (`vendor_id` + `responsible_party` + source flag) — reuse it. |
| D8 | Retention and legal-hold for operational records vs cost records. | Regulatory exposure differs; decide before data exists. |

---

## 10. What not to do

- **Do not create a second workspace to get separation.** You would break the identity, master-data
  and reconciliation model to obtain something one `require("ops-report:read")` already gives you.
- **Do not create a second database.** It forecloses the only join that makes the product valuable
  and breaks atomicity of the AFE position.
- **Do not keep deriving classification by regex on activity names.** It is acceptable as a
  compatibility fallback for existing cost data; it is unacceptable as the basis of an operations MIS.
- **Do not store the activity log as a JSON blob.** The repo's rule is column-wise, and time logs are
  precisely the data that must be indexed, constrained and reported on.
- **Do not add a second time engine.** One clock: `ops_activity_logs`. Cost consumes it.
- **Do not silently change tenant boundaries or authorization semantics** to make any of this fit
  (the repository's own working agreement forbids it).

---

## 11. What would change this recommendation

Being explicit about the conditions, so this can be re-litigated on evidence rather than taste:

1. If operations and costing are run by **different legal entities** or different customers of yours
   (e.g. you sell ops to a drilling contractor and costing to an operator), then they are genuinely
   two tenants — and Option B becomes correct.
2. If a **regulator or contract** forbids operational data and financial data in one database, the split
   is mandated; in that case choose *separate tenant, separate database* (Option C) and budget the
   transfer machinery in §5 as a first-class deliverable.
3. If operations must be **deployable without** the costing stack for cost or footprint reasons — that
   is still served by module entitlements (§4.2) and router-level mounting, not by a second database.
4. If a future acquisition requires merging two existing databases, plan around the
   `organization_id` remap described in §5 rather than redesigning the domain.

None of these apply to a single operator running its own wells through this product. For that case
the answer is unambiguous: **new modules, same workspace, same database, RBAC and entitlements for
separation.**
