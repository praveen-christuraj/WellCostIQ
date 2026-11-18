"""Explainable suggestions. Printed classification outranks the programme and keywords."""

import re


def tokens(text):
    return {
        w
        for w in re.findall(r"[a-z]{3,}", text.lower())
        if w
        not in {
            "the",
            "and",
            "with",
            "from",
            "for",
            "per",
            "continue",
            "cont",
            "same",
            "well",
            "plan",
            "hole",
            "depth",
        }
    }


def suggest(mark, narrative, library_allocation, timeline, elapsed_hours):
    words = tokens(narrative)
    best = None
    for item, start, end in timeline:
        wanted = tokens(item.description)
        common = wanted & words
        if len(common) < 2:
            continue
        overlap = len(common) / max(1, min(len(wanted), len(words)))
        if overlap < 0.3:
            continue
        in_window = elapsed_hours is not None and start <= elapsed_hours < end
        rank = (overlap + 0.3 * in_window, len(common))
        if best is None or rank > best[0]:
            best = rank, item, in_window
    hint = (
        ""
        if not best
        else f"Programme item {best[1].sequence_no}: {best[1].description[:95]}"
        + (" (scheduled window)" if best[2] else " (activity match)")
    )
    if not hint and elapsed_hours is not None:
        scheduled = next((it for it, a, z in timeline if a <= elapsed_hours < z), None)
        if scheduled:
            hint = (
                f"Programme window: {scheduled.sequence_no}. {scheduled.description[:85]} (no clear activity match)"
            )
    explicit = {
        "P": "PT",
        "PLANNED": "PT",
        "PT": "PT",
        "U": "UPA",
        "UPA": "UPA",
        "D": "NPT",
        "N": "NPT",
        "NPT": "NPT",
        "SP": "SP",
    }.get(mark.strip().upper())
    if explicit:
        allocation, source, confidence, reason = explicit, "report", 0.90, f"Report mark: {mark}"
    elif library_allocation in ("PT", "NPT", "UPA", "SP"):
        allocation, source, confidence, reason = library_allocation, "code", 0.75, "Workspace activity-code default"
    elif re.search(
        r"\b(wait(?:ed|ing)? (?:on|for)|breakdown|equipment failure|stuck pipe|lost circulation)\b",
        narrative,
        re.IGNORECASE,
    ):
        allocation, source, confidence, reason = "NPT", "keyword", 0.6, "Delay or failure in narrative"
    elif best:
        allocation, source, confidence, reason = "PT", "timeline", 0.7, "Matches the active programme"
    elif re.search(r"\b(unplanned|unscheduled|additional wiper trip)\b", narrative, re.IGNORECASE):
        allocation, source, confidence, reason = "UPA", "keyword", 0.6, "Unscheduled work in narrative"
    else:
        allocation, source, confidence, reason = (
            "PT",
            "unresolved",
            0.25,
            "No decisive evidence; verify classification",
        )
    classification = "Planned" if allocation in ("PT", "SP") else allocation
    return {
        "classification": classification,
        "allocation": allocation,
        "is_productive": classification != "NPT",
        "confidence": confidence,
        "classification_source": source,
        "classification_evidence": " · ".join(filter(None, [reason, hint])),
    }


def build_brief(
    well_code: str,
    well_name: str,
    report_date_str: str,
    day_number: int | None,
    depth_start: str,
    depth_end: str,
    footage: str,
    rop: str,
    blocks: list[dict],
    time_split: dict,
    npt_items: list[dict],
) -> str:
    """Deterministic brief composition."""
    lines: list[str] = []
    lines.append(f"Well {well_code} ({well_name}) — Day {day_number or '—'} — {report_date_str}")
    lines.append(f"Depth {depth_start} → {depth_end} ({footage} footage, ROP {rop})")
    lines.append("")
    # Top blocks by duration
    top = sorted(blocks, key=lambda b: b.get("duration_minutes", 0), reverse=True)[:3]
    if top:
        lines.append("Key activities:")
        for b in top:
            lines.append(
                f"  • {b.get('classification', '')} — {b.get('narrative', '')[:120]} ({b.get('duration_minutes', 0)} min)"
            )
        lines.append("")
    lines.append(
        f"Time: {time_split['planned_minutes'] / 60:.2f} h planned · {time_split['upa_minutes'] / 60:.2f} h UPA · {time_split['npt_minutes'] / 60:.2f} h NPT. Period balance: {time_split['unaccounted_minutes']} min."
    )
    if npt_items:
        lines.append("NPT events:")
        for n in npt_items[:3]:
            lines.append(
                f"  • {n.get('npt_code', '')} — {n.get('reason', '')[:100]} ({n.get('duration_minutes', 0)} min, {n.get('responsible_party', '')})"
            )
        lines.append("")

    return "\n".join(lines)
