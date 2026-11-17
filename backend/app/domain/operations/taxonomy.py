"""Taxonomy mapping helpers — pure functions, no DB."""

from decimal import Decimal

# Known OpenWells phase mapping to hole section hints
OPENWELLS_PHASE_MAP: dict[str, dict] = {
    "DRLPRO": {"hole_size": "8 1/2\"", "hint": "production"},
    "DRLSUR": {"hole_size": "16\"", "hint": "surface"},
    "DRLIN1": {"hole_size": "12 1/4\"", "hint": "intermediate"},
    "DRLIN2": {"hole_size": "12 1/4\"", "hint": "intermediate"},
    "DRLIN3": {"hole_size": "12 1/4\"", "hint": "intermediate"},
    "CSGIN2": {"hole_size": "12 1/4\"", "hint": "casing-intermediate"},
    "CSGSUR": {"hole_size": "16\"", "hint": "casing-surface"},
    "CSGPRO": {"hole_size": "8 1/2\"", "hint": "casing-production"},
    "CSGCON": {"hole_size": "26\"", "hint": "conductor"},
    "CSGDRV": {"hole_size": "26\"", "hint": "conductor"},
    "EVAL": {"hole_size": "8 1/2\"", "hint": "evaluation"},
    "EVALPR": {"hole_size": "8 1/2\"", "hint": "evaluation"},
}

# Activity code semantics (observed in report-study)
CODE_NPT_CANDIDATE = {"15", "21", "24", "25", "29"}
CODE_PRODUCTIVE_HINT = {"03", "05", "06", "07"}
