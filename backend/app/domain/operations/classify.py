"""Explainable classification and programme matching. Suggestions are never approvals."""

import re

from app.domain.operations.default_codes import find_code
from app.domain.operations.drilling import activities, time_signal


def tokens(text):
    stop = {'the', 'and', 'with', 'from', 'for', 'per', 'continue', 'cont', 'same', 'well', 'plan', 'hole', 'depth'}
    return set(re.findall(r'[a-z]{3,}', text.lower())) - stop


def programme_match(narrative, timeline, elapsed_hours):
    """Match the work first; schedule proximity only breaks ties between comparable activities."""
    words, actions = tokens(narrative), set(activities(narrative))
    candidates = []
    scheduled = None
    for item, start, end in timeline:
        in_window = elapsed_hours is not None and start <= elapsed_hours < end
        if in_window:
            scheduled = item
        wanted, planned_actions = tokens(item.description), set(activities(item.description))
        common = wanted & words
        action_match = bool(actions & planned_actions)
        if actions and planned_actions and not action_match:
            continue
        overlap = len(common) / max(1, len(wanted | words))
        if action_match or (len(common) >= 2 and overlap >= 0.2):
            candidates.append(((action_match, in_window, round(overlap, 3), len(common)), item))
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    if candidates and (len(candidates) == 1 or candidates[0][0] != candidates[1][0]):
        score, item = candidates[0]
        mode = 'scheduled window' if score[1] else 'activity match; timing not confirmed'
        return True, f'Programme item {item.sequence_no}: {item.description[:95]} ({mode})'
    if candidates:
        return False, 'Multiple programme activities match; confirm the checkpoint manually'
    if scheduled:
        return False, f'Programme window: {scheduled.sequence_no}. {scheduled.description[:85]} (no clear activity match)'
    return False, ''


def suggest(mark, narrative, library_allocation, timeline, elapsed_hours, *, mark_rule=None, printed_allocation=''):
    matches, hint = programme_match(narrative, timeline, elapsed_hours)
    explicit = find_code(mark, 'Source mark', 'Allocation', 'Trouble / NPT')
    signal = time_signal(narrative)
    classification = ''
    if mark_rule:
        allocation, source, confidence = mark_rule.default_allocation, 'workspace', 0.95
        classification = mark_rule.default_classification
        reason = f'Workspace mark: {mark_rule.mark_code} — {mark_rule.mark_name}'
    elif explicit:
        classification = explicit.classification
        allocation = explicit.allocation or {'Planned': 'PT', 'UPA': 'UPA', 'NPT': 'NPT'}[classification]
        source, confidence = 'report', 0.90
        reason = f'Report mark: {mark} — {explicit.name}'
    elif library_allocation in ('PT', 'NPT', 'UPA', 'SP'):
        allocation, source, confidence, reason = library_allocation, 'code', 0.75, 'Workspace activity-code default'
    elif signal:
        allocation, source, confidence, reason = signal[0], 'keyword', 0.60, f'Narrative signal: {signal[1]}'
    elif matches:
        allocation, source, confidence, reason = 'PT', 'timeline', 0.70, 'Activity matches programme'
    else:
        allocation, source, confidence, reason = 'PT', 'unresolved', 0.25, 'No decisive evidence; verify classification'
    if printed_allocation:
        # Summary can mark a block U while placing its hours under NPT. Never
        # replace a known classification with the other axis of the time ledger.
        allocation = printed_allocation
        if not classification and source == 'unresolved':
            reason = 'No printed classification; verify independently of allocation'
    classification = classification or ('Planned' if allocation in ('PT', 'SP') else allocation)
    return {
        'classification': classification,
        'allocation': allocation,
        'is_productive': classification != 'NPT' and allocation != 'NPT',
        'confidence': confidence,
        'classification_source': source,
        'classification_evidence': ' · '.join(filter(None, (reason, hint))),
    }
