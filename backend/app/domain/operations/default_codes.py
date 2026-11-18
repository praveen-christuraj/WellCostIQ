"""Read-only reference from the supplied engineering code sheets and OpenWells layouts.

This is not a vendor-wide official catalogue. These lists must not contain master data
such as wells, rigs, blocks, fields, or agencies. The extraction engine and Code Library
share them, so the same token always gets the same definition.

Two printed reference families are kept apart on purpose:

* ``ACTIVITY``/``OPERATION``/``PHASE``/``CAUSE``/``NPT`` come from the engineers'
  Operations Summary *Codes* sheet (``docs/operations/activity-taxonomy-extracted.csv``).
* ``OPENWELLS_OPERATION_CODES`` (01–26 with A/B/C sub-codes), ``OPENWELLS_OPERATE2``
  (D/P/U/S time marks) and ``OPENWELLS_PHASES`` come from the master data sheets filed in
  ``MODEL REPORTS/OpenWellsCodes``. They describe the OpenWells pick-list, so the same
  number (for example 06) means different work in each family.
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
    ('CSGIN1', 'First intermediate casing'),
    ('CSGIN2', 'Second intermediate casing'),
    ('CSGIN3', 'Third intermediate casing'),
    ('CSGPRO', 'Production casing'),
    ('EVAL 1', 'Formation evaluation / logging (stage 1)'),
    ('EVAL 2', 'Formation evaluation / logging (stage 2)'),
    ('EVAL 3', 'Formation evaluation / logging (stage 3)'),
    ('EVAL', 'Formation evaluation / logging'),
    ('EVALPR', 'Production-hole evaluation / logging'),
    ('MIRU', 'Move in / rig up'),
    ('RDMO', 'Rig down / move out'),
    ('SUSPEN', 'Suspend / re-enter operations'),
    ('ALL', 'All unplanned operations'),
    ('COMPLETION', 'Completion operations'),
)

# ``MODEL REPORTS/OpenWellsCodes/PK_OPCODE_from_images.xlsx``. The pick-list has a
# top-level operation number and optional A/B/C sub-codes; both are kept verbatim
# ("19" and "19-D") so a printed sub-code keeps its own meaning.
OPENWELLS_OPERATION_CODES = (
    ('01', 'Rig up / tear down'),
    ('01-A', 'Rig up'),
    ('01-B', 'Tear down'),
    ('02', 'Drill'),
    ('02-A', 'New hole'),
    ('02-B', 'Opening'),
    ('02-C', 'Underreaming'),
    ('02-D', 'Drill out casing'),
    ('02-E', 'Sidetracking'),
    ('03', 'Reaming'),
    ('03-A', 'Drill'),
    ('03-B', 'Coring'),
    ('03-C', 'Logging'),
    ('04', 'Coring'),
    ('04-A', 'Conventional'),
    ('04-B', 'Plastic sleeve'),
    ('04-C', 'Sponge'),
    ('04-D', 'Oriented'),
    ('04-E', 'Rig up core barrel'),
    ('04-F', 'Laydown barrel'),
    ('05', 'Condition mud and circulate'),
    ('05-A', 'Drilling'),
    ('05-B', 'Well control'),
    ('05-C', 'Loss circulation'),
    ('05-D', 'Logging'),
    ('05-E', 'Coring'),
    ('05-F', 'Casing'),
    ('05-G', 'Fishing'),
    ('05-H', 'Cementing'),
    ('05-I', 'Circulate samples'),
    ('05-J', 'Boulders / gravel'),
    ('06', 'Tripping'),
    ('06-A', 'Bit'),
    ('06-B', 'Fishing'),
    ('06-C', 'Logging'),
    ('06-D', 'Core'),
    ('06-E', 'DST'),
    ('06-F', 'Cement plug'),
    ('06-G', 'Casing'),
    ('06-H', 'Wiper'),
    ('06-I', 'Well control'),
    ('06-J', 'BHA'),
    ('06-K', 'DST / washout'),  # printed twice in the sheet with these two descriptions
    ('07', 'Rig service'),
    ('08', 'Rig repairs'),
    ('08-A', 'Mud system'),
    ('08-B', 'Rotary'),
    ('08-C', 'Drawworks'),
    ('08-D', 'Well control equipment'),
    ('08-E', 'Other'),
    ('09', 'Slip and cut drill line'),
    ('10', 'Survey'),
    ('10-A', 'Drift'),
    ('10-B', 'Directional single shot'),
    ('10-C', 'Directional multi shot'),
    ('10-D', 'Gyro'),
    ('10-E', 'MWD'),
    ('11', 'Wireline'),
    ('11-A', 'Evaluation'),
    ('11-B', 'Abandonment'),
    ('11-C', 'Formation tester'),
    ('11-D', 'Sidewall cores'),
    ('11-E', 'Velocity'),
    ('11-F', 'Other'),
    ('12', 'Casing and cement'),
    ('12-A', 'Rig up and run casing'),
    ('12-B', 'Rig up and run liner'),
    ('12-C', 'Circulate and cement'),
    ('12-D', 'Other'),
    ('13', 'Wait on cement'),
    ('14', 'Nipple up BOP'),
    ('14-A', 'Diverter'),
    ('14-B', 'Stack'),
    ('14-C', 'Manifold'),
    ('14-D', 'PVT system'),
    ('14-E', 'Other'),
    ('15', 'Pressure test BOP'),
    ('15-A', 'Stack'),
    ('15-B', 'Manifold'),
    ('15-C', 'FLOT'),
    ('16', 'Drill stem test'),
    ('16-A', 'Open hole'),
    ('16-B', 'Open hole closed chamber'),
    ('16-C', 'Cased hole'),
    ('16-D', 'Rig up tools'),
    ('16-E', 'Lay down tools'),
    ('17', 'Plug back'),
    ('17-A', 'Abandonment'),
    ('17-B', 'Kick off plug'),
    ('17-C', 'WOC'),
    ('17-D', 'Loss circulation'),
    ('17-E', 'Well control'),
    ('18', 'Squeeze cement'),
    ('18-A', 'Casing shoe'),
    ('18-B', 'Parted casing'),
    ('18-C', 'Perforations DST'),
    ('19', 'Fishing'),
    ('19-A', 'Cones'),
    ('19-B', 'Wireline tools'),
    ('19-C', 'BHA'),
    ('19-D', 'Stuck'),
    ('19-E', 'Other'),
    ('20', 'Directional work'),
    ('20-A', 'Motor drilling'),
    ('20-B', 'Rotary drilling'),
    ('20-C', 'Horizontal drilling'),
    ('20-D', 'Slant drilling'),
    ('20-E', 'Orient'),
    ('21', 'Waiting on orders'),
    ('21-A', 'Cut casing'),
    ('21-B', 'Set bridge plugs'),
    ('21-C', 'Pull casing'),
    ('22', 'Rig release'),
    ('22-A', 'Cut casing'),
    ('22-B', 'Install capping assembly'),
    ('23', 'Rig move'),
    ('23-A', 'Inter-pad move'),
    ('23-B', 'Inter-well move'),
    ('23-C', 'Skid rig'),
    ('23-D', 'Other'),
    ('24', 'Abandonment'),
    ('24-A', 'Run plugs'),
    ('24-B', 'Log plugs'),
    ('24-C', 'WOC'),
    ('25', 'Other'),
    ('26', 'Slot recovery / enhancement'),
)

# ``PK_OPERATE2_from_image.xlsx``: the printed time mark that sits beside each
# operation row. It is an allocation suggestion only; the narrative still decides.
OPENWELLS_OPERATE2 = (
    ('D', 'Downtime'),
    ('P', 'Planned'),
    ('U', 'Unplanned'),
    ('S', 'Skipped'),
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
    *(DefaultCode('OpenWells operation code', code, name, 'MODEL REPORTS/OpenWellsCodes · PK_OPCODE',
                  'Printed OpenWells pick-list entry. The number alone is not an operation; read the sub-code and the row narrative.')
      for code, name in OPENWELLS_OPERATION_CODES),
    *(DefaultCode('OpenWells time mark', code, name, 'MODEL REPORTS/OpenWellsCodes · PK_OPERATE2',
                  'The printed time mark beside an OpenWells row. It suggests Planned, Unplanned, Downtime or Skipped; verify against the narrative.',
                  {'P': 'Planned', 'U': 'UPA', 'D': 'NPT', 'S': 'Planned'}.get(code, ''),
                  {'P': 'PT', 'U': 'UPA', 'D': 'NPT', 'S': 'PT'}.get(code, ''))
      for code, name in OPENWELLS_OPERATE2),
    *(DefaultCode('OpenWells phase', code, name, 'MODEL REPORTS/OpenWellsCodes · PK_PHASE') for code, name in OPENWELLS_PHASES),
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
