"""Classification engine — rule-based, explainable."""

from decimal import Decimal

# Keyword lexicon for UPA/NPT detection
NPT_KEYWORDS = [
    "WAITING ON", "LOST CIRCULATION", "STUCK", "FISHING", "TRIPPED OFF",
    "RIG REPAIR", "WEATHER", "HOLD", "NO CIRCULATION", "REDRESS",
    "CREW", "EQUIPMENT FAILURE", "DOWN TIME", "DOWNTIME", "REPAIR",
    "BREAKDOWN", "FAILED", "FAILURE", "STUCK PIPE", "TIGHT HOLE",
    "CIRCULATING LOSS", "LOSS CIRCULATION", "WELL CONTROL", "KICK",
    "BOP", "CAVING", "SLIM HOLE", "BRIDGE", "FISH", "JAR",
]

UPA_KEYWORDS = [
    "WIPER TRIP", "REAMING", "CIRCULATION", "CONDITION MUD",
    "CIRCULATE", "BACKREAM", "WASH", "CLEAN",
]

SP_KEYWORDS = ["SLOW PROGRESS", "LOW ROP", "SLOW DRILLING"]

# Rule weights
WEIGHT_EXPLICIT = 1.0
WEIGHT_EXPLICIT_MARK = 0.55
WEIGHT_NPT_CODE = 1.0
WEIGHT_ACTIVITY_CODE = 0.45
WEIGHT_KEYWORD = 0.30
WEIGHT_TIMELINE = 0.35
WEIGHT_HISTORY = 0.15


def classify_block(
    sub_class: str,
    phase_raw: str,
    code: str,
    narrative: str,
    has_npt_code: bool = False,
    timeline_hint: str | None = None,
    history_hint: str | None = None,
) -> tuple[str, str, float, list[str]]:
    """Classify a block into (classification, allocation, confidence, reasons)."""
    upper_narr = (narrative or "").upper()
    sub = (sub_class or "").strip().upper()

    reasons: list[str] = []
    weights: list[float] = []

    # R1: explicit Sub/Class mark
    if sub == "P":
        weights.append(WEIGHT_EXPLICIT_MARK)
        reasons.append("Sub/Class P → Planned")
        base_class = "Planned"
        base_alloc = "PT"
    elif sub == "U":
        weights.append(WEIGHT_EXPLICIT_MARK)
        reasons.append("Sub/Class U → UPA")
        base_class = "UPA"
        base_alloc = "UPA"
    elif sub == "D":
        weights.append(WEIGHT_EXPLICIT_MARK)
        reasons.append("Sub/Class D → NPT (downtime)")
        base_class = "NPT"
        base_alloc = "NPT"
    else:
        base_class = "Planned"
        base_alloc = "PT"

    # R3: NPT code present
    if has_npt_code:
        weights.append(WEIGHT_NPT_CODE)
        reasons.append("NPT code assigned → NPT")
        base_class = "NPT"
        base_alloc = "NPT"

    # R4: activity code semantics
    if code in {"21", "24", "25"}:  # waiting / maintenance
        weights.append(WEIGHT_ACTIVITY_CODE)
        reasons.append(f"Activity code {code} → NPT candidate (waiting/maintenance)")
        if base_class != "NPT":
            base_class = "UPA" if code == "25" else "NPT"
            base_alloc = "NPT" if base_class == "NPT" else "UPA"
    elif code in {"29"}:  # fishing
        weights.append(WEIGHT_ACTIVITY_CODE)
        reasons.append(f"Activity code {code} → NPT (fishing)")
        base_class = "NPT"
        base_alloc = "NPT"

    # R5: keyword lexicon
    for kw in NPT_KEYWORDS:
        if kw in upper_narr:
            weights.append(WEIGHT_KEYWORD)
            reasons.append(f"Keyword '{kw}' → NPT")
            if base_class == "Planned":
                base_class = "NPT"
                base_alloc = "NPT"
            break

    # UPA keywords only if not already NPT
    if base_class != "NPT":
        for kw in UPA_KEYWORDS:
            if kw in upper_narr:
                if base_class == "Planned":
                    # wiper trip / reaming can be planned or UPA depending on plan
                    pass
                break

    for kw in SP_KEYWORDS:
        if kw in upper_narr:
            base_alloc = "SP"
            reasons.append(f"Keyword '{kw}' → SP allocation")
            break

    # R6 timeline
    if timeline_hint == "unplanned":
        weights.append(WEIGHT_TIMELINE)
        reasons.append("Timeline: not in plan → UPA/NPT")
        if base_class == "Planned":
            base_class = "UPA"
            base_alloc = "UPA"

    # R7 history
    if history_hint:
        weights.append(WEIGHT_HISTORY)
        reasons.append(f"History: previously {history_hint}")

    # Confidence
    if not weights:
        confidence = 0.55
    else:
        conf = 1.0
        for w in weights:
            conf *= (1 - w)
        confidence = 1 - conf
        confidence = max(0.0, min(1.0, confidence))

    return base_class, base_alloc, round(confidence, 2), reasons


def productive_for_classification(classification: str, counts_as_on_bottom: bool = False) -> bool:
    """Default is_productive for a classification."""
    if classification == "NPT":
        return False
    if classification == "UPA":
        return False
    return True


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
            lines.append(f"  • {b.get('classification','')} — {b.get('narrative','')[:120]} ({b.get('duration_minutes',0)} min)")
        lines.append("")
    lines.append(f"Time split: Planned {time_split.get('planned_minutes',0)} min, UPA {time_split.get('upa_minutes',0)} min, NPT {time_split.get('npt_minutes',0)} min, Unaccounted {time_split.get('unaccounted_minutes',0)} min")
    if npt_items:
        lines.append("NPT events:")
        for n in npt_items:
            lines.append(f"  • {n.get('npt_code','')} — {n.get('reason','')[:100]} ({n.get('duration_minutes',0)} min, {n.get('responsible_party','')})")
        lines.append("")
    lines.append("Forward plan: as per operations programme for next 24h.")
    lines.append(f"Data quality: {len(blocks)} blocks, avg confidence {time_split.get('avg_confidence','—')}")
    return "\n".join(lines)
