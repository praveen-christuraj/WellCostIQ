"""Reduce the decimal storage scale and retain printed operations code provenance.

The scale downgrade cannot restore discarded fractional digits. Back up before upgrading.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d9e5a4f702'
down_revision = 'b4d621f389aa'
branch_labels = None
depends_on = None

# Frozen from the previous revision, independent of runtime model changes.
COLUMNS = {
    'afe_consumable_lines': (
        'quantity', 'captured_rate', 'override_rate', 'estimated_amount',
    ),
    'afe_exchange_rates': (
        'rate',
    ),
    'afe_service_charges': (
        'quantity',
    ),
    'afe_service_lines': (
        'service_amount',
    ),
    'afe_service_rates': (
        'unit_rate',
    ),
    'afe_service_scope_days': (
        'quantity',
    ),
    'afe_service_scope_rates': (
        'unit_rate',
    ),
    'afe_service_section_rates': (
        'amount',
    ),
    'afe_sow_adjustments': (
        'original_services_total', 'original_consumables_total', 'original_tangibles_total', 'original_total',
        'adjusted_services_total', 'adjusted_consumables_total', 'adjusted_tangibles_total', 'adjusted_total',
    ),
    'afe_sow_consumable_lines': (
        'quantity', 'captured_rate', 'override_rate', 'estimated_amount',
    ),
    'afe_sow_exchange_rates': (
        'rate',
    ),
    'afe_sow_service_charges': (
        'quantity',
    ),
    'afe_sow_service_lines': (
        'service_amount',
    ),
    'afe_sow_service_rates': (
        'unit_rate',
    ),
    'afe_sow_service_scope_days': (
        'quantity',
    ),
    'afe_sow_service_scope_rates': (
        'unit_rate',
    ),
    'afe_sow_service_section_rates': (
        'amount',
    ),
    'afe_sow_tangible_lines': (
        'quantity', 'captured_rate', 'override_rate',
    ),
    'afe_tangible_lines': (
        'quantity', 'captured_rate', 'override_rate',
    ),
    'cement_additive_rate_revisions': (
        'unit_rate', 'previous_unit_rate', 'cost_uplift', 'final_cost', 'previous_final_cost',
    ),
    'cement_additives': (
        'unit_rate', 'cost_uplift', 'final_cost',
    ),
    'daily_cost_baseline_budget_lines': (
        'quantity', 'unit_rate', 'native_amount', 'exchange_rate', 'planned_amount',
    ),
    'daily_cost_baseline_exchange_rates': (
        'rate',
    ),
    'daily_cost_baseline_phases': (
        'days',
    ),
    'daily_cost_baseline_sections': (
        'from_depth', 'to_depth', 'total_days',
    ),
    'daily_cost_baseline_service_rates': (
        'unit_rate',
    ),
    'daily_cost_baselines': (
        'services_total', 'consumables_total', 'tangibles_total', 'total_amount',
    ),
    'daily_cost_catalogue_rate_snapshots': (
        'unit_rate',
    ),
    'daily_cost_consumable_lines': (
        'quantity', 'captured_rate', 'override_rate', 'exchange_rate', 'amount', 'standard_amount',
        'usd_exchange_rate', 'usd_amount', 'actual_depth', 'actual_depth_input',
    ),
    'daily_cost_entries': (
        'services_total', 'consumables_total', 'tangibles_total', 'total_cost', 'upa_total', 'npt_total',
        'other_expenses_total', 'usd_exchange_rate', 'services_total_usd', 'consumables_total_usd',
        'tangibles_total_usd', 'other_expenses_total_usd', 'total_cost_usd', 'upa_total_usd', 'npt_total_usd',
        'lead_lag_days',
    ),
    'daily_cost_item_profiles': (
        'median_value', 'spread', 'low_value', 'high_value', 'common_value',
    ),
    'daily_cost_other_expense_lines': (
        'quantity', 'captured_rate', 'override_rate', 'exchange_rate', 'amount', 'standard_amount',
        'usd_exchange_rate', 'usd_amount', 'actual_depth', 'actual_depth_input',
    ),
    'daily_cost_service_cost_items': (
        'amount',
    ),
    'daily_cost_service_lines': (
        'quantity', 'captured_rate', 'override_rate', 'exchange_rate', 'amount', 'standard_amount',
        'usd_exchange_rate', 'usd_amount', 'actual_depth', 'actual_depth_input',
    ),
    'daily_cost_tangible_lines': (
        'quantity', 'captured_rate', 'override_rate', 'exchange_rate', 'amount', 'standard_amount',
        'usd_exchange_rate', 'usd_amount', 'actual_depth', 'actual_depth_input',
    ),
    'drill_bit_rate_revisions': (
        'unit_rate', 'previous_unit_rate', 'cost_uplift', 'final_cost', 'previous_final_cost',
    ),
    'drill_bits': (
        'unit_rate', 'cost_uplift', 'final_cost',
    ),
    'fuel_cost_company_lines': (
        'litres',
    ),
    'fuel_cost_entries': (
        'rig_engine_consumption', 'gas_consumption', 'opening_stock', 'receipt_quantity', 'closing_stock',
    ),
    'fuel_price_revisions': (
        'unit_rate', 'previous_unit_rate', 'cost_uplift', 'final_cost', 'previous_final_cost',
    ),
    'fuel_types': (
        'unit_rate', 'cost_uplift', 'final_cost',
    ),
    'invoice_exchange_rates': (
        'rate',
    ),
    'invoice_idvs': (
        'disallowed_amount', 'advance_amount', 'invoice_subtotal', 'verified_subtotal', 'invoice_tax_total',
        'verified_tax_total', 'invoice_total', 'verified_total', 'adjusted_verified_amount', 'difference_amount',
        'net_payable_amount',
    ),
    'invoice_idvs_lines': (
        'invoice_quantity', 'invoice_unit_price', 'invoice_total', 'verified_quantity', 'verified_unit_price',
        'verified_total', 'difference_amount', 'invoice_days', 'verified_days',
    ),
    'invoice_idvs_payment_splits': (
        'percentage', 'exchange_rate', 'amount',
    ),
    'invoice_idvs_taxes': (
        'rate_percent', 'invoice_amount', 'verified_amount',
    ),
    'invoice_payment_term_splits': (
        'percentage',
    ),
    'invoice_tax_configurations': (
        'rate_percent',
    ),
    'lih_cost_entries': (
        'total_cost',
    ),
    'lih_cost_lines': (
        'od_size', 'id_size', 'fish_neck_od', 'fish_neck_length', 'length', 'no_of_units', 'unit_cost',
        'total_cost',
    ),
    'mud_chemical_rate_revisions': (
        'unit_rate', 'previous_unit_rate', 'cost_uplift', 'final_cost', 'previous_final_cost',
    ),
    'mud_chemicals': (
        'unit_rate', 'cost_uplift', 'final_cost',
    ),
    'mud_cost_entries': (
        'section_from_depth', 'section_to_depth',
    ),
    'mud_cost_entry_lines': (
        'amount',
    ),
    'mud_cost_section_settings': (
        'base_rate',
    ),
    'ndt_inspections': (
        'quantity_received', 'quantity_consumed', 'quantity_backloaded_good', 'quantity_backloaded_bad',
    ),
    'ops_activity_blocks': (
        'depth_from_m', 'depth_to_m', 'footage_m', 'bit_depth_m', 'rotating_hours', 'rop_m_per_hr', 'confidence',
    ),
    'ops_daily_metrics': (
        'depth_end_m', 'footage_m', 'rop_m_per_hr', 'cum_days_from_spud', 'cum_footage_m',
        'plan_cum_days_at_depth', 'lag_days', 'avg_confidence',
    ),
    'ops_daily_reports': (
        'depth_start_m', 'depth_end_m', 'tvd_m', 'progress_m', 'rotating_hours', 'dfs_days', 'est_days',
        'md_auth_m', 'last_casing_size_in', 'last_casing_depth_m',
    ),
    'ops_extraction_jobs': (
        'confidence',
    ),
    'ops_plan_items': (
        'target_depth_m', 'delta_depth_m', 'planned_hours', 'cum_planned_days', 'rop_assumption_m_per_hr',
        'trip_speed_m_per_hr', 'contingency_hours',
    ),
    'ops_plan_versions': (
        'planned_days',
    ),
    'ops_settings': (
        'classification_confidence_high', 'classification_confidence_low',
    ),
    'ops_surveys': (
        'md_m', 'inc_deg', 'azi_deg', 'tvd_m', 'ns_m', 'ew_m', 'vsec_m', 'dls_deg_per_30m', 'confidence',
    ),
    'record_template_well_phases': (
        'days',
    ),
    'record_template_well_sections': (
        'from_depth', 'to_depth',
    ),
    'tangible_rate_revisions': (
        'unit_rate', 'previous_unit_rate', 'cost_uplift', 'final_cost', 'previous_final_cost',
    ),
    'tangibles': (
        'unit_rate', 'cost_uplift', 'final_cost',
    ),
    'well_phases': (
        'days',
    ),
    'well_plan_adjustment_phases': (
        'days',
    ),
    'well_plan_adjustment_sections': (
        'from_depth', 'to_depth',
    ),
    'well_plan_adjustments': (
        'planned_days_before', 'planned_days_after',
    ),
    'well_sections': (
        'from_depth', 'to_depth',
    ),
}

SOURCE_FIELDS = {'source_activity_code': 100, 'source_operation_code': 100, 'source_cause_code': 50, 'source_mark': 30}


def _convert(old_scale, new_scale):
    context = op.get_context()
    quote = context.dialect.identifier_preparer.quote
    if context.dialect.name == 'postgresql':
        for table, columns in COLUMNS.items():
            # One ALTER per table, to avoid rewriting each ledger repeatedly.
            alters = ', '.join(f'ALTER COLUMN {quote(col)} TYPE NUMERIC(28, {new_scale})' for col in columns)
            op.execute(f'ALTER TABLE {quote(table)} {alters}')
        return
    for table, columns in COLUMNS.items():
        if new_scale < old_scale:
            # SQLite does not enforce NUMERIC scale. Round existing values explicitly;
            # leave integers and NULLs alone, including SQLite's large integer values.
            assignments = ', '.join(
                f'{quote(col)} = CASE WHEN typeof({quote(col)}) = \'real\' '
                f'THEN round({quote(col)}, {new_scale}) ELSE {quote(col)} END' for col in columns
            )
            op.execute(f'UPDATE {quote(table)} SET {assignments}')
        if table == 'services':
            # SQLite cannot reflect expression indexes through a batch copy.
            op.drop_index('uq_services_org_name_ci', table_name='services')
        with op.batch_alter_table(table) as batch:
            for col in columns:
                batch.alter_column(col, existing_type=sa.Numeric(28, old_scale), type_=sa.Numeric(28, new_scale))
        if table == 'services':
            op.create_index('uq_services_org_name_ci', 'services', ['organization_id', sa.text('lower(service_name)')], unique=True)


def _preflight_positive_values():
    # A rounded zero could erase a conversion or violate a positive-only constraint.
    # Check before changing a table; do not replace historical values with guesses.
    context = op.get_context()
    quote = context.dialect.identifier_preparer.quote

    def check(table, columns, kind):
        if not columns:
            return
        clauses = ' OR '.join(f'({quote(col)} > 0 AND {quote(col)} < 0.0005)' for col in columns)
        stmt = f'SELECT 1 FROM {quote(table)} WHERE {clauses} LIMIT 1'
        message = (
            f'Three-decimal migration stopped: {table} has {kind} that would round to zero. '
            'Review the source records with Finance and back up the ledger before retrying.'
        )
        if context.dialect.name == 'postgresql':
            # Kept in the generated SQL as well as the online migration.
            op.execute(f"DO $$ BEGIN IF EXISTS ({stmt}) THEN RAISE EXCEPTION '{message}'; END IF; END $$")
        elif op.get_bind().execute(sa.text(stmt)).first():
            raise RuntimeError(message)

    for table, columns in COLUMNS.items():
        fx_columns = [col for col in columns if col in ('exchange_rate', 'usd_exchange_rate')
                      or (col == 'rate' and 'exchange_rate' in table)]
        check(table, fx_columns, 'an FX rate')
    check('invoice_idvs_lines', ('invoice_quantity', 'invoice_days'), 'a required positive quantity or day count')
    for table in ('invoice_idvs_payment_splits', 'invoice_payment_term_splits'):
        check(table, ('percentage',), 'a required positive payment split')


def upgrade():
    _preflight_positive_values()
    _convert(10, 3)
    for name, size in SOURCE_FIELDS.items():
        op.add_column('ops_activity_blocks', sa.Column(name, sa.String(size), nullable=False, server_default=''))


def downgrade():
    with op.batch_alter_table('ops_activity_blocks') as batch:
        for name in SOURCE_FIELDS:
            batch.drop_column(name)
    _convert(3, 10)
