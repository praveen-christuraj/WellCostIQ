"""Study-book knowledge: the works the workspace was asked to learn from.

Two supplied references back this module:

* **Rabia, "Well Engineering & Construction"** — pore pressure and the dc
  exponent, formation integrity tests and fracture gradient, kick tolerance,
  casing properties and design (collapse, burst, tension, biaxial), wellbore
  stability (Mohr–Coulomb, Drucker–Prager, safe mud weight window), hole
  problems (differential sticking, hole pack-off, key seating, lost
  circulation), fishing, horizontal and multilateral wells, HPHT, rig
  components, and well costing.
* **Baker Hughes INTEQ, "Drilling Engineering Workbook"** — drilling fluids and
  material balance, hydraulics (Power Law, nozzle sizing, bit optimisation,
  swab and surge), casing and cementing, bit technology, drillstring basics
  (buoyancy, WOB, neutral point, torque and drag), directional drilling (well
  planning, motors, toolface, rotary assemblies), stuck pipe, well control,
  cost-per-foot and break-even analysis.

What is stored here, and what is deliberately not
-------------------------------------------------
A **derivation** is arithmetic: the formula, its symbol definitions, and the
decision it informs. A **rule of thumb** is a range the books print as
indicative, never a design value for a specific well. The module stores only
these two things, together with the page each came from, so:

* an answer cites a page a reader can open;
* no copyrighted passage is reproduced — the wording here is our own paraphrase
  of the physics, not the book's text;
* a number that depends on the well (a casing grade, a fracture gradient, a
  mud weight) is never asserted. The stored text says what must be measured and
  which test measures it.

Both guides read this module: the deterministic guide answers from it with no
model, and the Ollama prompt carries the matching entries as a compact block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class StudySource:
    """A citation a reader can act on: which book, which chapter, which page."""

    key: str
    short: str
    title: str
    author: str

    def citation(self, page: str) -> str:
        return f"{self.author}, {self.title} — {page}"


RABIA = StudySource(
    key="rabia",
    short="Rabia",
    title="Well Engineering & Construction",
    author="H. Rabia",
)
BAKER = StudySource(
    key="baker",
    short="Baker Hughes",
    title="Drilling Engineering Workbook (80270H Rev. B)",
    author="Baker Hughes INTEQ",
)

SOURCES: dict[str, StudySource] = {source.key: source for source in (RABIA, BAKER)}


@dataclass(frozen=True)
class StudyEntry:
    """One piece of engineering knowledge with its arithmetic and its citation.

    ``formula`` is plain text a reader can retype; ``symbols`` names every term
    in it; ``applies_to`` states when the relation holds and when it does not.
    """

    key: str
    title: str
    topic: str
    keywords: str
    summary: str
    formula: str = ""
    symbols: tuple[str, ...] = ()
    applies_to: str = ""
    checks: tuple[str, ...] = ()
    #: One (source id, chapter/section label, printed page) triple per citation.
    pages: tuple[tuple[str, str, str], ...] = ()
    follow_ups: tuple[str, ...] = ()

    def citations(self) -> list[str]:
        out: list[str] = []
        for source_key, section, page in self.pages:
            source = SOURCES.get(source_key)
            if source is None:
                continue
            label = source.citation(f"§{section}, p. {page}" if section else f"p. {page}")
            out.append(label)
        return out


STUDY_ENTRIES: tuple[StudyEntry, ...] = (
    # ------------------------------------------------------------------ pressure
    StudyEntry(
        key="study-pore-pressure-dc-exponent",
        title="Pore pressure from drilling data: the corrected d exponent",
        topic="pressure",
        keywords=(
            "pore pressure overpressure abnormal pressure dc exponent d exponent dexp eaton ratio method "
            "normal trend shale rop drilling break kick influx transition zone"
        ),
        summary=(
            "Pore pressure is inferred, not measured, while drilling: the d exponent normalises rate of "
            "penetration for weight on bit, rotary speed and bit size so a departure from the normal "
            "compaction trend reads as overpressure rather than as a change of drilling parameters."
        ),
        formula=(
            "d = log10(ROP / (60 · RPM)) / log10(12 · WOB / (10^6 · B));   "
            "dc = d · (normal pore pressure gradient / ECD)"
        ),
        symbols=(
            "ROP = rate of penetration, ft/h",
            "RPM = rotary speed, rev/min",
            "WOB = weight on bit, lbf",
            "B = bit diameter, in",
            "dc = corrected d exponent, dimensionless",
            "normal pore pressure gradient and ECD in ppg, so the correction is a ratio",
        ),
        applies_to=(
            "Clean, normally compacted shales only; the trend line is drawn through shale points. Eaton's "
            "method is the common sedimentary-basin choice, the ratio method has been used in clastic "
            "limestone sequences. A normalised rate is an indicator, never a substitute for a formation "
            "pressure measurement (RFT/DST) or a connection gas and flow check."
        ),
        checks=(
            "ROP responds to WOB, RPM, bit type, wear, hydraulics and lithology, so confirm the parameter "
            "changes before calling a drilling break overpressure.",
            "Plot dc against depth on semi-log paper and establish the normal trend through known clean "
            "shales before interpreting any departure.",
            "The printed limit: beyond about 500 psi overbalance, rate of penetration barely responds to "
            "further pressure change, so the method loses sensitivity deep in a well.",
        ),
        pages=(("rabia", "Pore Pressure §6.2–6.2.2", "27–35"),),
        follow_ups=(
            "How is a leak-off test interpreted?",
            "What increases kick tolerance?",
        ),
    ),
    StudyEntry(
        key="study-fit-fracture-gradient",
        title="Formation integrity, fracture gradient and casing seat selection",
        topic="pressure",
        keywords=(
            "fit lot leak off test fracture gradient formation breakdown casing seat shoe selection "
            "hubbert willis emw mud weight window integrity test pressure test"
        ),
        summary=(
            "A formation integrity test proves the shoe holds the mud weight planned for the next section; "
            "a leak-off test measures where the formation begins to take fluid, and that pressure is the "
            "upper bound of the mud weight window at that depth."
        ),
        formula=(
            "Mud weight equivalent at the shoe: EMW (ppg) = test pressure (psi) / (0.052 · shoe TVD (ft)) "
            "+ mud weight in the hole (ppg). Fracture gradient by Hubbert–Willis: FG = (effective stress "
            "ratio) · (overburden − pore) + pore, all as gradients."
        ),
        symbols=(
            "EMW = equivalent mud weight, ppg",
            "0.052 = psi per ft per ppg",
            "FG = fracture gradient, psi/ft or ppg equivalent",
            "overburden gradient is built from the density log and water depth offshore",
        ),
        applies_to=(
            "The test result is the evidence; a predicted gradient is a design assumption until a test "
            "confirms it. Deviated holes reduce the breakdown gradient, so a vertical-well correlation is "
            "not applied unchanged to a deviated well."
        ),
        checks=(
            "Confirm the gauge, the depth of the shoe and the mud weight in the hole before converting a "
            "test pressure to EMW; a wrong TVD or density shifts the answer materially.",
            "Casing seat selection compares the pore pressure of the next section, the fracture gradient at "
            "the shoe and the kick tolerance of the hole section below it.",
        ),
        pages=(("rabia", "Formation Integrity Tests §1–6.1", "51–69"),),
        follow_ups=(
            "How is kick tolerance calculated?",
            "What causes lost circulation?",
        ),
    ),
    StudyEntry(
        key="study-kick-tolerance",
        title="Kick tolerance: circulation, additional mud weight and drilling tolerance",
        topic="pressure",
        keywords=(
            "kick tolerance gas influx bubble shoe fracture max mud weight drilling kick m l d "
            "circulating influx height hpht well control swab"
        ),
        summary=(
            "Kick tolerance is the largest influx the well can take and still be circulated out without "
            "breaking the formation at the previous shoe. It is calculated at intervals through the hole "
            "section and recalculated whenever mud weight or string geometry changes."
        ),
        formula=(
            "Influx height at the shoe: H = [0.052 · pm · (TD − CSD) + (FG · CSD · 0.052 − Pf)] / (0.052 · pm − G). "
            "Gas pressure in the bubble: Pg = H · G."
        ),
        symbols=(
            "H = influx (gas) height when its top reaches the shoe, ft",
            "Pf = formation pressure at next TD, psi",
            "TD = next total depth, ft; CSD = casing setting depth, ft",
            "pm = maximum mud weight planned for the section, ppg",
            "FG = fracture gradient at the shoe, psi/ft",
            "G = gas gradient, 0.05–0.15 psi/ft",
        ),
        applies_to=(
            "The driller's method of circulating the influx. A rising pore pressure and a rising mud weight "
            "rapidly reduce the tolerance because the margin to the shoe is consumed first."
        ),
        checks=(
            "Three numbers are reported, not one: the circulating volume, the additional mud weight over the "
            "current weight, and the drilling kick tolerance (the maximum tolerated pore pressure).",
            "Recalculate after a mud weight change, a casing point, or a geometry change; a tolerance from "
            "the previous section does not carry over.",
        ),
        pages=(("rabia", "Kick Tolerance §5–6.2", "77–86"),),
        follow_ups=(
            "How do I interpret a leak-off test?",
            "What are the well control signs of a kick?",
        ),
    ),
    # ------------------------------------------------------------------ casing
    StudyEntry(
        key="study-casing-design",
        title="Casing design: collapse, burst, tension and biaxial derating",
        topic="casing",
        keywords=(
            "casing design collapse burst tension biaxial triaxial collapse resistance safety factor design "
            "factor conductor surface intermediate production liner salt section kick"
        ),
        summary=(
            "A casing string is sized for three separate loads — collapse, burst and tension — and then "
            "re-checked for the combination of them, because tension reduces collapse resistance. Design "
            "factors are applied to each criterion, not to the string as a whole."
        ),
        formula=(
            "Burst (pipe body): P = 0.875 · 2 · Yp · t / D. Collapse from the API yield strength formula for "
            "D/t, with the plastic and transitional regimes. Tension: P = Yp · A. Biaxial derating reduces "
            "collapse as axial tension rises."
        ),
        symbols=(
            "Yp = minimum yield strength, psi; for a grade such as P-110 that is 110,000 psi",
            "t = wall thickness, in; D = outside diameter, in; A = steel cross-section, in²",
            "0.875 = the API tolerance allowance on wall thickness used in burst",
        ),
        applies_to=(
            "The loads are chosen from the well's own case: collapse from mud weight and evacuation, burst "
            "from a kick (unlimited and limited-kick designs differ), tension from the string's own weight "
            "plus overpull. Salt sections are designed for an external collapse load that grows over time."
        ),
        checks=(
            "Name the load case behind each factor of safety; a factor without a load case is not a design.",
            "Check the biaxial effect before accepting a collapse rating: a long string in tension collapses "
            "below its uniaxial rating.",
            "A combination string has a change point whose load transfer must be checked, not assumed.",
        ),
        pages=(
            ("rabia", "Casing Design Principles §3–7", "148–177"),
            ("rabia", "Casing Properties §4.2–5.4", "116–132"),
        ),
        follow_ups=(
            "What are the standard casing sizes and their purposes?",
            "How is a kick tolerance used to select a casing seat?",
        ),
    ),
    StudyEntry(
        key="study-casing-types",
        title="Casing and liner types, and what each string is for",
        topic="casing",
        keywords=(
            "casing type conductor surface intermediate production liner drive pipe shoe function size "
            "api grade coupling premium thread drift"
        ),
        summary=(
            "Each string exists for a stated purpose: the conductor enables returns and holds the near-surface, "
            "the surface string protects freshwater and carries the BOP, the intermediate string seals a "
            "problem formation, and the production string isolates the reservoir."
        ),
        formula="",
        symbols=(),
        applies_to=(
            "Casing is roughly a fifth of a completed well's cost, so the string plan is a cost decision as "
            "much as an engineering one. The printed typical ranges are indicative; the actual size follows "
            "from the completion and the BOP stack."
        ),
        checks=(
            "Conductor: 16–36 in outside diameter, set 10–300 ft, drive pipe where hammered.",
            "Surface: usually 20 to 13-3/8 in, set in the first competent formation.",
            "Intermediate: sized from the surface string; set to seal the problem zone.",
            "Production or liner: set across the reservoir, with the liner-tieback and hanger decision taken "
            "before the well is drilled.",
        ),
        pages=(
            ("baker", "Casing and Cementing — Casing", "2-2"),
            ("rabia", "Casing Properties §2–2.2", "101–105"),
        ),
        follow_ups=(
            "How is casing design checked for collapse and burst?",
            "What does a cementing job have to achieve?",
        ),
    ),
    StudyEntry(
        key="study-cementing",
        title="Primary cementing: what the job must achieve and how it is checked",
        topic="casing",
        keywords=(
            "cement cementing primary job spacer slurry displacement annular isolation toc plug "
            "centraliser hole cleaning pump rate"
        ),
        summary=(
            "Cement is placed to bond the casing to the formation, support the string, isolate zones and "
            "protect the casing from corrosion. The job is designed for annular isolation, not for a fill "
            "volume, and it is verified after it sets."
        ),
        formula="",
        symbols=(),
        applies_to=(
            "The design covers slurry volume with excess, spacer and wash for mud removal, displacement "
            "rate for turbulent flow where the hole allows it, centralisation and the setting time before "
            "the shoe is drilled out."
        ),
        checks=(
            "Confirm top of cement on the evaluation log; a cement volume pumped is not a top of cement.",
            "Pressure-test the shoe and the casing before drilling out.",
            "A liner or tieback needs its lap tested and the hanger load checked.",
        ),
        pages=(("baker", "Casing and Cementing — Cementing", "2-6"),),
        follow_ups=(
            "What are the casing types and their purposes?",
            "What causes lost circulation during cementing?",
        ),
    ),
    # ------------------------------------------------------------------ fluids
    StudyEntry(
        key="study-hydraulics-power-law",
        title="Hydraulics: Power Law parameters and annular pressure loss",
        topic="fluids",
        keywords=(
            "hydraulics power law bingham consistency index n k fann 600 300 plastic viscosity yield point "
            "pressure loss annulus standpipe ecd equivalent circulating density pump pressure"
        ),
        summary=(
            "Annular pressure loss adds to hydrostatic pressure and is what makes circulating density higher "
            "than static mud weight. The Power Law model fits the flow curve with two parameters from the "
            "Fann viscometer."
        ),
        formula=(
            "n = 3.32 · log10(θ600 / θ300);  k = 1.067 · (PV + YP) / 511^n (field units). "
            "n and k can also be derived from PV and YP when the dial readings are unavailable."
        ),
        symbols=(
            "θ600, θ300 = Fann VG dial readings at 600 and 300 rpm",
            "k = consistency index (pumpability); n = power index (non-Newtonian behaviour); n = 1 is Newtonian",
            "PV = plastic viscosity, cP; YP = yield point, lb/100 ft²",
        ),
        applies_to=(
            "The Power Law is the common field model; it under-predicts shear stress slightly at low shear "
            "rates. Surface loss uses the IADC equipment class coefficient: Pls = 10⁻⁵ · ks · MD · Q^1.86."
        ),
        checks=(
            "Use the class closest to the rig's equipment, and note that longer surface lines raise the "
            "coefficient while larger IDs lower it.",
            "Drillstring pressure loss is typically about 35 % of pump pressure and varies with roughly the "
            "1.8 power of flow rate.",
            "ECD is the number to compare with the fracture gradient, not the static mud weight.",
        ),
        pages=(("baker", "Drilling Fluids and Hydraulics — Hydraulic Calculations", "1-41 to 1-42"),),
        follow_ups=(
            "How are bit nozzles and hydraulic power sized?",
            "What causes stuck pipe?",
        ),
    ),
    StudyEntry(
        key="study-swab-surge",
        title="Swab and surge: trip speed against the pore pressure and the shoe",
        topic="fluids",
        keywords=(
            "swab surge trip speed pulling running pipe pressure loss gel breaking mobilised annular "
            "friction eccentricity pipe speed kick trip margin"
        ),
        summary=(
            "Moving pipe acts as a piston: pulling the string lowers the pressure below the mud weight "
            "(swab) and running it raises the pressure (surge). Trip speed, mud rheology and gel strength "
            "decide whether either effect crosses the pore pressure or the fracture gradient."
        ),
        formula=(
            "The surge or swab pressure is the sum of the viscous annular loss and the gel-breaking pressure "
            "for the pipe speed used. The equivalent change in mud weight is that pressure divided by "
            "(0.052 · TVD ft)."
        ),
        symbols=(
            "closing pipe speed is the speed at the bit, not the block speed",
            "gel strength and low-shear viscosity dominate the loss at low pipe speed",
        ),
        applies_to=(
            "The swab margin is the trip margin, and a kick after a trip is often its first visible sign. "
            "A long, tight annulus and a fast pull compound the effect."
        ),
        checks=(
            "Compare the swabbed pressure with the pore pressure of the open hole, not with the mud weight.",
            "Compare the surge pressure with the fracture gradient at the shoe before running casing or a "
            "liner.",
        ),
        pages=(("baker", "Swab and Surge Pressures", "1-56 to 1-63"),),
        follow_ups=(
            "What are the well control signs of a kick?",
            "How do Power Law n and k describe the mud?",
        ),
    ),
    StudyEntry(
        key="study-bit-hydraulics",
        title="Bit hydraulics: nozzle area, nozzle velocity and optimisation",
        topic="fluids",
        keywords=(
            "bit hydraulics nozzle jet tfa total flow area nozzle velocity hsi hydraulic horsepower "
            "optimisation bit balling cleaning"
        ),
        summary=(
            "Hydraulic energy at the bit lifts cuttings from under the bit and cleans the face; it is sized "
            "from the total flow area of the nozzles, not from the pump alone."
        ),
        formula=(
            "One jet area = π · (size / 64)² / 4; total flow area = sum of the individual areas. "
            "Nozzle velocity: Vn = 418.3 · Q / Σdj²."
        ),
        symbols=(
            "dj = nozzle size in 32nds of an inch (a size 9 jet is 9/32 in)",
            "Q = flow rate, gal/min; Vn = nozzle velocity, ft/s",
            "Σdj² is the sum of the squares, not the square of the sum",
        ),
        applies_to=(
            "Roller-cone bits usually carry three or four nozzles, PDC six to nine. In soft formations the "
            "hole is partly made by jetting, so rate is limited by connection time and deviation rather than "
            "by bit cleaning."
        ),
        checks=(
            "Calculate the total flow area whenever nozzles are changed; a single plugged nozzle changes the "
            "distribution, not just the total.",
            "Nozzle velocity of the order of 200–250 ft/s is what the workbook quotes as typical for good "
            "bottom-hole cleaning.",
        ),
        pages=(("baker", "Bit Hydraulics and Optimization", "1-48"),),
        follow_ups=(
            "What are Power Law n and k used for?",
            "What is swab and surge pressure?",
        ),
    ),
    # ------------------------------------------------------------------ string
    StudyEntry(
        key="study-drillstring-buoyancy",
        title="Drillstring: buoyancy, hookload, neutral point and WOB",
        topic="drillstring",
        keywords=(
            "drillstring buoyancy buoyed weight hookload neutral point wob bit weight torque drag tubulars "
            "air weight block weight string weight"
        ),
        summary=(
            "The string in the hole weighs its air weight less the buoyant effect of the mud, and the bit "
            "sees only the difference between string weight and hookload. The neutral point is where the "
            "string changes from tension to compression."
        ),
        formula=(
            "Buoyancy factor = 1 − (mud weight ppg / 65.5). Buoyed weight = air weight · buoyancy factor. "
            "WOB = string weight in air − hookload (with the block and line friction accounted for)."
        ),
        symbols=(
            "65.5 ≈ density of steel in ppg, used for the buoyancy factor",
            "Neutral point = depth where axial stress changes sign; it must sit in the drill collars, not in the pipe",
        ),
        applies_to=(
            "The hookload reading is the evidence; a calculated WOB is a check on it. In a deviated hole the "
            "axial component that reaches the bit reduces with inclination and drag absorbs part of the load."
        ),
        checks=(
            "Confirm the neutral point stays within the heavy-weight section; a neutral point in the pipe is a "
            "fatigue path.",
            "Torque and drag are measured against a model; a growing difference on trips is a hole-cleaning "
            "signal.",
        ),
        pages=(
            ("baker", "Drillstring Basics — Buoyancy and Hookload", "4-2 to 4-11"),
            ("baker", "Drillstring Basics — Neutral Point and WOB", "4-11 to 4-24"),
        ),
        follow_ups=(
            "How is a BHA designed and what does the bit see?",
            "What causes stuck pipe?",
        ),
    ),
    # ------------------------------------------------------------------ direction
    StudyEntry(
        key="study-directional-planning",
        title="Directional well planning: profile, build rate and targets",
        topic="direction",
        keywords=(
            "directional well planning profile build turn tangent kick off kop target closure azimuth "
            "minimum curvature dogleg dls survey station anti collision"
        ),
        summary=(
            "A directional profile is defined from a surface location to a subsurface target: a build section, "
            "a tangent, and a turn as needed. The plan is expressed in the same coordinates the surveys are "
            "taken in, so actual and planned are compared station by station."
        ),
        formula=(
            "Minimum curvature between two stations: dogleg β = 2 · asin(√(sin²(Δinc/2) + sin inc1 · sin inc2 · "
            "sin²(Δazi/2))); ratio factor = (2/β) · tan(β/2). TVD and N/E gains are the chord times that factor."
        ),
        symbols=(
            "inc = inclination from vertical, deg; azi = azimuth from north, deg",
            "DLS in deg/30 m; 1 deg/100 ft = 0.9843 deg/30 m",
            "ratio factor tends to 1 as the dogleg tends to zero",
        ),
        applies_to=(
            "The minimum-curvature method is the standard survey calculation; it assumes a smooth arc between "
            "stations, so a long station interval hides a real dogleg. A planned build rate is a design "
            "choice, while DLS is what the survey measured."
        ),
        checks=(
            "Compare vertical section in one plane; a plan view alone does not show whether the well is ahead "
            "or behind in the direction that matters.",
            "Check that the survey's TVD and the report's TVD agree — a difference is a data question, not a "
            "rounding difference.",
        ),
        pages=(
            ("baker", "Directional Drilling — Well Planning", "5-7 to 5-20"),
            ("rabia", "Horizontal and Multilateral Wells — Well Profile Design", "631–637"),
        ),
        follow_ups=(
            "How do I read a directional survey and dogleg severity?",
            "What is toolface and how is it oriented?",
        ),
    ),
    StudyEntry(
        key="study-toolface-motors",
        title="Downhole motors, toolface and deflection methods",
        topic="direction",
        keywords=(
            "mud motor pdm toolface magnetic gravity highside deflection bent sub rotary steerable "
            "slide rotate build walk orientation"
        ),
        summary=(
            "A positive-displacement motor with a bent housing drills a curve when it slides and holds angle "
            "when it rotates. Toolface is the direction the bit is being pushed; it is referenced to magnetic "
            "north at low inclination and to high side at high inclination."
        ),
        formula="",
        symbols=(),
        applies_to=(
            "Slide drilling: the string does not turn, so the reactive torque settles and the toolface holds. "
            "Rotating the same assembly averages the bend out and builds less, or turns the hole, depending "
            "on the assembly."
        ),
        checks=(
            "Pick toolface reference from the inclination: magnetic toolface downhole, gravity/high-side where "
            "the hole is near horizontal.",
            "A slide's build is set by the bend and the formation; a reactive-torque estimate that is wrong by "
            "tens of degrees is a common cause of an unwanted turn.",
        ),
        pages=(
            ("baker", "Directional Drilling — Downhole Motors and Toolface", "5-21 to 5-49"),
        ),
        follow_ups=(
            "How is a directional well planned?",
            "How is dogleg severity calculated?",
        ),
    ),
    # ------------------------------------------------------------------ problems
    StudyEntry(
        key="study-differential-sticking",
        title="Differential sticking: force, recognition and freeing the pipe",
        topic="problems",
        keywords=(
            "differential differentially sticking stuck stick pipe wall contact overbalance filter cake "
            "freeing free pipe u tube spotting release spot release agent jar mop maximum overpull"
        ),
        summary=(
            "Differential sticking happens when the string rests against a permeable, overbalanced formation "
            "and the mud column pushes the pipe into the filter cake. The force is proportional to the "
            "overbalance and the contact area, so the cure is to reduce one of them."
        ),
        formula=(
            "Sticking force ≈ ΔP · A · μ, where ΔP is overbalance (psi), A the contact area (in²) and μ the "
            "friction coefficient between pipe and cake."
        ),
        symbols=(
            "ΔP = hydrostatic pressure − formation pressure, psi",
            "A = area of pipe in contact with the permeable zone",
            "μ = friction coefficient, a property of the cake and the pipe",
        ),
        applies_to=(
            "Recognised by: the string is stuck without circulation loss, it can be worked only in one "
            "direction, and the free point is above the permeable zone. Reduce hydrostatic pressure within "
            "the pore-pressure and kick-tolerance limits before pulling harder."
        ),
        checks=(
            "Never exceed the string's make-up torque or the derrick capacity to free pipe; calculate the "
            "maximum overpull first.",
            "Spotted release agents and U-tube displacement reduce the differential; both must be checked "
            "against the pore pressure of the open hole.",
        ),
        pages=(("rabia", "Hole Problems — Differential Sticking", "573–584"),),
        follow_ups=(
            "What causes mechanical sticking and hole pack-off?",
            "How is a free point found and a string backed off?",
        ),
    ),
    StudyEntry(
        key="study-hole-problems",
        title="Mechanical sticking: pack-off, key seating, undergauge hole and bit balling",
        topic="problems",
        keywords=(
            "mechanical sticking pack off hole collapse key seat undergauge tight hole bit balling shale "
            "instability unconsolidated salt mobile formation washout cuttings bed stuck pipe"
        ),
        summary=(
            "Mechanical sticking is a shape or a solid in the hole: a key seat, an undergauge section, a "
            "settled cuttings bed, a collapsing shale, or junk. Identifying which one decides the remedy."
        ),
        formula="",
        symbols=(),
        applies_to=(
            "The distinguishing evidence is where in the string the pipe stopped, whether circulation is "
            "possible, how the hole behaved on the last trip, and whether the string can be rotated."
        ),
        checks=(
            "Hole pack-off: restricted circulation, rising standpipe pressure, and a string that can be "
            "worked but not circulated — treat as a stuck-pipe event, not as a pump problem.",
            "Key seating: the pipe runs freely in the string's own groove and sticks immediately below a "
            "dogleg on the way out.",
            "Undergauge hole: the bit is oversized or the formation has closed in; reaming is the remedy, and "
            "the trip record shows it.",
            "Bit balling: reactive shale packing the bit; hydraulic and mud changes, not more weight.",
        ),
        pages=(("rabia", "Hole Problems §4–5", "584–603"),),
        follow_ups=(
            "How is differential sticking freed?",
            "What causes lost circulation and how is it cured?",
        ),
    ),
    StudyEntry(
        key="study-lost-circulation",
        title="Lost circulation: causes, classes and cures",
        topic="problems",
        keywords=(
            "lost circulation losses natural induced fracture seepage partial severe total lcm "
            "lost circulation material ecd surge mud weight cure"
        ),
        summary=(
            "Losses are either natural — into a porous or vuggy formation — or induced, when the pressure in "
            "the hole exceeds the formation's breakdown pressure. The class of the loss decides the cure."
        ),
        formula="Effective annular density due to cuttings ≈ mud weight + cuttings contribution; a full "
        "annulus of cuttings can raise ECD by a material amount. Total flow area is not the cure — the ECD is.",
        symbols=(
            "Seepage/partial/severe/total describe the loss rate, not the volume lost",
            "LCM = lost circulation material, sized to the pore throat or fracture width",
        ),
        applies_to=(
            "Reduce the ECD before adding material: mud weight, annular viscosity, gel strength, surge "
            "pressure on connections, and cuttings loading all raise it."
        ),
        checks=(
            "Confirm the loss is in the formation and not a surface leak or a shaker.",
            "Check whether the loss occurred while circulating, while static, or on a connection — that names "
            "the mechanism.",
            "A cure that reduces pressure too far can convert a loss into a kick; keep the pore pressure of "
            "the open hole in view.",
        ),
        pages=(("rabia", "Hole Problems — Lost Circulation §8", "613–622"),),
        follow_ups=(
            "What causes differential sticking?",
            "How do I interpret a leak-off test?",
        ),
    ),
    StudyEntry(
        key="study-well-control",
        title="Well control: kick signs, shut-in pressures and the kill sheet",
        topic="pressure",
        keywords=(
            "well control kick influx pit gain flow check shut in pressure sicp sidpp maasp kill mud "
            "driller method wait and weight slow circulation rate kick tolerance"
        ),
        summary=(
            "A kick is formation fluid entering the wellbore because the mud weight is below the pore pressure. "
            "It is detected by pit gain, an increase in flow with the pumps off, or a change in pump pressure, "
            "and controlled by shutting in and circulating kill-weight mud."
        ),
        formula=(
            "Kill mud weight (ppg) = current mud weight + SIDPP / (0.052 · TVD). Initial circulating pressure "
            "= SIDPP + slow circulating rate pressure. MAASP = (FG at shoe − current mud weight) · 0.052 · shoe TVD."
        ),
        symbols=(
            "SIDPP = shut-in drillpipe pressure, psi; SICP = shut-in casing pressure",
            "MAASP = maximum allowable annular surface pressure",
            "FG = fracture gradient at the shoe; TVD in ft",
        ),
        applies_to=(
            "The shut-in pressures are the evidence: drillpipe pressure reads the pore pressure, casing "
            "pressure reads the influx. Record both, plus pit gain and the slow circulating rate pressure, "
            "before any action."
        ),
        checks=(
            "Confirm the stabilised pressures before calculating; an early reading understates the kill weight.",
            "The choke holds casing pressure on the schedule, not at a fixed value; MAASP is a limit to stay "
            "under, not a target.",
            "A kick after a trip is often a swab effect; check the trip margin against the pore pressure.",
        ),
        pages=(
            ("baker", "Well Control — Kicks and Kick Control", "8-3 to 8-22"),
            ("rabia", "Kick Tolerance §11", "89–95"),
        ),
        follow_ups=(
            "How is kick tolerance calculated?",
            "What is swab and surge pressure?",
        ),
    ),
    # ------------------------------------------------------------------ bits
    StudyEntry(
        key="study-bit-selection",
        title="Bit selection: IADC classes, cutting structure and when a bit is dull",
        topic="bits",
        keywords=(
            "bit selection iadc roller cone pdc diamond cutting structure dull grading iadc dull code "
            "wear insert tungsten carbide gauge"
        ),
        summary=(
            "A bit is chosen for the formation it will drill: roller-cone for harder and more abrasive rock, "
            "PDC shearing for shale and homogeneous formations, diamond for the hardest and most abrasive. "
            "The dull grading is what tells you whether the choice was right."
        ),
        formula="",
        symbols=(),
        applies_to=(
            "The run record — footage, hours, dull grade — is the evidence. A bit that comes out with a "
            "ring-out or a broken cutter is a formation or a parameter problem, not a bit problem."
        ),
        checks=(
            "Read the dull code before the next bit is ordered: wear pattern names the failure mode.",
            "A gauge-under bit reams the next hole undersize; check gauge on every trip.",
        ),
        pages=(
            ("baker", "Bit Technology", "3-2 to 3-41"),
            ("baker", "Bit Technology — PDC and diamond bits", "3-13 to 3-30"),
        ),
        follow_ups=(
            "How are bit nozzles sized?",
            "How is cost per foot calculated?",
        ),
    ),
    # ------------------------------------------------------------------ cost
    StudyEntry(
        key="study-cost-per-foot",
        title="Cost per foot, break-even and drilling optimisation",
        topic="cost",
        keywords=(
            "cost per foot break even bit cost rig rate trip time optimisation drilling cost analysis "
            "technical limit p10 p50 p90 risked cost"
        ),
        summary=(
            "Cost per foot puts a bit run's footage, rotating time and the rig rate on one number, so two "
            "runs or two bit types can be compared honestly. Break-even analysis asks how much footage a "
            "more expensive bit must deliver to pay for itself."
        ),
        formula=(
            "Cost per foot = (bit cost + rig rate · (rotating hours + trip hours)) / footage. "
            "Break-even extra footage = extra bit cost / cost per foot of the alternative."
        ),
        symbols=(
            "rig rate includes the spread cost for the time the operation occupies the rig",
            "trip hours belong in the denominator's numerator because the trip is time the rig is paid for",
        ),
        applies_to=(
            "The comparison is only valid between runs in comparable formations. A cheaper bit that drills "
            "slower can still cost more per foot; that is what the formula is for."
        ),
        checks=(
            "Use the actual trip time for the well, not a standard; a deep well's trip is a real cost item.",
            "A P10/P50/P90 range states confidence in a cost estimate; it is not three forecasts.",
        ),
        pages=(
            ("baker", "Cost Analysis — Cost per Foot", "9-2 to 9-9"),
            ("rabia", "Well Costing §5–9", "751–764"),
        ),
        follow_ups=(
            "How is a well cost estimate built?",
            "How is NPT classified and charged?",
        ),
    ),
    StudyEntry(
        key="study-time-depth-cost",
        title="Time–depth curves, detailed time estimates and the well cost build-up",
        topic="cost",
        keywords=(
            "time depth curve drilling time estimate detailed estimate well costing rig rate tangibles "
            "services npt risked p10 p50 p90 technical limit contracting turnkey"
        ),
        summary=(
            "A well cost is a time estimate multiplied by the day rate plus the tangible and service items. "
            "The time–depth curve is built section by section from the operational steps, starting with the "
            "deepest offset that resembles the well to be drilled."
        ),
        formula=(
            "Total cost = rig time cost + tangibles + services + NPT allowance, with the time basis stated "
            "per section."
        ),
        symbols=(
            "day rate covers the rig and its crews; the spread is priced separately",
            "NPT is time that was not in the plan, costed with the same rate as the plan",
        ),
        applies_to=(
            "A risked estimate (P10/P50/P90) applies a range to the time, not to the rate. The technical limit "
            "is the best-in-class time for the same steps, used as a target, not as a budget."
        ),
        checks=(
            "State whether a day is a calendar day or an operating day; averaging across both hides the "
            "slow days.",
            "NPT allowance is a probability-weighted figure; a plan with no NPT allowance has assumed none.",
        ),
        pages=(
            ("rabia", "Well Costing §3–8", "747–763"),
            ("baker", "Cost Analysis — Breakeven and Optimisation", "9-11 to 9-24"),
        ),
        follow_ups=(
            "How is cost per foot calculated?",
            "What is the difference between planned, UPA and NPT hours?",
        ),
    ),
    # ------------------------------------------------------------------ holes
    StudyEntry(
        key="study-wellbore-stability",
        title="Wellbore stability: stress, failure criteria and the safe mud weight window",
        topic="problems",
        keywords=(
            "wellbore stability breakouts collapse mud weight window in situ stress mohr coulomb drucker "
            "prager tensile failure depletion compaction sand production"
        ),
        summary=(
            "The mud weight window is bounded below by shear failure (collapse) and above by tensile failure "
            "(breakdown). Both bounds depend on the in-situ stress state, the rock strength and the well's "
            "orientation and inclination relative to those stresses."
        ),
        formula=(
            "Mohr–Coulomb: failure when shear stress exceeds cohesion + normal stress · tan(friction angle). "
            "Drucker–Prager is a smooth generalisation suitable for numerical models."
        ),
        symbols=(
            "in-situ stresses: vertical (overburden) and two horizontal principal stresses, with an azimuth",
            "cohesion and friction angle come from core or log-derived rock strength",
            "the safe window also shifts with depletion of a nearby reservoir",
        ),
        applies_to=(
            "The stress state is inferred from breakouts, drilling-induced fractures and leak-off tests, not "
            "assumed from a world stress map. A deviated well transforms the stresses before a failure "
            "criterion is applied."
        ),
        checks=(
            "Calibrate the model against the observed breakouts and the measured fracture gradient in the same "
            "well; an uncalibrated model is a hypothesis.",
            "A tight window is a design constraint on the casing seats, not only on the mud weight.",
        ),
        pages=(("rabia", "Wellbore Stability §1–7", "527–565"),),
        follow_ups=(
            "What causes hole collapse and pack-off?",
            "How is a casing seat selected?",
        ),
    ),
    # ------------------------------------------------------------------ rig
    StudyEntry(
        key="study-rig-components",
        title="Rig components: hoisting, circulating system and power sizing",
        topic="rig",
        keywords=(
            "rig component hoisting drawworks derrick mast travelling block drilling line ton miles "
            "mud pump liner volumetric efficiency horsepower pump output standpipe rotary"
        ),
        summary=(
            "The hoisting system moves the string, the circulating system moves the fluid, and both are sized "
            "from the deepest and heaviest string the well will need. Line service — ton-miles — is a "
            "maintenance account as much as an engineering one."
        ),
        formula=(
            "Hook load = string weight in air · buoyancy factor + block weight. Line tension per line = hook "
            "load / (number of lines · efficiency). Pump output = liner area · stroke length · strokes/min · "
            "volumetric efficiency."
        ),
        symbols=(
            "number of lines is the strung line count, not the sheave count",
            "volumetric efficiency is typically below 100 % and is measured, not assumed as 100",
        ),
        applies_to=(
            "The derrick and substructure rating bounds the hook load. The pump's rated pressure is at a "
            "liner size; a larger liner gives more rate at lower pressure, not both."
        ),
        checks=(
            "Check the sheave and line count before converting a hook load to line tension.",
            "Cut and slip the drilling line on ton-miles, with the cut-off practice the contractor specifies.",
        ),
        pages=(("rabia", "Rig Components §2–5", "714–735"),),
        follow_ups=(
            "How is a mud pump's horsepower calculated?",
            "How is cost per foot calculated?",
        ),
    ),
    # ------------------------------------------------------------------ completion
    StudyEntry(
        key="study-hpht",
        title="HPHT wells: mud, casing, cement and trapped annulus pressure",
        topic="completion",
        keywords=(
            "hpht high pressure high temperature sbm water based barite sag gel breaking ballooning "
            "trapped annulus pressure thermal expansion casing design brine test fluid"
        ),
        summary=(
            "A high-pressure high-temperature well changes the answers to questions a conventional well takes "
            "for granted: the mud's own thermal behaviour, the casing's strength at temperature, and the "
            "pressure that builds in a sealed annulus."
        ),
        formula=(
            "Trapped annulus pressure rises with the temperature increase of the sealed fluid; the analysis "
            "uses the fluid's compressibility and the casing's elastic response."
        ),
        symbols=(
            "a sealed annulus has no route for thermal expansion; the pressure is a design load on both strings",
        ),
        applies_to=(
            "Barite sag, gel breaking pressures, ballooning and breathing are all HPHT mud behaviours that "
            "look like a well control event and are not one. Test with a fluid that does not mask the "
            "formation response."
        ),
        checks=(
            "Confirm the casing yield at the expected temperature; a burst rating at 20 °C is not the rating "
            "at 200 °C.",
            "Design for the trapped annulus pressure, including the effect of a cemented annulus that cannot "
            "relieve.",
        ),
        pages=(("rabia", "High Pressure and High Temperature Wells §1–8", "677–711"),),
        follow_ups=(
            "How is casing design checked?",
            "What causes ballooning and breathing?",
        ),
    ),
    StudyEntry(
        key="study-horizontal-multilateral",
        title="Horizontal and multilateral wells: profile, drag and junctions",
        topic="direction",
        keywords=(
            "horizontal well multilateral short radius medium long radius build curve torque drag buckling "
            "extended reach junction taml whipstock window"
        ),
        summary=(
            "A horizontal well trades vertical depth for reservoir exposure. The profile is a single or "
            "double build to horizontal, and the difficulty moves from trajectory to drag, buckling and hole "
            "cleaning in the long tangent."
        ),
        formula=(
            "Drag in the tangent: the axial force needed to move the string includes the friction of its "
            "buoyed weight against the low side. Critical buckling force sets the limit for weight transfer "
            "to the bit."
        ),
        symbols=(
            "short / medium / long radius describe the build rate to horizontal and the tool that achieves it",
            "TAML levels describe the pressure integrity of a multilateral junction",
        ),
        applies_to=(
            "An extended-reach well is limited by rig capacity and by the string's ability to transmit weight; "
            "the buckling check covers the build, the tangent and above the kick-off."
        ),
        checks=(
            "Check the critical buckling force in each hole section, not only at the bit.",
            "A junction has a pressure rating and a debris-control requirement; both are design inputs.",
        ),
        pages=(
            ("rabia", "Horizontal and Multilateral Wells §2–7", "627–671"),
            ("baker", "Horizontal Wells", "6-2"),
        ),
        follow_ups=(
            "How is a directional well planned?",
            "What is torque and drag and why does it matter?",
        ),
    ),
)


_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Words that carry no engineering meaning. Without this, "how do I do it" scores
#: against any entry whose prose happens to share a pronoun.
_STOP = frozenset(
    """
    a an and any are as at be been being but by can could did do does for from get got had has have
    how i if in into is it its just like may me more most much must my no not of on or our out over
    should so some than that the their them then there these they this those to too up us use used
    using was we were what when where whether which while who why will with would you your
    """.split()
)


def _stem(word: str) -> str:
    """A deliberately small plural strip: nozzles/nozzle, strings/string."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> set[str]:
    return {
        _stem(token)
        for token in _TOKEN_RE.findall((text or "").lower())
        if len(token) >= 2 and token not in _STOP
    }


#: Compound terms that carry a specific meaning; an exact phrase is stronger
#: evidence than the same words apart.
_PHRASES = (
    "d exponent",
    "dc exponent",
    "d-exponent",
    "dc-exponent",
    "pore pressure",
    "leak off test",
    "fracture gradient",
    "kick tolerance",
    "casing design",
    "collapse resistance",
    "cost per foot",
    "break even",
    "toolface",
    "dogleg",
    "minimum curvature",
    "well control",
    "shut in",
    "lost circulation",
    "differential sticking",
    "stuck pipe",
    "hole cleaning",
    "nozzle velocity",
    "flow area",
    "power law",
    "neutral point",
    "trapped annulus",
    "multilateral",
    "horizontal well",
    "wellbore stability",
    "mud weight window",
    "ton miles",
    "casing seat",
    "drilling line",
    "cementing",
    "cement job",
)


#: Words every well question contains. They earn nothing toward a match: a
#: question naming "drilling depth and NPT summary" must not be answered from an
#: entry about time–depth cost curves merely because both mention depth and
#: drilling. Distinctive words are what carry a match.
_COMMON_DOMAIN_WORDS = frozenset("""
    bit bha casing cement depth drill drilled driller drilling formation hole
    log mud oil field gas npt operation operations pipe pressure report rig
    section string summary tool well wells welle wellbore
""".split())


def match_study_entries(question: str, *, limit: int = 3, minimum: int = 6) -> list[tuple[int, StudyEntry]]:
    """Rank the study entries against a free-text engineering question.

    The threshold exists because a weak match is worse than no match: an entry
    about cost per foot must not be offered for a question about mud weight.
    A match must also rest on at least one *distinctive* word, so a question
    that only shares the vocabulary of the domain with an entry is not answered
    from it.
    """
    q = (question or "").lower()
    tokens = _tokens(q)
    if not tokens:
        return []
    distinctive = tokens - _COMMON_DOMAIN_WORDS
    scored: list[tuple[int, StudyEntry]] = []
    for entry in STUDY_ENTRIES:
        keyword_tokens = _tokens(entry.keywords)
        title_tokens = _tokens(entry.title)
        topic_tokens = _tokens(entry.topic)
        overlap = tokens & keyword_tokens
        if not overlap:
            # A title or topic hit alone is a hint, never a match.
            continue
        if not (distinctive & (keyword_tokens | title_tokens)):
            # Only domain-wide words agree: no evidence this entry is the subject.
            continue
        score = len(overlap) * 3 + len(tokens & title_tokens) * 2 + len(tokens & topic_tokens)
        if any(phrase in q for phrase in _PHRASES):
            # A printed compound term is stronger evidence than the same words
            # apart. Short words ("d" in "d exponent") are legitimate here, so the
            # check uses raw words rather than the stop-worded token set.
            raw_keywords = set(_TOKEN_RE.findall(entry.keywords.lower()))
            raw_title = set(_TOKEN_RE.findall(entry.title.lower()))
            for phrase in _PHRASES:
                if phrase in q and all(
                    _stem(word) in raw_keywords or _stem(word) in raw_title for word in phrase.split()
                ):
                    score += 6
        if score >= minimum:
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], item[1].key))
    return scored[:limit]


def study_context(question: str, *, max_entries: int = 2) -> str:
    """A compact block for an Ollama system prompt: the arithmetic, not the prose."""
    matches = match_study_entries(question, limit=max_entries)
    if not matches:
        return ""
    lines = ["STUDY-BOOK ENGINEERING REFERENCE (derivations and printed ranges only; a value that depends on "
             "the well must be measured, not assumed):"]
    for _, entry in matches:
        lines.append(f"[{entry.title}] {entry.summary}")
        if entry.formula:
            lines.append(f"  FORMULA: {entry.formula}")
        if entry.symbols:
            lines.append("  SYMBOLS: " + "; ".join(entry.symbols))
        if entry.applies_to:
            lines.append(f"  APPLIES TO: {entry.applies_to}")
        for citation in entry.citations()[:2]:
            lines.append(f"  SOURCE: {citation}")
    return "\n".join(lines)


def study_follow_ups(question: str, *, limit: int = 1) -> list[str]:
    """Questions that lead a reader deeper into the same subject."""
    out: list[str] = []
    for _, entry in match_study_entries(question, limit=limit):
        out.extend(entry.follow_ups)
    return out


#: The order a reader expects the library in: what is being drilled, then what
#: can go wrong, then what it costs.
TOPIC_ORDER = ("pressure", "casing", "fluids", "drillstring", "direction", "bits", "problems", "rig", "completion", "cost")

TOPIC_LABELS = {
    "pressure": "Pressure, integrity and well control",
    "casing": "Casing and cementing",
    "fluids": "Fluids and hydraulics",
    "drillstring": "Drillstring and bit mechanics",
    "direction": "Directional drilling",
    "bits": "Bit technology",
    "problems": "Hole problems and stuck pipe",
    "rig": "Rig equipment",
    "completion": "Completion and HPHT",
    "cost": "Cost and optimisation",
}


def study_library() -> list[dict]:
    """The study books as a browsable library, grouped by subject.

    This is what the guide page reads when nobody wants to ask a question: the
    same entries the assistant answers from, with their arithmetic and their
    page references, so a reader can use the books without a model in the loop.
    """
    grouped: dict[str, list[dict]] = {topic: [] for topic in TOPIC_ORDER}
    for entry in STUDY_ENTRIES:
        grouped.setdefault(entry.topic, []).append(
            {
                "key": entry.key,
                "title": entry.title,
                "topic": entry.topic,
                "summary": entry.summary,
                "formula": entry.formula,
                "symbols": list(entry.symbols),
                "applies_to": entry.applies_to,
                "checks": list(entry.checks),
                "citations": entry.citations(),
                "follow_ups": list(entry.follow_ups),
            }
        )
    return [
        {
            "topic": topic,
            "label": TOPIC_LABELS.get(topic, topic.replace("-", " ").title()),
            "entries": grouped.get(topic, []),
        }
        for topic in TOPIC_ORDER
        if grouped.get(topic)
    ]


def study_sources() -> list[dict]:
    """The works themselves, for the page's own attribution line."""
    return [
        {"key": source.key, "author": source.author, "title": source.title}
        for source in (RABIA, BAKER)
    ]
