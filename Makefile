.PHONY: test build graph up up-ai seed-admin check-admin ui-check ui-rollback operations-codes-check daily-cost-check daily-cost-scope-check daily-cost-date-check cautions-check entry-checks-check entry-checks-simulation afe-scope-dialog-check afe-print-check well-lifecycle-check mud-cost-reconciliation-check mud-cost-kpi-check lih-worksheet-check fuel-cost-check usage-reports-check templates-check catalogue-check assistant-check chart-drill-check export-report-check cost-intelligence-check ollama-ai-check invoice-config-deleted-check well-visuals-check

test:
	cd backend && ../.venv/bin/python -m pytest -q
build:
	cd frontend && npm run build
graph:
	python3 .agent/tools/graphify.py
up:
	docker compose up --build
up-ai:
	docker compose -f docker-compose.yml -f docker-compose.ollama.yml up --build
seed-admin:
	cd backend && ../.venv/bin/python -m app.seed
check-admin:
	cd backend && ../.venv/bin/python -m app.seed --check
# Render the real theme and shared components in a DOM and assert the design rules
# (light + dark). jsdom is a locked development dependency.
ui-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/ui-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/ui-check.mjs --loader:.jsx=jsx --log-level=error \
		--external:jsdom && node node_modules/.cache/ui-check.mjs
# Restore the pre-design-layer interface. Use it if the enhanced UI is rejected.
ui-rollback:
	bash scripts/ui-rollback.sh

# In-application guide: the answer card shows the sentence, the labelled figures
# with the capability that guards each one, the steps, the proving pages, and it
# refuses honestly (jsdom is a locked dev dependency).
assistant-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/assistant-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/assistant-check.mjs --loader:.jsx=jsx --external:jsdom && \
		node node_modules/.cache/assistant-check.mjs

# Full daily/well printing and list-only register regressions (jsdom is a locked dev dependency).
# Daily cost register: printing, allocations, entry windows and the cost items of
# one service (one entry may bill several AFE cost items, one ledger line each).
daily-cost-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/daily-cost-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/daily-cost-check.mjs --external:jsdom && \
		node node_modules/.cache/daily-cost-check.mjs

# Daily Cost register shortcuts: the current rig and well load as defaults and
# every related register opens already scoped to them (still changeable).
daily-cost-scope-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/daily-cost-scope-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/daily-cost-scope-check.mjs --external:jsdom && \
		node node_modules/.cache/daily-cost-scope-check.mjs

# Draft daily-sheet date correction: dedicated PATCH, preserved unsaved edits,
# duplicate-date conflict, submitted/read-only boundaries.
daily-cost-date-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/daily-cost-date-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/daily-cost-date-check.mjs --external:jsdom && \
		node node_modules/.cache/daily-cost-date-check.mjs

# Dismissible cautions: the per-workspace store, the component, the page's
# "Show dismissed cautions" affordance, expiry when the facts change and the
# transient messages that must never be remembered.
cautions-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/cautions-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/cautions-check.mjs --external:jsdom && \
		node node_modules/.cache/cautions-check.mjs

# Daily-sheet entry checks: findings beside the sheet, applying a suggestion to
# the unsaved sheet only, keeping a value as entered (audited) and reopening it,
# read-only sheets, actions waiting while findings are out of date, a failed
# read, a deployment with the checks turned off, the well card, and the same
# words and actions under the light and the dark theme.
entry-checks-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/entry-checks-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/entry-checks-check.mjs --external:jsdom && \
		node node_modules/.cache/entry-checks-check.mjs

# What the entry checks catch, what they flag by mistake and how often an
# offered correction is the intended value: prints the two tables quoted in
# docs/entry-checks.md. Standard library only, seeded, about a minute. Run it
# after changing a threshold in backend/app/domain/entry_statistics.py.
entry-checks-simulation:
	python3 .agent/tools/entry-checks-simulation.py

# Mud type / Cost/BBL configuration dialog rules (section-scoped reconciliation).
mud-cost-reconciliation-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/mud-cost-reconciliation-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/mud-cost-reconciliation-check.mjs --external:jsdom && \
		node node_modules/.cache/mud-cost-reconciliation-check.mjs

# Mud Cost Analysis: section KPI balances, grouped latest stock/rates and refresh.
mud-cost-kpi-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/mud-cost-kpi-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/mud-cost-kpi-check.mjs --external:jsdom && \
		node node_modules/.cache/mud-cost-kpi-check.mjs

# LIH worksheet: multi-row entry, duplicate, paste, shortcuts and the one-save payload.
lih-worksheet-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/lih-worksheet-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/lih-worksheet-check.mjs --external:jsdom && \
		node node_modules/.cache/lih-worksheet-check.mjs

# Fuel Cost Register: daily AGO/gas entry, company classification and material balance.
fuel-cost-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/fuel-cost-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/fuel-cost-check.mjs --external:jsdom && \
		node node_modules/.cache/fuel-cost-check.mjs

# Reports module: usage/cost matrix, NPT/UPA matrix and the shared filter panel.
usage-reports-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/usage-reports-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/usage-reports-check.mjs --loader:.jsx=jsx --log-level=error \
		--external:jsdom && node node_modules/.cache/usage-reports-check.mjs

# Chart drill-through identity: a plotted point opens the record it was drawn
# from even when the plot is reversed or sorted, and never the neighbouring well.
chart-drill-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/chart-drill-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/chart-drill-check.mjs --loader:.jsx=jsx --external:jsdom && \
		node node_modules/.cache/chart-drill-check.mjs

# Operations code correlations, the 300 m depth axis / completion ordinal axis, the
# lead(+)/lag(-) convention and the permanent delete on Deleted timelines.
.PHONY: operations-codes-check
operations-codes-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/operations-codes-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/operations-codes-check.mjs --loader:.jsx=jsx --external:jsdom && \
		node node_modules/.cache/operations-codes-check.mjs

.PHONY: operations-overview-check
operations-overview-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/operations-overview-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/operations-overview-check.mjs --external:jsdom && \
		node node_modules/.cache/operations-overview-check.mjs

# Well visuals: the marker, the survey endpoint and the report snapshot stay
# separate; severity belongs to an interval; the schematic and the section use
# different axes; every mark can explain its source.
.PHONY: well-visuals-check
well-visuals-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/well-visuals-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/well-visuals-check.mjs --external:jsdom && \
		node node_modules/.cache/well-visuals-check.mjs

# Invoice Configuration Deleted entries: Restore / Delete permanently act on the
# tab the row belongs to, never on a hard-coded list.
invoice-config-deleted-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/invoice-config-deleted-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/invoice-config-deleted-check.mjs --loader:.jsx=jsx --external:jsdom && \
		node node_modules/.cache/invoice-config-deleted-check.mjs

# Cost Intelligence: the analysis finds what the shaped demo wells contain, and
# the page selects the well whose bar was pressed.
cost-intelligence-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/cost-intelligence-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/cost-intelligence-check.mjs --loader:.jsx=jsx --external:jsdom && \
		node node_modules/.cache/cost-intelligence-check.mjs

# Offline LAN Ollama AI: Guide comparison/fallback alerts, Cost Intelligence
# opt-in toggle (default OFF -> ON -> error -> OFF), and light/dark tokens.
ollama-ai-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/ollama-ai-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/ollama-ai-check.mjs --loader:.jsx=jsx --external:jsdom && \
		node node_modules/.cache/ollama-ai-check.mjs

# Export as shown: the dashboard PDF (figures + the visuals themselves), the
# matrix Excel (merged header bands, stacked well/section columns, totals) and
# the workbook the reader can re-import.
export-report-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/export-report-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/export-report-check.mjs --loader:.jsx=jsx --external:jsdom && \
		node node_modules/.cache/export-report-check.mjs

# Reusable templates: the library page, the picker preview/confirm and the
# code-scoped well plan preview (the structures that must survive Master Data changes).
templates-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/templates-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/templates-check.mjs --loader:.jsx=jsx --log-level=error \
		--external:jsdom && node node_modules/.cache/templates-check.mjs

# Catalogue tables: the description column and the bulk price revision dialog's
# preview, reason gate and all-or-nothing refusal (Master Data → Tangibles/Consumables).
catalogue-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/catalogue-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/catalogue-check.mjs --loader:.jsx=jsx --log-level=error \
		--external:jsdom && node node_modules/.cache/catalogue-check.mjs

# AFE one-dialog scope configuration: a Day Rate service priced per section and
# phase in a single dialog, with its amount as the sum of those sections.
afe-scope-dialog-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/afe-scope-dialog-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/afe-scope-dialog-check.mjs --loader:.jsx=jsx --log-level=error \
		--external:jsdom && node node_modules/.cache/afe-scope-dialog-check.mjs

# AFE print: two A4 pages, one grand total, one row per service even when the
# service is priced on several sections.
afe-print-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/afe-print-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/afe-print-check.mjs --loader:.jsx=jsx --log-level=error \
		--external:jsdom && node node_modules/.cache/afe-print-check.mjs

# Well status and plan status ladders: register tabs, the status menu per ladder
# step (forward and one-step rollback), the confirmation dialog, and the CSS
# rule that keeps the hidden print sheet out of the on-screen report View.
well-lifecycle-check:
	cd frontend && npm ci && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/well-lifecycle-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/well-lifecycle-check.mjs --loader:.jsx=jsx --log-level=error \
		--external:jsdom && node node_modules/.cache/well-lifecycle-check.mjs
