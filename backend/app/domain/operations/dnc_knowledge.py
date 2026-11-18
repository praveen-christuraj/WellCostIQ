"""Authoritative Drilling & Completion (D&C) engineering knowledge base for WellCostIQ.

Used by:
1. Deterministic technical Q&A in Well Operations Ask & Guide and the workspace Guide.
2. Compact retrieval-augmented system context for offline LAN Ollama models (tuned for
   compact models such as ``qwen3:1.7b`` and ``qwen3:4b-q4_K_M``) so narrative generation,
   report extraction/prefill, database Q&A, and operational analytics reason with accurate
   oilfield engineering terminology, unit conversions, and formulas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DncEntry:
    key: str
    title: str
    category: str
    keywords: str
    summary: str
    key_points: tuple[str, ...]
    follow_ups: tuple[str, ...] = ()


# Compact engineering rule-sheet injected into Ollama system prompts for qwen3:1.7b.
DNC_CORE_PRIMER = (
    "DRILLING & COMPLETION ENGINEERING RULES:\n"
    "- Units: 1 ft = 0.3048 m (1 m = 3.28084 ft). WellCostIQ stores all depths in metres (m), "
    "fluid weight in ppg (1 SG = 8.33 ppg), pressure in psi, volume in bbl, timestamps in WAT (Africa/Lagos, UTC+1:00).\n"
    "- MD vs TVD: Measured Depth (MD) is along-hole pipe length from active datum (RT/KB). "
    "True Vertical Depth (TVD) is vertical depth from datum. In vertical wells TVD = MD; in deviated/horizontal wells TVD <= MD ALWAYS (never TVD > MD). "
    "Bit depth is current string position and changes during trips (RIH/POOH) without drilling new hole.\n"
    "- Footage & ROP: Drilled footage = Closing MD - Opening MD (new hole only, never trip movement). "
    "Rotating ROP (m/h) = drilled footage (m) / on-bottom rotating hours.\n"
    "- Hydrostatic & ECD: P_hyd (psi) = 0.052 * MW (ppg) * TVD (ft) = 0.1706 * MW (ppg) * TVD (m). "
    "ECD (ppg) = MW + dP_annular / (0.1706 * TVD_m). Keep MW < ECD < fracture/LOT EMW and MW > pore pressure.\n"
    "- Surveys & DLS: Directional stations record MD, Inclination (deg), Azimuth (deg), TVD, N/S, E/W, V.Sec, and Dogleg Severity (DLS in deg/30m; 1 deg/100ft = 0.9843 deg/30m). Minimum curvature connects stations.\n"
    "- Time taxonomy: Classification is Planned (P), UPA (U, unplanned productive activity such as extra wiper trip/reaming), or NPT (D/N, non-productive downtime: TP well problems, TR rig failure, TD downhole failure, TS surface failure, TW waiting). "
    "Allocation is PT (planned time), UPA, NPT, or SP (slow progress). NPT is never productive.\n"
    "- Report types: DDR (Daily Drilling Report), DCR (Daily Completion Report), DMR (Daily Mud Report — fluid/rheology/depth only, 0 activity hours), RMR (Rig Move Report — partial or full day rig-up/down/skid).\n"
    "- Field abbreviations: RIH=run in hole, POOH=pull out of hole, CHC=circulate hole clean, BHA=bottomhole assembly, "
    "WOB=weight on bit, RPM=rotary speed, GPM=flow rate, SPP=standpipe pressure, TDS=top drive, BOP=blowout preventer, "
    "MWD/LWD=measurement/logging while drilling, LOT/FIT=leak-off/formation integrity test, TOC=top of cement, "
    "TOL=top of liner, TOF=top of fish, OBM/WBM=oil/water-based mud, PV/YP=plastic viscosity/yield point, "
    "TCP=tubing-conveyed perforation, SCSSV=surface-controlled subsurface safety valve, SSD=sliding side door, "
    "BPV/TWCV=back-pressure/two-way check valve, HPJSM=high-profile job safety meeting, DSLTI=days since LTI, POB=personnel on board."
)


DNC_ENTRIES: tuple[DncEntry, ...] = (
    DncEntry(
        key="dnc-md-tvd-surveys",
        title="MD, TVD, Bit Depth, Directional Surveys & Dogleg Severity",
        category="drilling",
        keywords="md tvd measured depth true vertical depth bit depth datum rt kb survey mwd gyro inclination azimuth dls dogleg minimum curvature",
        summary=(
            "Measured Depth (MD) is the total length measured along the wellbore path from the active depth datum "
            "(typically Rotary Table RT or Kelly Bushing KB), whereas True Vertical Depth (TVD) is the perpendicular "
            "vertical distance from that same datum to the point in the wellbore. TVD always governs hydrostatic "
            "pressure, pore pressure, and fracture gradient; MD governs pipe tally, trip time, hole volume, and cement displacement."
        ),
        key_points=(
            "Physical invariant: TVD is always less than or equal to MD (TVD = MD in a strictly vertical well; dTVD = dMD * cos(inclination) along a tangent). TVD must never exceed MD.",
            "Bit Depth vs Hole MD: Hole MD is the deepest drilled total depth; Bit Depth is where the bit/assembly sits right now (e.g. at casing shoe during conditioning or mid-string while RIH/POOH). Tripping changes bit depth without generating drilled footage.",
            "Minimum Curvature & DLS: Surveys (MWD, magnetic multishot, or wireline gyro inside casing/high interference) measure MD, Inclination, and Azimuth and compute TVD, N/S, E/W, Vertical Section, and Dogleg Severity (DLS in deg/30m; 1 deg/100ft = 0.9843 deg/30m). Elevated DLS (>3–5 deg/30m) raises torque, drag, keyseat risk, and casing wear.",
            "Unit standardization: WellCostIQ converts imperial depths using 1 ft = 0.3048 m exact and records whether report TVD came from the printed header, survey table, narrative MWD survey, or manual entry.",
        ),
        follow_ups=(
            "How are ROP, time balance and lead or lag calculated?",
            "How do drilling hydraulics, ECD and hole cleaning work?",
        ),
    ),
    DncEntry(
        key="dnc-directional-bha-rop",
        title="Rotary & Directional Drilling, BHA Design and ROP Optimization",
        category="drilling",
        keywords="bha directional rotary slide sliding mud motor pdm rss wob rpm torque drag rop bit pdc tricone mse build hold drop",
        summary=(
            "A directional Bottomhole Assembly (BHA) combines bit (PDC or roller-cone), steerable positive-displacement "
            "mud motor (PDM with bent housing/ACO) or rotary steerable system (RSS), stabilizers, non-magnetic drill "
            "collars (NMDC) housing MWD/LWD sensors, drilling jars, heavy-weight drill pipe (HWDP), and drill pipe."
        ),
        key_points=(
            "Rotary vs Slide drilling: With a bent-housing motor, rotating the drillstring drills a straight/tangent path (higher ROP, better cuttings transport), while holding the string stationary and orienting toolface (sliding) builds, drops, or turns azimuth.",
            "Drilling parameters: Monitor Weight on Bit (WOB), surface + motor RPM, flow rate (GPM), standpipe pressure (SPP), differential pressure across the motor, on/off-bottom torque, and pick-up / slack-off / rotating hookloads.",
            "ROP & Slow Progress (SP): Rotating ROP = new measured-depth footage (m) / matching on-bottom rotating hours. Low ROP arises from bit balling, worn cutters, excessive overbalance, inadequate bottomhole cleaning, stick-slip/whirl vibrations, or hard/abrasive stringers.",
            "Drilling jars: Placed in tension (vertical/low-angle) or engineered neutral/compression placement in high-angle wells with sufficient weight above the jar (recorded as Weight Above/Below Jars in OpenWells Section 5.1).",
        ),
        follow_ups=(
            "What causes stuck pipe and how is it prevented?",
            "How are MD and TVD different in deviated wells?",
        ),
    ),
    DncEntry(
        key="dnc-hydraulics-ecd-cleaning",
        title="Drilling Hydraulics, Equivalent Circulating Density (ECD) & Hole Cleaning",
        category="drilling",
        keywords="hydraulics ecd equivalent circulating density hole cleaning cuttings annular velocity gpm spp bottoms up sweep tandem pill",
        summary=(
            "Drilling hydraulics controls bit nozzle jetting, downhole MWD/motor power, cuttings transport out of the "
            "annulus, and Equivalent Circulating Density (ECD) — the effective mud weight exerted on the formation while circulating."
        ),
        key_points=(
            "Hydrostatic & ECD equations: Hydrostatic pressure (psi) = 0.052 * MW(ppg) * TVD(ft) = 0.1706 * MW(ppg) * TVD(m). ECD(ppg) = static MW + annular friction loss (psi) / (0.1706 * TVD_m).",
            "Drilling window: Static MW must exceed pore pressure (with trip margin) to prevent kicks, while dynamic ECD plus cuttings loading and surge pressure must remain below the formation fracture gradient / LOT EMW to avoid induced losses.",
            "Hole cleaning by inclination: In vertical wells (<30 deg), annular velocity and Yield Point (YP) suspend cuttings; in critical high-angle wells (35–65 deg), cuttings beds form on the low side and slide back (avalanching) — requiring high flow rate, pipe rotation (120+ RPM where safe), controlled ROP, tandem low-vis/high-weight sweeps, and full bottoms-up circulation (CHC) before connections or trips.",
            "Warning signs of poor hole cleaning: Increasing torque and drag, overpull on connections, pack-off / SPP spikes, fill on bottom after connections, and reduced cuttings recovery across shakers.",
        ),
        follow_ups=(
            "What do mud weight, PV, YP, OWR and ES mean on a mud report?",
            "What causes lost circulation and how is it controlled?",
        ),
    ),
    DncEntry(
        key="dnc-drilling-fluids-brines",
        title="Drilling Fluids (WBM / OBM / SOBM) & Completion Brine Properties",
        category="drilling",
        keywords="mud wbm obm sobm rheology density mw ppg funnel viscosity pv yp plastic yield point gel strength hthp owr es lime brine cacl2 kcl ntu",
        summary=(
            "Drilling fluids maintain primary well control, clean and cool the bit, carry cuttings, stabilize reactive "
            "shales, build a thin low-permeability filter cake, and minimize reservoir damage; completion brines provide "
            "solids-free hydrostatic control during completion and workover operations."
        ),
        key_points=(
            "Key rheology metrics (OpenWells Section 4.1 & DMR): Mud Weight (ppg) sets hydrostatic pressure; Funnel Viscosity (s/qt) tracks quick marsh thickness; Plastic Viscosity (PV, cP) reflects mechanical friction from solids and base fluid viscosity (keep ALAP via solids control); Yield Point (YP, lbf/100ft2) governs dynamic cuttings carrying capacity; 10s/10m/30m Gel Strengths measure static suspension (progressive gels raise surge/swab and ECD).",
            "OBM / SOBM specifics: Oil-Water Ratio (OWR, e.g. 75/25 to 85/15), Electrical Stability (ES, mV — typically >400 mV indicating tight water-in-oil emulsion), HTHP filtrate (<4 mL, all-oil filtrate), Water Phase Salinity (CaCl2 for osmotic shale inhibition), and Excess Lime (ppb for alkalinity and acid-gas buffering).",
            "Solids control: Shale shakers, mud cleaner (desander/desilter), degasser, and high/low-gravity centrifuges manage Low-Gravity Solids (LGS) and recover barite.",
            "Completion & workover brines: Filtered solids-free NaCl, KCl, CaCl2, CaBr2, ZnBr2, or formate brines verified for density (ppg), clarity (<10–20 NTU turbidity, <0.05% TSS), True Crystallization Temperature (TCT below minimum ambient/wellhead temperature), corrosion inhibitor, oxygen scavenger, and biocide.",
        ),
        follow_ups=(
            "How do wellbore cleanout and brine displacement work in completions?",
            "How do drilling hydraulics, ECD and hole cleaning work?",
        ),
    ),
    DncEntry(
        key="dnc-stuck-pipe",
        title="Stuck Pipe Mechanisms, Prevention & Freeing (NPT Code TP02)",
        category="drilling",
        keywords="stuck pipe differential sticking pack off packoff bridge keyseat ledge undergauge overpull backreaming jarring free point",
        summary=(
            "Stuck pipe (NPT code TP02) falls into three primary mechanisms — differential sticking, mechanical "
            "pack-off/bridging, and wellbore geometry — each identified from pipe movement, circulation pressure, and "
            "what the string was doing immediately before sticking."
        ),
        key_points=(
            "Differential sticking: Occurs when stationary BHA/pipe contacts a permeable depleted sand under high overbalance and thick filter cake. Signature: full unrestricted circulation maintained, zero up/down/rotary movement. Action: maintain low circulation, apply right-hand torque and slump down / jar DOWN, reduce hydrostatic if safe, spot organic/OBM freeing pill.",
            "Pack-off / bridge: Settled cuttings beds, cavings/sloughing shale, or junk plug the annulus. Signature: restricted or impossible circulation (high SPP spike), often while POOH or after pumps off. Action: bleed trapped pressure carefully, establish low-rate step-up circulation, work pipe in opposite direction of last movement (if stuck pulling up, slack off / jar down; never over-pressure and fracture the shoe).",
            "Wellbore geometry: Keyseats at sharp doglegs, ledges, undergauge hole, mobile salt, or stiff casing/BHA. Signature: unrestricted circulation, stuck while moving string at a repeatable depth. Action: work/jar opposite to travel direction (jar down if stuck pulling out; jar up if stuck running in), then ream carefully.",
            "Prevention: Minimize stationary pipe time across permeable zones, monitor torque/drag trends and shaker cavings, circulate sufficient bottoms-up before trips, control wiper-trip/backreaming speeds, and keep DLS within plan.",
        ),
        follow_ups=(
            "What do OpenWells trouble/NPT codes TP, TR, TD, TS and TW mean?",
            "How do fishing and milling operations work?",
        ),
    ),
    DncEntry(
        key="dnc-lost-circulation-well-control",
        title="Well Control (TP03), Lost Circulation (TP01), LOT, FIT & MAASP",
        category="drilling",
        keywords="well control kick influx shut in sidpp sicp kill mud weight drillers method wait and weight lot fit emw maasp lost circulation lcm losses",
        summary=(
            "Well control preserves two independent barriers against unplanned formation fluid influx (kick, TP03), "
            "while pressure-integrity tests (FIT/LOT) define the upper mud-weight limit before lost circulation (TP01)."
        ),
        key_points=(
            "Kick indicators & shut-in: Positive indicators are flow rate increase and active pit volume gain; drilling breaks, gas-cut mud, pump pressure drop/stroke increase, and improper trip-tank fill require an immediate flow check and shut-in. Record stabilized Shut-In Drill Pipe Pressure (SIDPP), Shut-In Casing Pressure (SICP), and pit gain.",
            "Kill calculations: Formation pressure = P_hyd_dp + SIDPP. Kill Mud Weight KMW (ppg) = Original MW + SIDPP / (0.1706 * TVD_m). Initial Circulating Pressure ICP = SCR + SIDPP; Final Circulating Pressure FCP = SCR * (KMW / OMW). Driller's Method circulates influx out in 1st circulation and kills in 2nd; Wait & Weight (Engineer's Method) kills and removes influx in one circulation with lower shoe pressure in long open-hole sections.",
            "LOT, FIT & MAASP: After drilling out casing shoe + 3–5 m new formation, a Formation Integrity Test (FIT) verifies pressure to a target Equivalent Mud Weight (EMW), whereas a Leak-Off Test (LOT) determines actual fracture initiation EMW. MAASP (psi) = (Shoe_EMW - Current_MW) * 0.1706 * Shoe_TVD_m — recalculated every time mud weight changes.",
            "Lost circulation (TP01): Classified as seepage (<10 bbl/hr), partial (10–100 bbl/hr), severe (>100 bbl/hr), or total (no returns). Treated by lowering flow/ECD, spotting sized CaCO3/fiber/mica LCM pills, squeezing cement/gunk plugs, and keeping the annulus full to prevent a secondary kick from hydrostatic drop.",
        ),
        follow_ups=(
            "How do BOP and wellhead pressure tests work?",
            "How are MD and TVD different in deviated wells?",
        ),
    ),
    DncEntry(
        key="dnc-casing-cementing-bop",
        title="Casing Running, Liner Hanging, Primary Cementing & BOP Testing",
        category="drilling",
        keywords="casing liner shoe cementing cement slurry spacer plug bump float check woc cbl toc bop annular ram koomey pressure test wellhead",
        summary=(
            "Casing/liner strings (Operation G) and primary cementing (Operation H) isolate pressure zones, protect "
            "freshwater aquifers, support wellhead/BOP loads, and provide zonal isolation for completion and production."
        ),
        key_points=(
            "Casing & liner running: Condition hole (wiper trip + bottoms-up), verify casing tally and drift ID, install float shoe/float collar and centralizers per standoff plan, control RIH speed to limit surge pressure, fill pipe on schedule, and land casing hanger or set/expand liner hanger at TOL (Top of Liner).",
            "Primary cementing sequence: Rig up cement head and pressure-test surface lines, circulate conditioning volume, drop bottom plug, pump spacer, mix and pump lead and tail cement slurries at planned density (ppg), release top plug, displace with measured mud/brine volume, bump plug at planned differential pressure, bleed back to confirm float valves hold, Wait on Cement (WOC), and evaluate zonal isolation via CBL/VDL/USIT and casing pressure test.",
            "BOP & wellhead integrity (Operation C, API Std 53): Test annular preventer, upper/middle/lower pipe rams, blind/shear rams, choke & kill manifold valves, HCRs, IBOP/TIW/kelly valves with a low-pressure stage (250–300 psi) followed by rated high-pressure hold, plus Koomey accumulator drawdown/recharge and shear function checks. Record test chart and drill-out shoe track safely.",
        ),
        follow_ups=(
            "How do wellbore cleanout and brine displacement work in completions?",
            "How do single and dual completion strings, packers and SCSSV work?",
        ),
    ),
    DncEntry(
        key="dnc-completion-operations",
        title="Well Completion: Cleanout, Perforation, Sand Control, Strings, Packers & Xmas Tree",
        category="completion",
        keywords="completion dcr cleanout scraper brine displacement perforation tcp wireline gravel pack screen sand control tubing dual string packer scssv ssd nipple xmas tree slickline coiled tubing nitrogen",
        summary=(
            "Well completion transforms a cased/drilled wellbore into a safe, sand-free, zonal-isolated producing or "
            "injecting conduit with verified dual well barriers from reservoir to Christmas tree (Xmas tree)."
        ),
        key_points=(
            "Wellbore cleanout & fluid displacement: Run bit, casing scraper, brush, and magnet to PBTD / landing collar / TOL; perform positive & inflow (negative) casing/liner-lap tests; pump chemical surfactant/solvent/viscous spacer train at turbulent rates and displace mud to filtered solids-free completion brine (<10–20 NTU).",
            "Perforation & sand control: Correlate depth with GR-CCL (gamma ray / casing collar locator), perforate reservoir intervals via Tubing-Conveyed Perforation (TCP) or wireline/e-line guns under strict radio-silence and explosives PTW procedures; where formations are unconsolidated (common in Niger Delta reservoirs), install standalone screens (SAS), open-hole/cased-hole gravel packs (OHGP/CHGP), or frac-packs.",
            "Single & dual completion strings: Make up and torque-turn production tubing (short string SS and long string LS in dual completions), landing nipples (X/XN/R/F), Sliding Side Doors (SSD), production/isolation packers (hydraulic or mechanical set), blast joints, pup joints, and Surface-Controlled Subsurface Safety Valve (SCSSV/TRSV) with control line continuously pressure-tested during RIH. Space out, land tubing hanger, set and annulus-test packers, inflow/pressure-test SCSSV, install BPV/TWCV.",
            "Xmas tree, unloading & well test: Nipple down BOP, nipple up and pressure-test Xmas tree & tubing-head seals, pull BPV/TWCV via slickline/lubricator, drift tubing, shift SSDs / pull plugs, unload well (often via coiled tubing nitrogen lift), clean up to test separator monitoring WHP, FTHP, choke size (x/64 in), oil/gas/water rates, BS&W, sand cut, and GOR.",
        ),
        follow_ups=(
            "What do mud weight, PV, YP, OWR and ES mean on a mud report?",
            "How do I review and reopen a submitted daily operation report?",
        ),
    ),
    DncEntry(
        key="dnc-fishing-milling-sidetrack",
        title="Fishing, Milling, Abandonment Plugs & Sidetracking",
        category="drilling",
        keywords="fishing fish overshot grapple spear tof top of fish junk mill milling taper ccl wireline back off whipstock sidetrack cement plug",
        summary=(
            "Fishing (Activity 29) and milling (Activity 14) recover or dress lost/stuck downhole tubulars, BHA "
            "components, packers, or wireline tools; when recovery is uneconomic, isolation plugs and a whipstock or "
            "cement kick-off plug initiate a sidetrack (Operation F)."
        ),
        key_points=(
            "Fishing workflow: Confirm exact fish dimensions (OD, ID, fish-neck length, Top of Fish TOF depth), dress and verify overshot (spiral/basket grapple + pack-off) or internal spear alongside fishing jars, bumper sub, and accelerator; tag TOF gently, circulate clean, engage fish, pull free or jar, and recover to surface.",
            "Milling & plug/abandonment: Junk/flat-bottom/watermelon/taper mills dress tight casing, mill bridge plugs/packers, or cut casing windows; balanced cement plugs and mechanical/cast-iron bridge plugs (CIBP) isolate abandoned intervals with tagged TOC and pressure verification.",
            "Time accounting: Unplanned fishing caused by BHA/tool failure, stuck pipe, or wireline parting is classified as NPT (typically TD01, TD03, TD04, or TP02) with the responsible agency and clear root-cause reason recorded; planned perforation-mill or plug-mill runs in a completion programme are classified as Planned (PT) or UPA.",
        ),
        follow_ups=(
            "What do OpenWells trouble/NPT codes TP, TR, TD, TS and TW mean?",
            "What causes stuck pipe and how is it prevented?",
        ),
    ),
    DncEntry(
        key="dnc-npt-codes-time-wat",
        title="NPT Trouble Families, PT/UPA/NPT/SP Accounting, Reopen Controls & WAT Timezone",
        category="workflow",
        keywords="npt upa pt sp trouble tp01 tp02 tp03 tr01 tr02 tr03 tr04 tr05 td01 ts01 tw01 tw02 reopen timeline daily report wat west africa time utc lagos summary export",
        summary=(
            "WellCostIQ classifies every operational block along two axes — Classification (Planned, UPA, NPT) and "
            "Allocation (PT, UPA, NPT, SP) — timestamps all displays and exports in West Africa Time (WAT, UTC+1:00, "
            "Africa/Lagos), compiles full multi-day Well Operation Summaries (PDF/Excel/CSV), and supports audited "
            "reopening of timelines and daily reports."
        ),
        key_points=(
            "Trouble / NPT families: TP = Well problems (TP01 losses, TP02 stuck pipe, TP03 kick/influx, TP04 geological, TP05 cased hole); TR = Rig failures (TR01 drawworks, TR02 mud pumps, TR03 power/engines, TR04 top drive/TDS, TR05 surface BOP); TD = Downhole equipment failure (TD01 BHA/MWD/motor/string, TD02 casing/liner, TD03 completion/test tools, TD04 wireline, TD05 coiled tubing); TS = Surface equipment (TS01 wellhead, TS02 company, TS03 contractor); TW = Waiting (TW01 weather, TW02 contractor equipment/materials, TW03 company equipment/materials/orders). Prefix X (e.g. XW01) marks unplanned trouble equivalents.",
            "Reopen controls: Active or superseded timelines can be reopened to draft with ops-plan:reopen and mandatory audit remarks, revised, and re-activated. Submitted or approved daily reports can be reopened to draft with ops-report:reopen (plus ops-report:amend when older than 30 days) and mandatory remarks, incrementing revision_no and preserving a full immutable audit trail.",
            "Well Operation Summary: Open Well Operations -> Operation summary to inspect and export any well's cumulative KPIs, chronological multi-day activity log, day-by-day rollup, PT/NPT agency & cause breakdown, hole-section breakdown, and directional surveys in PDF, Excel (.xlsx), or CSV.",
            "Timezone standard: All operational clocks, inputs, daily periods, audit displays, and PDF/Excel/CSV exports operate in West Africa Time (Africa/Lagos, WAT UTC+1:00).",
        ),
        follow_ups=(
            "How do I review an extracted daily report?",
            "How do I import and activate a timeline?",
        ),
    ),
)


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 2}


def match_dnc_entries(question: str, *, limit: int = 2) -> list[tuple[int, DncEntry]]:
    """Rank relevant D&C engineering entries against a free-text engineering question."""
    q_low = (question or "").lower()
    q_tokens = _tokens(q_low)
    if not q_tokens:
        return []
    scored: list[tuple[int, DncEntry]] = []
    for entry in DNC_ENTRIES:
        kw_tokens = _tokens(entry.keywords)
        title_tokens = _tokens(entry.title)
        overlap = q_tokens & kw_tokens
        score = len(overlap) * 3 + len(q_tokens & title_tokens) * 2
        # Phrase bonuses for exact engineering compound terms.
        for phrase in (
            "stuck pipe",
            "lost circulation",
            "well control",
            "hole cleaning",
            "mud motor",
            "gravel pack",
            "sand control",
            "dual completion",
            "coiled tubing",
            "xmas tree",
            "leak off",
            "kill mud",
            "plastic viscosity",
            "yield point",
            "dogleg",
            "minimum curvature",
            "true vertical",
            "measured depth",
            "bit depth",
            "west africa time",
            "operation summary",
        ):
            if phrase in q_low and all(w in kw_tokens for w in phrase.split()):
                score += 6
        if score >= 5:
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], item[1].key))
    return scored[:limit]


def format_dnc_context(question: str, *, max_entries: int = 2) -> str:
    """Return a compact D&C reference snippet tailored to the user's question."""
    matches = match_dnc_entries(question, limit=max_entries)
    lines = [DNC_CORE_PRIMER]
    if matches:
        lines.append("\nRELEVANT D&C TECHNICAL REFERENCE:")
        for _, entry in matches:
            lines.append(f"[{entry.title}] {entry.summary}")
            for pt in entry.key_points[:3]:
                lines.append(f"  * {pt}")
    return "\n".join(lines)
