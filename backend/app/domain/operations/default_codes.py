"""Read-only reference from the supplied engineering code sheet and observed OpenWells layouts.

This is not a vendor-wide official catalogue. These lists must not contain master data
such as wells, rigs, blocks, fields, or agencies. The extraction engine and Code Library
share them, so the same token always gets the same definition.
"""

from dataclasses import asdict, dataclass

from app.domain.operations.taxonomy import code_key


@dataclass(frozen=True)
class DefaultCode:
    family: str
    code: str
    name: str
    source: str = "Engineering workbook"
    description: str = ""
    classification: str = ""
    allocation: str = ""

    @property
    def label(self) -> str:
        return f"{self.code} — {self.name}"


# Paired columns from docs/operations/activity-taxonomy-extracted.csv. Display
# Workbook definitions. Zero padding is not significant within a code family.
ACTIVITY = (
    ('01', 'Preparation'),
    ('02', 'Rig moves'),
    ('03', 'Rotation hours at bottom'),
    ('04', 'Trips'),
    ('05', 'Installation / disassembly'),
    ('06', 'Wiper trip and reaming'),
    ('07', 'Circulation'),
    ('08', 'Fluids preparation'),
    ('09', 'Fluids pumping in well'),
    ('10', 'Fluid / core recovery'),
    ('11', 'Measurement and detection in well'),
    ('12', 'Equipment test'),
    ('13', 'Working on'),
    ('14', 'Milling'),
    ('15', 'Through tubing operation'),
    ('16', 'Shot / perforation'),
    ('17', 'Plugs & squeezes'),
    ('18', 'Casing & tubing cut and recovery'),
    ('19', 'Various operations in well'),
    ('20', 'Various operations at surface'),
    ('21', 'Waiting in general'),
    ('22', 'Waiting environmental conditions'),
    ('23', 'Waiting materials'),
    ('24', 'Waiting materials'),
    ('25', 'Maintenance and repair'),
    ('26', 'Strike'),
    ('27', 'Not accurate or no news available'),
    ('28', 'Hole opening'),
    ('29', 'Fishing'),
    ('30', 'Various safety drills'),
    ('31', 'Redress tubing safety valve (TSV)'),
    ('32', 'Redress surface-controlled subsurface safety valve (SCSSV)'),
    ('33', 'Test surface-controlled subsurface safety valve (SCSSV)'),
    ('34', 'Cement drilling'),
    ('35', 'Directional work'),
    ('36', 'Downhole test (LOT / FIT / casing test)'),
    ('37', 'HSE issues'),
)

OPERATION = (
    ('A', 'MOVING (Rig up / Rig down)'),
    ('B', 'Skidding'),
    ('C', 'Wellhead and BOP'),
    ('D', 'Conductor pipe'),
    ('E', 'Drilling'),
    ('F', 'SIDE TRACK or RE-DRILLING'),
    ('G', 'Casing job'),
    ('H', 'Cementing job'),
    ('I', 'Coring'),
    ('J', 'Logging'),
    ('K', 'Well completion'),
    ('L', 'Well decompletion'),
    ('M', 'Well preparation'),
    ('N', 'Sand control'),
    ('O', 'Wellbore treatment'),
    ('P', 'Well test / drill stem test (DST)'),
    ('Q', 'Well abandoning'),
    ('R', 'Slickline'),
    ('S', 'Coiled tubing'),
    ('T', 'Artificial lift'),
)

PHASE = (
    ('ABAN', 'Well abandoning'),
    ('COMP', 'Completion'),
    ('DRILL', 'Drilling'),
    ('MOB', 'Rig moving'),
    ('PREP', 'Preliminary'),
    ('PROD-MAN', 'Production maintenance'),
    ('RE-EN', 'Re-entry'),
    ('SEC-WELL', 'Secure the well'),
    ('W.O.', 'Work over'),
    ('W.T.', 'Well testing'),
)

CAUSE = (
    ('SP', 'Slow progress'),
    ('TH', 'Tubular Handling'),
    ('CH', 'Casing Handling'),
    ('BHAH', 'BHA Handling'),
    ('EQF', 'Equipment Failure'),
    ('CRW', 'Crew non-performance or non-availability'),
    ('OTH', 'Other reasons'),
    ('UPA', 'Unplanned Activity'),
    ('TNA', 'Third-party tools unavailable'),
    ('WOE', 'Waiting on Equipment'),
    ('DHP', 'Down Hole Problem'),
    ('HC', 'Hole Cleaning'),
    ('DLS', 'Well Inclination'),
    ('TW01', 'Trouble-Waiting-Weather'),
    ('TW02', 'Trouble-Waiting-Contractors equipment/materials'),
    ('TW03', 'Trouble-Waiting-Company equipment/materials/orders'),
    ('TW99', 'Trouble-Waiting-Other'),
)

NPT = (
    ('TP01', 'Well problems / Circulating Losses'),
    ('TP02', 'Well problems / Stuck pipe'),
    ('TP03', 'Well problems / Fluid influx'),
    ('TP04', 'Well problems / Other geological problems'),
    ('TP05', 'Well problems / Cased hole problems'),
    ('TP99', 'Well problems / Other well problems'),
    ('TR01', 'Rig Failure / Drawwork'),
    ('TR02', 'Rig Failure / Mud pumps'),
    ('TR03', 'Rig Failure / Power generation system'),
    ('TR04', 'Rig Failure / TDS'),
    ('TR05', 'Rig Failure / Surface B.O.P.'),
    ('TR06', 'Rig Failure / Subsea Equipment'),
    ('TR07', 'Rig Failure / Mooring'),
    ('TR99', 'Rig Failure / Other'),
    ('TD01', 'Down Hole Equipment Failure / BHA/drill string'),
    ('TD02', 'Down Hole Equipment Failure / Casing/Liner'),
    ('TD03', 'Downhole equipment failure / Completion or testing tools'),
    ('TD04', 'Downhole equipment failure / Wireline equipment'),
    ('TD05', 'Down Hole Equipment Failure / Coiled tubing'),
    ('TD99', 'Down Hole Equipment Failure / Other'),
    ('TS01', 'Surface equipment Failure / Wellhead'),
    ('TS02', 'Surface equipment Failure / Company surface'),
    ('TS03', 'Surface equipment failure / Contractor equipment'),
    ('TS99', 'Surface equipment Failure / Other'),
    ('TW01', 'Waiting / Weather'),
    ('TW02', 'Waiting / Contractors equipment/materials'),
    ('TW03', 'Waiting / Company equipment/materials/orders'),
    ('TW99', 'Waiting / Other'),
)

OPENWELLS_PHASES = (
    ('DRLSUR', 'Drill surface hole'),
    ('DRLIN1', 'Drill first intermediate hole'),
    ('DRLIN2', 'Drill second intermediate hole'),
    ('DRLIN3', 'Drill third intermediate hole'),
    ('DRLPRO', 'Drill production hole'),
    ('CSGDRV', 'Drive casing'),
    ('CSGCON', 'Conductor casing'),
    ('CSGSUR', 'Surface casing'),
    ('CSGIN2', 'Second intermediate casing'),
    ('CSGPRO', 'Production casing'),
    ('EVAL', 'Formation evaluation / logging'),
    ('EVAL 1', 'Formation evaluation / logging (stage 1)'),
    ('EVALPR', 'Production-hole evaluation / logging'),
    ('COMPLETION', 'Completion operations'),
)

# These are descriptions of use in the supplied exports, not vendor definitions.
# Even the same number within this set can cover more than one kind of work.
OPENWELLS_CODES = (
    ('01', 'Cement-job setup / surface line testing'),
    ('02', 'Drilling ahead or rigging down tools'),
    ('03', 'Backreaming / downreaming'),
    ('05', 'Circulation and displacement'),
    ('06', 'Wiper trips, reaming and other trips'),
    ('07', 'Top drive service / saver-sub change'),
    ('08', 'Engine trip and interruption'),
    ('10', 'Shallow mud-motor test'),
    ('11', 'Gyro surveys, logging or slickline work'),
    ('12', 'Running casing or liner and related setup'),
    ('15', 'BOP pressure test or tester handling'),
    ('19', 'Fishing and overshot handling'),
    ('21', 'Waiting for a decision / housekeeping'),
    ('24', 'Pumping out of hole'),
    ('25', 'Mixed preparation, equipment and downhole work'),
)

MARKS = (
    ('P', 'Planned', 'Planned', ''),
    ('PLANNED', 'Planned (long form)', 'Planned', ''),
    ('U', 'Unplanned productive activity', 'UPA', ''),
    ('D', 'Down / downtime', 'NPT', ''),
    ('N', 'Nonproductive time (short form)', 'NPT', ''),
)
ALLOCATIONS = (
    ('PT', 'Planned time', '', 'PT'),
    ('UPA', 'Unplanned productive activity', '', 'UPA'),
    ('NPT', 'Nonproductive time', '', 'NPT'),
    ('SP', 'Slow progress', '', 'SP'),
)

_ACTIVITY_DETAILS = {
    '03': 'Time rotating at bottom. Confirm actual rotating hours and matching measured-depth gain before calculating ROP.',
    '04': 'Moving the drillstring in or out of the hole. Bit depth can change without any new hole drilled.',
    '06': 'Conditioning a hole by making a wiper trip or reaming. This code alone does not indicate downtime or newly drilled footage.',
    '07': 'Circulating drilling fluid. Circulation hours are not automatically rotating hours.',
    '25': 'Maintenance or repair. Verify whether it was scheduled or a breakdown before assigning downtime.',
}

DEFAULT_CODES = (
    *(DefaultCode('Activity', code, name, 'Engineering workbook · Codes sheet', _ACTIVITY_DETAILS.get(code, ''))
      for code, name in ACTIVITY),
    *(DefaultCode('OpenWells code token', code, name, 'Observed OpenWells narrative',
                  'Observed use in the supplied PDFs, not a vendor definition. Check the row narrative; the same token can cover different work.')
      for code, name in OPENWELLS_CODES),
    *(DefaultCode('OpenWells phase', code, name, 'Observed OpenWells layout') for code, name in OPENWELLS_PHASES),
    *(DefaultCode('Operation', code, name) for code, name in OPERATION),
    *(DefaultCode('Programme phase', code, name) for code, name in PHASE),
    *(DefaultCode('Source mark', code, name, 'Report convention',
                  'A classification suggestion; verify against the activity narrative.', classification, allocation)
      for code, name, classification, allocation in MARKS),
    *(DefaultCode('Allocation', code, name, 'Report convention',
                  'Allocation is reviewed separately from classification.', classification, allocation)
      for code, name, classification, allocation in ALLOCATIONS),
    *(DefaultCode('Cause', code, name) for code, name in CAUSE),
    *(DefaultCode('Trouble / NPT', code, name, classification='NPT', allocation='NPT') for code, name in NPT),
    *(DefaultCode('Trouble / NPT', 'X' + code[1:], f'Unplanned trouble / {name}', classification='UPA', allocation='NPT')
      for code, name in NPT),
)

_BY_CODE = {(entry.family, code_key(entry.code)): entry for entry in DEFAULT_CODES}


def find_code(value: str, *families: str) -> DefaultCode | None:
    key = code_key(value)
    return next((entry for family in families if (entry := _BY_CODE.get((family, key)))), None)


def describe_code(value: str, *families: str) -> str:
    if not value:
        return ''
    entry = find_code(value, *families)
    return f'{value} — {entry.name}' if entry else f'{value} — not mapped'


def catalogue_rows() -> list[dict]:
    return [{'id': f'{entry.family}:{entry.code}', **asdict(entry)} for entry in DEFAULT_CODES]
