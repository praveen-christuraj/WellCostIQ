"""Small, inspectable drilling vocabulary for interpreting recorded activities.

A term is a description, not an operating instruction or proof of progress.
Each activity can contain several actions (e.g. POOH and then run casing).
"""

import re

# Specific terms first so deterministic briefs can describe multiple recorded actions.
_RULES = (
    ('Drill ahead', r'\b(?:spud(?:ded)?|drill(?:ed|ing)? (?:ahead|(?:the |a )?new hole|(?:the )?(?:surface|production|intermediate) hole|\d[\d /¼½⅜⅝.-]*["”]))'),
    ('Wiper trip / reaming', r'\b(?:wiper trip|back[ -]?ream\w*|ream(?:ed|ing)?|wash(?:ed|ing)? and ream)\b'),
    ('Pull out of hole (POOH)', r'\b(?:p\.?o\.?o\.?h|pull(?:ed|ing)? out(?: of (?:the )?hole)?|trip(?:ped|ping)? out)\b'),
    ('Run in hole (RIH)', r'\b(?:r\.?i\.?h|(?:ran|run(?:ning)?) in(?:to)? (?:the )?hole|trip(?:ped|ping)? in)\b'),
    ('Run casing / liner', r'\b(?:run(?:ning)?|ran|land(?:ed|ing)?)\b[^.;\n]{0,45}\b(?:casing|liner)\b'),
    ('Cementing', r'\b(?:cement(?:ed|ing)?|w\.?o\.?c\.?|waiting on cement)\b'),
    ('Circulation / hole cleaning', r'\b(?:circ|circulat\w*|hole clean(?:ing)?)\b'),
    ('Logging / surveys', r'\b(?:logging|wireline|mwd|lwd|gyro|survey(?:s|ed|ing)?)\b'),
    ('Pressure testing', r'\b(?:press(?:ure)? test\w*|test(?:ed|ing)? (?:the )?(?:bop|wellhead)|fit|lot)\b'),
    ('Completion / intervention', r'\b(?:completions?|slickline|coiled tubing|perforat\w*|packer)\b'),
    ('Rig move / rig-up', r'\b(?:rig mov\w*|rig(?:ged|ging)? (?:up|down)|skid(?:ded|ding)?)\b'),
    ('Fishing / recovery', r'\b(?:fish(?:ing|ed)?|recover\w* (?:the )?(?:fish|lost (?:tool|string)))\b'),
    ('Maintenance / repair', r'\b(?:maintenance|repair\w*|replace\w*)\b'),
)
_ACTIONS = tuple((name, re.compile(pattern, re.I)) for name, pattern in _RULES)
_DELAY = re.compile(
    r'\b(?:breakdown|(?:equipment|pump|engine|power|tds) (?:failed|failure)|(?:pipe|string) (?:was |became )?stuck|'
    r'stuck pipe|lost circulation|(?:wait(?:ed|ing)? (?:on|for)|\bwo) (?:the )?(?:parts|spares|equipment|weather|repairs?))\b',
    re.I,
)
_UNPLANNED = re.compile(r'\b(?:unplanned|unscheduled|additional wiper trip)\b', re.I)


def activities(text: str) -> tuple[str, ...]:
    return tuple(name for name, pattern in _ACTIONS if pattern.search(text))


def time_signal(text: str) -> tuple[str, str] | None:
    # 'No equipment failure' and 'drilled ... without lost circulation' do not
    # prove NPT. Normal waiting on cement is a programme step, not a delay rule.
    for pattern, allocation in ((_DELAY, 'NPT'), (_UNPLANNED, 'UPA')):
        for hit in pattern.finditer(text):
            prior = re.split(r'[.;!\n]', text[:hit.start()])[-1][-85:]
            if re.search(r'\b(?:no|not|without)\b(?:\W+\w+){0,4}\W*$', prior, re.I):
                continue
            return allocation, hit.group(0)
    return None
