# Cost Intelligence

*Reports → Cost Intelligence* reads the daily cost record against each AFE and
reports what it finds, why, and what to do next. It is advice: nothing is
changed or blocked. The same record always produces the same findings.

## Access

| Capability | Allows |
| --- | --- |
| `cost-intelligence:read` | Open the module |
| `cost-intelligence:export` | Export the report (audited) |

The figures follow the source modules exactly as on the Operations dashboard.
Without `afe:read` the budget and forecast checks are skipped and the page says
so; without `daily-cost:read` the day-by-day checks are skipped. Migration
`c4e8a1d7f392` grants read to existing roles that hold `daily-cost:read` or
`afe:read`, and export to roles that can already export one of those modules.

## What is checked

| Subject | Finding | Rule |
| --- | --- | --- |
| Budget and forecast | AFE exceeded | Recorded cost above the effective AFE |
| | Forecast overrun | Recorded + recent daily rate x remaining planned days is 5% (warning) or 15% (critical) over the AFE |
| | Cost ahead of time | Share of AFE spent leads share of planned days by 15 points |
| | Cost group overrun | A cost group is more than 5% over its AFE estimate |
| Cost trend | Creeping cost | Two-sided CUSUM (slack 0.5, limit 4) against the median of the opening third of the record |
| Unusual days | Spike or dip | Modified z-score beyond 3.5 against 7 days either side, 25% from the local median, no neighbour within 15% |
| Schedule | Beyond planned days | Actual days above planned days (critical from 20%) |
| Non-productive time | NPT share | NPT cost is 10% (warning) or 20% (critical) of recorded cost |
| Record quality | Missing sheets | A date between the first and last cost date has no sheet |
| | Stale record | Active well, 3 or more days since the last sheet |
| | Repeated total | 3 or more consecutive days with the identical total |
| | Zero-cost sheet, draft sheets, kept entry-check warnings | Listed as notes |

A step to a new cost level (a new hole section, an added service) is left to the
trend check and is not reported as a run of unusual days. A peak that recurs is
not an unusual day.

## Scores

A well starts at 100 and loses 25 per critical finding, 10 per warning and 3
per note (never below 0): 80 and above is *Good*, 55 to 79 *Watch*, below 55
*At risk*. The workspace score is the AFE-weighted average of its wells.

## Forecast

Estimate at completion = recorded cost + the mean of the last 7 recorded days
(unusual days excluded) for each remaining planned day. The range is an 80%
band from the recent day-to-day spread. A well past its planned days has no
remaining days to project, so the page states its daily rate instead.

## Report

*Export report* offers three presets (management brief, full analysis, record
quality review) and a checkbox per section. The PDF carries the charts as shown;
Excel has a findings sheet and a well health sheet; CSV is the findings list as
filtered. Each export writes an audit entry naming the format and sections.

## Limits

- Up to 40 wells are analysed day by day per request (largest recorded cost
  first); the rest show budget position only. Filter to analyse them.
- The trend check needs 12 recorded days; unusual days need 5 neighbouring days.
- Findings cannot be dismissed or annotated; the module stores nothing.

## Verification

`backend/tests/test_cost_intelligence.py` covers the rules and the access,
tenant and audit behaviour. `make cost-intelligence-check` mounts the page
against the analysis of five shaped wells seeded by `.agent/tools/demo-data.py`.
