.PHONY: test build graph up seed-admin check-admin ui-check ui-rollback daily-cost-check daily-cost-scope-check daily-cost-date-check entry-checks-check entry-checks-simulation afe-scope-dialog-check afe-print-check well-lifecycle-check mud-cost-reconciliation-check mud-cost-kpi-check lih-worksheet-check fuel-cost-check usage-reports-check templates-check catalogue-check assistant-check chart-drill-check export-report-check

test:
	cd backend && ../.venv/bin/python -m pytest -q
build:
	cd frontend && npm run build
graph:
	python3 .agent/tools/graphify.py
up:
	docker compose up --build
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
