"""Reproducible engineering briefs from saved facts or a user's timeline preview."""

from decimal import Decimal

from app.core.precision import rounded
from app.domain.operations.drilling import activities, time_signal


def format_value(value, unit=''):
    return f'{value:,.3f}{(" " + unit) if unit else ""}' if value is not None else 'not reported'


def excerpt(text, limit):
    text = ' '.join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(' ', 1)[0].rstrip(',.;') + '…'


def timeline_study(items, *, has_start, scope):
    """Only sum planned row hours. Never derive a target, speed, start or as-built checkpoint."""
    if not items:
        return {'summary': 'No timeline rows to study.', 'warnings': ['Add or import programme activities first.']}
    hours = sum((i.planned_hours for i in items), Decimal(0))
    days = rounded(hours / 24)
    depths = [i.target_depth_m for i in items if i.target_depth_m is not None]
    missing = len(items) - len(depths)
    actions = list(dict.fromkeys(a for item in items for a in activities(item.description)))
    warnings = []
    if not has_start:
        warnings.append('No programme start. ' + (
            'Completion lead/lag is unavailable.' if scope == 'completion'
            else 'Drilling lead/lag needs confirmed days from spud as the time origin.'
        ))
    if not hours:
        warnings.append('No positive planned hours. Check the programme before activating it.')
    if missing:
        warnings.append(f'{missing} activities have no target MD. Confirm a completed checkpoint when depth is not comparable.')
    if any(b <= a for a, b in zip(depths, depths[1:])):
        warnings.append('Target MD repeats or decreases. Do not infer elapsed time through a plateau or reversal; confirm a checkpoint.')
    summary = [f'{len(items)} activities · {format_value(hours, "planned hours")} · {format_value(days, "planned days")} (hours ÷ 24).']
    if depths:
        summary.append(f'Last stated target MD: {format_value(depths[-1], "m")}. This is not a forecast of newly drilled footage.')
    if actions:
        summary.append('Work described: ' + '; '.join(actions[:6]) + '.')
    major = sorted((i for i in items if i.planned_hours > 0), key=lambda i: (-i.planned_hours, i.sequence_no))[:3]
    if major:
        summary.append('Longest steps: ' + '; '.join(
            f'{i.sequence_no}. {excerpt(i.description, 115)} ({format_value(i.planned_hours, "h")})' for i in major
        ) + '.')
    return {'summary': '\n'.join(summary), 'warnings': warnings}


def daily_brief(report, blocks, footage, rotating_hours, rop, *, labels=None):
    labels = labels or {}
    prefix = [report.well_code_snapshot, str(report.report_date), report.report_type]
    if report.day_number is not None:
        prefix.append(f'Day {report.day_number}')
    lines = [' · '.join(filter(None, prefix))]
    if any(value is not None for value in (report.depth_start_m, report.depth_end_m, footage)):
        lines.append(
            f'Measured depth: {format_value(report.depth_start_m, "m")} to {format_value(report.depth_end_m, "m")}. '
            f'Hole gain: {format_value(footage, "m")}.'
        )
    if report.scope == 'completion':
        lines.append('ROP: N/A (completion operation).')
    elif rop is not None:
        lines.append(f'Rotating ROP: {format_value(rop, "m/h")} on {format_value(rotating_hours, "rotating hours")}.')
    elif report.scope == 'drilling' and blocks:
        lines.append('Rotating ROP unavailable: comparable depth gain and rotating hours must be reported together.')
    if any(b.review_state == 'suggested' for b in blocks) or report.extraction_status == 'needs_review':
        lines.append('Draft suggestions: verify classifications, allocations and measurements against the source.')
    if blocks:
        totals = {kind: sum(b.duration_minutes for b in blocks if b.allocation == kind) for kind in ('PT', 'UPA', 'NPT', 'SP')}
        names = {'PT': 'Productive Time', 'UPA': 'Unplanned Activity', 'NPT': 'Non-Productive Time', 'SP': 'Slow Progress'}
        lines.append('Allocated time: ' + ' · '.join(f'{names[kind]} {format_value(Decimal(minutes) / 60, "h")}' for kind, minutes in totals.items()) + '.')
        balance = report.period_minutes - sum(totals.values())
        if balance:
            lines.append(f'Log is {abs(balance)} min {"short of" if balance > 0 else "over"} the report period.')
        top = sorted(sorted(blocks, key=lambda b: b.duration_minutes, reverse=True)[:3], key=lambda b: b.sequence_no)
        for block in top:
            label = labels.get('activity', {}).get(getattr(block, 'activity_id', None)) or 'Logged activity'
            lines.append(f'- {label} ({format_value(Decimal(block.duration_minutes) / 60, "h")}): {excerpt(block.narrative, 130)}')
        npt = sorted((b for b in blocks if b.classification == 'NPT' or b.allocation == 'NPT'), key=lambda b: -b.duration_minutes)
        if npt:
            reasons = [
                ' · '.join(filter(None, (labels.get('npt', {}).get(getattr(b, 'operation_id', None)), excerpt(b.reason or b.narrative, 115)))) + (f' ({b.responsible_party})' if b.responsible_party else '')
                for b in npt[:2] if b.reason or b.narrative
            ]
            lines.append('Reported downtime: ' + '; '.join(reasons) + '.' if reasons else 'Downtime noted; no reason recorded.')
            signals = list(dict.fromkeys(signal[1].casefold() for b in npt if (signal := time_signal(b.narrative)) and signal[0] == 'NPT'))
            if signals:
                lines.append('Downtime indicators: ' + ', '.join(signals[:3]) + '.')
    elif report.report_type == 'DMR':
        lines.append('Mud measurements only. No activity hours allocated.')
    else:
        lines.append('No activity log recorded.')
    if report.operation_summary:
        lines.append('Report summary: ' + excerpt(report.operation_summary, 320))
    if report.forward_plan:
        lines.append('Reported next work: ' + excerpt(report.forward_plan, 220))
    return '\n'.join(lines)
