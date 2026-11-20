# Planned directional surveys and expanded visuals

## Operator workflow

1. Open **Operations → Plans & timeline** and select **Planned survey** on the correct version. A draft with plan-update access has an **Edit / import survey** action.
2. Enter stations manually or, with plan-import access, choose **Import / extract survey**. Review the file, sheet, units and extracted rows, then append or replace the draft table. **Apply to draft** is not a save. An `.xls` workbook needs to be resaved as an unencrypted `.xlsx` first; a scanned PDF needs a text or spreadsheet source.
3. Confirm the shared reference only when both surveys use the same bore, MD/TVD datum, north reference and N/E origin. A below-surface start still needs a recorded TVD and N/E tie-on for position deltas. Save the survey separately from the timeline activities.
4. Compare the **selected version** against actual survey records in Plans & timeline. **Well path** and the Operations Overview schematic use only the **active version**. A missing active survey never falls back to a draft. Inspect an MD in **Expand** to see both positions and, where supported, **Actual − Planned**.

Preview accepts CSV, `.xlsx`, `.xlsm` and text-based PDFs with a supported survey table. Planned surveys allow up to 5,000 stations. Metre conversion follows the same workspace depth convention as the daily-report path. Replacing a planned survey does not change activity hours, daily-report surveys, the report's closing-depth marker, or the separate time-vs-depth baseline.

## Data and calculation boundaries

- `ops_plan_survey_stations` holds normalized station columns and source file/sheet metadata per plan version, protected by a unique version/MD key and organization scoping. Alembic `9ac1f4e72b03` adds the table and an opt-in shared-reference flag. Existing records are not rewritten. API contract `0.23.0` is paired in server and browser.
- `GET/PUT /operations/plans/{id}/surveys`, `POST .../surveys/preview` and `GET .../trajectory` use the existing plan permissions; actual rows on the Plans page require report-read. The active survey in the Well path payload requires plan-read. Only a live draft may be written. Saves compare the plan timestamp and audit the station count and reference status; active/superseded versions require the existing reopen workflow.
- Both paths use the same minimum-curvature integration and vertical-section bearing. The display interpolates only between usable stations, labels interpolated values, and does not extrapolate or derive deltas beyond either survey's valid coverage. An invalid integration interval cuts off comparative geometry downstream. The N/E map uses equal scales; the casing construction keeps its own MD axis separate from the trajectory TVD axis.

## Visual inspection

`InteractiveChart` supplies the Expand action and reuses the same plot/options and click identities in the dialog. Numeric bounds, category/date windows, zoom/pan, labels, and reset are shown when suitable. The custom trajectory, dogleg and casing diagram supply depth-aware controls instead; the Time classification card expands its related cost-share bars together. Loading indicators, embedded KPI progress meters and print-only figures are not expandable graphs. Expanded figures do not register as dashboard PDF figures or persist any chart settings. Closing restores the inline chart and its filters.
