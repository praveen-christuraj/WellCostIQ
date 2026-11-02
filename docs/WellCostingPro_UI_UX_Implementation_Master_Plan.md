# WellCostingPro / WellCostIQ — Enterprise UI/UX Design & Implementation Master Plan

**Document version:** 1.0  
**Prepared:** 2026-11-02  
**Source repository:** https://github.com/praveen-christuraj/WellCostingPro  
**Audited branch:** `main`  
**Repository snapshot / commit:** `b365d26a49e4c5bfa5c8889b44d621cb4c1245cd`  
**Primary stack:** React 19, TypeScript, Vite 7, MUI 7, AG Grid Community 35, Apache ECharts 6, React Router 7, FastAPI, SQLAlchemy, PostgreSQL 17  
**Purpose:** A production-oriented, implementation-ready UI/UX modernization blueprint that improves navigation, screen composition, data comprehension, visual design, task efficiency, accessibility, and interaction quality **without breaking existing application behavior**.

> **Read this first:** This is an implementation *plan*, not a claim that any proposed feature has been built. The plan is tailored to repository files inspected on the snapshot above. For any later commit, reconcile the route registry and components before implementation. The app is called **WellCostIQ** in the current README and UI branding; the GitHub repository is **WellCostingPro**. Preserve current product naming unless the owner approves a naming change.

---

## 1. Executive decision

### 1.1 Recommended design identity

**Enterprise Navy Financial & Operations Workbench**: a calm, high-density, highly polished software workspace for cost engineers, drilling engineers, well planners, AFE reviewers, supervisors, finance analysts and administrators. Blend the strength of three visual paradigms:

1. **Enterprise SaaS shell** — efficient navigation, unified workspace layout, clear focus and reliable data-entry flows.
2. **Financial analysis terminal** — trustworthy numeric alignment, AFE-to-actual variance analysis, auditable calculations and powerful grids.
3. **Drilling operations workbench** — wells/rigs/scopes, time-versus-depth, mud/fuel/LIH, NPT/UPA and drill-down to source records.

**Not** a generic admin-template redesign, marketing landing page, video-game command center or glassmorphic dashboard. Priority is **information architecture and task ergonomics**, not decorative effects.

### 1.2 Objectives in descending order

1. Make the user's current **workspace, rig, well, scope, AFE, date and currency** obvious.
2. Make navigation fast and predictable across many modules.
3. Reduce steps and field re-entry in AFE estimates and daily cost sheets.
4. Make every analytical figure explainable and traceable to source entries.
5. Improve tables, charts, form affordances, errors and task feedback.
6. Increase visual consistency across current and future modules.
7. Meet accessibility, responsiveness and performance gates without weakening authorization or data accuracy.

### 1.3 Non-negotiable engineering rule

**Improve the experience around existing business rules; do not substitute UI assumptions for backend policy.** Any proposed new calculation, endpoint, permission, workflow state or data field is a **candidate enhancement**, not an existing implemented capability. Prioritize UI-only work; split backend-dependent changes into separate approved work items.

---

## 2. Repository evidence and existing capabilities

### 2.1 Files reviewed and roles

| Existing source | Observed role | Implementation implication |
|---|---|---|
| `README.md` | Tenant-aware app description, stack, Master Data, approvals, tasks, notifications, security, reporting, deployment | Use live behavior and rules as baseline |
| `frontend/package.json` | React 19, MUI 7, AG Grid **Community**, ECharts; no MUI X dependency | Reuse current grid/charts; do **not** casually prescribe MUI X or AG Grid Enterprise |
| `frontend/src/App.tsx` | Actual React Router routes and permission guards | Source of truth for page inventory and deep links |
| `frontend/src/components/Layout.tsx` | Permission-filtered expandable/collapsible navigation, mobile drawer, top bar, theme/account/notification controls | **Refine** existing shell rather than building a duplicate |
| `frontend/src/components/DataTable.tsx` | AG Grid search, advanced/date filters, import/export, selection, action pinning, content/fill-height sizing | Extend the shared component, preserving behavior |
| `frontend/src/components/Common.tsx` | Shared headings, tags, form/panel dialogs and unsaved-changes guard | Prefer canonical components, not one-off replacements |
| `frontend/src/designSystem.ts`, `theme.ts`, `styles.css` | Design tokens and visual rules; light/dark; grid theme; CSS variable mirror | Single source of visual truth |
| `.agent/memory/design-system.md` | Existing enterprise navy design contract and checks | This plan **extends** it; it does not override it |
| `AGENTS.md`, `.agent/skills/ui-design.md` | Mandatory project/agent workflow, permission and UX conventions | Agents must read and obey these first |
| `frontend/src/pages/BusinessDashboard.tsx` | Existing cross-module dashboard with rig/well/AFE/date/currency filters, charts and grids | Refine existing analytic hierarchy, not invent dashboard from scratch |
| `AfeOverview`, `AfeManagement`, `AfeEstimate` | AFE overview/register/estimate, approvals, scope-of-work changes and multi-category cost lines | Preserve state machine, calculations and report/print flow |
| `DailyCostManagement`, `DailyCostSheet`, `DailyCostAnalysis` | Daily register, multi-category cost sheet, well analysis, previews, totals, printing, guarded unsaved edits | Design high-priority data-entry and analysis journeys |
| `MudCostAnalysis`, `FuelCostRegister`, `LihCostRegister` | Existing high-density operational costing ledgers | Specialist UX improvements, not new functional clones |
| `ReportBuilder`, `ReportDesigner`, custom/reports pages | Report configuration, designer, previews and published reports | Work on progressive disclosure, configuration clarity and print fidelity |
| `SecurityCenter`, `TaskManager`, `Notifications`, `BackupRecovery` | Existing security and operational control flows | Preserve separation of duties and approvals |
| `backend/app/api/*`, `backend/app/models/*`, `backend/tests/*` | Existing API, data model and regression suite | UI must be verified against actual contracts; new capability requires separate design and API work |

**Evidence basis:** GitHub `main`, commit recorded above. This assessment is based on repository source inspection, not a live usability study or executed end-to-end browser review. Usability weaknesses identified below are **hypotheses to validate through screenshots and task observation**, not claims that the existing implementation is defective.

### 2.2 Current UI investments to retain

- Navy-on-white enterprise palette; light and dark modes; locally bundled variable **Inter**; token-driven typography, semantic colors, radii, spacing, shadows and AG Grid skin.
- Permission-aware sidebar, collapse/expand, saved preference, mobile drawer, module disclosure and route guards.
- Shared `PageHeading`, `Tag`, `FormDialog`, `PanelDialog`, `DataTable`, API error presentation, unsaved-changes guards and input conventions.
- Search, advanced filters, date range filters, 20/50/100 pagination, CSV/XLSX/PDF exports, selective imports, multi-select/bulk patterns and recoverable deletion where currently supported.
- Cross-module operations dashboard with charts and source tables; AFE planning/review; daily costing and specialized mud/fuel/LIH ledgers; report builder and reporting.
- RBAC enforced in backend; tenant boundaries; notification/task workflows; audit trail; default workspace currency; print/report routines.

### 2.3 Standing conventions — must remain intact

Read **`AGENTS.md`**, **`.agent/memory/project.md`** (especially *Standing product conventions*), **`.agent/memory/design-system.md`**, and **`.agent/skills/ui-design.md`** before any code change. Important existing requirements:

- **No silent data loss.** Data-entry dialogs preserve Save / Discard / Continue editing; full-page editors guard route navigation, browser back, refresh and close.
- **No loss of permissions or tenant scoping.** UI hiding is not authorization; direct route/API access remains protected.
- **No currency mixing.** Every displayed monetary aggregate must identify its currency, standardization method, conversion date/rate, or intentionally separate totals.
- **No change to financial or drilling business formulas** as a UI-side optimization. AFE, SOW, NPT, UPA, mud reconciliations and depth calculations remain governed by existing models.
- **No unapproved design drift.** Existing design direction rules out gradients, glassmorphism, emojis, busy animations and decorative cards. Motion is short, purely state-feedback and respects reduced-motion.
- **No new paid grid requirement by assumption.** AG Grid Community currently powers `DataTable`. Advanced grouping/pivoting that needs Enterprise licensing must be evaluated and budget-approved before implementation.
- Preserve current dialog close contract and destructive-action safeguards; do not add backdrop/Escape dismissal that causes unsaved loss.
- Preserve existing manual/automated imports, export formats, print outputs, audit events and deleted-record recovery flows.
- Existing `#root { zoom: 0.875 }` is a documented UI behavior. **Do not** change it casually: measure accessibility/readability, overlay positioning and responsive layout, then migrate only through a controlled, regression-tested decision.

---

## 3. Full present-day page / route inventory

The entries in this inventory were found in **`frontend/src/App.tsx`** on the audited commit. The rightmost column describes the intended **UX improvement**, not a new implemented feature. Existing navigation grouping comes from **`frontend/src/components/Layout.tsx`**.

### 3.1 Global entry, workspace and identity

| Existing route | Screen / component | UX plan |
|---|---|---|
| `/login` | `Login` | Clear workspace slug, username/password, error and reset-state messaging; secure accessible input focus |
| `/` | `Landing` logic | Preserve permission-based route selection; make appropriate overview fast and coherent |
| `/business-dashboard` | `BusinessDashboard` | Role-aware summary, unified filter context, well/AFE drill-down, readable visual hierarchy |
| `/dashboard` | `Overview` | Distinguish user-management overview from operations overview; prevent ambiguous 'Dashboard' titles |
| `*` | `NotFound` | Preserve explicit not-found recovery and breadcrumbs |

### 3.2 User, access and security

| Route | Component | UX plan |
|---|---|---|
| `/users` | `Users` | Searchable employee register, access scope and account state details |
| `/roles` | `Roles` | Comprehensible role register and change feedback |
| `/permissions` | `Permissions` | Group by resource/action, explain permission meaning |
| `/assignments` | `Assignments` | Role assignment matrix, permission preview and review before applying |
| `/security` | `SecurityCenter` | Separate password recovery, lock/unlock and session actions; protect dangerous controls |

### 3.3 Master Data and commercial documents

| Route | Component | UX plan |
|---|---|---|
| `/master-data` | `MasterDataOverview` | Registry health, most-used catalogs and guided navigation |
| `/master-data/records` | `MasterDataRecords` | Consistent records for UOM, currency, phase, hole section, activity |
| `/master-data/services` | `Services` | Six reporting-group context, provider type, vendor linkage, bulk reclassification |
| `/master-data/vendors` | `Vendors` | Vendor classification, lifecycle and linked-services/order context |
| `/master-data/po-so-orders` | `PoSoOrders` | Revision chain, document previews and latest-approved/active revision clarity |
| `/master-data/tangibles` | `Tangibles` | Confirm current route's screen maturity; plan completed catalog UX only if feature enabled |
| `/master-data/consumables` | `Consumables` | Drill bits, chemicals, cement additives, fuel categories and validation |
| `/master-data/catalogue-lists` | `CatalogueLists` | Specialized list/search/selection conventions |
| `/master-data/deleted` | `DeletedMasterData` | Safe restore and permanent-delete confirmation, dependency visibility |

### 3.4 Rig and well lifecycle

| Route | Component | UX plan |
|---|---|---|
| `/rig-well` | `RigWellOverview` | Operational inventory, scoped lifecycle and drill-down |
| `/rig-well/blocks` | `Blocks` | Block register navigation and linked rigs/wells |
| `/rig-well/rigs` | `Rigs` | Rig directory, links to currently assigned wells and filters |
| `/rig-well/wells` | `Wells` | Clear *Drilling vs Completion* scoped tabs, plan/status progress, configuration entry points |
| `/rig-well/sub-activities` | `WellSubActivities` | Activity scope and dependency, planned/NPT/UPA classification clarity |
| `/rig-well/deleted` | `RigWellDeleted` | Safe recoverability for independent scope entries |

### 3.5 AFE, costing sets, daily costs and specialist registers

| Route | Component | UX plan |
|---|---|---|
| `/afe` | `AfeOverview` | AFE portfolio, approval pipeline and well context |
| `/afe/register` | `AfeManagement` | Registry tabs, status queues, clear review/approval actions |
| `/afe/estimate/:afeId` | `AfeEstimate` | Structured scope/phase/section estimate editor with services, consumables, tangibles, currency and validation |
| `/costing-sets` | `CostingSets` | Discoverable reusable templates, preview before applying, safe reuse |
| `/daily-cost` | `DailyCostManagement` | Daily register; filters and saved-sheet actions, with no misleading workspace-level totals |
| `/daily-cost/entries/:entryId` | `DailyCostSheet` | High-priority editor: scope, progress, daily/cumulative metrics, cost-group sheets, preview, submit/print |
| `/daily-cost/analysis` | `DailyCostAnalysis` | Require explicit well selection, clarify raw vs reconciled totals |
| `/daily-cost/analysis/:wellId` | `DailyCostAnalysis` | Deep-linked well-specific analysis preserving context |
| `/daily-cost/mud-cost-analysis` | `MudCostAnalysis` | Daily Entries / Material Balance / Reconciliation; section and date controls |
| `/daily-cost/lih-register` | `LihCostRegister` | Lost in Hole grouped worksheet, bulk/import workflows, cost impact |
| `/daily-cost/fuel-cost-register` | `FuelCostRegister` | Rig-scoped AGO ledger, physical stocks, material balance and company-wise allocation |
| `/daily-cost/ndt-inspections` | `NdtInspectionRegister` | Inspection records, status, document/view navigation |

### 3.6 Reporting and custom reports

| Route | Component | UX plan |
|---|---|---|
| `/reports` | `Reports` | Clearly categorized report catalog; recent/pinned reports if feasible |
| `/reports/builder` | `ReportBuilder` | Template/report library; create/manage/report status |
| `/reports/builder/:reportId` | `ReportDesigner` | Progressive step workflow, preview, field mapping and filter explanation |
| `/reports/custom` | `CustomReports` | Published report gallery and saved filters |
| `/reports/custom/:reportId` | `CustomReportViewer` | Runtime parameters, export/print, provenance |
| `/reports/custom-report/:reportId` | `CustomReportViewer` | Preserve legacy/alternate deep-link compatibility |
| `/reports/well-cost-comparison` | `WellCostComparisonReport` | Clear well/AFE scope, comparable currency, actual-to-AFE visual |
| `/reports/consumption-losses` | `ConsumptionLossesReport` | Quantities, reconciliation and losses |
| `/reports/mud-chemicals-usage` | `MudChemicalsUsageReport` | Mud chemical usage trend and tabular export |
| `/reports/drill-bits-usage` | `DrillBitsUsageReport` | Drill-bit usage, well/section comparisons |
| `/reports/tangibles-usage` | `TangiblesUsageReport` | Tangible material usage |
| `/reports/service-wise-cost` | `ServiceWiseCostReport` | Service-group budgets/actuals and drill-down |
| `/reports/vendor-wise-cost` | `VendorWiseCostReport` | Vendor/company cost attribution |
| `/reports/npt-upa` | `NptUpaReport` | NPT vs UPA durations and cost exposure |

### 3.7 Work queues, administration and resilience

| Route | Component | UX plan |
|---|---|---|
| `/other-management` | `OtherManagementOverview` | Organize admin workbench by action, not by vague title |
| `/other-management/tasks` | `TaskManager` | My tasks / team queue, due dates, claiming, reassignment, bulk actions |
| `/other-management/notifications` | `Notifications` | Relevant feed, unread/severity filters, announcement state |
| `/other-management/audit` | `AuditLog` | Effective event timeline, actor/action/object filters, read-only data |
| `/other-management/database` | `DatabaseBrowser` | Controlled schema navigation, clearly administrative/read-only |
| `/other-management/database/:tableName` | `DatabaseTableView` | Read-only table details with safe export controls |
| `/other-management/backup` | `BackupRecovery` | Backup verification, restore request/approval, dry-run and destructive-action safeguards |
| `/audit` | redirect to `/other-management/audit` | Keep compatibility |

**Coverage rule:** All routes above need a page-level UX specification, existing-permission review and responsive/accessibility QA. The dynamic route is *not* an excuse to skip per-record deep-link testing.

---

## 4. Information architecture: make the large app navigable

### 4.1 Problem statement to validate

The actual navigation currently organizes modules as User Management, Master Data Management, Rig & Well Management, AFE Management, Daily Cost Management, Reports and Other Managements. It is technically sound and permission-aware. With many specialized screens, the next level of polish should be **workflow-oriented navigation, prominent context and progressive disclosure**—not replacing all groups with an unrelated taxonomy.

### 4.2 Proposed workspace map (navigation labels are proposals; retain existing routes)

```text
WELLCOSTIQ
├── HOME
│   ├── Operations Dashboard               /business-dashboard
│   └── My Tasks & Alerts                   existing tasks/notifications deep links
├── WELL OPERATIONS
│   ├── Wells & Well Plans                  /rig-well/wells
│   ├── Rigs                                 /rig-well/rigs
│   ├── Blocks                               /rig-well/blocks
│   └── Well Sub-Activities                 /rig-well/sub-activities
├── COST MANAGEMENT
│   ├── AFE Portfolio                        /afe
│   ├── AFE Register                         /afe/register
│   ├── Daily Cost Register                  /daily-cost
│   ├── Well Cost Analysis                   /daily-cost/analysis
│   ├── Reusable Costing Sets                /costing-sets
│   ├── Mud Cost Analysis                    /daily-cost/mud-cost-analysis
│   ├── Fuel Cost Register                   /daily-cost/fuel-cost-register
│   ├── Lost in Hole                         /daily-cost/lih-register
│   └── NDT Inspections                      /daily-cost/ndt-inspections
├── REPORTS & ANALYTICS
│   ├── Report Catalog                       /reports
│   ├── Well Comparison                      /reports/well-cost-comparison
│   ├── Usage & Losses Reports               existing report routes
│   ├── NPT / UPA                             /reports/npt-upa
│   ├── Report Builder                       /reports/builder
│   └── Custom Reports                       /reports/custom
├── MASTER DATA & PROCUREMENT REFERENCES
│   ├── Master Records                       /master-data/records
│   ├── Services / Vendors                   existing master-data routes
│   ├── PO/SO Documents                      /master-data/po-so-orders
│   ├── Consumables / Tangibles              existing master-data routes
│   ├── Catalogue Lists                      /master-data/catalogue-lists
│   └── Deleted Master Data                  /master-data/deleted
└── ADMINISTRATION (role restricted)
    ├── Users / Roles / Permissions          current user routes
    ├── Security Center                      /security
    ├── Task Management                      /other-management/tasks
    ├── Notifications                        /other-management/notifications
    ├── Audit Log                            /other-management/audit
    ├── Database Browser                     /other-management/database
    └── Backup & Recovery                    /other-management/backup
```

**Important:** This is a proposed **navigation mapping**, not a mandate to rename routes, move business logic, merge modules or expose admin capabilities to everyone. The team can alternatively retain current top-level groups and implement all navigation enhancements in place.

### 4.3 Navigation specifications

**P0 — Refine shell without breaking routes**

- Keep permission-aware item filtering and guards from `App.tsx` / `Layout.tsx`; preserve conditional access for security center and restore workflows.
- Support expanded (about 272px) and collapsed (about 76px) desktop navigation, with tooltip accessible names and consistent active states. Existing widths are baseline, not arbitrary new requirements.
- Highlight *exact selected page*, *parent section* and breadcrumb; dynamic pages show `AFE / Estimate / AFE-...` or `Daily Cost / Sheet / ...`.
- Keep sidebar expanded state and module groups stable across navigation; avoid unexpected resets.
- Preserve keyboard tab order and focus after collapsing a group; in narrow screens use existing accessible drawer.
- Ensure separate label hierarchy: workspace → module → page → record; do not duplicate multiple large titles.
- Separate the top-level global dashboard from the user-management dashboard in labels.

**P1 — Context and navigation productivity**

- Add an **in-context active selection strip** for Rig / Well / Scope / AFE / Date/Period / Currency only where relevant; do not force a global filter onto pages whose semantics differ.
- Derive allowed selections from current scoped API data. Display a plain-text fallback for missing/deleted/unauthorized resources.
- Keep filters synchronized to URL query parameters where appropriate and safe; don't leak confidential identifiers into unauthenticated destinations.
- Save user filter preferences with explicit “Reset”; avoid invisible persistent scopes that quietly exclude records.
- Add breadcrumbs and record switchers on long-running editors; confirm unsaved changes before switching records.
- Offer **Recently visited wells/AFEs**, **Pinned workspaces/reports**, and **Global search/command menu** as separate gated enhancements **only if an efficient, tenant-scoped API/index is available**. Do not load all master data into the browser to simulate global search.

### 4.4 Role-aware starting points

- **Cost controller:** assigned wells, pending cost reviews, daily/weekly budget exposure, shortcuts to daily registers and well analysis.
- **Drilling engineer:** active rigs/wells, planned versus actual days/depth, NPT/UPA indicators, well plan and daily cost sheet.
- **AFE preparer/reviewer:** draft/review queue, estimate incompleteness, SOW revision visibility, one-click open of authorized estimates.
- **Operations manager:** portfolio-level variance, flags, drill-down to source evidence and approval queue.
- **Master-data administrator:** blocked vendors, catalog quality, pending imports and order revision references.
- **Security administrator:** only authorized account recovery, audit, session and backup/restore actions, consistent with existing RBAC.

Do not create fabricated role permission groups. Use actual `resource:action` grants and live `/auth/me` behavior. Acceptance: a low-permission test user never sees unauthorized navigation, data previews, search results or deep-link content.

---

## 5. Visual design system — preserve and raise quality

### 5.1 Baseline tokens (current project conventions)

- **Primary light:** navy `#12315F`; dark accent `#6F99D5`.
- **Canvas:** light `#F3F5F9`, dark `#0B1220`.
- **Paper:** light `#FFFFFF`, dark `#121B2E`.
- **Main text:** light `#0F1F3D`, dark `#E7EDF6`.
- **Inter Variable:** bundled locally. Numeric values use tabular figures; codes/order numbers may use monospace.
- **Spacing rhythm:** multiples of 4px; subtle hairline borders and restrained elevation.
- **Controls:** existing compact 30px, standard 36px and comfortable 44px; existing AG Grid row 42px/header 40px; increase coarse-pointer touch targets.
- **Motion:** short state-feedback only, generally 80–160ms, reduced-motion aware.

**Do not replace the palette with an unrelated brand.** Improve accessible contrast and information hierarchy *within* the existing framework. Update `designSystem.ts`, `theme.ts` and `styles.css` together. Avoid hard-coded per-page styles.

### 5.2 Design tokens to formalize or extend (only after auditing existing definitions)

| Token family | Required decisions |
|---|---|
| Color | Primary ramp, surface/raised/overlay, outline, text hierarchy, semantic good/warning/error/info, chart series palette |
| Typography | Hero-less page title, section title, table header, body, caption, tabular money, machine-readable IDs |
| Layout | Sidebar, utility bar, page gutter, section gap, sticky section-header, data table sizing |
| Density | Compact vs comfortable rules; **do not** blindly change global zoom |
| Form | Label, help, required, validation, prefix/suffix, numeric and currency/units formatting |
| Feedback | Pending, saving, saved, invalid, submitted, approved, stale, retry, destructive |
| Elevation | Flat panel, interactive overlay, modals only; avoid shadow-heavy card grids |
| Chart | Series color order, line/bars/markers, axes, thresholds, interactive legend, annotations |
| Responsive | 1440, 1280, 1024, 768, 390/375px verification points; scroll isolation |
| Accessibility | Focus ring, non-color indicators, keyboard/helptext, table naming and contrast |

### 5.3 Practical visual composition

**Page contract:**

```text
APP SHELL / selected module
Breadcrumb trail                                      context + account actions
PAGE EYEBROW
Page title                           Primary action / secondary action
One-sentence page purpose or relevant record context
--------------------------------------------------------------------------
Scope bar: [Rig] [Well] [Drilling/Completion] [Date] [Currency] [Reset]
--------------------------------------------------------------------------
High-signal KPIs or workflow state                    (only if relevant)
Main chart / working table / editor                   (task comes first)
Supporting details, warnings, provenance, audit       (progressive disclosure)
```

- One meaningful top-level title per page. Avoid dashboards made entirely of identical cards.
- Use **KPI strips** only where they represent meaningful, differently interpreted values; keep register pages list-first where current behavior requires it.
- Show money with consistently positioned currency and right-aligned figures, clear negatives and thousands separators; provide full unrounded number on hover/focus where needed.
- Use “—” for unavailable values; use `0` only for a known zero; use “Not calculated” for missing prerequisites.
- Show status with label + contextual action; green/red alone never convey status.
- Document time zones, inclusive dates, aggregation level and currency basis in chart captions or info popovers.
- Respect print screens: screen redesign must not disturb financial model reports and regulatory-ready PDF pages.

---

## 6. Shared UX component backlog

This is the strongest multiplier for quality: invest in components **once**, then apply consistently across modules.

| ID / Priority | Component or pattern | Current basis | Implementation details | Acceptance |
|---|---|---|---|---|
| DS-01 P0 | Page shell / `PageHeading` refinements | `Common.tsx` | Action overflow, breadcrumb slot, record subtitle, persistent status placement, mobile wrapping | Every route has predictable title/actions; no duplicated title |
| DS-02 P0 | Data-grid controls | `DataTable.tsx` | Filter summaries, explicit reset, active-filter chips, visible row counts, loading/empty/error/success semantics, right-aligned amounts | No changes to paging, imports/exports, selected rows or pinned Actions |
| DS-03 P0 | Financial formatters | `lib/units.ts`, existing money formatting | Shared currency-aware formatter, negative/zero/null standard, precision rules, tax/units distinction | No cross-currency totaling or precision loss |
| DS-04 P0 | Context selector | `lib/activeScope.ts` | Rig → Well → Scope → AFE linkage, contextual readonly badges, URL-safe state | Reopening deep link restores appropriate context |
| DS-05 P0 | Empty/loading/error states | Current `ErrorMessage`, `Alert` | Empty dataset vs permissions vs no filters vs offline vs no AFE; skeletons where appropriate | Helpful next action, not blank screens |
| DS-06 P0 | Safe financial action toolbar | Existing buttons/dialogs | Save/Preview/Submit/Approve/Print, role gating, pending status, dirty-state consistency | No unsafe or duplicated submit; no lost edits |
| DS-07 P1 | Chart panel | Existing ECharts usage | Reusable chart header, timeframe, currency badge, legend, expand, view-data, export controls | Chart axes, legend, drill-through and table equivalent verified |
| DS-08 P1 | Detail drawer/panel | Existing `PanelDialog` | Read-only details and record links; keep edit dialogs canonical until interaction approved | Opening details does not reset grid filter/scroll |
| DS-09 P1 | Task/approval state rail | Tasks/AFE workflows | Stage list, actor/date/remarks, rejection/return reason, progress label | Matches backend status history exactly |
| DS-10 P1 | Smart form field system | MUI fields | Numeric inputs, units, validation, helper text, required/readonly appearance, keyboard navigation | Tab order and accessible error association |
| DS-11 P1 | Saved grid views | Shared grid | Optional client/server preference, column visibility/order/sort/filter; explicit reset | Personal views never alter shared/default policy |
| DS-12 P2 | Command palette / global search | New | Keyboard-driven route + entity search, permission/tenant scoped; server API if needed | No inaccessible data or expensive full-table fetch |
| DS-13 P2 | Printable report preview UI | Existing reports | Page orientation/size/print status; PDF fidelity and cross-page headers | Does not change official report totals |
| DS-14 P2 | Cross-record activity timeline | Existing task/audit APIs | Authorized audit trail in contextual record view | No new exposure of sensitive audit data |

### 6.1 AG Grid implementation principles

- Stay with **AG Grid Community** initially: sorting, filtering, pinned Actions, column sizing and page navigation are already in use. Document what needs custom implementation versus paid features.
- Introduce optional **column chooser**, saved preset and keyboard navigation only if supported/tested with Community API; store preferences by user + grid ID, not universally.
- Keep client-side filtering for small registers where current data model is safe; for large datasets propose **server-side pagination/filtering** as a separately scoped API enhancement, including totals and export behavior.
- Provide clear **selected count**, total available rows, filtering scope, active sort, reset and bulk-action eligibility.
- Align money right, text left; use tabular numerals and semantic negative formatting. Preserve precision throughout API representation.
- For multi-table editors like `AfeEstimate` / `DailyCostSheet`, do **not** apply full-height grid sizing to every grid; the existing design document explicitly prohibits this.
- Pinned Actions column must not eat half the viewport; test compressed-width fallbacks and discoverable overflow menus.
- Maintain 20 / 50 / 100 rows per page and existing CSV/XLSX/PDF exports unless a change has written approval.
- Never turn hidden columns into security: sensitive fields must be filtered server-side.

### 6.2 Form behavior rules

- Required fields shown before save; validation adjacent to the field and summarized for long editors.
- Establish a **field error index** for long AFE/daily forms (“3 incomplete lines; jump to each”).
- Numeric fields accept appropriate decimal precision and locale-independent server normalization; never format while typing such that caret jumps.
- Copy previous-day and reusable-set actions must show **what will be added or replaced** before execution.
- Make save state unmistakable: `Unsaved changes`, `Saving…`, `Saved at ...`, `Submission blocked: fix ...`, `Read-only / Approved`.
- Preserve current three-choice discard convention and current dialog closing rules.
- Keyboard shortcut proposals (Ctrl/Cmd+S to save, `/` for search) only when safe outside text areas and after explicit user-testing.

---

## 7. High-impact page-by-page implementation plans

### 7.1 Operations Dashboard — `BusinessDashboard.tsx` — **P0**

**Existing features observed:** Rig/well/AFE/period/currency/status filters, auto-refresh, tabs, KPI figures (wells, days, NPT/UPA, AFE, SOW adjusted, actual, balance, depth), ECharts, detailed grids and drill navigation.

**Proposed enhancements:**

1. Reorganize top into `Portfolio context` → `Financial exposure` → `Operations performance` → `Well/AFE detail` so the reading order matches managerial decisions.
2. Use meaningful KPI grouping: *Adjusted AFE*, *Actual*, *Balance/Variance*, *Depth Progress*, *Planned vs Actual Days*, *NPT/UPA*; avoid duplicate values and ambiguous comparisons.
3. Make currency/date/scope assumptions persistently visible; preserve existing rejection of multi-currency mixing.
4. Offer two view presets (subject to user testing): **Financial** and **Operations**, backed by existing data—not two disconnected dashboards.
5. Make chart selection reversible and meaningful: AFE/actual/SOW stacked or grouped with labels; cumulative cost line over cost-date; planned/actual duration and NPT/UPA; depth progress with units and known denominators.
6. Add chart-to-table interactions using already-returned well/AFE IDs; preserve accessible click targets and table fallback.
7. Use direct record links instead of a generic modal that traps an analyst.
8. Make `Last refreshed`, manual refresh and optional auto-refresh visible and non-disruptive.

**Acceptance:** A manager can find a well exceeding its effective AFE, inspect its budget/actual provenance and open its well-analysis or estimate record in ≤3 deliberate interactions after filters are set; numbers remain identical to existing API response. Avoid claiming a hard interaction count unless validated with representative users.

### 7.2 AFE Portfolio/Register — `AfeOverview.tsx`, `AfeManagement.tsx` — **P0**

- Maintain drilling/completion scoped AFE types and well lifecycle tabs; do not merge approval states.
- Reorder key columns to emphasize AFE number, well, rig, scope, current status, value/currency, last modified, owner and next permitted action.
- Clarify **draft / submitted / under review / approved / rejected / SOW-adjusted** using actual backend status vocabulary; never create invented states in UI.
- Provide status-based queue views (`My drafts`, `Needs my attention`, `All allowed`) only where backend assignment semantics support them.
- Show status provenance on hover/inspect and in a detail panel without showing sensitive information to unauthorized users.
- Make the difference between **saved base AFE** and **latest approved SOW adjustment** visually explicit; do not silently treat both as the same record.
- Provide safe quick actions, but require the exact same confirmation/remarks logic as existing full editor.

**Acceptance:** A user can identify an incomplete AFE, understand why it cannot advance and navigate to the exact missing cost line; a reviewer sees only allowed actions.

### 7.3 AFE Estimate — `AfeEstimate.tsx` — **P0**

**Observed:** Large editor, services/consumables/tangibles grids, scope and currency details, preview and saved estimate, SOW changes, print, status action controls, unsaved changes guard.

**Redesign as a financial engineering workbench:**

- A compact sticky (not obscuring) context summary: **AFE code, well/rig, drilling or completion scope, estimate version/status, standard currency, dirty/saved state**.
- A stable page layout: **Estimate Summary** → **Well Plan and Scope** → **Services** → **Consumables** → **Tangibles** → **Validation/Preview** → **Approval/Print**. Use anchors or local in-page navigation while preserving current data shape and scroll position.
- Above each grid, show section subtotal, incomplete rows, conflicts, and a meaningful add/import/apply-set action.
- Use a *rate breakdown* side-panel for pricing basis, quantity/day rules, standard currency conversion and warnings; preserve the source field and backend calculation.
- Show the delta between current unsaved preview and the last saved estimate, clearly labeled **preview**.
- Build a validation rail with links to the exact row/field and messages such as missing rate, unsupported scope, missing vendor or incompatible currency (only if those errors truly exist).
- Keep SOW adjustments separate from approved base estimate and clearly distinguish original vs effective values.
- Preserve print preview, existing status restrictions and the “save before print/submit” rule.

**Acceptance:** Incomplete line items can be discovered and corrected without scanning three long tables; no change to computed amount, approval state or print totals; dirty state survives safe edits and navigation warning tests.

### 7.4 Daily Cost Register — `DailyCostManagement.tsx` — **P0**

**Observed:** Existing list-focused register, rig/well scopes, status and dates, tabs, create and opening daily sheets, printed/exportable records.

- Respect `docs/daily-cost-management.md`: **do not** add portfolio KPI cards or workspace-wide charts to the list-only register; these belong in the dashboard/analysis pages.
- Put scope filter and actions above the main grid; explain how **Daily total** and **Cumulative to date** are calculated and why a row can differ from an analysis total.
- Distinguish drafts, submitted, approved and deleted records as actual backend supports; add filtering and a label for draft inclusion where reporting permits it.
- Make `New daily sheet` a guided, minimal decision: well → configured scope → compatible saved AFE → date; show validation early, not after an empty form.
- Preserve well-specific history, copy-from-previous logic, and print flows.

**Acceptance:** Users identify the latest editable sheet for a well, create a new valid sheet and print the correct saved sheet without switching to a different well inadvertently.

### 7.5 Daily Cost Sheet — `DailyCostSheet.tsx` — **P0, highest editorial effort**

**Observed:** Multi-category grids for Services, Consumables, Tangibles, Other Expenses; progress, rate/AFE comparisons, daily/cumulative summary, NPT/UPA, preview, copy previous day, import, line selection, save, submit and print.

**Redesign:**

1. Sticky, compact record band: day/date, rig, well, AFE, scope, lifecycle state, preview/dirty state and author.
2. A **daily financial summary** clearly separates *cost on this date* from *cumulative to date* and *adjusted AFE remaining*. Include labels explaining NPT/UPA and other expenses; no implicit cross-currency total.
3. A **step-free tab/anchor structure** for `Progress`, `Services`, `Consumables`, `Tangibles`, `Other Expenses`, `Review/Submit`. This is **in-page navigation**, not a forced wizard that hides details needed by cost controllers.
4. Row editors with concise field groups; show rate source, quantity unit, scope and AFE match directly with each row.
5. A single persistently visible **validation/action summary**: `N unsaved changes`, `N blocking errors`, `Save draft`, `Preview`, `Submit`, `Print saved`. Buttons gate correctly by status and permission.
6. Side-by-side **Daily vs Cumulative** view where space permits, stacking on smaller screens.
7. Differentiate **actuals entered today** from **historical/reconciled** data and from **unsaved preview** using text, timestamps and context—not color alone.
8. Make dangerous delete/copy/replace operations obvious and undoable when supported; otherwise confirm before mutation.
9. Keep AFE standard currency and locked rate descriptions visible; do not enable arbitrary post-approval edits.
10. Preserve printed daily/well report structure defined in `docs/daily-cost-management.md`, including drilling/completion scopes, depths, time positions and section reports.

**Acceptance:** User can complete a typical daily-cost entry with keyboard, see pending validation, compare with the prior day, save, print, and submit without accidental context loss; exact daily/cumulative totals match existing backend.

### 7.6 Well Cost Analysis and Well-wise Comparison — **P0/P1**

**Observed:** `DailyCostAnalysis.tsx` requires a well, shows AFE planned/actual, other expenses, average/day, NPT/UPA, reconciled mud variants, date selectors and factor tables. Well comparisons live in Reports.

- Explicitly show **selected well** and the effective AFE scope; do not auto-select first well or display a deceptively aggregated multi-well figure.
- Comparative visuals: `AFE planned → SOW adjusted → actual → remaining` (waterfall-style only if backend semantics support it), cumulative actual over dates, breakdown by service/section/phase/vendor/AFE and NPT/UPA.
- **Cost vs depth** chart: numeric depth axis (metres), actual cumulative cost and selected AFE planned relationship where those fields truly exist; do **not** sum depths or invent intermediate planned depth points.
- Reconciled mud costs: label raw actual vs reconciliation-adjusted comparison; document when raw totals remain the accounting source of truth.
- Provide click-through source registers with rig/well/date/AFE scope encoded safely.
- Show percentage denominators and edge cases (zero AFE, multiple AFEs, missing rates, incompatible currencies).

**Acceptance:** Every variance, average/day and NPT/UPA total can be reconciled by a named source table or drill-down; mixed currency combinations are separated or blocked.

### 7.7 Mud Cost Analysis — `MudCostAnalysis.tsx` — **P1**

- Preserve existing tabs `Daily Entries`, `Material Balance`, `Reconciliation`.
- Keep **well + section** highly visible; prevent a user mistaking one section's stock for another's.
- Material balance: accessible opening/receipts/consumption/losses/closing summary with movement table and warnings when entries are incomplete.
- Reconciliation: paired **recorded actual mud chemicals cost** versus **reconciled mud cost**, explicit WBM/non-WBM assumptions and Cost/BBL latest basis as present in API.
- Small multiple section trends or layered charts only after unit/currency compatibility review; never mix bbl, litres and currency on unlabeled axes.
- Clearly show calculation timestamp, period boundaries and the reason for any reconciliation delta.

**Acceptance:** A reviewer can explain the reconciliation difference and trace it to source daily sheets and stock movement for a specific section and date range.

### 7.8 Fuel / LIH / NDT — specialist register UX — **P1**

**Fuel (`FuelCostRegister.tsx`):** Rig and date persistent context; material balance, company-wise allocation, physical stock and rig-saving distinction; warn on negative stock or suspicious entries only if backend validation supports it. Provide separate clear **litres**, **money**, and **company** breakdowns.

**LIH (`LihCostRegister.tsx`):** Worksheet-style entry with predictable keyboard navigation, import preview, line validation, item duplication, remarks, and impact on actual/AFE balance; emphasize that LIH is an unexpected additional charge, not a hidden AFE allowance.

**NDT (`NdtInspectionRegister.tsx`):** Consistent register pattern, state and due/inspection information grounded in existing columns; avoid inventing certification deadlines or compliance rules.

**Acceptance:** Units and financial amounts are unmistakable; recorded source movements and category allocations are unchanged.

### 7.9 Well planning / rig management — **P1**

- Existing `Wells.tsx` distinguishes **Drilling** and **Completion** scopes and scoped well plan/configuration. Make this differentiation visually explicit across the register, planning dialogs, sub-activities and cost filters.
- Present well lifecycle as *a linked operational hierarchy*: Block → Rig → Well → Scope → Section/Phase → Sub-activity → AFE → Daily Cost (relationship view, not a new database schema).
- For `WellConfigurationDialog` and plan adjustment controls, provide hierarchical planned days/depth totals, scope dependency warnings, and validation before applying changes.
- In `WellSubActivities`, distinguish Planned, NPT and UPA context by grouping and labeling; preserve current backend definitions.
- Preserve separate scoped deletion/restoration and the dependency behavior of drilling/completion sibling scopes.

**Acceptance:** A planner cannot mistake the completion plan for drilling, and can reach related AFE/daily records without losing well context.

### 7.10 Master Data / vendor / PO-SO document UX — **P1**

- Standardize header/filters/actions across UOM, currency, phases, hole sections, activities, services, vendors, orders, consumables and tangible catalogs.
- **Services:** preserve service reporting groups, vendor/provider category and provider type; organize filter controls to match the six groups without obscuring bulk reclassification.
- **Vendors:** expose status (active, inactive, blocked), type, linked services/orders and reason for blocked actions.
- **PO/SO Orders:** **do not invent order prices**: README specifies documents only, no stored order values. Show original revision and amendment chronology, mandatory reason, latest revision label, files, restore and checksum/duplicate handling.
- **Currency:** default workspace currency consistently preselected and visually identified; avoid passive UI changes to the default without authorized action.
- Show deleted entries distinctly from active catalog and provide dependency-aware recovery.
- Where route `Tangibles.tsx`/`Consumables.tsx` is currently thin or redirects to another catalog, first confirm actual mounted behavior before redesigning it as a standalone page.

**Acceptance:** Every catalog follows the same table/filter/dialog rules and communicates the impact of vendor/service/PO dependencies before changes.

### 7.11 Reporting catalog and Report Designer — **P1**

**Observed:** `ReportDesigner.tsx` already implements an authored step-based model including source table, row arrangement, columns, matrix layout, grouping/totals, built-in and runtime filters, audience and preview.

- Recast these existing steps as a readable horizontal/vertical progress rail, without modifying report schema: **Identity & Source → Rows → Fields → Matrix → Groups/Totals → Filters → Audience → Preview/Publish**.
- Explain source fields in plain business language, with examples and unit/currency metadata.
- Put a live read-only report preview alongside settings on large screens; on narrow screens use preview tab. Debounce refresh or explicit preview button to avoid costly requests.
- Show completeness errors **by step** and link to the failing control; avoid generic “report invalid”.
- Clearly distinguish **draft**, **preview**, **published**, and **saved/last run** only where backend states exist.
- In built-in reports use consistent filter bars, totals, print/export controls and provenance; ensure A4 landscape/portrait respects each report specification, not a blanket redesign.
- For NPT/UPA, service-wise, vendor-wise, chemicals, bits and tangibles reports, use the *same analytic grammar*: identify population, unit, currency, date bounds, drill-down and export.

**Acceptance:** A user builds a report with field/filter/aggregation context clearly understood and can reproduce the output using the same saved parameters.

### 7.12 Tasks / Notifications / Security / Audit / Backup — **P1/P2**

- **Tasks:** current queue supports filtering, claiming, completion, comments/events and bulk actions. Improve triage with urgency/owner/due structure and safe action placement; keep state semantics unchanged.
- **Notifications:** severity, unread/read, announcements and recall remain; notifications must link to an authorized destination and never reveal hidden record detail in tooltips.
- **Security Center:** separate recovery queue from account register; preserve action-specific permissions (`security:read`, `security:password-reset`, `security:unlock`). Display why an action is disabled without disclosing private data.
- **Audit Log:** readable actor/action/object/time sequence, with evidence/export for authorized staff; no edit affordance.
- **Database Browser:** clearly read-only administrative tool, sensitive credential/session columns omitted at API level.
- **Backup & Recovery:** distinguish **backup created**, **checksum verified**, **restore requested**, **restore approved**, **dry-run validated**, **restore executed**; preserve two-person approval and typed confirmation. Never make execution a one-click shortcut.

**Acceptance:** High-risk actions require intentional confirmation, role gating and auditable feedback; no UX polish weakens safeguards.

---

## 8. Analytics and visual semantics specification

### 8.1 Chart selection matrix

| Business question | Best visual | X / Y definition | Required interpretation |
|---|---|---|---|
| How much of the AFE is spent? | Bullet/comparison bar + table | Original AFE / approved adjusted AFE / actual, by **single currency** | Identify source and SOW revision |
| Which well drives overspend? | Ranked horizontal bars | Well vs variance amount/% | Include sign, threshold and denominator |
| Is spending accelerating? | Daily bars + cumulative line | Date vs daily/cumulative actual | Do not sum daily and cumulative lines |
| Are days ahead or behind plan? | Paired bars / dot plot | Planned vs actual days per well/scope | Distinguish elapsed, productive, NPT and UPA |
| What is cost progress against depth? | Line/scatter, optional dual panel | Measured depth (m) vs cumulative cost | Depth is not additive; use correct depth basis |
| Where is cost concentrated? | Sorted bars / treemap only if useful | Group/service/vendor vs financial amount | Expose group subtotals and long-tail table |
| Which sections consume mud? | Flow/balance summary + grid | Opening + receipts − usage/losses = closing | Display bbl/UOM clearly |
| What is the NPT/UPA driver? | Stacked duration/cost comparison | Categorized activity/responsible party | Time and money in separate axes/panels |
| Is physical fuel stock consistent? | Movement timeline | Opening/receipts/use/closing by day/rig | Litres distinct from financial allocations |
| Which tasks need action? | Queue with counts by state | Assigned/due/priority | Not a decorative donut chart |

### 8.2 Always-on chart rules

- Every axis label has **unit**: USD, NGN, bbl, litres, days, metres, percentage, count.
- Currency normalization and conversion policy explicitly stated. Preserve source currency where appropriate.
- Zero baseline on bars unless a clearly documented exception is justified; avoid misleading truncation.
- Separate planned, actual and adjusted AFE series with persistent visual assignment; never swap color mapping between pages.
- Chart interactions support pointer, keyboard or adjacent tabular alternative; essential data never requires hover alone.
- Provide `View underlying records`, `View data table`, `Reset chart selection`, tooltips with full numeric precision.
- Show explicit empty, loading, permission and stale-data states. Charts must not imply real-time telemetry unless actual refresh/data support it.
- Where useful, show threshold reference with a label, not red-only highlights.
- Legends should be clickable only when hidden series and calculated totals stay understandable.
- No arbitrary 3D charts, over-animated gauges, pie chart overload or decorative gradients.

### 8.3 Financial correctness examples

- **AFE variance:** define whether the chosen comparison is `actual − approved-effective AFE` or `effective AFE − actual`; use a single definition per chart, show a legend or note. Do not swap sign based on a visual preference.
- **Cost/m:** only calculate if depth increment and source costs are within the selected well/scope and period; explicitly mark no-progress and negative/reversal depth cases.
- **Cost/BBL:** derive only from existing mud reconciliation definitions; display section, WBM/OBM context, cumulative period and source.
- **NPT/UPA:** distinguish time-based and monetary exposure, clearly explain deduplicated hours or adopted API method.
- **SOW:** show original, latest **approved** adjustment, effective budget and actual as separate fields.
- **Multi-AFE / multi-currency:** partition, convert by established auditable policy, or refuse aggregation; never combine as plain numeric addition.

---

## 9. Interaction flows / user journeys to prototype and test

| Journey | Starting point | Desired completion | Important edge cases |
|---|---|---|---|
| J01 | Login | Land in authorized relevant workspace | Missing workspace admin, expired password, low-permission account |
| J02 | Dashboard | Identify overspent well → open underlying record | Mixed currency, deleted well, zero AFE |
| J03 | Wells | Open drilling/completion scope → adjust plan → return | Sibling scope independence, unsaved configuration |
| J04 | AFE register | Create or open AFE → price lines → preview → save | Missing services/rates, scope conflicts, no default currency |
| J05 | AFE review | Find pending estimate → inspect breakdown → approve/reject | Role denied, stale state, mandatory remarks |
| J06 | Daily register | Select rig/well/date → new sheet → enter costs → save | No AFE, prior-day carry-over, no configured scope |
| J07 | Daily sheet | Copy prior day/reusable set → edit → preview → submit | Rate source changed, dirty fields, failed save |
| J08 | Mud | Enter movements → review balance → reconcile | Section change, missing opening stock, zero usage |
| J09 | Fuel | Choose rig/date → stock/allocation → save → review | Negative balance, unit mismatch, missing vendor |
| J10 | PO/SO | Open order → inspect amendment sequence → download document | Missing file, blocked vendor, duplicate attachment |
| J11 | Report builder | Configure fields/filters → preview → publish | Unsupported aggregation, field permission, empty results |
| J12 | User admin | Assign role → validate capability changes | Privilege escalation, stale assignment |
| J13 | Backup | Create backup → verify → request restore → approve + dry-run | Two-person gate, failed verification, execution confirmation |

For each journey, record **current baseline time/steps, mistakes, pause points and subjective ease**, then prototype and re-measure. Target fewer unnecessary actions; do not optimize by removing essential approval safeguards.

---

## 10. Technical implementation architecture

### 10.1 Existing front-end should remain the core

```text
frontend/src/
├── App.tsx                          # existing routes/guards; avoid route churn
├── components/
│   ├── Layout.tsx                   # existing permission-aware shell
│   ├── Common.tsx                   # PageHeading/Tag/dialogs/unsaved guard
│   ├── DataTable.tsx                # shared AG Grid Community
│   └── ...                          # current domain components
├── context/                         # auth and theme, retain
├── designSystem.ts                  # existing token source
├── theme.ts                         # existing MUI composition
├── styles.css                       # existing CSS token mirror/print rules
├── lib/                             # typed API/domain clients, retain
└── pages/                           # existing route components
```

### 10.2 Suggested additions (proposals; don't create until corresponding task)

```text
frontend/src/
├── components/ui/
│   ├── BreadcrumbTrail.tsx
│   ├── PageActionBar.tsx
│   ├── ScopeContextBar.tsx
│   ├── FinancialValue.tsx
│   ├── SavingState.tsx
│   ├── ValidationSummary.tsx
│   ├── DatasetState.tsx
│   ├── DataGridToolbar.tsx
│   ├── ChartPanel.tsx
│   └── RecordDetailPanel.tsx
├── components/analytics/
│   ├── BudgetActualChart.tsx
│   ├── CumulativeCostChart.tsx
│   ├── WellProgressChart.tsx
│   └── CostBreakdownChart.tsx
├── features/navigation/
│   ├── navConfig.ts                  # extracted only if useful; permission contract unchanged
│   └── breadcrumbConfig.ts
├── features/context/
│   └── useWellScopeContext.ts        # compose with existing lib/activeScope.ts
├── features/formatting/
│   └── financialDisplay.ts
└── tests/ux/                         # Playwright tests if approved/added
```

Do not introduce component wrappers with no proven repetition. Before extracting an abstraction, identify 2–3 existing usages and a demonstrated improvement.

### 10.3 State and URL rules

- The selected **well/AFE/scope/date** must not be duplicated in disconnected state holders.
- Use the route path for record identity; use query string for relevant, shareable filters; use local component state for unsaved form edits.
- Reuse `lib/activeScope.ts` where it already handles persistent scope. Any new context should *compose with it* and not silently replace it.
- Save views/pins only after deciding privacy, tenant-aware keying and default resets. Never persist sensitive server responses in browser storage.
- Use typed `lib/*` API methods; do not fetch raw endpoints within each new UI component.
- Preserve existing API concurrency and cancel stale requests on context switches to avoid showing previous-well data.

### 10.4 Performance expectations and verification

- Keep route-level lazy loading (already present in `App.tsx`).
- Memoize heavy ECharts options and grid column definitions; isolate live clock/refresh UI so the entire dashboard doesn't rerender.
- Use debounce for user-entered search only where it reduces work; explicit Apply for expensive server filters.
- Support 100-row grid pages without noticeable lag in supported office hardware, and profile real 1k/10k record sets if the API permits such volumes.
- Prevent expensive repeated calls when drilling from chart to record and back; use explicit caching strategy only after reviewing API sensitivity/invalidation.
- Avoid pulling a second full design framework or charts package to solve problems current MUI/ECharts can handle.
- Audit existing `#root` zoom, typography at 100% and reduced-motion accessibility. A zoom removal is a separate controlled RFC, not a cosmetic tweak.

### 10.5 Backend / data contract change policy

**UI-only backlog first.** Classify each ticket as:

- `UI-ONLY`: hierarchy, reuse, styling via tokens, accessible labels, layout, navigation, existing API data visualization.
- `UI+API`: global search, saved personal views stored server-side, new action queue aggregates, new calculated analytics, provenance or audit details not currently returned.
- `BACKEND-RULE`: changes to AFE accounting, conversion, status, reconciliation, scope and permissions — **out of scope** for this UX program without a signed functional design.

Any `UI+API` request must define endpoint contract, read/write capability, tenant scope, performance/pagination, audit requirement, schema migration, backward compatibility, API and UI tests before work starts.

---

## 11. Agent and skill workflow for Arena.ai / other AI agents

### 11.1 The actual project already has agents

The repo already contains `.agent/skills/ui-design.md`, `.agent/skills/feature.md`, `.agent/skills/review.md`, `.agent/skills/rbac.md`, `AGENTS.md`, `.agent/memory/design-system.md` and the reference list `docs/UI_skills`. **Do not reinstall an unrelated framework or duplicate conflicting instructions.** Treat `AGENTS.md` and standing conventions as controlling rules.

**Suggested outside review resources** (review licenses/contents before adoption):

- [Anthropic frontend-design skill](https://github.com/anthropics/skills/tree/main/skills/frontend-design) — design critique and high-quality visual direction.
- [UI/UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) — layout, hierarchy, design-system reasoning and interaction suggestions.
- [Impeccable](https://github.com/pbakaus/impeccable) — critique/deslop/polish workflow.
- [Vercel agent skills](https://github.com/vercel-labs/agent-skills) — web design review and React performance guidance.
- [Playwright](https://playwright.dev/) — cross-browser screenshots and interaction/regression testing.
- [MUI](https://mui.com/) and [AG Grid](https://www.ag-grid.com/) — existing component technologies.

Skills are prompts/instructions, not a security or testing substitute. Verify Arena.ai actually reads the chosen location and `AGENTS.md`; if not, include these file paths in the task prompt. Do not execute untrusted skill scripts or repository installation hooks without review.

### 11.2 Recommended specialized agent roles

| Agent | Input | Must produce | Hard boundary |
|---|---|---|---|
| UX Product Architect | Route and current workflow | IA, task flow, wireframe, failure states, priority | No unauthorized functional changes |
| Enterprise Visual Designer | Tokens + screenshots | Clean desktop/mobile layouts, visual hierarchy, typography | No gradient/glass/brand drift |
| React + MUI UI Engineer | Approved spec + source | Minimal TSX/CSS changes, shared components, tests | Preserve MUI / AG Grid Community stack |
| Financial Visualization Specialist | API response/meaning | Reconciled charts, unit/currency labels, source links | No invented totals or formulas |
| Interaction & Accessibility Reviewer | Running UI + task script | Keyboard/responsive/contrast observations and fixes | Cannot drop required validation |
| Regression and RBAC Reviewer | Diff + tests | Changed-route matrix, permission and data-integrity report | Must flag risky changes |

### 11.3 Required agent execution protocol

```text
1. Read: AGENTS.md; .agent/README.md; .agent/memory/project.md;
   .agent/memory/design-system.md; .agent/skills/ui-design.md;
   this UI/UX master plan.
2. Inspect: target page and its related API client, shared components,
   guards, route, backend endpoint and relevant tests.
3. Write an audit: current UX, primary user task, top 3 bottlenecks,
   relevant permission/currency/scope/unsaved-state constraints.
4. Propose wireframe and scope as UI-ONLY / UI+API / BACKEND-RULE.
5. Obtain design approval for substantive IA/workflow changes.
6. Implement one small vertical slice on a feature branch.
7. Validate both themes, 1440/1024/768/390px, keyboard and print.
8. Run frontend build, UI design checks, security tests and related
   backend tests. Report evidence, regressions and screenshots.
9. Update documentation/agent memory only with approved durable changes.
10. Open a PR; no direct production deploy / silent migration.
```

### 11.4 Copyable agent prompt for the first implementation ticket

> You are the lead enterprise SaaS UI/UX engineer for WellCostIQ. Before coding, read `AGENTS.md`, `.agent/memory/project.md`, `.agent/memory/design-system.md`, `.agent/skills/ui-design.md` and `docs/WellCostingPro_UI_UX_Implementation_Master_Plan.md`. Inspect `frontend/src/components/Layout.tsx`, `frontend/src/App.tsx`, the relevant page, `DataTable.tsx`, current API clients and tests. Improve one clearly scoped UX issue. Preserve all routes, permissions, tenant isolation, default currency, pricing formulas, data entry behavior, imports/exports, print outputs and unsaved-change safeguards. Reuse tokens and existing components. First return a route/component impact map, UI-only vs API dependencies, proposed before/after wireframe and test plan. Then implement only the approved slice. Verify light/dark, keyboard, desktop/mobile, build/UI checks and regression tests. Provide screenshots and a concise change log with rollback instructions.

---

## 12. Phased delivery / milestone plan

**Planning estimates below are relative effort ranges**, not promises. They assume one experienced frontend engineer with periodic domain-user review and existing test environments. Re-estimate after live interface audit. Use PR-sized work, not a big-bang redesign.

| Phase | Target | Key outputs | Indicative effort | Exit gate |
|---|---|---|---|---|
| **0** | Discovery & baseline | Screenshots, role/route inventory, task metrics, design audit, risky rules matrix | 3–5 engineer-days | Owners approve direction and no-regression list |
| **1** | Shell & interaction foundations | Breadcrumbs, page contract, context semantics, table/form/feedback standards | 5–9 engineer-days | Existing routes/guards/import/export/print unchanged |
| **2** | Operations dashboard | Financial/operations hierarchy, drill-through, chart conventions | 5–8 engineer-days | Chart reconciliation and representative manager usability review |
| **3** | AFE workflows | AFE register/portfolio and estimate editor polish | 7–12 engineer-days | Estimate amount, approval, SOW and print regression pass |
| **4** | Daily costing | Daily list, sheet workbench, analysis refinements | 9–15 engineer-days | Daily/cumulative and unsaved-state regression pass |
| **5** | Specialist costing & well plan | Mud/fuel/LIH/NDT, rigs/wells/sub-activity UI | 8–14 engineer-days | Stock/units/scope checks, edge-case validation |
| **6** | Master data & reporting | Master data, PO/SO revision UX, report designer and reports | 8–14 engineer-days | Import/export, revision, report/print fidelity pass |
| **7** | Administration + polish | Tasks, notifications, security, audit, backup, a11y/perf | 6–10 engineer-days | RBAC/accessibility/restore two-person gates pass |

Phases 3 and 4 are most valuable for daily operations; phases can run in overlapping streams only if shared component contracts are stabilized first.

### 12.1 Priority legend

- **P0:** Delivery blocker or high-frequency work. Do first.
- **P1:** Important cross-module experience improvement; do after shared component stabilization.
- **P2:** Optional productivity and polish; implement only if evidence supports value.

### 12.2 Recommended first 15 PR-sized tickets

| Ticket | Priority | Scope | Concrete deliverable | Dependencies |
|---|---|---|---|---|
| UX-001 | P0 | Baseline | Route-to-role audit, screenshots and reference task scripts | None |
| UX-002 | P0 | Tokens | Token/contrast/type audit; fix only confirmed inconsistencies | UX-001 |
| UX-003 | P0 | Page shell | Breadcrumbs and uniform action overflow without breaking shell | UX-001 |
| UX-004 | P0 | Feedback | Reusable empty/loading/error/permission states | UX-002 |
| UX-005 | P0 | Context | Rig/well/scope/AFE context prototype using `activeScope.ts` | UX-003 |
| UX-006 | P0 | Data grid | Filter summary, reset, money alignment and row-count states | UX-002/004 |
| UX-007 | P0 | Financial display | Currency/units/precision and null/zero shared display rules | UX-002 |
| UX-008 | P0 | Dashboard | KPI and chart hierarchy; drill-down to existing routes | UX-005/007 |
| UX-009 | P0 | AFE register | Status/approval workflow clarity, accessible action cells | UX-006 |
| UX-010 | P0 | AFE estimate | Incomplete-line index, section summary, save/preview rail | UX-005/006/007 |
| UX-011 | P0 | Daily register | Context/filter improvements on list-first layout | UX-005/006 |
| UX-012 | P0 | Daily sheet | Editor information architecture, validation and action visibility | UX-005/007/010 |
| UX-013 | P0 | Well analysis | Well selection, source-traceable financial chart, table fallback | UX-008/012 |
| UX-014 | P1 | Specialist | Mud material balance/reconciliation clarity | UX-007/013 |
| UX-015 | P1 | Reports | Designer progress/field explanation/preview/validation | UX-004/007 |

Every PR should include **before/after screenshots, impact inventory, risk classification, tests and review notes**.

---

## 13. Quality gates and detailed acceptance criteria

### 13.1 Release-blocking gates

| Category | Required result |
|---|---|
| Build | `cd frontend && npm run build` passes; no TypeScript errors |
| UI contract | Existing `.agent/tools/ui-check.jsx` check passes; expand tests if changing tokens/dialogs/grid |
| Backend | Relevant `backend/tests/*` pass; use PostgreSQL test environment for DB-sensitive behavior |
| Access | Authorized and unauthorized users verified against changed paths and APIs |
| Finance | AFE, adjusted AFE, actual, daily/cumulative, cost/BBL unchanged for test fixtures |
| Currency | No mixed-currency totals; default currency and displayed unit supported everywhere |
| Workflow | Save / draft / preview / submit / approve / print / restore behave as before |
| Imports/exports | CSV/XLSX/PDF and print reports still contain correct records, columns and totals |
| Unsaved changes | Dialog cancel, route change, browser back/reload, cross-record change tested |
| Accessibility | Logical keyboard order, visible focus, labels, error announcements, WCAG 2.2 AA target |
| Layout | No page-level horizontal overflow at 1440, 1024, 768 and 390px; scroll remains inside appropriate grids |
| Theme | Light and dark screens checked including overlays and native controls |
| Browser | Current supported Edge and Chrome validated; reduced-motion check |
| Safety | Backup/restore approval and typed confirmation preserved; no hidden background destructive actions |

### 13.2 Additional automated tests to propose

- Playwright smoke by major route and role (mocked data and real test environment as appropriate).
- Visual regression screenshots: Operations Dashboard, AFE Estimate, Daily Cost Sheet, Mud Reconciliation, Report Designer, Security Center, Backup & Recovery—**both themes**.
- Keyboard tests: sidebar open/collapse, grid filter panel, dialog focus trap, save/submit, date selectors, report designer stepper.
- No-authorization tests: direct URL, search result, cached tab, hidden actions, low-permission security view.
- Data-integrity fixtures: multi-currency, zero AFE, negative balance, missing rate, deleted record, draft versus approved, WBM/OBM, drilling/completion sibling scopes.
- Navigation state tests: filter-to-detail-to-back, browser back/forward, deep link open, existing unsaved guard.
- Export/print snapshot tests using known business figures and report sections, not merely file existence.

### 13.3 User experience metrics (proposed targets to validate)

| Measure | Baseline method | Target direction |
|---|---|---|
| Daily-cost completion time | 5 users complete real representative sheet | Reduce unnecessary clicks/time by ≥20% **if baseline supports it** |
| AFE missing-field discovery | Record time to find intentionally incomplete lines | User identifies blockers within 30 seconds in test task |
| Navigation efficiency | Count steps to open a given well's sheet/AFE | ≤3 purposeful transitions from active scoped workflow |
| Financial chart trust | Ask user to explain three totals and their provenance | ≥90% correct interpretation in moderated study |
| Task success | Participants complete 12 defined journeys | ≥95% completion without assistance for trained users |
| Accessibility | Automated + manual keyboard/contrast checks | No critical WCAG 2.2 AA violations |
| Visual consistency | Component and screenshot review | No repeated bespoke styles for an established shared pattern |

These are **planning targets**, not empirical findings. Confirm with actual users and realistic data volumes.

---

## 14. Risks, trade-offs and decisions requiring approval

| Topic | Risk | Recommendation |
|---|---|---|
| Whole-app redesign | Breakage and poor adoption | Roll out page by page; keep routes and existing module behavior |
| Global search | Tenant data leakage, inefficient all-data fetch | Build only after scoped, permission-safe search API and usability need |
| AG Grid Premium / MUI X | License cost and implementation churn | Keep AG Grid Community; approve upgrades against concrete requirements |
| Root zoom 0.875 | Accessibility and overlay alignment challenges | Measure first; plan separate migration RFC if changing |
| Sticky headers | Hide tabbed editor controls or capture too much viewport | Prototype on 768/1024 and zoomed UI; guard viewport |
| Chart drill-down | Wrong detail context or financial misinterpretation | Use backend IDs and labeled filter provenance; test URL + return |
| Saved views | Hidden filters and stale scope | Show selected preset, visible reset, tenant/user-specific storage |
| Autosave | Partial costing state and surprise workflow changes | Do not add without transactional API design and explicit approval |
| Drag/drop editing | Hard to audit and poor keyboard parity | Prefer explicit controls; only add if task study proves value |
| Report re-layout | Print/export mismatch | Make print preview/QA independent release gate |
| Realtime-looking dashboard | False impression of live cost data | Display refresh timestamp and manual/auto refresh source |
| UI-only status tags | Misleading workflow state | Use exact backend state names and capability guards |
| Overloaded dashboards | Slow render, poor executive comprehension | Show top 4–8 significant signals, progressive drill-down |
| AI agent skill installation | Conflicting instructions / unsafe scripts | Adopt skill guidance selectively under `AGENTS.md` |

### Explicit product decisions to collect *during implementation planning*

1. Approve new navigation wording/grouping (retaining current URL paths).
2. Approve whether context selection is per-page or global for each module.
3. Decide if user-specific saved views and pinned records merit backend persistence.
4. Approve financial KPI definitions, SOW comparison basis and chart annotations.
5. Decide if a paid table/chart feature is worth licensing; no assumption by default.
6. Approve visual changes to print layouts separately from on-screen UX changes.
7. Decide whether `#root` zoom remains; treat it as a dedicated accessibility/performance decision.

---

## 15. Branching, rollout and rollback

### 15.1 Safe integration approach

- Create a feature branch such as `uiux/phase-1-shell-foundations` from audited current `main`.
- Add this plan to `docs/WellCostingPro_UI_UX_Implementation_Master_Plan.md` in the project **only after the document is reviewed and approved**.
- Do not modify production data or run migrations for purely visual work.
- Use feature flags for material navigation/editor changes only where justified; keep old component fallbacks until validated.
- Submit one reviewable PR per ticket; link screenshots and test outcomes.
- Merge only after CI/regression and business-owner acceptance; deploy to test VM before office-network production.
- Preserve safe database backups and existing HTTPS/security controls; do not change Docker networking as part of a UI-only sprint.

### 15.2 Existing rollback behavior

Repo docs describe a previous design-layer rollback (`make ui-rollback`) to restore the pre-design-layer tagged appearance. **That is not a universal feature-by-feature rollback plan** and could discard the new work. For this program, use normal PR/commit revert, UI feature flags and release tags. Verify intended rollback behavior before touching existing generated assets or running broad rollback commands.

---

## 16. Immediate implementation checklist (first two sprints)

### Sprint A — evidence, system and shell

- [ ] Verify current branch/commit and all existing routes on the running app.
- [ ] Capture authenticated screenshots: light/dark, 1440, 1024, 768, 390px; use safe synthetic/test data.
- [ ] Create route-to-permission and route-to-API inventory with current `App.tsx` guards.
- [ ] Observe five representative workflows with end users; record task time and errors.
- [ ] Audit tokens against `designSystem.ts`, `theme.ts`, `styles.css`; do not introduce a competing design system.
- [ ] Design new breadcrumb/action-area rules and mock up shell at desktop and mobile widths.
- [ ] Implement tested shared empty/loading/error and financial formatting behavior.
- [ ] Review global zoom concerns and document measured evidence.
- [ ] Run all required visual/security regression gates.

### Sprint B — first visible business value

- [ ] Deliver Operations Dashboard revised hierarchy using existing ECharts and live API schema.
- [ ] Implement traceable well/AFE drill-down without changing data aggregation.
- [ ] Improve AFE Register queue/status/action comprehensibility.
- [ ] Prototype AFE Estimate validation rail and section summary with at least one real AFE fixture.
- [ ] Confirm Daily Cost Sheet page architecture and test no-unsaved-loss behavior.
- [ ] Collect user feedback and record revised acceptance criteria before broader rollout.

---

## 17. Definition of Done for each page

A page is **done** only when:

- [ ] Its primary user job and expected next action are obvious.
- [ ] It fits the approved navy enterprise design system in both themes.
- [ ] Title, breadcrumbs, selected rig/well/scope/date/currency are correct and accessible where relevant.
- [ ] All status, money, unit and calculated metrics are semantically accurate.
- [ ] All table, filter, import, export and print affordances continue to work.
- [ ] Dialog and editor behaviors preserve unsaved data safeguards.
- [ ] Keyboard, focus, labels, reduced-motion and responsive layout have been manually checked.
- [ ] Error/empty/loading/stale/unauthorized states have actionable feedback.
- [ ] No hidden permission, tenant, accounting or workflow regression is introduced.
- [ ] The related tests and visual evidence are attached to a PR.
- [ ] At least one representative domain user approves the updated workflow.

---

## 18. Source links and future audit pointers

**Repository and authority**

- Main repo: https://github.com/praveen-christuraj/WellCostingPro
- GitHub snapshot: https://github.com/praveen-christuraj/WellCostingPro/tree/b365d26a49e4c5bfa5c8889b44d621cb4c1245cd
- README: https://github.com/praveen-christuraj/WellCostingPro/blob/main/README.md
- Agent agreement: https://github.com/praveen-christuraj/WellCostingPro/blob/main/AGENTS.md
- Existing design specification: https://github.com/praveen-christuraj/WellCostingPro/blob/main/.agent/memory/design-system.md
- Existing UI skill: https://github.com/praveen-christuraj/WellCostingPro/blob/main/.agent/skills/ui-design.md
- Durable product rules: https://github.com/praveen-christuraj/WellCostingPro/blob/main/.agent/memory/project.md
- Daily Cost requirements: https://github.com/praveen-christuraj/WellCostingPro/blob/main/docs/daily-cost-management.md

**Key implementation points**

- Routes/guards: `frontend/src/App.tsx`
- Navigation: `frontend/src/components/Layout.tsx`
- Data Grid: `frontend/src/components/DataTable.tsx`
- Common UI: `frontend/src/components/Common.tsx`
- Tokens/theme: `frontend/src/designSystem.ts`, `frontend/src/theme.ts`, `frontend/src/styles.css`
- Dashboard: `frontend/src/pages/BusinessDashboard.tsx`
- AFE: `frontend/src/pages/AfeOverview.tsx`, `AfeManagement.tsx`, `AfeEstimate.tsx`
- Daily: `frontend/src/pages/DailyCostManagement.tsx`, `DailyCostSheet.tsx`, `DailyCostAnalysis.tsx`
- Specialty: `MudCostAnalysis.tsx`, `FuelCostRegister.tsx`, `LihCostRegister.tsx`, `NdtInspectionRegister.tsx`
- Reporting: `frontend/src/pages/Reports.tsx`, `ReportBuilder.tsx`, `ReportDesigner.tsx`, `CustomReportViewer.tsx`, `frontend/src/pages/reports/*`
- Access and recovery: `SecurityCenter.tsx`, `TaskManager.tsx`, `BackupRecovery.tsx`, `AuditLog.tsx`
- Design checks: `.agent/tools/ui-check.jsx`, `Makefile` (`make ui-check`)
- Frontend build: `cd frontend && npm run build`
- Backend tests: `backend/tests/*` (use correct test runtime/container)

---

## 19. Final implementation directive

> **Build an exceptionally clear, fast, polished WellCostIQ workbench by improving current shared infrastructure and the most-used financial workflows first. Preserve existing accounting, scoped drilling/completions logic, AFE review, dirty-state protection, RBAC, reports and deployment safeguards. Let evidence from real end-user tasks—not decorative design trends—determine every subsequent redesign.**

**Recommended first coding PR:** `UX-003 — Breadcrumbs + uniform page action area`, preceded by `UX-001` screen/role audit and `UX-002` token review. This produces a visible, low-risk improvement across the application while protecting the subsequent AFE and Daily Cost transformations.
