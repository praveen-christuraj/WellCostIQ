# Decision record: Operations and Costing run independently

**Status:** accepted. Supersedes Phase 2 ("the join") in `docs/operations-implementation-plan.md`, which is now deferred to a future Phase 5.
**Date:** 2026-11-17
**Decision owner:** product

---

## 1. The decision

Well Operations (DDR/DCR, activity log, NPT/UPA, productive versus non-productive time, rig
operations) will be built and run **independently of the costing modules** (AFE, Daily Cost, Invoice
Processing). No data flows between them, in either direction, until the operations workflow has been
streamlined and accepted in use. Correlation — automatic extraction of Planned/UPA/NPT from the
operations record into costing — is a **later, separate phase**.

**The stated reason is correct and worth recording in its own words:** running both without a live
dependency removes the contradiction risk and the confusion while the operations workflow is still
finding its shape. A shared dependency during a design-still-moving phase means every operations
change becomes a costing regression, and every costing change becomes an operations blocker.

## 2. This does not conflict with the architecture decision

It is worth being explicit, because the two documents could look like they disagree.

The earlier recommendation was: **one workspace, one database, no new tenant.** That stands, and
this decision actually *strengthens* it. Correlation later is only cheap because the two modules
already share the same well IDs, the same rig IDs, the same master data and the same database. In a
separate workspace, "correlate later" would be an ETL project between two tenants with no shared
well identity — every well would need to be mapped by hand, and every match would be a guess.

So: **same workspace, same database, and for now, zero edges between the two modules.** Those are
compatible statements, not competing ones.

## 3. The three-layer model that makes "independent" precise

The confusion in the word "independent" comes from treating this as two modules. It is three layers.

```
Layer 1 — SHARED FOUNDATION  (neither costing nor operations; both consume)
    Master Data: activities, hole sections, phases, UOM, currencies, vendors, services
    Rig & Well:  blocks, rigs, wells, well sections/phases, planned days, spud milestones

Layer 2 — SIBLING MODULES  (independent of each other)
    COSTING                      │   OPERATIONS
    AFE, Daily Cost,             │   DDR/DCR, activity log,
    Invoice Processing           │   NPT/UPA, rig ops registers

Layer 3 — INTELLIGENCE  (may read both, later)
    Reports, Report Builder, Cost Intelligence, Assistant, dashboards
```

"Independent" means exactly one thing, and it is testable:

> **No foreign key from any `ops_*` table to any `afe*` or `daily_cost_*` table, and none in the
> reverse direction.** No shared mutable state. No service in `services/operations.py` imports
> costing services, and no costing service reads an `ops_*` table.

Referencing `wells`, `rigs`, `activities`, `hole_sections`, `phases` and `vendors` is **not** a
costing dependency — those belong to Layer 1, which is shared by design and predates both modules.
This distinction is what lets Operations have a fully populated well picker and still be
independent.

A CI-checkable assertion follows from this, and should be written as a test rather than trusted to
review: walk the `ops_*` tables' foreign keys and assert none targets a costing table; walk the
costing tables' FKs and assert none targets an `ops_*` table. That test is the guard that keeps this
decision true for years.

## 4. What changes in the build plan

### 4.1 Phase 2 is removed from the critical path

| Before | After |
| --- | --- |
| Phase 1 (spine) → Phase 2 (join, 4-5 weeks) → Phase 4 (MIS) | Phase 1 (spine) → Phase 3 (registers) and Phase 4a (ops-only MIS) → … → **Phase 5 (correlation), unscheduled** |

Phase 2's entire content moves to Phase 5, unbuilt:

- the nullable `ops_activity_log_id` column on the cost line tables;
- NPT/UPA duration and cost reading from the time log;
- the dual-run with a "time basis" label;
- retiring the daily-cost 24-hour deduplication rule;
- re-pointing cost links on report amendment;
- the DDR report number cross-referenced on the printed daily cost report.

**No schema change is needed now to enable any of it later.** Every column Phase 5 needs is
nullable and additive, so it arrives in a single ordinary migration whenever the client asks for it.
Deferring costs nothing.

### 4.2 Phase 4 splits

| Sub-phase | Content | Needs the join? |
| --- | --- | --- |
| **4a — ops-only MIS** (buildable now) | Flat-time and time-distribution analysis; productive/NPT/UPA percentages; NPT hours by cause, by responsible party, by rig, by well; ROP and days-per-1000 m/ft benchmarks by hole section; planned-vs-actual days per phase from `well_phases`; rig performance league table | **No** |
| **4b — financial MIS** (deferred) | Cost of NPT (hours × day rate, and actual linked charges); variance explained by flat time; cost-per-metre by section; Cost Intelligence rules that cross the boundary | Yes |

Phase 4a is the majority of the analytical value and is fully deliverable on operations data alone.
The single report that genuinely needs the join is "what did NPT cost us" — and that is also the one
report that will be *more* defensible once built on a settled operations record.

### 4.3 RBAC simplifies

Operations capabilities are **`ops-*` only**. No operations endpoint depends on `daily-cost:read`,
`afe:read` or `rig-well:*` beyond the shared well/rig lookups, and no operations role needs any
costing grant.

| Role | Grants (revised) |
| --- | --- |
| Drilling Supervisor | `ops-report:*` except approve, `ops-master:read` |
| Night Company Man | `ops-report:read`, `ops-report:create`, `ops-report:update` (own tour) |
| Completion Supervisor | same, completion scope |
| Operations Manager | `ops-report:read/approve/amend/export`, `ops-master:*`, `ops-hse:*` |
| HSE Officer | `ops-hse:*`, `ops-report:read` |
| Drilling Manager (analyst) | `ops-report:read`, `ops-report:export` |

`ops-timelog` stays unallocated for the same reason as before — time blocks live inside a report and
are governed by `ops-report`. Do not add it speculatively.

### 4.4 Two items to remove from the Phase 1 spec

1. **`ops_daily_reports.afe_id`** — drop it from Phase 1. It is the one deliberate seam in the
   original design and it creates a soft costing reference for no operational benefit today. Add it
   in Phase 5 if it proves useful. Operations identifies a well by `well_id`; which AFE funds that
   well is a costing question.
2. **"NPT cost" on the DDR print and dashboard** — replace with NPT **hours**. The `npt_cost` panel
   described in the implementation plan's print section belongs to Phase 4b.

## 5. The costs of independence — accepted deliberately

Naming these now, because they are the price of the decision and someone will raise them later.

### 5.1 Double entry (the real cost)

Today's plan assumed the DDR would become the single place time is typed. Running independently
means **the same day's hours get typed twice** during the interim: once as time blocks in the DDR,
once as `hours`-quantified cost allocations on the daily cost sheet.

Mitigation, and it is cheap: **make the DDR the one place crews type time from day one**, even though
costing does not consume it yet. The DDR grid becomes the working document the supervisor actually
uses; the cost sheet's hours are entered from it by a clerk. When Phase 5 arrives, costing reads what
was already being typed instead of starting to type it — the correlation becomes a *consumption*
change, not a *data-entry* project. This costs nothing extra now and preserves the entire benefit.

### 5.2 Two independent 24-hour validations

The daily cost sheet rejects more than 24 deduplicated hours per sheet. The DDR will reject a period
that is not fully accounted for. These are **different objects over different windows** — a cost
sheet and a report period — so they cannot contradict each other, and this decision is what makes
that true. No further action needed; do not attempt to reconcile them now.

### 5.3 Classification derivation stays duplicated, for now

Costing keeps its regex derivation (`classify_activity`, `services/daily_cost.py:265`) unchanged.
Operations stores `classification` explicitly on the time block. Two derivations exist, deliberately,
with different inputs. They will disagree on some days. **That disagreement is the Phase 5
worklist**, and it is better found by comparison on real data than assumed away now.

## 6. The compatibility contract — lock these now, they are free

None of these require a line of code beyond what Phase 1 already contains. Each one is expensive to
retrofit, so they are stated as a contract that both modules build to.

| # | Contract | Why it must be now |
| --- | --- | --- |
| **C1** | Operations references shared entities **by ID** (`well_id`, `rig_id`, `activity_id`, `hole_section_id`, `phase_id`, `vendor_id`) *as well as* by snapshot. Snapshots are for history; IDs are for joining. | A design that stores only names cannot be correlated without name matching. |
| **C2** | `ops_daily_reports` stores the exact `period_start_at` / `period_end_at`, and `ops_activity_logs` stores `started_at` / `ended_at`. | Correlation must eventually match by **time interval overlap**, not by date equality, because the operating day and the calendar cost date are not the same window. Without the exact instants, that match is impossible. |
| **C3** | Classification uses the identical three literals, same spelling and case: `Planned`, `UPA`, `NPT`. | They are already persisted as literal strings in four `daily_cost_*_lines` tables. A different vocabulary means a translation layer and a class of silent bugs. |
| **C4** | Operations stores durations as **integer minutes**. Costing stores hours as `Numeric(28,10)`. | The conversion (`minutes / 60`, quantised to ten places) is documented once, in one helper, so both sides round identically. Never store decimal hours in operations. |
| **C5** | Operations uses the shared `depth_to_meters()` / `normalize_depth_unit()` from `core/units.py`, and stores both the entered value and the metre value. | Cost lines store `actual_depth` in metres with `actual_depth_input` / `actual_depth_unit` beside it. Matching depths across modules needs the same normalisation. |
| **C6** | Operations never writes to a `daily_cost_*` or `afe*` table; costing never writes to an `ops_*` table. Enforced by the FK assertion in §3. | The invariant that defines independence. |
| **C7** | The eventual arbiter, recorded in advance: **operations is authoritative for duration; costing is authoritative for cost; a disagreement between them is surfaced to a human, never auto-resolved.** | This is the question that causes the most argument in Phase 5. Deciding it now, before the code exists, costs one sentence. |

C2 is the one that would genuinely hurt to get wrong. It is the reason the report period is stored as
two timestamps rather than a date and a tour — a decision already made for other good reasons
(overlap validation, unaccounted time), which now also pays for correlation later.

## 7. What NOT to do now

Each of these is tempting "just in case" work. All are premature.

- **Do not add `ops_activity_log_id` to the cost line tables** as a placeholder column. A nullable FK
  nothing uses is a column that rots, gets a wrong value from a future writer, and has to be cleaned
  before it can be used. Add it in Phase 5 in one migration.
- **Do not add a `source` / `origin` / `correlation_status` flag** to costing rows to prepare for a
  join that has not been designed.
- **Do not build the dual-run comparison** before there is a second number to compare against.
- **Do not fork the `Well` model** or create operations-side copies of wells, rigs or master data.
  That would destroy the thing that makes Phase 5 cheap.
- **Do not create a second classification vocabulary** because operations needs "productive" as well.
  `classification` stays the shared three; `is_productive` is an operations-only extra column.
- **Do not cross-reference documents** — no DDR number on the daily cost print, no cost figure on the
  DDR. That is Phase 5 presentation work.

## 8. Revised sequencing

| Phase | Content | Status |
| --- | --- | --- |
| 0 | Decisions and spec (unchanged, minus the two removals in §4.4) | As planned |
| 1 | The time spine: operation/NPT codes, DDR/DCR, activity log, validations, submit/approve, dashboard, print, import/export, RBAC, migration | As planned, **independently deployable** |
| 3 | Operational registers: rig moves and day types, bit/BHA, mud checks, surveys, pressure tests, POB, HSE | Promoted — now the main follow-on |
| 4a | Ops-only MIS: flat time, NPT by cause/party/rig, ROP, planned-vs-actual days, rig performance | Promoted — needs no costing data |
| **5** | **Correlation: auto-extraction of Planned/UPA/NPT into costing.** The column, the consumed duration, the dual-run, the retirement of the cost-derived rule, the cost-of-NPT report, cross-referenced prints | **Deferred, unscheduled.** Trigger: operations workflow accepted in production use, with the client asking for the cost of NPT. |

Phase 5's prerequisites are already stated: C1-C7 honoured, a period of real reports to compare
against, and the C7 arbiter agreed.

## 9. How we will know the deferral was the right call

Three observable signals, reviewed when someone proposes starting Phase 5:

1. **The DDR is being used without complaint** — reports filed daily, unaccounted time trending down,
   no bypass spreadsheets. If it is not, correlating an unused record with costing multiplies the
   problem rather than solving it.
2. **A named person asks for the cost of NPT**, not for the join in the abstract. Financial MIS is
   worth building when someone is making a decision with it.
3. **The two derivations disagree in a way that matters** — the comparison is now a worklist of real
   classification errors, instead of a hypothetical reconciliation.

If none of the three is true, the correct action is to keep improving operations, not to start Phase 5.
