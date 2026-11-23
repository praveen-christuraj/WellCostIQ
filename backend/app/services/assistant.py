"""The in-application guide: a curated memory plus deterministic reasoning.

Two things make this assistant useful and safe:

* **A constant memory.** Every workflow, calculation, entry rule and navigation
  path is recorded once, in ``SYSTEM_MEMORY``, and seeded per workspace. Answers
  quote that memory instead of inventing prose, so the same question always
  produces the same, checkable answer and an administrator can read exactly what
  the assistant is allowed to say. Workspaces can add their own memory entries
  (a local approval rule, a cost-code convention) that the assistant cites the
  same way.
* **Answers computed from the workspace's own data, under the caller's
  permissions.** Operational questions ("what is the AFE balance on WELL-01?",
  "which wells have no spud date?") are answered from the same services the
  pages use, with Decimal arithmetic, and a caller who cannot read a module is
  told which capability is missing rather than shown a number.

There is no model call anywhere: the assistant cannot hallucinate a figure or a
route. It is a fast, explainable expert on this application, not a general web
assistant.
"""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.precision import DECIMAL_QUANT
from app.services.operations.guide import answers as operations_answer
from app.models import (
    Afe,
    CementAdditive,
    DailyCostConsumableLine,
    DailyCostEntry,
    DailyCostOtherExpenseLine,
    DailyCostServiceLine,
    DailyCostTangibleLine,
    DrillBit,
    FuelType,
    LihCostEntry,
    LihCostLine,
    MudChemical,
    NdtInspection,
    Service,
    Tangible,
    User,
    Vendor,
    Well,
    WellSubActivity,
)
from app.models.assistant import AssistantConversation, AssistantMemory
from app.schemas.assistant import (
    AssistantAnswer,
    AssistantFact,
    AssistantMemoryIn,
    AssistantMemoryOut,
    AssistantMemoryUpdate,
    AssistantOverview,
    AssistantSource,
    AssistantTable,
)

MONEY = DECIMAL_QUANT
DAYS = DECIMAL_QUANT
TRANSCRIPT_LIMIT = 40

# ---------------------------------------------------------------------------
# The constant memory. Seeded once per workspace; never overwritten.
# ---------------------------------------------------------------------------
SYSTEM_MEMORY: tuple[dict[str, Any], ...] = (
    {
        "memory_key": "workflow-first-well",
        "title": "Start here: set up a well from Master Data to a daily cost sheet",
        "category": "workflow",
        "keywords": "start setup begin first well onboarding order master data rig block configuration",
        "route": "/rig-well/wells",
        "permission": "",
        "sort_order": 10,
        "body": (
            "A well can only be costed after four steps, and each one feeds the next: "
            "Master Data (currencies, UOM, hole sections, phases, activities, vendors, services), "
            "Rig & Well Management (rig, block, well, then the well configuration with its sections, "
            "phases and planned days), the AFE register (create the AFE, build and save the estimate, "
            "then submit/approve it), and finally the Daily Cost register."
        ),
        "steps": (
            "Master Data: add the workspace default currency, hole sections, phases, activities and vendors.\n"
            "Rig & Well: create the rig and block, then the well.\n"
            "Well configuration: add each drilling (and completion) hole section with its phases and planned days.\n"
            "Mark the plan Configured so the well shows as Upcoming and accepts work.\n"
            "AFE: create the AFE for the well, build the estimate, save it, then submit and approve it.\n"
            "Daily Cost: create the first sheet — the first sheet automatically starts the well.\n"
            "Enter the Well Spud Date & Time so actual days count from the real start instant."
        ),
    },
    {
        "memory_key": "calc-actual-days",
        "title": "How actual days are calculated (and why sheets are not days)",
        "category": "calculation",
        "keywords": "actual days duration spud sheet count fractional precision elapsed 13.4",
        "route": "/daily-cost",
        "permission": "daily-cost:read",
        "sort_order": 20,
        "body": (
            "Actual days are elapsed time, not a count of daily cost sheets. The count starts at the "
            "Well Spud Date & Time and ends at the Progress Completed Date & Time once that is entered, "
            "otherwise at the end of the last included cost date, and is reported at three decimals. "
            "A well spudded at 10:00 on 19 October counts 0.583 days on that report. Fourteen sheets "
            "can therefore cover 13.417 days. NPT and UPA days use the same three-decimal basis."
        ),
        "steps": (
            "Open the well in Daily Cost → Well progress and enter the Well Spud Date & Time.\n"
            "Enter the Progress Completed Date & Time when the scope finishes; the count then stops there.\n"
            "Read actual days on the Business Dashboard, the well cost analysis and the printed report."
        ),
    },
    {
        "memory_key": "calc-npt-upa-days",
        "title": "How NPT and UPA days are calculated",
        "category": "calculation",
        "keywords": "npt upa days non productive unplanned hours divided 24 deduplicated",
        "route": "/daily-cost",
        "permission": "daily-cost:read",
        "sort_order": 25,
        "body": (
            "NPT/UPA days are deduplicated operational service hours divided by 24, at three decimals. "
            "Only Day Rate service lines entered in hours count, and simultaneous services repeating the "
            "same allocation are counted once (the greatest hours value per sheet, activity, sub-activity, "
            "section and phase). A cost date where NPT was recorded is not itself a day of NPT."
        ),
        "steps": (
            "Enter the NPT or UPA work as a Day Rate service line with the quantity in hours.\n"
            "Pick the Master Data activity that classifies it (NPT or UPA) and the responsible sub-activity.\n"
            "Mobilization, Demobilization and Fixed Charge lines never count towards duration."
        ),
    },
    {
        "memory_key": "calc-responsible-party",
        "title": "How cost is attributed to a responsible party",
        "category": "calculation",
        "keywords": "responsible party vendor attribution booked exposure npt upa cost provider",
        "route": "/daily-cost/analysis",
        "permission": "daily-cost:read",
        "sort_order": 30,
        "body": (
            "Two different questions are reported side by side. **Booked** cost is what the vendor that "
            "charges the line is paid, whatever the reason for the work — a provider on standby for 24 "
            "hours bills 24 hours. **NPT/UPA exposure** is the cost of the unplanned hours attributed to "
            "the responsible party recorded on the Well Sub-activity. Provider A can therefore be booked "
            "for the full 24 hours while provider B carries the 14 unplanned hours it caused. The two "
            "measures are never added together and the booked column always reconciles with the ledger."
        ),
        "steps": (
            "On the Well Sub-activity, record who is responsible for the work (vendor or named party).\n"
            "On the daily sheet, classify the line through its Master Data activity (Planned, UPA or NPT).\n"
            "Open Well cost analysis → Cost factors → Responsible party to see booked versus exposure."
        ),
    },
    {
        "memory_key": "calc-afe-balance",
        "title": "How the AFE balance and utilisation are calculated",
        "category": "calculation",
        "keywords": "afe balance utilization percentage remaining budget spent",
        "route": "/afe",
        "permission": "afe:read",
        "sort_order": 35,
        "body": (
            "The effective AFE amount is the latest approved SOW-adjusted total when one exists, "
            "otherwise the saved estimate. The AFE balance is the effective amount less the actual cost "
            "(and, where comparisons include it, less the LIH cost). Utilisation is actual cost divided "
            "by the effective amount. Amounts are only added when they share the selected standard "
            "currency; anything excluded is counted and reported."
        ),
        "steps": (
            "Save the estimate so the AFE carries a total.\n"
            "Approve an SOW adjustment when scope genuinely changes; the adjusted total replaces the original.\n"
            "Read the balance on the Business Dashboard or the well cost analysis."
        ),
    },
    {
        "memory_key": "calc-forecast",
        "title": "How the cost forecast is calculated",
        "category": "calculation",
        "keywords": "forecast projection final cost run rate burn projected overrun",
        "route": "/daily-cost/analysis",
        "permission": "daily-cost:read",
        "sort_order": 40,
        "body": (
            "The forecast is cost recorded so far plus the run rate multiplied by the planned days still "
            "ahead. The run rate is total actual cost divided by recorded cost dates (or by exact elapsed "
            "days once a spud instant is entered), and the days ahead are the effective planned days less "
            "elapsed days. It is a warning device, not a new budget: it uses the same ledger as every other "
            "figure on the page."
        ),
        "steps": (
            "Keep the well configuration's planned days current.\n"
            "Enter the Well Spud Date & Time so the run rate is per elapsed day.\n"
            "Open Well cost analysis to see the forecast, its variance and days to budget."
        ),
    },
    {
        "memory_key": "calc-out-of-scope",
        "title": "What counts as an out-of-scope cost",
        "category": "calculation",
        "keywords": "out of scope unbudgeted unplanned cost not in afe estimate other expenses",
        "route": "/daily-cost/analysis",
        "permission": "daily-cost:read",
        "sort_order": 45,
        "body": (
            "Out-of-scope cost is any recorded cost with no AFE allowance behind it, plus other expenses "
            "(LIH, hole problems, third-party claims, penalties and similar), which never carry an "
            "allowance. The analysis lists each unbudgeted line, its group and its NPT/UPA split so the "
            "reason can be chased. LIH is reported separately because it is deducted from the AFE total "
            "rather than spent against one line."
        ),
        "steps": (
            "Open Well cost analysis and read the Out of scope tile.\n"
            "Use the listed unbudgeted lines to decide whether an SOW adjustment is justified.\n"
            "Record LIH items in the LIH Cost Register so they are deducted from the right AFE."
        ),
    },
    {
        "memory_key": "calc-lih-treatment",
        "title": "How LIH cost is treated in every comparison",
        "category": "calculation",
        "keywords": "lih lost in hole treatment deduct compare actual register",
        "route": "/daily-cost/lih-register",
        "permission": "daily-cost:read",
        "sort_order": 50,
        "body": (
            "LIH cost is recorded in its own register. It is added to the actual cost and deducted from "
            "the AFE total it is filed against; it is never folded into a budgeted line. Every comparison "
            "therefore prints actual including LIH, AFE available after LIH and the balance both ways."
        ),
        "steps": (
            "Open Daily Cost → LIH Cost Register for the well.\n"
            "File each lost-in-hole item against the AFE that carries the exposure.\n"
            "Check the LIH block on the well cost analysis to see the deduction per AFE."
        ),
    },
    {
        "memory_key": "entry-daily-sheet",
        "title": "What to enter on a daily cost sheet",
        "category": "data-entry",
        "keywords": "daily sheet entry what enter line quantity rate hours service consumable tangible other expense",
        "route": "/daily-cost",
        "permission": "daily-cost:create",
        "sort_order": 55,
        "body": (
            "One sheet per well per cost date. A service line needs the Master Data activity (which sets "
            "Planned/UPA/NPT), the sub-activity, the service, the charging basis, the quantity with its "
            "unit and either the locked AFE rate or a justified override. Consumables and tangibles are "
            "entered against their catalogue item or master record; other expenses need an expense type "
            "and a remark of at least three characters."
        ),
        "steps": (
            "Day Rate: enter hours for the hours actually worked (the rate is per 24 hours).\n"
            "Per Service / Per Section / Monthly: enter days, service or section as the quantity unit requires.\n"
            "Enter an override only with a reason; the locked AFE or catalogue rate is used otherwise.\n"
            "Pick the sub-activity so the responsible party and budget line are captured."
        ),
    },
    {
        "memory_key": "entry-checks",
        "title": "Entry checks: values that look mistyped",
        "category": "data-entry",
        "keywords": (
            "entry check checks mistyped typo typing mistake unusual anomaly outlier suggestion suggested "
            "keep entered zero decimal"
        ),
        "route": "/daily-cost",
        "permission": "daily-cost:read",
        "sort_order": 57,
        "body": (
            "A daily cost sheet compares each quantity, rate override, exchange rate and depth with the "
            "other sheets of the same AFE, the rates locked for the well and the locked well plan, and "
            "points out a value that looks mistyped: one zero too many, hours entered as days, feet "
            "entered as metres, the same line entered twice. It is arithmetic over this workspace's own "
            "sheets, with no model and no outside service. A check is advice only: it never stops a save "
            "and never changes a figure by itself."
        ),
        "steps": (
            "Read the Entry checks section above the cost lines; each check says what it was compared with.\n"
            "Apply the suggested value when the check is right; it edits the unsaved sheet, which you still save.\n"
            "Keep as entered when the value is right, with a short note; the decision is written to the audit log.\n"
            "Reopen a kept value while the sheet is a Draft if it needs another look."
        ),
    },
    {
        "memory_key": "entry-sub-activity",
        "title": "Why the Well Sub-activity is required on a cost line",
        "category": "data-entry",
        "keywords": "sub activity responsible party mandatory why required cost line",
        "route": "/rig-well/sub-activities",
        "permission": "rig-well:create",
        "sort_order": 60,
        "body": (
            "The sub-activity is what links a cost to who is responsible for it. It carries the activity "
            "classification, the responsible party (a vendor or a named party) and the description of the "
            "work. Without it an NPT/UPA cost cannot be attributed, which is why UPA/NPT lines refuse to "
            "save until a vendor or responsible party is identified."
        ),
        "steps": (
            "Create the sub-activities for each well and scope first.\n"
            "Set the responsible party to the vendor or company that owns the work.\n"
            "Keep codes short and stable; they are snapshotted onto every cost line."
        ),
    },
    {
        "memory_key": "entry-well-progress",
        "title": "Entering the spud date and progress completion",
        "category": "data-entry",
        "keywords": "spud date time progress completion milestone enter edit clear",
        "route": "/daily-cost",
        "permission": "daily-cost:update",
        "sort_order": 65,
        "body": (
            "The Well Spud Date & Time can be entered once and then edited, never cleared, because the "
            "actual-day count needs a start point. The Progress Completed Date & Time freezes the count "
            "at that exact minute. Both accept minutes; a milestone cannot be in the future. Updating a "
            "value recalculates the days immediately and is written to the audit log."
        ),
        "steps": (
            "Open the well in Daily Cost and use the Well progress panel.\n"
            "Choose the scope (drilling or completion) and enter the date & time.\n"
            "Save; the actual days and their variance against the plan update at once."
        ),
    },
    {
        "memory_key": "entry-afe-estimate",
        "title": "Building an AFE estimate the daily register can use",
        "category": "data-entry",
        "keywords": "afe estimate build save approve rates section phase service consumable tangible",
        "route": "/afe",
        "permission": "afe:estimate",
        "sort_order": 70,
        "body": (
            "An AFE estimate is built from service, consumable and tangible lines against the well's "
            "configured sections and phases. Day Rate services can carry a rate per section in one dialog; "
            "the service amount is the sum of those section amounts. Saving locks the rates that the daily "
            "register then reuses, so a later catalogue price change cannot rewrite history."
        ),
        "steps": (
            "Create the AFE for the well and the correct scope (drilling or completion).\n"
            "Add every budgeted service with its section, phase, rate category and quantity.\n"
            "Save the estimate, then submit it, review it and approve it before daily costing begins."
        ),
    },
    {
        "memory_key": "nav-business-dashboard",
        "title": "Where the operational dashboard lives",
        "category": "navigation",
        "keywords": "business dashboard operations where find overview rig well kpi",
        "route": "/dashboard/business",
        "permission": "",
        "sort_order": 75,
        "body": (
            "Business Dashboard is the one read-only page across rigs, wells, AFEs and daily costs. "
            "It shows planned and actual days, NPT/UPA, AFE against actual, depth progress and alerts, "
            "each only when the viewer holds that module's read permission."
        ),
        "steps": (
            "Open Business Dashboard from the main navigation.\n"
            "Filter by rig, well, AFE, type, status, currency and date range.\n"
            "Select a well to drill through to its AFEs, activities, sections and sheets."
        ),
    },
    {
        "memory_key": "nav-well-cost-analysis",
        "title": "Where well cost analysis lives and what it answers",
        "category": "navigation",
        "keywords": "well cost analysis where factors criteria responsible party forecast pivot",
        "route": "/daily-cost/analysis",
        "permission": "daily-cost:read",
        "sort_order": 80,
        "body": (
            "Daily Cost → Well cost analysis is the whole-well costing page: the daily run sheet, the AFE "
            "position, cost factors by group, classification, section, phase, activity, sub-activity, "
            "responsible party, rate source and currency, the multi-criteria pivot, the forecast, "
            "out-of-scope spend and the budget reconciliation."
        ),
        "steps": (
            "Choose the well, optionally a date range and whether drafts are included.\n"
            "Read the Cost factors tabs for one cut of the same ledger.\n"
            "Use Cost by criteria to read two factors at once, e.g. phase against activity."
        ),
    },
    {
        "memory_key": "nav-reports",
        "title": "Which report shows which figure",
        "category": "navigation",
        "keywords": "reports report print npt upa usage comparison well wise",
        "route": "/reports",
        "permission": "",
        "sort_order": 85,
        "body": (
            "Reports groups the NPT/UPA matrix and usage reports, the well-wise cost comparison, the "
            "custom reports built in the Report Builder and the printable AFE, daily and well costing "
            "sheets. Each report states its basis in its subtitle so a figure is never taken out of context."
        ),
        "steps": (
            "Open Reports for the catalogue.\n"
            "Use Well-wise cost comparisons for one row per well.\n"
            "Print the AFE sheet, daily cost sheet or whole-well costing sheet from their own registers."
        ),
    },
    {
        "memory_key": "policy-permissions",
        "title": "Permissions and why a screen or figure is missing",
        "category": "policy",
        "keywords": "permission denied cannot see hidden role rbac access capability 403",
        "route": "/security",
        "permission": "",
        "sort_order": 90,
        "body": (
            "Every action is checked against a capability such as daily-cost:read or afe:read. The "
            "assistant, the dashboard and every page hide a figure the caller may not read rather than "
            "showing a placeholder, and an action that is not granted answers with the exact capability "
            "the administrator must add to the role."
        ),
        "steps": (
            "Ask your administrator for the capability named in the message.\n"
            "Administrators manage roles and capabilities under Security.\n"
            "The owner role always holds every capability and cannot be edited away."
        ),
    },
    {
        "memory_key": "policy-deletion",
        "title": "Deleting is soft, restoring keeps full history",
        "category": "policy",
        "keywords": "delete restore deleted entries permanent recover audit",
        "route": "",
        "permission": "",
        "sort_order": 95,
        "body": (
            "Deleting a record removes it from the working registers but keeps it in Deleted Entries, "
            "where it can be restored. Permanent deletion is a separate capability and is audited. "
            "Costing never loses history: rates and names are snapshotted onto the records that used them."
        ),
        "steps": (
            "Use the Deleted Entries view of the module to find and restore a record.\n"
            "Permanent deletion needs its own permission and is written to the audit log."
        ),
    },
    {
        "memory_key": "policy-unsaved",
        "title": "Unsaved work is never lost silently",
        "category": "policy",
        "keywords": "unsaved changes leave discard save prompt navigation tab close",
        "route": "",
        "permission": "",
        "sort_order": 100,
        "body": (
            "Data-entry dialogs ask Save / Discard / Continue editing before closing with input present, "
            "and full-page editors block navigation, the back button and tab close until you save or "
            "deliberately discard. This applies to every module."
        ),
        "steps": (
            "Save, or choose Discard deliberately, when a prompt appears.\n"
            "Use Continue editing to return to the form with everything intact."
        ),
    },
    {
        "memory_key": "policy-currency",
        "title": "Currency, FX and the workspace default",
        "category": "policy",
        "keywords": "currency default fx exchange rate conversion standard usd mix",
        "route": "/master-data",
        "permission": "",
        "sort_order": 105,
        "body": (
            "Exactly one active currency is the workspace default and every currency dropdown preloads "
            "it. Multi-currency estimates store an exchange rate per currency and report a standard "
            "currency; the analysis only adds amounts that share the selected standard currency and "
            "reports how many records were excluded."
        ),
        "steps": (
            "Set the default on Master Data → Currency.\n"
            "Enter exchange rates on the records that need conversion.\n"
            "Choose the standard currency when reading a dashboard or analysis."
        ),
    },
    {
        "memory_key": "policy-depth",
        "title": "Depths are standardized to metres",
        "category": "calculation",
        "keywords": "depth feet metres meters standardization ft conversion",
        "route": "",
        "permission": "",
        "sort_order": 110,
        "body": (
            "Depths may be entered in feet or metres and are standardized to metres (feet ÷ 3.281) "
            "wherever they are added or compared, so a total never mixes units. The page prints the "
            "unit it is using."
        ),
        "steps": (
            "Enter the depth in the well's configured unit.\n"
            "Read metre totals on the dashboards and reports."
        ),
    },
    {
        "memory_key": "workflow-month-end",
        "title": "Closing a well: the correct order",
        "category": "workflow",
        "keywords": "close complete final review submit monthly end month freeze",
        "route": "/rig-well/wells",
        "permission": "",
        "sort_order": 115,
        "body": (
            "Wells move Upcoming → Active → Final review → Completed. Submit or reopen the daily sheets, "
            "clear the warnings and reconcile LIH and mud before asking for Final review. Sheets stay "
            "editable during Final review (that is when they are corrected) and freeze once the scope is "
            "Completed, until it is rolled back one step."
        ),
        "steps": (
            "Submit the daily sheets for the period.\n"
            "Clear the warnings on each sheet and reconcile mud and LIH.\n"
            "Move the well scope to Final review, correct anything found, then complete it."
        ),
    },
    {
        "memory_key": "ops-code-correlations",
        "title": "Operations Code Library & Codes Correlation",
        "category": "workflow",
        "keywords": (
            "code codes correlation correlations correlate correlated link linked multi criteria "
            "batch tree schematic hierarchy openwells operation activity npt cause phase agency "
            "source mark library unlink extract"
        ),
        "route": "/operations/library?tab=correlations",
        "permission": "ops-master:read",
        "sort_order": 120,
        "body": (
            "Well Operations → Code library maintains Operations, Sub-phases, Causes, "
            "Responsible agency labels and Source marks, the read-only Default Codes dictionary, and "
            "the Correlations workspace. Correlations map each exact printed source code to one or more selected criteria "
            "(optionally restricted to a report scope), while Link "
            "criteria creates multi-criteria relationships across two or more workspace codes. Both "
            "support atomic batch saving, switch between Table view (default) and an interactive Tree "
            "schematic, enforce the Planned/UPA/NPT classification matrix, pre-select codes as reviewable "
            "suggestions during report extraction, and block deleting any code until it is unlinked."
        ),
        "steps": (
            "Create or import workspace codes in Well Operations → Code library for Operations, Sub-phases, Causes, Responsible agency labels and Source marks.\n"
            "Open the Correlations tab and click Add correlation or Batch correlate to map each printed code to at least one criterion, such as Hole Section alone.\n"
            "Click Link criteria to link multiple workspace codes across Phase, Operation, Activity, NPT, Cause, Agency, Source mark, Scope, Classification and Allocation in one save.\n"
            "Switch between Table view (default) for search, filtering and bulk actions and Tree schematic to inspect the code hierarchy and unlinked codes visually.\n"
            "To retire a correlated code, unlink or delete its correlation first, delete the code to Deleted entries, then Restore or Delete permanently if no historical report references it."
        ),
    },
    {
        "memory_key": "ops-analytics-axes-rop",
        "title": "Operations Analytics: chart axis intervals & completion ROP",
        "category": "calculation",
        "keywords": (
            "operations analytics time depth completion progress axis axes scale step interval min max "
            "reset rop penetration rate na not applicable"
        ),
        "route": "/operations/analytics",
        "permission": "ops-analytics:read",
        "sort_order": 125,
        "body": (
            "On Well Operations → Analytics, drilling Time vs measured depth defaults to 300 m depth "
            "steps and completion Time vs completion progress automatically picks clean whole-number "
            "activity intervals so labels never overlap. Open Axis scale on the chart to set custom X "
            "(days) and Y (depth or activity) minimum, maximum and step intervals or one-click presets, "
            "and click Reset axes to restore defaults. Rate of penetration (ROP) applies only to drilling "
            "and is always reported as N/A across completion reports, summaries, analytics and exports."
        ),
        "steps": (
            "Open Well Operations → Analytics and pick a well and Drilling or Completion scope.\n"
            "Use Axis scale on the progress curve to adjust X-axis (days) and Y-axis (MD or activity number) min, max and step interval, or click Reset axes.\n"
            "Export SVG or PDF directly from the chart panel with your active axis scale preserved; completion views always report ROP as N/A."
        ),
    },
    {
        "memory_key": "workflow-permanent-delete",
        "title": "Deleting, restoring and permanently deleting records",
        "category": "workflow",
        "keywords": (
            "delete deleted permanently permanent purge remove trash restore recover dependency blocked "
            "linked unlink safeguard audit"
        ),
        "route": "/audit-logs",
        "permission": "",
        "sort_order": 130,
        "body": (
            "WellSenseIQ uses a uniform two-step deletion safeguard across Master Data, Rig & Well, AFE, "
            "Daily Costing, Fuel Cost, Invoices, Invoice Configuration, Templates and Well Operations "
            "(Documents, Daily Reports, Timelines, Code Library and Correlations). Deleting a live record "
            "moves it to Deleted entries where it can be restored intact; live items linked to active "
            "code correlations are blocked until unlinked. Permanent deletion is available only inside "
            "Deleted entries for authorized users, requires explicit confirmation, refuses records still "
            "referenced by operational history, and writes an immutable audit log entry."
        ),
        "steps": (
            "If a code or catalogue item is blocked by an active correlation, remove or update the correlation first.\n"
            "Delete the live record to move it safely into Deleted entries (inactive in pickers, preserved in history).\n"
            "Open Show deleted / Deleted entries and choose Restore to recover the record, or Delete permanently to remove unreferenced items irreversibly."
        ),
    },
)


# ---------------------------------------------------------------------------
# Seeding and memory reads
# ---------------------------------------------------------------------------


def seed_memory(db: Session, organization_id: str) -> int:
    """Insert any shipped memory entry the workspace does not have yet.

    Idempotent and additive: an entry is never overwritten, so a workspace can
    rely on the wording it has been trained on. Returns how many were added.
    """
    existing = set(db.scalars(
        select(AssistantMemory.memory_key).where(AssistantMemory.organization_id == organization_id)
    ).all())
    added = 0
    for entry in SYSTEM_MEMORY:
        if entry["memory_key"] in existing:
            continue
        db.add(AssistantMemory(
            organization_id=organization_id,
            memory_key=entry["memory_key"],
            title=entry["title"],
            category=entry["category"],
            keywords=entry["keywords"],
            body=entry["body"],
            steps=entry["steps"],
            route=entry["route"],
            permission=entry["permission"],
            is_system=True,
            is_active=True,
            sort_order=entry["sort_order"],
            created_by_name="WellSenseIQ guide",
        ))
        added += 1
    if added:
        db.flush()
    return added


def memory_out(row: AssistantMemory) -> AssistantMemoryOut:
    return AssistantMemoryOut(
        id=row.id,
        memory_key=row.memory_key,
        title=row.title,
        category=row.category,  # type: ignore[arg-type]
        keywords=row.keywords,
        body=row.body,
        steps=[line for line in row.steps.splitlines() if line.strip()],
        route=row.route,
        permission=row.permission,
        is_system=row.is_system,
        is_active=row.is_active,
        sort_order=row.sort_order,
        created_by_name=row.created_by_name,
        updated_at=row.updated_at,
    )


def list_memory(db: Session, organization_id: str) -> list[AssistantMemoryOut]:
    seed_memory(db, organization_id)
    rows = db.scalars(
        select(AssistantMemory)
        .where(AssistantMemory.organization_id == organization_id)
        .order_by(AssistantMemory.sort_order, AssistantMemory.title)
    ).all()
    return [memory_out(row) for row in rows]


def _clean_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")[:80]
    return key or "memory"


def create_memory(
    db: Session, organization_id: str, data: AssistantMemoryIn, user: User,
) -> AssistantMemoryOut:
    key = _clean_key(data.memory_key or data.title)
    existing = db.scalar(select(AssistantMemory).where(
        AssistantMemory.organization_id == organization_id, AssistantMemory.memory_key == key,
    ))
    if existing is not None:
        raise ValueError(f"The memory key '{key}' is already used in this workspace.")
    row = AssistantMemory(
        organization_id=organization_id,
        memory_key=key,
        title=data.title.strip(),
        category=data.category,
        keywords=" ".join(data.keywords.lower().split()),
        body=data.body.strip(),
        steps="\n".join(step.strip() for step in data.steps if step.strip()),
        route=data.route.strip(),
        permission=data.permission.strip(),
        is_system=False,
        is_active=data.is_active,
        sort_order=data.sort_order,
        created_by_name=user.full_name,
    )
    db.add(row)
    db.flush()
    return memory_out(row)


def update_memory(
    db: Session, organization_id: str, memory_id: str, data: AssistantMemoryUpdate, user: User,
) -> AssistantMemoryOut:
    row = db.scalar(select(AssistantMemory).where(
        AssistantMemory.id == memory_id, AssistantMemory.organization_id == organization_id,
    ))
    if row is None:
        raise LookupError("That memory entry is not in this workspace.")
    if row.is_system:
        raise PermissionError(
            "This is shipped application memory and cannot be edited. Add a workspace memory "
            "entry beside it with your own wording."
        )
    payload = data.model_dump(exclude_unset=True)
    for field in ("title", "category", "body", "route", "permission"):
        if field in payload and payload[field] is not None:
            setattr(row, field, str(payload[field]).strip())
    if "keywords" in payload and payload["keywords"] is not None:
        row.keywords = " ".join(str(payload["keywords"]).lower().split())
    if "steps" in payload and payload["steps"] is not None:
        row.steps = "\n".join(step.strip() for step in payload["steps"] if step.strip())
    if "is_active" in payload and payload["is_active"] is not None:
        row.is_active = bool(payload["is_active"])
    if "sort_order" in payload and payload["sort_order"] is not None:
        row.sort_order = int(payload["sort_order"])
    db.flush()
    return memory_out(row)


def delete_memory(db: Session, organization_id: str, memory_id: str) -> None:
    row = db.scalar(select(AssistantMemory).where(
        AssistantMemory.id == memory_id, AssistantMemory.organization_id == organization_id,
    ))
    if row is None:
        raise LookupError("That memory entry is not in this workspace.")
    if row.is_system:
        raise PermissionError(
            "Shipped application memory cannot be deleted; deactivate your own entries instead."
        )
    db.delete(row)
    db.flush()


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


def _permissions(user: User) -> set[str]:
    if any(role.is_owner for role in user.roles):
        return {"*"}
    return {permission.key for role in user.roles for permission in role.permissions}


def _can(permissions: set[str], key: str) -> bool:
    return "*" in permissions or not key or key in permissions


# ---------------------------------------------------------------------------
# Question classification
# ---------------------------------------------------------------------------

INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("data_health", (
        "missing", "incomplete", "what should i enter", "what to enter", "ready", "check my data",
        "data quality", "what is left", "to do", "todo", "hygiene", "clean up",
    )),
    ("price_lookup", (
        "price of", "rate of", "unit price", "unit rate", "unit cost", "how much is", "how much does",
        "tariff", "po rate", "price list", "tangible price", "tangibles price", "consumable price",
        "consumables price", "chemical price", "bit price", "fuel price", "diesel price",
        "additive price", "catalogue price", "catalog price", "prices of", "rates of",
        "cost of tangible", "cost of consumable", "list tangibles", "list consumables",
        "show tangibles", "show consumables",
    )),
    ("cost_search", (
        "search cost", "find cost", "lookup cost", "look up cost", "costs related to",
        "cost related to", "costs for", "spend on", "spent on", "all costs for", "search for",
        "find item", "lih cost", "ndt cost", "ndt inspection",
    )),
    ("actual_days", ("actual day", "how many day", "duration", "spud", "13.4", "elapsed")),
    ("forecast", ("forecast", "projection", "projected", "overrun", "run rate", "burn")),
    ("out_of_scope", ("out of scope", "unbudgeted", "not in the afe", "other expense", "lih")),
    ("npt_upa", ("npt", "upa", "non productive", "unplanned", "downtime")),
    ("cost_position", (
        "afe balance", "balance", "spent", "spend", "cost detail", "cost breakdown",
        "cost summary", "cost", "budget", "variance", "utilisation", "utilization", "over budget",
    )),
    ("status", ("how many wells", "active wells", "well status", "portfolio", "overview", "summary")),
)


# A question that asks *how the application works* is answered from memory, even
# when it names a figure ("how are actual days calculated?"). A question that
# names a concrete record ("how many actual days does WELL-01 have?") is answered
# from data. These cues keep the two apart instead of matching "actual day" first.
EXPLANATION_CUES: tuple[str, ...] = (
    "how is ", "how are ", "how do ", "how does ", "how should ", "how can ",
    "how to ", "why ", "explain", "calculated", "calculation", "definition",
    "meaning of", "difference between", "what does ",
)

_RECORD_REFERENCE = re.compile(r"\b[A-Z]{2,}[-/ ]?\d")


def _asks_for_explanation(text: str, question: str) -> bool:
    """True when the caller wants the rule, not a figure for one record."""
    if "how many" in text or "how much" in text:
        return False
    if _RECORD_REFERENCE.search(question):
        return False
    return any(cue in text for cue in EXPLANATION_CUES)


def _detect_intent(question: str) -> str:
    text = question.lower()
    if _asks_for_explanation(text, question):
        return "knowledge"
    for intent, needles in INTENT_RULES:
        if any(needle in text for needle in needles):
            return intent
    return "knowledge"


def _find_well(db: Session, organization_id: str, question: str) -> Well | None:
    """Resolve a well from its code or name, never guessing between two matches."""
    wells = db.scalars(select(Well).where(
        Well.organization_id == organization_id, Well.is_deleted.is_(False),
    )).all()
    text = question.casefold()
    for well in wells:
        if well.well_code and well.well_code.casefold() in text:
            return well
    matches = [well for well in wells if well.well_name and well.well_name.casefold() in text]
    if len(matches) == 1:
        return matches[0]
    return None


def _money(value: Any) -> str:
    if value is None:
        return "—"
    return f"{Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP):,.3f}"


def _days(value: Any) -> str:
    if value is None:
        return "—"
    return f"{Decimal(str(value)).quantize(DAYS, rounding=ROUND_HALF_UP):,.3f}"


def _well_label(well: Well) -> str:
    return f"{well.well_code} · {well.well_name}" if well.well_name else well.well_code


# ---------------------------------------------------------------------------
# Data-quality checks — "what should I enter, and what should I not"
# ---------------------------------------------------------------------------


def data_checks(db: Session, organization_id: str, permissions: set[str]) -> list[AssistantFact]:
    """The shortest list of missing entries that blocks clean costing.

    Only checks the caller may read are returned; a viewer without AFE access is
    never told about AFE gaps, and nothing here mutates data.
    """
    checks: list[AssistantFact] = []
    wells = db.scalars(select(Well).where(
        Well.organization_id == organization_id, Well.is_deleted.is_(False),
    )).all()
    if _can(permissions, "rig-well:read") and _can(permissions, "daily-cost:read"):
        no_spud = [
            _well_label(well) for well in wells
            if well.drilling_spud_at is None and well.completion_spud_at is None
        ][:8]
        if no_spud:
            checks.append(AssistantFact(
                label="Wells without a spud instant",
                value=str(len(no_spud)),
                hint=(
                    "Actual days cannot be exact until the Well Spud Date & Time is entered: "
                    + ", ".join(no_spud)
                ),
                route="/daily-cost",
                permission="daily-cost:update",
            ))
    if _can(permissions, "rig-well:read"):
        pending_plans = [
            _well_label(well) for well in wells if well.config_status == "draft"
        ][:8]
        if pending_plans:
            checks.append(AssistantFact(
                label="Wells still on a Draft plan",
                value=str(len(pending_plans)),
                hint=(
                    "A Draft plan blocks new daily cost sheets and AFE estimates: "
                    + ", ".join(pending_plans)
                ),
                route="/rig-well/wells",
                permission="rig-well:update",
            ))
    if _can(permissions, "afe:read"):
        unsaved = db.scalar(select(func.count(Afe.id)).where(
            Afe.organization_id == organization_id, Afe.is_deleted.is_(False),
            Afe.estimate_saved_at.is_(None),
        )) or 0
        if unsaved:
            checks.append(AssistantFact(
                label="AFEs without a saved estimate",
                value=str(unsaved),
                hint="The daily register needs a saved, approved estimate before it can price work.",
                route="/afe",
                permission="afe:estimate",
            ))
        waiting = db.scalar(select(func.count(Afe.id)).where(
            Afe.organization_id == organization_id, Afe.is_deleted.is_(False),
            Afe.estimate_saved_at.is_not(None), Afe.status != "approval",
        )) or 0
        if waiting:
            checks.append(AssistantFact(
                label="Estimates not yet approved",
                value=str(waiting),
                hint="Submit, review and approve them so daily costing starts against an authorised budget.",
                route="/afe",
                permission="afe:approve",
            ))
    if _can(permissions, "daily-cost:read"):
        drafts = db.scalar(select(func.count(DailyCostEntry.id)).where(
            DailyCostEntry.organization_id == organization_id,
            DailyCostEntry.is_deleted.is_(False), DailyCostEntry.status == "draft",
        )) or 0
        if drafts:
            checks.append(AssistantFact(
                label="Draft daily sheets",
                value=str(drafts),
                hint="Check their warnings, then submit them; drafts stay editable and are excluded when drafts are off.",
                route="/daily-cost",
                permission="daily-cost:submit",
            ))
    if _can(permissions, "rig-well:read"):
        missing_party = db.scalar(select(func.count(WellSubActivity.id)).where(
            WellSubActivity.organization_id == organization_id,
            WellSubActivity.is_deleted.is_(False),
            WellSubActivity.responsible_party.in_(("", "Not Applicable")),
        )) or 0
        if missing_party:
            checks.append(AssistantFact(
                label="Sub-activities without a responsible party",
                value=str(missing_party),
                hint="UPA/NPT cost cannot be attributed to anyone until a vendor or party is named.",
                route="/rig-well/sub-activities",
                permission="rig-well:update",
            ))
    if _can(permissions, "master-data:read"):
        no_vendor = db.scalar(select(func.count(Service.id)).where(
            Service.organization_id == organization_id, Service.is_deleted.is_(False),
            Service.vendor_id.is_(None),
        )) or 0
        if no_vendor:
            checks.append(AssistantFact(
                label="Services without a vendor",
                value=str(no_vendor),
                hint="A service with no vendor cannot book cost to a provider on the daily sheet.",
                route="/master-data",
                permission="master-data:update",
            ))
    return checks


# ---------------------------------------------------------------------------
# Answer building
# ---------------------------------------------------------------------------


# Words that carry no meaning for matching a question to a memory entry. Without
# this filter "Who won the world cup?" scores against every title that contains
# "the" and the guide answers a question it does not know.
STOPWORDS = frozenset("""
a about above after again against all am an and any are as at be because been
before being below between both but by can could did do does doing down during
each few for from further had has have having he her here hers him his how i if
in into is it its just me more most my no nor not now of off on once only or
other our out over own same she should so some such than that the their them
then there these they this those through to too under until up very was we were
what when where which while who whom why will with would you your
""".split())


def _content_tokens(text: str) -> list[str]:
    return [
        token for token in re.split(r"[^a-z0-9]+", text.casefold())
        if len(token) > 2 and token not in STOPWORDS
    ]


def _knowledge_score(
    row: AssistantMemory, question: str, route: str, permissions: set[str],
) -> float:
    """How well one memory entry answers the question.

    Only the curated ``keywords``, the title and the page the caller is on can
    raise the score. The body is prose and matching it makes any stray word look
    like a match, so it is not scored.
    """
    if not row.is_active:
        return 0.0
    if row.permission and not _can(permissions, row.permission):
        return 0.0
    text = question.casefold()
    tokens = _content_tokens(text)
    keywords = _content_tokens(row.keywords)
    keyword_set = set(keywords)
    title_set = set(_content_tokens(row.title))
    score = 0.0
    for token in tokens:
        if token in keyword_set:
            score += 3.0
        elif any(keyword.startswith(token) or token.startswith(keyword) for keyword in keywords if len(keyword) > 3):
            score += 1.5
        if token in title_set:
            score += 2.0
    # A multi-word keyword the caller typed almost verbatim is a strong signal.
    for keyword in keywords:
        if len(keyword) > 4 and re.search(rf"\b{re.escape(keyword)}", text):
            score += 0.5
    if row.route and route and row.route.rstrip("/") == route.rstrip("/"):
        score += 2.5
    # A category hint in the question ("how is ... calculated") is a mild signal.
    if "how" in text and row.category == "calculation":
        score += 1.0
    if ("where" in text or "find" in text) and row.category == "navigation":
        score += 1.0
    return score


def _answer_from_memory(row: AssistantMemory, reason: str = "") -> AssistantAnswer:
    steps = [line for line in row.steps.splitlines() if line.strip()]
    return AssistantAnswer(
        answer=row.body,
        intent="knowledge",
        memory_key=row.memory_key,
        confidence="high" if reason else "medium",
        category=row.category,  # type: ignore[arg-type]
        steps=steps,
        sources=[AssistantSource(label=row.title, route=row.route)] if row.route else [],
        follow_ups=_follow_ups_for(row),
    )


def _follow_ups_for(row: AssistantMemory) -> list[str]:
    if row.category == "calculation":
        return [
            "Which wells are missing a spud date?",
            "What is out of scope on this well?",
            "How do I record a responsible party?",
        ]
    if row.category == "navigation":
        return [
            "What should I enter on a daily cost sheet?",
            "How is the AFE balance calculated?",
            "What is missing before I close a well?",
        ]
    return [
        "How are actual days calculated?",
        "What is missing in my workspace?",
        "Where is the well cost analysis?",
    ]


def _permission_answer(key: str) -> AssistantAnswer:
    return AssistantAnswer(
        answer=(
            f"That answer needs the {key} capability, which your role does not hold. "
            "Ask your administrator to add it to your role in Security → Roles; nothing is hidden "
            "because the data is missing."
        ),
        intent="permission",
        confidence="high",
        category="policy",
        follow_ups=["How do permissions work here?", "What is missing in my workspace?"],
    )


def _answer_status(db: Session, organization_id: str) -> AssistantAnswer:
    wells = db.scalars(select(Well).where(
        Well.organization_id == organization_id, Well.is_deleted.is_(False),
    )).all()
    counts = Counter(well.tracking_status for well in wells)
    active = counts.get("active", 0)
    upcoming = counts.get("upcoming", 0)
    review = counts.get("final_review", 0)
    completed = counts.get("completed", 0)
    facts = [
        AssistantFact(label="Wells", value=str(len(wells))),
        AssistantFact(label="Active", value=str(active)),
        AssistantFact(label="Upcoming", value=str(upcoming)),
        AssistantFact(label="Final review", value=str(review)),
        AssistantFact(label="Completed", value=str(completed)),
    ]
    return AssistantAnswer(
        answer=(
            f"This workspace has {len(wells)} well(s): {active} active, {upcoming} upcoming, "
            f"{review} in final review and {completed} completed. Open the Business Dashboard for "
            "planned against actual days, NPT/UPA and AFE exposure by rig and well."
        ),
        intent="status",
        confidence="high",
        category="calculation",
        facts=facts,
        sources=[AssistantSource(label="Business Dashboard", route="/dashboard/business")],
        follow_ups=["How are actual days calculated?", "What is missing in my workspace?"],
    )


def _answer_actual_days(
    db: Session, organization_id: str, question: str,
) -> AssistantAnswer:
    from app.services.daily_cost import progress_overview

    reports = progress_overview(db, organization_id)
    well = _find_well(db, organization_id, question)
    rows = reports if well is None else [row for row in reports if row.well_id == well.id]
    lines: list[str] = []
    facts: list[AssistantFact] = []
    for report in rows[:8]:
        parts: list[str] = []
        for scope in report.scopes:
            if scope.actual_days is None:
                parts.append(f"{scope.scope_label.lower()}: not started")
            else:
                parts.append(
                    f"{scope.scope_label.lower()} {_days(scope.actual_days)} days against "
                    f"{_days(scope.planned_days)} planned"
                )
        line = f"{report.well_code}: " + "; ".join(parts)
        lines.append(line)
        if well is not None:
            for scope in report.scopes:
                facts.append(AssistantFact(
                    label=f"{scope.scope_label} actual days",
                    value=_days(scope.actual_days),
                    hint=(
                        f"planned {_days(scope.planned_days)} · basis "
                        f"{'spud instant' if scope.basis == 'spud' else 'recorded cost dates'}"
                    ),
                ))
    if not rows:
        return AssistantAnswer(
            answer=(
                "No well has recorded daily cost yet, so there are no actual days to report. Actual days "
                "start from the Well Spud Date & Time; create the first daily sheet and enter the spud "
                "instant."
            ),
            intent="actual_days",
            confidence="medium",
            category="calculation",
            sources=[AssistantSource(label="Daily Cost register", route="/daily-cost")],
        )
    intro = (
        f"Actual days for {_well_label(well)}:" if well is not None else "Exact actual days by well:"
    )
    return AssistantAnswer(
        answer=(
            f"{intro}\n" + "\n".join(f"• {line}" for line in lines)
            + "\n\nThese are elapsed days from the spud instant to the end of the last cost date (or to "
            "the Progress Completed instant), at three decimals. They are not the number of daily sheets: "
            "fourteen sheets can cover 13.417 days."
        ),
        intent="actual_days",
        confidence="high",
        category="calculation",
        facts=facts,
        sources=[AssistantSource(label="Daily Cost register", route="/daily-cost")],
        follow_ups=["Why is my sheet count higher than my actual days?", "What is missing in my workspace?"],
    )


def _summary_for(db: Session, organization_id: str, well: Well) -> Any:
    from app.services.daily_cost import well_cost_summary

    return well_cost_summary(db, organization_id, well.id)


def _answer_cost_position(
    db: Session, organization_id: str, question: str, permissions: set[str],
) -> AssistantAnswer:
    well = _find_well(db, organization_id, question)
    if well is None:
        wells = db.scalars(select(Well).where(
            Well.organization_id == organization_id, Well.is_deleted.is_(False),
        ).order_by(Well.well_code)).all()
        names = ", ".join(well.well_code for well in wells[:12])
        return AssistantAnswer(
            answer=(
                "Name the well and I will cost it exactly: for example \"AFE balance on "
                f"{wells[0].well_code if wells else 'WELL-01'}\". Wells in this workspace: {names or 'none yet'}."
            ),
            intent="cost_position",
            confidence="medium",
            category="navigation",
            follow_ups=["How is the AFE balance calculated?", "What is missing in my workspace?"],
        )
    summary = _summary_for(db, organization_id, well)
    totals = summary.totals
    currency = totals.currency or ""
    facts = [
        AssistantFact(label="AFE planned", value=f"{currency} {_money(totals.planned)}"),
        AssistantFact(label="Actual to date", value=f"{currency} {_money(totals.actual)}",
                      hint=f"{_money(totals.used_percent)}% of the locked AFE"),
        AssistantFact(label="Remaining balance", value=f"{currency} {_money(totals.balance)}",
                      hint="over budget" if Decimal(totals.balance) < 0 else "within budget"),
        AssistantFact(label="Actual days", value=_days(totals.actual_days or totals.spud_actual_days),
                      hint=f"{totals.recorded_days} recorded cost date(s)"),
        AssistantFact(label="NPT / UPA cost", value=f"{currency} {_money(totals.npt)} / {currency} {_money(totals.upa)}"),
    ]
    if summary.forecast is not None and summary.forecast.available:
        facts.append(AssistantFact(
            label="Forecast final cost",
            value=f"{currency} {_money(summary.forecast.forecast_final_cost)}",
            hint=(
                f"{'over' if summary.forecast.forecast_over_budget else 'within'} the plan by "
                f"{currency} {_money(abs(Decimal(summary.forecast.forecast_variance)))}"
            ),
        ))
    if summary.out_of_scope is not None and summary.out_of_scope.available:
        facts.append(AssistantFact(
            label="Out of scope",
            value=f"{currency} {_money(summary.out_of_scope.amount)}",
            hint=f"{summary.out_of_scope.line_count} unbudgeted line(s) plus other expenses",
        ))
    tables: list[AssistantTable] = []
    # Build cost-group breakdown table (Services / Tangibles / Consumables / Other Expenses)
    group_totals: dict[str, list[Decimal]] = {}
    for line in getattr(summary, "budget_lines", []) or []:
        grp = line.cost_group or "Other"
        bucket = group_totals.setdefault(grp, [Decimal("0"), Decimal("0")])
        bucket[0] += Decimal(str(line.planned or 0))
        line_actual_val = getattr(line, "actual_to_date", None)
        if line_actual_val is None:
            line_actual_val = getattr(line, "actual", 0)
        bucket[1] += Decimal(str(line_actual_val or 0))
    if group_totals:
        group_rows: list[list[str]] = []
        for grp, (planned_val, actual_val) in sorted(group_totals.items(), key=lambda kv: -kv[1][1]):
            pct = (
                f"{(actual_val / planned_val * Decimal('100')).quantize(MONEY, rounding=ROUND_HALF_UP):,.1f}%"
                if planned_val > 0 else "—"
            )
            group_rows.append([
                grp,
                f"{currency} {_money(planned_val)}" if _can(permissions, "afe:read") else "—",
                f"{currency} {_money(actual_val)}",
                pct if _can(permissions, "afe:read") else "—",
                f"{currency} {_money(planned_val - actual_val)}" if _can(permissions, "afe:read") else "—",
            ])
        tables.append(AssistantTable(
            title=f"Cost breakdown · {well.well_code}",
            columns=["Cost Group", "AFE Planned", "Actual", "Actual / AFE %", "Balance"],
            rows=group_rows,
        ))
    # Show top line items (filtered by requested group if the user named one)
    q_low = question.casefold()
    requested_group: str | None = None
    for needle, grp_name in (
        ("tangible", "Tangibles"),
        ("service", "Services"),
        ("consumable", "Consumables"),
        ("other expense", "Other Expenses"),
    ):
        if needle in q_low:
            requested_group = grp_name
            break
    def _line_actual(item: Any) -> Decimal:
        val = getattr(item, "actual_to_date", None)
        if val is None:
            val = getattr(item, "actual", 0)
        return Decimal(str(val or 0))

    candidate_lines = [
        line for line in (getattr(summary, "budget_lines", []) or [])
        if _line_actual(line) > 0
        and (requested_group is None or (line.cost_group or "").lower() == requested_group.lower())
    ]
    candidate_lines.sort(key=lambda item: -_line_actual(item))
    if candidate_lines:
        item_rows = [
            [
                line.cost_group or "—",
                line.item_name or line.item_code or "—",
                f"{currency} {_money(line.planned)}" if (_can(permissions, "afe:read") and line.is_planned) else "Unbudgeted",
                f"{currency} {_money(_line_actual(line))}",
            ]
            for line in candidate_lines[:10]
        ]
        tables.append(AssistantTable(
            title=(
                f"{requested_group} lines on {well.well_code}"
                if requested_group else f"Top cost items on {well.well_code}"
            ),
            columns=["Group", "Item", "AFE Planned", "Actual"],
            rows=item_rows,
            note=f"Showing top {len(item_rows)} of {len(candidate_lines)} active cost line(s).",
        ))
    afe_pct = f"{_money(totals.used_percent)}%" if totals.planned and Decimal(totals.planned) > 0 else "—"
    return AssistantAnswer(
        answer=(
            f"{_well_label(well)}: {currency} {_money(totals.actual)} spent of "
            f"{currency} {_money(totals.planned)} ({afe_pct} of AFE) on the {currency} AFE, leaving "
            f"{currency} {_money(totals.balance)}. {totals.recorded_days} cost date(s) are recorded and "
            f"the exact actual days are {_days(totals.actual_days or totals.spud_actual_days)}. "
            f"NPT is {currency} {_money(totals.npt)} and UPA {currency} {_money(totals.upa)}."
        ),
        intent="cost_position",
        confidence="high",
        category="calculation",
        facts=facts,
        tables=tables,
        sources=[AssistantSource(label=f"Well cost analysis · {well.well_code}", route=f"/daily-cost/analysis/{well.id}")],
        follow_ups=[
            f"What is out of scope on {well.well_code}?",
            f"Forecast for {well.well_code}",
            f"Show tangibles on {well.well_code}",
        ],
    )


def _answer_forecast(db: Session, organization_id: str, question: str) -> AssistantAnswer:
    well = _find_well(db, organization_id, question)
    if well is None:
        return AssistantAnswer(
            answer="Tell me which well to forecast, for example \"forecast for WELL-01\".",
            intent="forecast",
            confidence="medium",
            category="calculation",
            follow_ups=["How is the forecast calculated?"],
        )
    summary = _summary_for(db, organization_id, well)
    forecast = summary.forecast
    if forecast is None or not forecast.available:
        return AssistantAnswer(
            answer=(
                f"{_well_label(well)} has no recorded cost yet, so there is no run rate to project. "
                "Record the first daily sheet, then the forecast appears."
            ),
            intent="forecast",
            confidence="high",
            category="calculation",
            sources=[AssistantSource(label="Well cost analysis", route=f"/daily-cost/analysis/{well.id}")],
        )
    currency = forecast.currency
    verdict = "above" if forecast.forecast_over_budget else "within"
    return AssistantAnswer(
        answer=(
            f"At {currency} {_money(forecast.run_rate)} per "
            f"{'elapsed day' if forecast.basis == 'spud' else 'recorded day'} and "
            f"{_days(forecast.remaining_planned_days)} planned days still ahead, {_well_label(well)} is "
            f"projected to finish at {currency} {_money(forecast.forecast_final_cost)} against a plan of "
            f"{currency} {_money(forecast.planned_final_cost)} — {verdict} the plan by "
            f"{currency} {_money(abs(Decimal(forecast.forecast_variance)))}. {forecast.note}"
        ),
        intent="forecast",
        confidence="high",
        category="calculation",
        facts=[
            AssistantFact(label="Run rate", value=f"{currency} {_money(forecast.run_rate)}"),
            AssistantFact(label="Days ahead", value=_days(forecast.remaining_planned_days)),
            AssistantFact(label="Forecast final cost", value=f"{currency} {_money(forecast.forecast_final_cost)}"),
            AssistantFact(label="Plan", value=f"{currency} {_money(forecast.planned_final_cost)}"),
        ],
        sources=[AssistantSource(label="Well cost analysis", route=f"/daily-cost/analysis/{well.id}")],
        follow_ups=["How is the forecast calculated?", "What is out of scope on this well?"],
    )


def _answer_out_of_scope(db: Session, organization_id: str, question: str) -> AssistantAnswer:
    well = _find_well(db, organization_id, question)
    if well is None:
        return AssistantAnswer(
            answer=(
                "Name the well so I can list its out-of-scope spend, for example "
                "\"out of scope on WELL-01\". Out-of-scope means any cost with no AFE allowance "
                "behind it, plus other expenses."
            ),
            intent="out_of_scope",
            confidence="medium",
            category="calculation",
            follow_ups=["How is the forecast calculated?"],
        )
    summary = _summary_for(db, organization_id, well)
    scope = summary.out_of_scope
    if scope is None or not scope.available:
        return AssistantAnswer(
            answer=f"There is no recorded cost on {_well_label(well)} yet, so nothing can be out of scope.",
            intent="out_of_scope",
            confidence="high",
            category="calculation",
        )
    currency = scope.currency
    lines = scope.lines[:6]
    detail = "\n".join(
        f"• {line.cost_group}: {line.item_name or line.item_code} — {currency} {_money(line.actual)}"
        for line in lines
    )
    return AssistantAnswer(
        answer=(
            f"{currency} {_money(scope.amount)} of {_well_label(well)}'s actual cost has no AFE allowance "
            f"behind it ({_money(scope.share_percent)}% of the ledger): {scope.line_count} unbudgeted "
            f"line(s) worth {currency} {_money(scope.unbudgeted)} and other expenses of "
            f"{currency} {_money(scope.other_expenses)}."
            + (f"\n\nLargest unbudgeted lines:\n{detail}" if detail else "")
        ),
        intent="out_of_scope",
        confidence="high",
        category="calculation",
        facts=[
            AssistantFact(label="Out of scope", value=f"{currency} {_money(scope.amount)}"),
            AssistantFact(label="Unbudgeted lines", value=str(scope.line_count)),
            AssistantFact(label="Other expenses", value=f"{currency} {_money(scope.other_expenses)}"),
        ],
        sources=[AssistantSource(label="Well cost analysis", route=f"/daily-cost/analysis/{well.id}")],
        follow_ups=["How is the forecast calculated?", "How is LIH cost treated?"],
    )


def _answer_npt_upa(db: Session, organization_id: str, question: str) -> AssistantAnswer:
    well = _find_well(db, organization_id, question)
    if well is None:
        return _answer_from_memory(
            _memory_or_raise(db, organization_id, "calc-npt-upa-days"),
            reason="npt",
        )
    summary = _summary_for(db, organization_id, well)
    totals = summary.totals
    currency = totals.currency
    party = next((group for group in summary.factors if group.dimension == "party"), None)
    exposed = sorted(
        (row for row in (party.rows if party else []) if Decimal(row.responsible_amount or 0) > 0),
        key=lambda row: -Decimal(row.responsible_amount or 0),
    )[:5]
    detail = "\n".join(
        f"• {row.name}: {currency} {_money(row.responsible_amount)} exposure "
        f"({_days(row.upa_days)} UPA days, {_days(row.npt_days)} NPT days)"
        for row in exposed
    )
    return AssistantAnswer(
        answer=(
            f"{_well_label(well)} carries {currency} {_money(totals.npt)} of NPT and "
            f"{currency} {_money(totals.upa)} of UPA. The recorded sheets also classify "
            f"{_days(totals.actual_days or totals.spud_actual_days)} of elapsed time in total; NPT and UPA "
            "days are deduplicated service hours ÷ 24, not the number of affected cost dates."
            + (f"\n\nResponsible parties:\n{detail}" if detail else "")
        ),
        intent="npt_upa",
        confidence="high",
        category="calculation",
        facts=[
            AssistantFact(label="NPT cost", value=f"{currency} {_money(totals.npt)}"),
            AssistantFact(label="UPA cost", value=f"{currency} {_money(totals.upa)}"),
            AssistantFact(label="Actual days", value=_days(totals.actual_days or totals.spud_actual_days)),
        ],
        sources=[
            AssistantSource(label="Well cost analysis", route=f"/daily-cost/analysis/{well.id}"),
            AssistantSource(label="NPT / UPA report", route="/reports"),
        ],
        follow_ups=["How are NPT and UPA days calculated?", "How is cost attributed to a responsible party?"],
    )


def _answer_data_health(db: Session, organization_id: str, permissions: set[str]) -> AssistantAnswer:
    checks = data_checks(db, organization_id, permissions)
    if not checks:
        return AssistantAnswer(
            answer=(
                "Nothing blocking is missing in the parts of the workspace you can read: every visible "
                "well has a spud instant where a scope is open, every visible AFE has a saved estimate, "
                "and there are no draft sheets waiting. Keep the spud instant and progress completion "
                "current as each scope finishes."
            ),
            intent="data_health",
            confidence="high",
            category="workflow",
            sources=[AssistantSource(label="Daily Cost register", route="/daily-cost")],
        )
    lines = "\n".join(f"• {fact.label}: {fact.value} — {fact.hint}" for fact in checks)
    return AssistantAnswer(
        answer=f"Before the costing can be exact, these entries are outstanding:\n{lines}",
        intent="data_health",
        confidence="high",
        category="workflow",
        facts=checks,
        sources=[AssistantSource(label="Rig & Well register", route="/rig-well/wells")],
        follow_ups=[
            "How are actual days calculated?",
            "What should I enter on a daily cost sheet?",
            "How is cost attributed to a responsible party?",
        ],
    )


def _memory_or_raise(db: Session, organization_id: str, key: str) -> AssistantMemory:
    row = db.scalar(select(AssistantMemory).where(
        AssistantMemory.organization_id == organization_id, AssistantMemory.memory_key == key,
    ))
    if row is None:
        seed_memory(db, organization_id)
        row = db.scalar(select(AssistantMemory).where(
            AssistantMemory.organization_id == organization_id, AssistantMemory.memory_key == key,
        ))
    if row is None:  # pragma: no cover - seeded catalogue is complete
        raise LookupError(key)
    return row


_LOOKUP_NOISE = frozenset("""
price prices rate rates unit cost costs how much does is are what the a an of
for on in to by from with about show list find search lookup look get give tell
me all any my our this that these those related spend spent item items detail
details breakdown summary register report current latest catalogue catalog quote
tariff po well wells
""".split())


def _extract_search_terms(question: str, *, keep_category_words: bool = False) -> list[str]:
    """Extract substantive search tokens (codes, sizes, names, keywords)."""
    category_words = frozenset({
        "tangible", "tangibles", "consumable", "consumables", "chemical", "chemicals",
        "additive", "additives", "fuel", "fuels", "bit", "bits", "drill", "service",
        "services", "vendor", "vendors", "lih", "ndt", "inspection", "inspections",
    })
    raw_tokens = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9._/\-]*", question)
    terms: list[str] = []
    seen: set[str] = set()
    for raw in raw_tokens:
        low = raw.casefold().strip(".,?!:;\"'()")
        if not low or low in STOPWORDS or low in _LOOKUP_NOISE:
            continue
        if not keep_category_words and low in category_words:
            continue
        if len(low) < 2 and not any(ch.isdigit() for ch in low):
            continue
        if low not in seen:
            seen.add(low)
            terms.append(low)
    return terms


def _matches_any(columns: list[Any], terms: list[str]):
    """SQLAlchemy OR-predicate matching any search term against any text column."""
    clauses = [col.ilike(f"%{term}%") for term in terms for col in columns]
    return or_(*clauses) if clauses else None


def _rate_display(unit_rate: Any, final_cost: Any, currency: str, uom: str) -> str:
    effective = final_cost if final_cost is not None and Decimal(str(final_cost)) > 0 else unit_rate
    prefix = f"{currency} " if currency else ""
    suffix = f" / {uom}" if uom else ""
    return f"{prefix}{_money(effective)}{suffix}"


def _answer_price_lookup(
    db: Session, organization_id: str, question: str, permissions: set[str],
) -> AssistantAnswer:
    """Return live master-data prices (tangibles, consumables, services) and recent booked rates."""
    can_master = _can(permissions, "master-data:read")
    can_daily = _can(permissions, "daily-cost:read")
    if not can_master and not can_daily:
        return _permission_answer("master-data:read")

    q_low = question.casefold()
    terms = _extract_search_terms(question, keep_category_words=False)
    want_tangibles = any(w in q_low for w in ("tangible", "casing", "tubing", "wellhead", "liner", "hanger", "packer", "christmas tree"))
    want_bits = any(w in q_low for w in ("drill bit", "bit ", "bits", "pdc", "tricone"))
    want_mud = any(w in q_low for w in ("mud", "chemical", "barite", "bentonite", "polymer", "brine", "kcl", "consumable"))
    want_cement = any(w in q_low for w in ("cement", "additive", "retarder", "accelerator", "spacer", "consumable"))
    want_fuel = any(w in q_low for w in ("fuel", "diesel", "ago", "hsd", "gasoil", "consumable"))
    want_services = any(w in q_low for w in ("service", "vendor", "contractor", "rig rate", "day rate", "standby"))
    search_all_categories = not any((want_tangibles, want_bits, want_mud, want_cement, want_fuel, want_services))
    if search_all_categories:
        want_tangibles = want_bits = want_mud = want_cement = want_fuel = want_services = True

    catalogue_rows: list[list[str]] = []
    service_rows: list[list[str]] = []
    booked_rows: list[list[str]] = []

    if can_master:
        if want_tangibles:
            stmt = select(Tangible).where(
                Tangible.organization_id == organization_id, Tangible.is_deleted.is_(False),
            )
            pred = _matches_any(
                [Tangible.tangible_code, Tangible.tangible_name, Tangible.scope, Tangible.po_number, Tangible.remarks],
                terms,
            )
            if pred is not None:
                stmt = stmt.where(pred)
            for item in db.scalars(stmt.order_by(Tangible.tangible_name).limit(12)).all():
                uplift = f"{Decimal(item.cost_uplift):,.1f}%" if item.cost_uplift is not None else "—"
                catalogue_rows.append([
                    "Tangible",
                    f"{item.tangible_code} · {item.tangible_name}",
                    f"{item.currency} {_money(item.unit_rate)}" if item.currency else _money(item.unit_rate),
                    uplift,
                    _rate_display(item.unit_rate, item.final_cost, item.currency, item.uom),
                    item.effective_date.isoformat() if item.effective_date else "—",
                ])

        if want_bits:
            stmt = select(DrillBit).where(
                DrillBit.organization_id == organization_id, DrillBit.is_deleted.is_(False),
            )
            pred = _matches_any(
                [DrillBit.bit_code, DrillBit.bit_name, DrillBit.model_no, DrillBit.size, DrillBit.iadc_code, DrillBit.remarks],
                terms,
            )
            if pred is not None:
                stmt = stmt.where(pred)
            for item in db.scalars(stmt.order_by(DrillBit.bit_name).limit(10)).all():
                uplift = f"{Decimal(item.cost_uplift):,.1f}%" if item.cost_uplift is not None else "—"
                catalogue_rows.append([
                    "Drill Bit",
                    f"{item.bit_code} · {item.bit_name} ({item.size})",
                    f"{item.currency} {_money(item.unit_rate)}" if item.currency else _money(item.unit_rate),
                    uplift,
                    _rate_display(item.unit_rate, item.final_cost, item.currency, ""),
                    item.effective_date.isoformat() if item.effective_date else "—",
                ])

        if want_mud:
            stmt = select(MudChemical).where(
                MudChemical.organization_id == organization_id, MudChemical.is_deleted.is_(False),
            )
            pred = _matches_any(
                [MudChemical.chemical_code, MudChemical.chemical_name, MudChemical.part_number, MudChemical.remarks],
                terms,
            )
            if pred is not None:
                stmt = stmt.where(pred)
            for item in db.scalars(stmt.order_by(MudChemical.chemical_name).limit(10)).all():
                catalogue_rows.append([
                    "Mud Chemical",
                    f"{item.chemical_code} · {item.chemical_name}",
                    f"{item.currency} {_money(item.unit_rate)}" if item.currency else _money(item.unit_rate),
                    "—",
                    _rate_display(item.unit_rate, item.final_cost, item.currency, item.uom),
                    item.effective_date.isoformat() if item.effective_date else "—",
                ])

        if want_cement:
            stmt = select(CementAdditive).where(
                CementAdditive.organization_id == organization_id, CementAdditive.is_deleted.is_(False),
            )
            pred = _matches_any(
                [CementAdditive.additive_code, CementAdditive.additive_name, CementAdditive.part_number, CementAdditive.remarks],
                terms,
            )
            if pred is not None:
                stmt = stmt.where(pred)
            for item in db.scalars(stmt.order_by(CementAdditive.additive_name).limit(10)).all():
                catalogue_rows.append([
                    "Cement Additive",
                    f"{item.additive_code} · {item.additive_name}",
                    f"{item.currency} {_money(item.unit_rate)}" if item.currency else _money(item.unit_rate),
                    "—",
                    _rate_display(item.unit_rate, item.final_cost, item.currency, item.uom),
                    item.effective_date.isoformat() if item.effective_date else "—",
                ])

        if want_fuel:
            stmt = select(FuelType).where(
                FuelType.organization_id == organization_id, FuelType.is_deleted.is_(False),
            )
            pred = _matches_any([FuelType.fuel_code, FuelType.fuel_name, FuelType.remarks], terms)
            if pred is not None:
                stmt = stmt.where(pred)
            for item in db.scalars(stmt.order_by(FuelType.fuel_name).limit(10)).all():
                catalogue_rows.append([
                    "Fuel",
                    f"{item.fuel_code} · {item.fuel_name}",
                    f"{item.currency} {_money(item.unit_rate)}" if item.currency else _money(item.unit_rate),
                    "—",
                    _rate_display(item.unit_rate, item.final_cost, item.currency, item.uom),
                    item.effective_date.isoformat() if item.effective_date else "—",
                ])

        if want_services and terms:
            stmt = select(Service).outerjoin(Vendor, Service.vendor_id == Vendor.id).where(
                Service.organization_id == organization_id, Service.is_deleted.is_(False),
            )
            pred = _matches_any(
                [Service.service_code, Service.service_name, Service.service_group, Vendor.vendor_name],
                terms,
            )
            if pred is not None:
                stmt = stmt.where(pred)
            for svc in db.scalars(stmt.order_by(Service.service_name).limit(10)).all():
                vendor_label = svc.vendor.vendor_name if svc.vendor else svc.provider_type
                service_rows.append([
                    f"{svc.service_code} · {svc.service_name}",
                    svc.service_group,
                    vendor_label,
                    svc.service_category,
                ])

    if can_daily and terms:
        for label, model, code_col, name_col in (
            ("Service", DailyCostServiceLine, DailyCostServiceLine.service_code_snapshot, DailyCostServiceLine.service_name_snapshot),
            ("Tangible", DailyCostTangibleLine, DailyCostTangibleLine.tangible_code_snapshot, DailyCostTangibleLine.tangible_name_snapshot),
            ("Consumable", DailyCostConsumableLine, DailyCostConsumableLine.item_code_snapshot, DailyCostConsumableLine.item_name_snapshot),
        ):
            pred = _matches_any([code_col, name_col, model.remarks], terms)
            if pred is None:
                continue
            rows = db.execute(
                select(
                    DailyCostEntry.well_code_snapshot,
                    name_col,
                    func.max(func.coalesce(model.override_rate, model.captured_rate)),
                    func.sum(model.standard_amount),
                    func.count(model.id),
                    func.max(DailyCostEntry.standard_currency),
                )
                .join(DailyCostEntry, DailyCostEntry.id == model.entry_id)
                .where(
                    model.organization_id == organization_id,
                    DailyCostEntry.is_deleted.is_(False),
                    pred,
                )
                .group_by(DailyCostEntry.well_code_snapshot, name_col)
                .order_by(func.sum(model.standard_amount).desc())
                .limit(6)
            ).all()
            for well_code, item_name, max_rate, total_amt, cnt, curr in rows:
                booked_rows.append([
                    label,
                    well_code,
                    item_name,
                    f"{curr} {_money(max_rate)}",
                    f"{curr} {_money(total_amt)} ({cnt} line{'s' if cnt != 1 else ''})",
                ])

    tables: list[AssistantTable] = []
    if catalogue_rows:
        tables.append(AssistantTable(
            title="Catalogue rates (Master Data)",
            columns=["Category", "Item", "PO / Unit Rate", "Uplift", "Effective Rate", "Effective Date"],
            rows=catalogue_rows[:20],
            note=(
                f"Showing {min(len(catalogue_rows), 20)} matching item(s) from the workspace catalogue."
                if len(catalogue_rows) > 20 else ""
            ),
        ))
    if service_rows:
        tables.append(AssistantTable(
            title="Matching services",
            columns=["Service", "Service Group", "Provider / Vendor", "Category"],
            rows=service_rows[:12],
        ))
    if booked_rows:
        tables.append(AssistantTable(
            title="Recorded daily cost rates & spend",
            columns=["Group", "Well", "Item", "Recorded Rate", "Total Recorded"],
            rows=booked_rows[:15],
        ))

    total_hits = len(catalogue_rows) + len(service_rows) + len(booked_rows)
    if total_hits == 0:
        query_desc = ", ".join(terms) if terms else "that category"
        return AssistantAnswer(
            answer=(
                f"No priced catalogue item, service or recorded cost line matched \"{query_desc}\" "
                "in this workspace. Check the item code or name in Master Data, or try a shorter keyword."
            ),
            intent="price_lookup",
            confidence="medium",
            category="navigation",
            sources=[AssistantSource(label="Master Data catalogue", route="/master-data")],
            follow_ups=["List tangibles", "List consumables", "What is missing in my workspace?"],
        )

    facts: list[AssistantFact] = []
    if catalogue_rows:
        first = catalogue_rows[0]
        facts.append(AssistantFact(
            label=f"Top catalogue match ({first[0]})",
            value=f"{first[1]} — {first[4]}",
            hint=f"Effective {first[5]}" if first[5] != "—" else "Master Data rate",
            route="/master-data",
        ))
    facts.append(AssistantFact(
        label="Matched records",
        value=f"{len(catalogue_rows)} catalogue · {len(service_rows)} service · {len(booked_rows)} recorded usage",
    ))
    sources = []
    if can_master:
        sources.append(AssistantSource(label="Master Data catalogue", route="/master-data"))
    if can_daily:
        sources.append(AssistantSource(label="Daily Cost register", route="/daily-cost"))
    summary_label = f" for \"{' '.join(terms)}\"" if terms else ""
    return AssistantAnswer(
        answer=(
            f"Found {len(catalogue_rows)} catalogue rate(s), {len(service_rows)} service definition(s), and "
            f"{len(booked_rows)} recorded daily-cost usage match(es){summary_label} in this workspace."
        ),
        intent="price_lookup",
        confidence="high",
        category="navigation",
        facts=facts,
        tables=tables,
        sources=sources,
        follow_ups=["List tangibles", "List consumables", "What is missing in my workspace?"],
    )


def _answer_cost_search(
    db: Session, organization_id: str, question: str, permissions: set[str], *, explicit: bool = True,
) -> AssistantAnswer | None:
    """Search across daily cost lines, LIH, NDT, catalogue, services/vendors and AFEs by keyword."""
    can_daily = _can(permissions, "daily-cost:read")
    can_master = _can(permissions, "master-data:read")
    can_afe = _can(permissions, "afe:read")
    can_wells = _can(permissions, "rig-well:read")
    if explicit and not any((can_daily, can_master, can_afe, can_wells)):
        return _permission_answer("daily-cost:read")

    terms = _extract_search_terms(question, keep_category_words=True)
    if not terms:
        if not explicit:
            return None
        return AssistantAnswer(
            answer=(
                "Include a keyword to search across your workspace costs — for example "
                "\"search costs for casing\", \"costs related to barite\", or \"LIH costs\"."
            ),
            intent="cost_search",
            confidence="medium",
            category="navigation",
            follow_ups=["Price of tangibles", "What is missing in my workspace?"],
        )

    daily_rows: list[list[str]] = []
    daily_total = Decimal("0")
    daily_curr = ""
    lih_rows: list[list[str]] = []
    ndt_rows: list[list[str]] = []
    catalogue_rows: list[list[str]] = []
    afe_rows: list[list[str]] = []
    matched_well = _find_well(db, organization_id, question) if can_wells else None

    if can_daily:
        for grp, model, code_col, name_col in (
            ("Services", DailyCostServiceLine, DailyCostServiceLine.service_code_snapshot, DailyCostServiceLine.service_name_snapshot),
            ("Tangibles", DailyCostTangibleLine, DailyCostTangibleLine.tangible_code_snapshot, DailyCostTangibleLine.tangible_name_snapshot),
            ("Consumables", DailyCostConsumableLine, DailyCostConsumableLine.item_code_snapshot, DailyCostConsumableLine.item_name_snapshot),
            ("Other Expenses", DailyCostOtherExpenseLine, DailyCostOtherExpenseLine.expense_type_label, DailyCostOtherExpenseLine.expense_description),
        ):
            pred = _matches_any([code_col, name_col, model.remarks, DailyCostEntry.well_code_snapshot, DailyCostEntry.well_name_snapshot], terms)
            if pred is None:
                continue
            stmt = (
                select(
                    DailyCostEntry.well_code_snapshot,
                    name_col,
                    func.sum(model.standard_amount),
                    func.count(model.id),
                    func.max(DailyCostEntry.cost_date),
                    func.max(DailyCostEntry.standard_currency),
                )
                .join(DailyCostEntry, DailyCostEntry.id == model.entry_id)
                .where(
                    model.organization_id == organization_id,
                    DailyCostEntry.is_deleted.is_(False),
                    pred,
                )
            )
            if matched_well is not None:
                stmt = stmt.where(DailyCostEntry.well_id == matched_well.id)
            rows = db.execute(
                stmt.group_by(DailyCostEntry.well_code_snapshot, name_col)
                .order_by(func.sum(model.standard_amount).desc())
                .limit(8)
            ).all()
            for well_code, item_name, amt, cnt, last_dt, curr in rows:
                amt_dec = Decimal(str(amt or 0))
                daily_total += amt_dec
                if curr and not daily_curr:
                    daily_curr = curr
                daily_rows.append([
                    well_code,
                    grp,
                    item_name or "—",
                    str(cnt),
                    last_dt.isoformat() if last_dt else "—",
                    f"{curr} {_money(amt_dec)}",
                ])

        lih_pred = _matches_any(
            [LihCostLine.item_description, LihCostLine.serial_number, LihCostLine.remarks,
             LihCostEntry.well_code_snapshot, LihCostEntry.remarks],
            terms,
        )
        lih_query = (
            select(LihCostEntry.well_code_snapshot, LihCostEntry.cost_date, LihCostLine.item_description,
                   LihCostLine.no_of_units, LihCostLine.total_cost, LihCostEntry.currency)
            .join(LihCostEntry, LihCostEntry.id == LihCostLine.entry_id)
            .where(LihCostEntry.organization_id == organization_id, LihCostEntry.is_deleted.is_(False))
        )
        if "lih" not in terms and lih_pred is not None:
            lih_query = lih_query.where(lih_pred)
        if matched_well is not None:
            lih_query = lih_query.where(LihCostEntry.well_id == matched_well.id)
        for well_code, dt, desc, units, cost, curr in db.execute(lih_query.order_by(LihCostEntry.cost_date.desc()).limit(10)).all():
            lih_rows.append([well_code, dt.isoformat(), desc, f"{Decimal(units):,.3f}", f"{curr} {_money(cost)}"])

        ndt_pred = _matches_any(
            [NdtInspection.description, NdtInspection.remarks, NdtInspection.well_code_snapshot],
            terms,
        )
        ndt_query = select(NdtInspection).where(
            NdtInspection.organization_id == organization_id, NdtInspection.is_deleted.is_(False),
        )
        if "ndt" not in terms and "inspection" not in terms and ndt_pred is not None:
            ndt_query = ndt_query.where(ndt_pred)
        if matched_well is not None:
            ndt_query = ndt_query.where(NdtInspection.well_id == matched_well.id)
        for ndt in db.scalars(ndt_query.order_by(NdtInspection.created_at.desc()).limit(10)).all():
            ndt_rows.append([
                ndt.well_code_snapshot,
                ndt.scope.title(),
                ndt.description,
                f"{Decimal(ndt.quantity_received):,.0f}",
                f"{Decimal(ndt.quantity_consumed):,.0f}",
                f"{Decimal(ndt.quantity_backloaded_good):,.0f} / {Decimal(ndt.quantity_backloaded_bad):,.0f}",
            ])

    if can_master:
        for label, model, code_col, name_col, uom_col in (
            ("Tangible", Tangible, Tangible.tangible_code, Tangible.tangible_name, Tangible.uom),
            ("Mud Chemical", MudChemical, MudChemical.chemical_code, MudChemical.chemical_name, MudChemical.uom),
            ("Cement Additive", CementAdditive, CementAdditive.additive_code, CementAdditive.additive_name, CementAdditive.uom),
            ("Fuel", FuelType, FuelType.fuel_code, FuelType.fuel_name, FuelType.uom),
        ):
            pred = _matches_any([code_col, name_col, model.remarks], terms)
            if pred is None:
                continue
            for item in db.scalars(
                select(model).where(model.organization_id == organization_id, model.is_deleted.is_(False), pred).limit(6)
            ).all():
                catalogue_rows.append([
                    label,
                    f"{getattr(item, code_col.key)} · {getattr(item, name_col.key)}",
                    _rate_display(item.unit_rate, item.final_cost, item.currency, getattr(item, uom_col.key)),
                    item.effective_date.isoformat() if item.effective_date else "—",
                ])

    if can_afe:
        from app.services import afe as afe_service

        lowered_terms = [t.lower() for t in terms]
        for afe_out in afe_service.list_afes(db, organization_id, deleted=False):
            hay = f"{afe_out.afe_code} {afe_out.afe_name} {afe_out.well_code} {afe_out.remarks}".lower()
            if any(term in hay for term in lowered_terms):
                amount = afe_out.adjusted_total if afe_out.has_sow_adjustment and afe_out.adjusted_total is not None else afe_out.total_cost
                afe_rows.append([
                    f"{afe_out.afe_code} · {afe_out.afe_name}",
                    (afe_out.configuration_scope or "").title() or "—",
                    afe_out.status.title(),
                    f"{afe_out.standard_currency} {_money(amount)}".strip(),
                ])
                if len(afe_rows) >= 8:
                    break

    total_hits = len(daily_rows) + len(lih_rows) + len(ndt_rows) + len(catalogue_rows) + len(afe_rows)
    if total_hits == 0:
        if not explicit:
            return None
        return AssistantAnswer(
            answer=(
                f"No recorded costs, LIH entries, NDT inspections, catalogue items or AFEs matched "
                f"\"{' '.join(terms)}\" in the modules you may read."
            ),
            intent="cost_search",
            confidence="medium",
            category="navigation",
            sources=[AssistantSource(label="Daily Cost register", route="/daily-cost")],
            follow_ups=["What is missing in my workspace?", "List tangibles"],
        )

    tables: list[AssistantTable] = []
    if daily_rows:
        tables.append(AssistantTable(
            title="Matching daily cost lines",
            columns=["Well", "Group", "Item", "Lines", "Last Date", "Total Recorded"],
            rows=daily_rows[:18],
        ))
    if catalogue_rows:
        tables.append(AssistantTable(
            title="Matching catalogue prices",
            columns=["Category", "Item", "Effective Rate", "Effective Date"],
            rows=catalogue_rows[:15],
        ))
    if lih_rows:
        tables.append(AssistantTable(
            title="Lost In Hole (LIH) register matches",
            columns=["Well", "Date", "Item Description", "Units", "Total Cost"],
            rows=lih_rows[:10],
        ))
    if ndt_rows:
        tables.append(AssistantTable(
            title="NDT Inspection register matches",
            columns=["Well", "Scope", "Description", "Received", "Consumed", "Backloaded (G/B)"],
            rows=ndt_rows[:10],
        ))
    if afe_rows:
        tables.append(AssistantTable(
            title="Matching AFEs",
            columns=["AFE", "Scope", "Status", "Total Amount"],
            rows=afe_rows[:8],
        ))

    facts: list[AssistantFact] = []
    if daily_rows:
        facts.append(AssistantFact(
            label="Matched daily cost spend",
            value=f"{daily_curr} {_money(daily_total)}".strip(),
            hint=f"Across {len(daily_rows)} matched item group(s)",
            route="/daily-cost",
        ))
    if catalogue_rows:
        facts.append(AssistantFact(
            label="Catalogue rate matches",
            value=str(len(catalogue_rows)),
            route="/master-data",
        ))
    if lih_rows:
        facts.append(AssistantFact(label="LIH matches", value=str(len(lih_rows)), route="/daily-cost/lih-register"))
    if ndt_rows:
        facts.append(AssistantFact(label="NDT matches", value=str(len(ndt_rows)), route="/daily-cost/ndt-inspections"))

    sources: list[AssistantSource] = []
    if daily_rows:
        sources.append(AssistantSource(label="Daily Cost register", route="/daily-cost"))
    if catalogue_rows:
        sources.append(AssistantSource(label="Master Data catalogue", route="/master-data"))
    if lih_rows:
        sources.append(AssistantSource(label="LIH Cost Register", route="/daily-cost/lih-register"))
    if ndt_rows:
        sources.append(AssistantSource(label="NDT Inspection Register", route="/daily-cost/ndt-inspections"))
    if afe_rows:
        sources.append(AssistantSource(label="AFE Register", route="/afe"))

    return AssistantAnswer(
        answer=(
            f"Found {total_hits} workspace record(s) matching \"{' '.join(terms)}\""
            + (f" — recorded daily cost total {daily_curr} {_money(daily_total)}." if daily_rows else ".")
        ),
        intent="cost_search",
        confidence="high",
        category="navigation",
        facts=facts,
        tables=tables,
        sources=sources,
        follow_ups=["What is missing in my workspace?", "List tangibles", "List consumables"],
    )


def _knowledge_answer(
    db: Session,
    organization_id: str,
    question: str,
    route: str,
    permissions: set[str],
) -> AssistantAnswer:
    rows = db.scalars(select(AssistantMemory).where(
        AssistantMemory.organization_id == organization_id,
        AssistantMemory.is_active.is_(True),
    )).all()
    scored = sorted(
        ((_knowledge_score(row, question, route, permissions), row) for row in rows),
        key=lambda item: (-item[0], item[1].sort_order),
    )
    best_score, best = scored[0] if scored else (0.0, None)
    if best is None or best_score < 2.0:
        # Before giving up, check if the question refers directly to a well,
        # catalogue item, service, LIH/NDT record or cost keyword in this workspace.
        if _can(permissions, "daily-cost:read") and _find_well(db, organization_id, question) is not None:
            return _answer_cost_position(db, organization_id, question, permissions)
        live_hit = _answer_cost_search(db, organization_id, question, permissions, explicit=False)
        if live_hit is not None:
            return live_hit
        options = "\n".join(
            f"• {row.title}" for row in rows
            if _can(permissions, row.permission) and row.is_active
        )
        return AssistantAnswer(
            answer=(
                "I could not match that to the application memory I am allowed to use. I answer about "
                "this application's workflows, calculations, data entry and navigation — for example "
                "\"how are actual days calculated?\", \"what is missing in my workspace?\", "
                "\"AFE balance on WELL-01\", or \"price of tangibles\".\n\nTopics in memory:\n" + options[:1800]
            ),
            intent="knowledge",
            confidence="low",
            category="faq",
            follow_ups=["What is missing in my workspace?", "How are actual days calculated?", "List tangibles"],
        )
    answer = _answer_from_memory(best, reason="matched")
    if best.permission and not _can(permissions, best.permission):
        return _permission_answer(best.permission)
    # Related entries the caller may read, so the answer can be followed up.
    related = [
        AssistantSource(label=row.title, route=row.route or "/")
        for score, row in scored[1:4]
        if score > 0 and row.is_active and _can(permissions, row.permission) and row.route
    ]
    answer.sources = answer.sources + [source for source in related if source not in answer.sources]
    return answer


def _maybe_well_comparison(
    db: Session,
    organization_id: str,
    question: str,
    permissions: set[str],
) -> tuple[AssistantAnswer | None, list[Well], list[str], Any]:
    """Detect and answer single/multi-well comparisons with exact Decimal figures."""
    from app.services import ai_context

    wants_compare = ai_context.is_comparison_question(question)
    lower = question.lower()
    asks_well_topic = wants_compare or any(
        k in lower for k in ("well", "cost", "afe", "budget", "spend", "actual", "balance", "npt", "upa", "lih", "mud")
    )
    if not (_can(permissions, "daily-cost:read") or _can(permissions, "rig-well:read")):
        if wants_compare and "well" in lower:
            return _permission_answer("daily-cost:read"), [], [], None
        return None, [], [], None

    matched_wells, unmatched_wells = ai_context.find_well_mentions(db, organization_id, question)
    asks_all_wells_compare = wants_compare and any(
        phrase in lower for phrase in ("all wells", "active wells", "every well", "our wells", "wells in")
    )
    should_compare = (
        len(matched_wells) >= 2
        or (wants_compare and bool(unmatched_wells))
        or asks_all_wells_compare
    )
    if not should_compare and not (matched_wells and asks_well_topic):
        return None, matched_wells, unmatched_wells, None

    if should_compare and not _can(permissions, "daily-cost:read"):
        return _permission_answer("daily-cost:read"), matched_wells, unmatched_wells, None

    all_wells = list(
        db.scalars(
            select(Well)
            .where(Well.organization_id == organization_id, Well.is_deleted.is_(False))
            .order_by(Well.well_code)
        ).all()
    )
    all_labels = [_well_label(w) for w in all_wells]

    if should_compare:
        target_wells = list(matched_wells)
        if not target_wells and asks_all_wells_compare:
            active_only = [w for w in all_wells if w.status == "active"] if "active wells" in lower else all_wells
            target_wells = (active_only or all_wells)[: ai_context.MAX_COMPARED_WELLS]
        if not target_wells:
            missing = ", ".join(f"'{u}'" for u in unmatched_wells)
            available = ", ".join(all_labels[:10]) or "none recorded yet"
            return (
                AssistantAnswer(
                    answer=(
                        f"No well in this workspace matched {missing}. "
                        f"Available wells: {available}. Name two workspace wells to compare their total cost, AFE budget and variance."
                    ),
                    intent="well_comparison",
                    confidence="medium",
                    category="calculation",
                    sources=[AssistantSource(label="Well cost comparison", route="/reports/well-cost-comparison")],
                    follow_ups=["What is missing in my workspace?", "How is the AFE balance calculated?"],
                ),
                matched_wells,
                unmatched_wells,
                None,
            )
        comp = ai_context.build_well_comparison(
            db,
            organization_id,
            target_wells,
            unmatched=unmatched_wells,
            all_well_labels=all_labels,
        )
        return (
            AssistantAnswer(
                answer=comp.prose,
                intent="well_comparison",
                confidence="high",
                category="calculation",
                facts=comp.facts,
                tables=comp.tables,
                sources=comp.sources,
                follow_ups=comp.follow_ups,
            ),
            target_wells,
            unmatched_wells,
            comp,
        )

    # Single matched well context (for AI grounding even when an existing single-well handler answers).
    if _can(permissions, "daily-cost:read") and len(matched_wells) == 1:
        comp = ai_context.build_well_comparison(
            db,
            organization_id,
            matched_wells,
            unmatched=unmatched_wells,
            all_well_labels=all_labels,
        )
        return None, matched_wells, unmatched_wells, comp
    return None, matched_wells, unmatched_wells, None


def _default_ai_sources(question: str, permissions: set[str]) -> list[AssistantSource]:
    lower = question.lower()
    out: list[AssistantSource] = []
    candidates = (
        (("invoice", "idvs", "epicor", "payable"), "invoice-processing:read", "Invoice Processing", "/invoice-processing"),
        (("fuel", "ago", "diesel", "rig saving"), "daily-cost:read", "Fuel Cost Register", "/daily-cost/fuel-cost-register"),
        (("mud", "obm", "wbm", "sobm", "bbl"), "daily-cost:read", "Mud Cost Analysis", "/daily-cost/mud-cost-analysis"),
        (("lih", "lost in hole", "fish"), "daily-cost:read", "LIH Cost Register", "/daily-cost/lih-register"),
        (("ndt", "inspection", "backload"), "daily-cost:read", "NDT Inspection Register", "/daily-cost/ndt-inspections"),
        (("anomal", "spike", "drift", "health", "intelligence"), "cost-intelligence:read", "Cost Intelligence", "/reports/cost-intelligence"),
        (("afe", "sow", "estimate"), "afe:read", "AFE Register", "/afe/register"),
        (("vendor", "supplier", "po", "so"), "master-data:read", "Vendors & PO/SO", "/master-data/vendors"),
        (("well", "cost", "budget", "npt", "upa"), "daily-cost:read", "Well Cost Comparison", "/reports/well-cost-comparison"),
    )
    for needles, perm, label, page_route in candidates:
        if _can(permissions, perm) and any(n in lower for n in needles):
            out.append(AssistantSource(label=label, route=page_route))
        if len(out) >= 3:
            break
    return out


def _matching_ai_memories(
    db: Session, organization_id: str, question: str, route: str, permissions: set[str], *, workspace_only: bool = False,
) -> list[AssistantMemory]:
    stmt = select(AssistantMemory).where(
        AssistantMemory.organization_id == organization_id,
        AssistantMemory.is_active.is_(True),
    )
    if workspace_only:
        stmt = stmt.where(AssistantMemory.is_system.is_(False))
    mem_rows = db.scalars(stmt).all()
    return [
        row
        for score, row in sorted(
            ((_knowledge_score(r, question, route, permissions), r) for r in mem_rows if _can(permissions, r.permission)),
            key=lambda item: (-item[0], item[1].sort_order),
        )
        if score >= 1.5
    ][:5]


def _enrich_with_ollama(
    db: Session,
    organization_id: str,
    *,
    user: User,
    question: str,
    route: str,
    permissions: set[str],
    base: AssistantAnswer,
    matched_wells: list[Well],
    unmatched_wells: list[str],
    comparison: Any,
) -> AssistantAnswer:
    """Invoke the configured LAN Ollama model over verified workspace context."""
    from app.core.config import get_settings
    from app.services import ai_context, ai_knowledge, ollama as ollama_service

    if base.intent == "permission":
        return base

    top_memories = _matching_ai_memories(db, organization_id, question, route, permissions)

    dossier = ai_context.build_assistant_dossier(
        db,
        organization_id,
        user=user,
        question=question,
        route=route,
        capabilities=permissions,
        matched_memories=top_memories,
        focus_wells=matched_wells,
        unmatched_wells=unmatched_wells,
        comparison=comparison,
    )
    cfg = get_settings()
    references = ai_knowledge.retrieve(cfg.ai_knowledge_directory, organization_id, question)
    user_prompt = (
        f"USER QUESTION: {question}\n\n"
        f"{ai_knowledge.verified_context(base)}"
        f"{ai_knowledge.prompt_context(references)}\n"
        f"VERIFIED WORKSPACE DATABASE CONTEXT & WELLCOSTIQ WORKFLOW & MEMORY:\n{dossier}"
    )
    try:
        reply = ollama_service.chat(
            system_prompt=ai_context.ASSISTANT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            settings=cfg,
        )
    except ollama_service.OllamaCommunicationError as exc:
        return base.model_copy(
            update={
                "ai_used": False,
                "ai_model": exc.model,
                "ai_error": exc.message,
                "ai_error_code": exc.code,
            }
        )

    sources = list(base.sources) or _default_ai_sources(question, permissions)
    sources.extend(AssistantSource(label=p.citation, route="") for p in references)
    facts = list(base.facts)
    tables = list(base.tables)
    if comparison is not None and not tables and base.intent not in ("price_lookup", "cost_search"):
        tables = list(comparison.tables)
        if not facts:
            facts = list(comparison.facts)
        for src in comparison.sources:
            if src not in sources:
                sources.append(src)

    confidence = "high" if (facts or tables or top_memories or base.confidence == "high") else "medium"
    return base.model_copy(
        update={
            "answer": reply.content,
            "verified_answer": base.answer if base.facts or base.tables else "",
            "confidence": confidence,
            "facts": facts,
            "tables": tables,
            "sources": sources,
            "ai_used": True,
            "ai_model": reply.model,
            "ai_duration_ms": reply.duration_ms,
            "ai_error": "",
            "ai_error_code": "",
        }
    )


def ask(
    db: Session,
    organization_id: str,
    user: User,
    question: str,
    *,
    route: str = "",
    save: bool = True,
    use_ai: bool = False,
) -> AssistantAnswer:
    """Answer one question from memory, workspace figures, and optional LAN Ollama AI."""
    permissions = _permissions(user)
    if not _can(permissions, "assistant:read"):
        return _permission_answer("assistant:read")
    text = " ".join(question.strip().split())
    if not text:
        return AssistantAnswer(
            answer="Ask me about a workflow, a calculation, where a screen lives, or a specific well.",
            intent="knowledge", confidence="low", category="faq",
            follow_ups=["How are actual days calculated?", "What is missing in my workspace?"],
        )
    seed_memory(db, organization_id)
    intent = _detect_intent(text)
    matched_wells: list[Well] = []
    unmatched_wells: list[str] = []
    comparison: Any = None
    operations = operations_answer(text, route, permissions, db=db, organization_id=organization_id)
    try:
        if operations is not None:
            answer = operations
        else:
            # Costing and workspace analysis stay separate from Well Operations.
            comp_answer, matched_wells, unmatched_wells, comparison = _maybe_well_comparison(
                db, organization_id, text, permissions
            )
            if comp_answer is not None:
                answer = comp_answer
            elif intent == "data_health":
                answer = _answer_data_health(db, organization_id, permissions)
            elif intent == "price_lookup":
                answer = _answer_price_lookup(db, organization_id, text, permissions)
            elif intent == "cost_search":
                answer = _answer_cost_search(db, organization_id, text, permissions, explicit=True) or _knowledge_answer(
                    db, organization_id, text, route, permissions
                )
            elif intent == "status" and _can(permissions, "rig-well:read"):
                answer = _answer_status(db, organization_id)
            elif intent == "actual_days" and _can(permissions, "daily-cost:read"):
                answer = _answer_actual_days(db, organization_id, text)
            elif intent == "forecast" and _can(permissions, "daily-cost:read"):
                answer = _answer_forecast(db, organization_id, text)
            elif intent == "out_of_scope" and _can(permissions, "daily-cost:read"):
                answer = _answer_out_of_scope(db, organization_id, text)
            elif intent == "npt_upa" and _can(permissions, "daily-cost:read"):
                answer = _answer_npt_upa(db, organization_id, text)
            elif intent == "cost_position" and _can(permissions, "daily-cost:read"):
                if len(matched_wells) == 1 and comparison is not None and unmatched_wells:
                    answer = AssistantAnswer(
                        answer=comparison.prose,
                        intent="cost_position",
                        confidence="high",
                        category="calculation",
                        facts=comparison.facts,
                        tables=comparison.tables,
                        sources=comparison.sources,
                        follow_ups=comparison.follow_ups,
                    )
                else:
                    answer = _answer_cost_position(db, organization_id, text, permissions)
            elif intent in ("actual_days", "forecast", "out_of_scope", "npt_upa", "cost_position", "status"):
                answer = _permission_answer("daily-cost:read" if intent != "status" else "rig-well:read")
            else:
                if len(matched_wells) == 1 and comparison is not None and any(
                    k in text.lower() for k in ("total cost", "well cost", "cost of", "total spend", "how much")
                ):
                    answer = AssistantAnswer(
                        answer=comparison.prose,
                        intent="cost_position",
                        confidence="high",
                        category="calculation",
                        facts=comparison.facts,
                        tables=comparison.tables,
                        sources=comparison.sources,
                        follow_ups=comparison.follow_ups,
                    )
                else:
                    answer = _knowledge_answer(db, organization_id, text, route, permissions)
    except Exception:  # noqa: BLE001 - a bad stored figure must not break the assistant
        answer = AssistantAnswer(
            answer=(
                "I could not read that figure just now — one of the source records could not be priced. "
                "Open the page itself and check its warnings; the assistant never guesses a number."
            ),
            intent=intent,
            confidence="low",
            category="faq",
        )
    if use_ai and operations is not None:
        from app.core.config import get_settings

        if answer.intent != "permission":
            try:
                from app.services.ai_context import workflow_memory_context
                from app.services.operations.ops_ai import enrich_operations_answer

                cfg = get_settings()
                notes = workflow_memory_context(_matching_ai_memories(
                    db, organization_id, text, route, permissions, workspace_only=True,
                )) if cfg.ollama_enabled else ""
                answer = enrich_operations_answer(
                    db,
                    organization_id,
                    user=user,
                    question=text,
                    permissions=permissions,
                    base=answer,
                    workspace_notes=notes,
                )
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).exception("Unexpected operations assistant AI enrichment error")
                cfg = get_settings()
                answer = answer.model_copy(
                    update={
                        "ai_used": False,
                        "ai_model": cfg.ollama_model,
                        "ai_error": (
                            "AI communication error: failed to complete the Well Operations AI request. "
                            "Verified workspace answer shown below; check server logs and retry."
                        ),
                        "ai_error_code": "server_error",
                    }
                )
    elif use_ai and operations is None:
        try:
            answer = _enrich_with_ollama(
                db,
                organization_id,
                user=user,
                question=text,
                route=route,
                permissions=permissions,
                base=answer,
                matched_wells=matched_wells,
                unmatched_wells=unmatched_wells,
                comparison=comparison,
            )
        except Exception:  # noqa: BLE001 - preserve the verified deterministic answer on any unexpected failure
            import logging
            from app.core.config import get_settings

            logging.getLogger(__name__).exception("Unexpected assistant AI enrichment error")
            cfg = get_settings()
            answer = answer.model_copy(
                update={
                    "ai_used": False,
                    "ai_model": cfg.ollama_model,
                    "ai_error": (
                        "AI communication error: failed to prepare or complete the AI request. "
                        "Verified workspace answer shown below; check server logs and retry."
                    ),
                    "ai_error_code": "server_error",
                }
            )
    if save:
        db.add(AssistantConversation(
            organization_id=organization_id,
            user_id=user.id,
            question=text[:500],
            intent=answer.intent,
            memory_key=answer.memory_key,
            route=route[:200],
        ))
        db.flush()
    return answer


def overview(db: Session, organization_id: str, user: User) -> AssistantOverview:
    permissions = _permissions(user)
    seed_memory(db, organization_id)
    total = db.scalar(select(func.count(AssistantMemory.id)).where(
        AssistantMemory.organization_id == organization_id,
        AssistantMemory.is_active.is_(True),
    )) or 0
    custom = db.scalar(select(func.count(AssistantMemory.id)).where(
        AssistantMemory.organization_id == organization_id,
        AssistantMemory.is_system.is_(False),
    )) or 0
    checks = data_checks(db, organization_id, permissions) if _can(permissions, "assistant:read") else []
    recent = [
        row.question for row in db.scalars(
            select(AssistantConversation)
            .where(
                AssistantConversation.organization_id == organization_id,
                AssistantConversation.user_id == user.id,
            )
            .order_by(AssistantConversation.created_at.desc())
            .limit(5)
        ).all()
    ]
    return AssistantOverview(
        enabled=_can(permissions, "assistant:read"),
        can_manage=_can(permissions, "assistant:manage"),
        memory_entries=int(total),
        workspace_entries=int(custom),
        outstanding_checks=len(checks),
        checks=checks,
        quick_prompts=[
            "Compare all active wells",
            "What should I enter on a daily cost sheet?",
            "How are actual days calculated?",
            "What is missing in my workspace?",
            "List tangibles",
            "List consumables",
            "How is cost attributed to a responsible party?",
            "What counts as out of scope?",
        ],
        recent_questions=recent,
        ai=_ai_overview_status(),
    )


def _ai_overview_status():
    from app.services import ollama as ollama_service

    return ollama_service.check_status(probe=False)


def conversation_history(db: Session, organization_id: str, user: User) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(AssistantConversation)
        .where(
            AssistantConversation.organization_id == organization_id,
            AssistantConversation.user_id == user.id,
        )
        .order_by(AssistantConversation.created_at.desc())
        .limit(TRANSCRIPT_LIMIT)
    ).all()
    return [
        {"question": row.question, "intent": row.intent, "memory_key": row.memory_key,
         "route": row.route, "created_at": row.created_at}
        for row in rows
    ]
