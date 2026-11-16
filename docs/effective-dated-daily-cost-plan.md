# Effective-dated catalogue pricing for daily costs — implementation plan

Status: **not implemented**. Daily-cost catalogue rates currently come from a
well-level immutable snapshot (`DailyCostWellRateBaseline` and
`DailyCostCatalogueRateSnapshot`), captured when daily costing is first locked.
The saved lines and their native, standard and USD amounts are persisted, and
other reports and dashboards consume those persisted amounts. Replacing the
snapshot lookup with the current master price would silently reprice history and
leave those totals inconsistent.

## Proposed behaviour

- For mud chemicals, drill bits and tangibles, resolve the latest applicable
  revision with `effective_date <= cost_date`, ordered by effective date then
  revision number, within the workspace and item. Never use a future revision.
  Use the revision's currency, unit and final cost (for uplift-priced items), not
  the item's current fields. A missing applicable revision must be explicit,
  never silently priced as zero. Other kinds retain their existing semantics.
- Expose eligible new catalogue items in the daily-sheet picker even if absent
  from the original well snapshot. The selected item and rate provenance must be
  validated again server-side; the browser must not be trusted as the authority.
- Preserve AFE pricing and budget baselines as historical estimates. Explicitly
  distinguish master-derived daily lines from negotiated/manual overrides so
  only master-derived lines participate in revisions. Store revision identity
  and pricing source column-wise for traceability.
- A backdated rate revision can affect existing records. Recompute affected
  master-derived lines and all persisted dependent totals/FX amounts in a single
  transaction or auditable controlled job, with clear impact preview and audit
  trail. Ensure dashboards, usage reports, exports, balances and cost
  intelligence agree. Concurrent edits and duplicate jobs need locking or
  version checks. Surface failures rather than leaving partial results.
- Add a migration and a conservative backfill that does not infer master-price
  provenance where it is uncertain. Regression tests must cover initial, future,
  same-day and backdated revisions; items created after AFE and after the daily
  snapshot; manual overrides; uplift and FX; deletion, tenant isolation, date
  edits, imports, dashboards and totals, and transaction rollback.

## Decisions required before automatic repricing

1. Should submitted, approved, or closed days be recalculated automatically, or
   require an amendment/reapproval? Existing workflows protect submitted records.
2. Should an AFE-negotiated daily price or an explicit override supersede the
   master revision? What should happen for existing lines with ambiguous origin?
3. For a revision effective before an existing day, should the change be applied
   automatically on revision save, or after an authorised impact review? What FX
   source applies if the revision changes currency?

Until these rules are settled and implemented end-to-end, existing snapshot
pricing remains unchanged. Do not treat this document as an implemented feature.
