"""One set of Well Operations manual topics for the guide page and Ask."""

from dataclasses import asdict, dataclass
import re

from app.domain.operations.default_codes import find_code
from app.domain.operations.dnc_knowledge import match_dnc_entries
from app.domain.operations.reference_knowledge import (
    abbreviation_meanings,
    describe_code_token,
    glossary_definition,
    glossary_term,
)
from app.domain.operations.study_knowledge import match_study_entries
from app.schemas.assistant import AssistantAnswer, AssistantSource


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    question: str
    keywords: str
    permission: str
    route: str
    body: str
    steps: tuple[str, ...]


TOPICS = (
    Topic('workflow', 'Review, reopen and submit daily reports', 'How do I review or reopen a daily report?',
          'workflow extract extraction review reopen amend source draft submit approve daily report ddr dcr dmr rmr summary export',
          'ops-report:read', '/operations/reports',
          'File the original, extract or enter a draft, then review and submit the time log in West Africa Time (WAT, UTC+1:00). Submitted and approved reports count in analytics and can be reopened to draft with remarks when corrections are needed.',
          ('Open the rig, well and optional drilling or completion scope. Choose a filed document or upload and extract a PDF or Excel report (with optional offline AI prefill refinement).',
           'Verify the extracted MD, TVD, bit depth, casing, mud properties, surveys, narrative fields and WAT activity clocks. Use the AI narrative generator to draft or polish 24-hr summaries and forecasts from extracted rows.',
           'Confirm suggested blocks, save, then submit and approve. Authorized users can click Reopen with audit remarks to return a submitted or approved report to draft. Open Operation Summary to export the full multi-day well summary as PDF, Excel or CSV.')),
    Topic('codes', 'Read the printed codes', 'What do OpenWells codes and source marks mean?',
          'openwells code codes marks phase activity allocation pt upa npt sp library default mapping',
          'ops-master:read', '/operations/library?tab=default-codes',
          'Default Codes is a read-only dictionary based on supported OpenWells layouts and the engineering code sheet, not an official vendor-wide list. Workspace codes are managed on separate tabs.',
          ('Workbook Activity 06 means Wiper trip and reaming. The same token is seen on several kinds of trips in OpenWells. A printed code does not by itself say what kind of activity the time was.',
           'Every Master Data Activity carries an Activity Type: Planned, UPA (unplanned activity) or NPT (nonproductive time). Selecting the Activity on a daily-report block sets that block\'s Activity Type, so the editor asks for one value instead of a separate classification. PT, UPA, NPT and SP (slow progress) remain the separate Allocation column.',
           'A workspace mark can override the Activity Type. Printed Excel allocations stay separate. An unknown code stays visible for review rather than being assigned a generic name.')),
    Topic('source-marks', 'When to use source mark rules', 'Do I need a source mark rule?',
          'source marks mark rules printed classification allocation defaults',
          'ops-master:read', '/operations/library?tab=source-marks',
          'A source mark is a short label printed beside a time entry. A source mark rule tells extraction how your workspace interprets that label for Activity Type and default Allocation. These rules are optional: you do not need one to correlate a printed code with a section, phase or other field.',
          ('For example, if your reports use BD for breakdown, add BD on the Source mark rules tab with Activity Type NPT and default Allocation NPT. On the next extraction, a row marked BD then starts with those suggestions. An allocation printed explicitly in a workbook is read separately.',
           'Skip the rule if the built-in interpretation fits. Without a workspace rule, extraction uses the printed reference and other available evidence. Review the suggestion against the narrative; a rule neither approves a block nor changes a saved report.')),
    Topic('correlations', 'Correlate and link workspace codes', 'How do I correlate codes and link multi-criteria code rules?',
          'correlation correlations correlate correlated link linked linking multi criteria multicriteria batch tree schematic hierarchy library operations sub phase cause agency mark hole section phase activity vendor unlink delete permanent',
          'ops-master:read', '/operations/library?tab=correlations',
          'Open Well Operations → Code library → Correlations to map printed source codes to your workspace criteria, and to link several criteria into one row. Hole Section, Phase, Activity and Agency / service vendor come from Master Data; Sub-phase, Operations, Cause and the Responsible agency label are configured in the Code library. No costing register is involved: the same Master Data names are simply reused. Correlations pre-select suggestions during PDF/Excel extraction and guide report review without ever guessing or auto-approving a block.',
          ('Configure the Code library tabs — Operations, Sub-phases, Causes, Responsible agency labels and Source marks — and keep Hole Sections, Phases, Activities and vendors in Master Data.',
           'In the Correlations tab, use Add correlation for one rule or Batch correlate to validate and save many printed-to-workspace rules in one atomic pass. Select the printed code, then choose at least one field to pre-fill. For example, map a printed operation code to Hole Section alone, or add Phase and Sub-phase to the same rule. No particular field is required. Scope only limits where the rule applies.',
           'Click Link criteria to create multi-criteria relationships among your own criteria (for example Hole Section + Phase + Sub-phase + Activity + Operations + Cause + Responsible agency label), so one rule such as DRLSUR describes everything the printed code implies and pre-fills it on the extracted block for the engineer to adjust. Cause is only ever required when the Activity Type is NPT or UPA, and a rule cannot force a cause onto Planned work.',
           'Keep Table view for searchable tabular auditing and bulk actions, or switch to Tree schematic to inspect relationships visually (by Phase → Sub-phase → Activity → Operations / Cause / Responsible agency label, by Printed code → Workspace criterion, or by Code family), see unlinked codes, and add, edit or unlink rules inline.',
           'Deletion safeguard: any workspace code referenced by an active correlation or code link cannot be deleted until it is unlinked in Correlations. Once unlinked and soft-deleted to Deleted entries, authorized users (ops-master:permanent-delete) can either Restore it or click Delete permanently — permanent removal is blocked whenever any historical report block, timeline row or deleted rule still references the code.')),
    Topic('timeline', 'Import, study and activate a programme', 'How do I import and activate a timeline?',
          'timeline plan programme program baseline planned import activate preview sheet target duration hours',
          'ops-plan:read', '/operations/plans',
          'Operations planned days equal the sum of planned activity hours divided by 24. The timeline is versioned per well and scope; it does not change a costing plan.',
          ('Create a draft version and enter a programme start if known. Import a timeline sheet or enter its rows in the editor.',
           'Review each description, planned duration and optional target measured depth. The study flags repeated or missing target depths and missing start dates. It does not assume a speed or set one.',
           'Save the reviewed timeline, then activate it when ready. Authorized users holding ops-plan:reopen can reopen an active or superseded timeline back to draft with audit remarks, update its items or start time (WAT), and re-activate it while preserving historical baseline references.')),
    Topic('calculations', 'Time balance, ROP, chart axes and lead/lag', 'How are ROP, chart axes, time balance and lead or lag calculated?',
          'rop completion axis axes scale step interval min max lead lag compare calculation elapsed time balance footage measured depth rotating checkpoint progress days',
          'ops-report:read', '/operations/analytics',
          'The period balance is report-period minutes minus logged minutes, not always 24 hours. Schedule position compares actual elapsed days with planned days on the active baseline: a positive number is a lead ahead of plan, a negative number is a lag behind it. Rate of penetration (ROP) applies only to drilling operations and is always reported as N/A for completion operations.',
          ('Drilling ROP uses only comparable measured-depth gain divided by matching rotating hours (m/h). Completion reports, summaries, analytics, PDF exports and AI briefs always report ROP as N/A and never project depth from ROP.',
           'On Operations Analytics, Time vs measured depth defaults to 300 m vertical depth steps, while Time vs completion progress chooses clean integer activity intervals so tick labels never collide. Use Axis scale on the chart to set custom X (days) and Y (MD or activity) min, max and step values or presets, and click Reset axes to return to automatic scaling.',
           'Use a confirmed completed programme activity when depth stays flat, reverses or is ambiguous. Otherwise the engine compares depth only where the programme gives an unambiguous result.',
           'Use programme start, or confirmed drilling days from spud when appropriate. Each daily report carries a suggested lead/lag comparison that the engineer accepts, edits or rejects with a note before submitting.')),
    Topic('well-path', 'Read the well path, dogleg and casing diagram', 'How do I read the well path, dogleg charts and casing diagram?',
          'well path trajectory survey plan view vertical section tvd md dogleg dls interval casing schematic shoe liner bit depth short string long string hole bottom off bottom snapshot unsurveyed gap azimuth inclination closure grid north datum',
          'ops-report:read', '/operations/well-path',
          'The well visuals answer three different questions and never mix them: where the hole was drilled (surveyed trajectory), what has been installed (casing schematic) and where the tool or string was reported (report snapshot). A line is only drawn where a survey station exists.',
          ('Plan view means looking down, not planned well. Vertical section is the shadow of the path on a vertical plane facing the stated bearing, so sideways motion out of that plane disappears; rotating the plane changes the shadow, not the well. Select a station in either projection to highlight it in the other, the schematic and the table.',
           'Dogleg severity belongs to an interval, not a station: it is the angle between two 3D tangent directions, normalised to 30 m. The first station has no interval and shows no severity, which is not the same as zero. A printed rate is kept as a separate mark and a printed rate in deg/100 ft is converted with 30/30.48.',
           'The schematic is drawn on measured depth and the trajectory on true vertical depth, as two labelled axes. A casing seat ends in a shoe; only recorded seats are solid. Below the last known shoe the drawing says casing coverage unknown, and no liner, cement, packer or total depth is invented.',
           'The marker is the selected report closing measured depth. The survey endpoint is the deepest station: any hole below it is unsurveyed and annotated, never drawn as a continuation of the line. The bit or string position is a separate observation and is only compared with the hole when both come from the same report, datum and bore.',
           'Every mark carries an Explain this action that names the fact and its source: recorded, calculated, configured or missing, with the report, date and status. Drawings and their numbers come from the same service, so a card and a chart cannot disagree.')),
    Topic('documents', 'File and find originals', 'How do I file and find documents for a well?',
          'documents document file vault upload original folder rig well search',
          'ops-doc:read', '/operations/documents',
          'Documents keeps the original files grouped by rig and well. Uploading a file does not create a daily report.',
          ('Choose a configured well scope and document type when filing a new source.',
           'To find a file, open its rig, then its well. Filter by scope, date or document details inside the folder.',
           'Use Daily reports → Extract PDF / Excel to turn an eligible source into a draft. Verify the source header instead of relying on the filename.')),
)


def manual(permissions):
    return [asdict(topic) for topic in TOPICS if '*' in permissions or topic.permission in permissions]


_STUDY_SOURCES = [
    AssistantSource(label='Abbreviations and Glossary', route='/operations/guide'),
    AssistantSource(label='Default Codes', route='/operations/library?tab=default-codes'),
]

#: Words that only introduce a definition request, stripped before lookup.
_ASK_PREFIX = re.compile(
    r"^(?:what\s+(?:does|is|are|do)\s+|what's\s+|define\s+|the\s+meaning\s+of\s+|meaning\s+of\s+|explain\s+|"
    r"tell\s+me\s+about\s+|full\s+form\s+of\s+|expand\s+)",
    re.IGNORECASE,
)


#: Ordinary words that are never a printed code or a defined term. A question
#: such as "how much does the well cost" must reach the costing modules, not be
#: answered as the four-letter token ``cost``.
_NOT_A_TERM = frozenset(
    """
    a an and any are as at be by can cost costs did do does for from get got had has have how i if in
    into is it its just like many may me more much my no not of on or our out over should so some
    than that the their them then there these they this those to too up us was we were what when
    where whether which while who why will with would you your well wells
    """.split()
)


def _asked_token(question: str) -> str:
    text = (question or "").strip().rstrip("?.! ")
    # "what is the meaning of RIH" asks twice — "what is" and "meaning of" — so
    # the prefix strip runs until nothing more is removed.
    for _ in range(3):
        stripped = _ASK_PREFIX.sub("", text)
        if stripped == text:
            break
        text = stripped
    text = re.sub(r"^(?:the\s+)?(?:abbreviation|term|acronym)\s+", "", text, flags=re.IGNORECASE)
    # "what is a kick?" asks about *kick*, not about the letter a.
    text = re.sub(r"^(?:a|an|the)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:the\s+)?full\s+form\s+of\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:mean|means|stand\s+for|stands\s+for)$", "", text, flags=re.IGNORECASE)
    return text.strip(" '\"?.!")


def _reference_answer(question: str, q: str, permissions) -> AssistantAnswer | None:
    """Answer an abbreviation or glossary question from the supplied study modules."""
    asks_abbreviation = re.search(r"\b(?:abbreviation|acronym|stand(?:s)? for|full form|expand)\b", q)
    token = _asked_token(question)
    if not token or token.casefold() in _NOT_A_TERM:
        return None
    plain_words = len(token.split()) <= 5
    meanings = abbreviation_meanings(token.split(" ", 1)[0]) if plain_words else ()
    # A phrase the glossary defines exactly is a definition question, not an
    # acronym question: "what is mud weight" is the density term, while the sheet
    # also lists MUD as "Mud Log". The exact glossary entry wins.
    if glossary_definition(token) and len(token.split()) > 1:
        meanings = ()
    if meanings and (asks_abbreviation or len(token.split()) <= 2):
        shown = token.split(" ", 1)[0].upper()
        every = "; ".join(meanings)
        answer = f"{shown} has {len(meanings)} printed meaning{'s' if len(meanings) != 1 else ''}: {every}."
        if len(meanings) > 1:
            answer += " Use the meaning the report context supports; do not merge them."
        return AssistantAnswer(
            answer=answer,
            intent='knowledge',
            confidence='high',
            category='faq',
            memory_key='operations-abbreviations',
            sources=_STUDY_SOURCES,
        )
    # A code token: name the family, because the same number differs per family.
    code = re.search(r"\b(?:code|operation|activity)\s+(\S+)", q)
    token = code.group(1) if code else token
    if re.fullmatch(r"[a-z0-9][a-z0-9/-]{0,11}", token, re.IGNORECASE) and token.casefold() not in _NOT_A_TERM:
        described = describe_code_token(
            token,
            ("OpenWells operation code", "Activity", "OpenWells code token", "Trouble / NPT", "Cause"),
        )
        if described:
            return AssistantAnswer(
                answer=described + ".",
                intent='knowledge',
                confidence='high',
                category='faq',
                memory_key='operations-codes',
                sources=_STUDY_SOURCES,
            )
    # A glossary term, including a phrase the sheet defines and a phrase that only
    # starts with a defined term ("dogleg severity" -> "dogleg").
    key = glossary_term(token) or token
    definition = glossary_definition(key)
    if not definition and len(token.split()) > 1:
        key = glossary_term(token.split()[0])
        definition = glossary_definition(key)
    # ``kick tolerance`` starts with ``kick``, a defined term whose meaning
    # (an influx) is not the question. A multi-word phrase that names a distinct
    # subject is left to the study books rather than answered from one word.
    if (
        definition
        and len(token.split()) > 1
        and key.casefold() != token.casefold()
        and any(term in " ".join(token.lower().split()) for term in _COMPOUND_SUBJECTS)
    ):
        return None
    if definition and len(token.split()) <= 6:
        return AssistantAnswer(
            answer=f"{key}: {definition}",
            intent='knowledge',
            confidence='high',
            category='faq',
            memory_key='operations-glossary',
            sources=_STUDY_SOURCES,
        )
    return None


#: Phrases a glossary splits into a narrower first word. ``Kick tolerance`` is not
#: ``kick``; ``mud weight`` is not ``mud``. Each is a subject in its own right and
#: is answered from the study books when one covers it.
_COMPOUND_SUBJECTS = (
    "kick tolerance",
    "mud weight",
    "leak off",
    "lot test",
    "fit test",
    "d exponent",
    "dc exponent",
    "hole cleaning",
    "neutral point",
    "tool face",
)


def _study_answer(question: str, permissions) -> AssistantAnswer | None:
    """Answer a drilling-engineering question from the supplied study books.

    Only a confident match answers. A formula, its symbols and the page it came
    from are what a reader can check, so the answer is the derivation rather than
    a paraphrase, and the citation names the book, the section and the page.
    """
    matches = match_study_entries(question, limit=2, minimum=9)
    if not matches:
        return None
    _score, entry = matches[0]
    related = [other for _, other in matches[1:]]
    # "What is the difference between differential and mechanical sticking?" names
    # two subjects: naming the second and where it is answered is more honest than
    # answering only the first and leaving the reader to notice.
    related_titles = [other.title for other in related if other.topic == entry.topic]
    steps = [f"{entry.title}."]
    if entry.formula:
        steps = [f"Formula: {entry.formula}"]
        if entry.symbols:
            steps.append("Where: " + "; ".join(entry.symbols) + ".")
    elif entry.symbols:
        steps = ["Where: " + "; ".join(entry.symbols) + "."]
    if entry.applies_to:
        steps.append(f"Applies to: {entry.applies_to}")
    steps.extend(entry.checks)
    if related_titles:
        steps.append(
            "A related subject is also covered: " + "; ".join(related_titles) + "."
        )
    citations = entry.citations()
    return AssistantAnswer(
        answer=entry.summary,
        intent='knowledge',
        confidence='high',
        category='calculation' if entry.formula else 'faq',
        memory_key=entry.key,
        steps=steps,
        sources=[
            *(AssistantSource(label=citation, route='') for citation in citations),
            AssistantSource(label='Operations guide', route='/operations/guide'),
        ],
        follow_ups=list(entry.follow_ups),
    )


def _dnc_outscores_study(question: str, study: AssistantAnswer) -> bool:
    """Whether the DNC entry for this question is a better match than the study one.

    Both knowledge bases score keyword overlap, and the study matcher is the
    stricter of the two, so a DNC entry that still scores higher is the better
    evidence. The study answer is only worth pre-empting when the DNC match is
    genuinely stronger; ties stay with the study books.
    """
    hits = match_dnc_entries(question, limit=1)
    if not hits:
        return False
    dnc_score, dnc_entry = hits[0]
    study_hits = match_study_entries(question, limit=1, minimum=0)
    study_score = study_hits[0][0] if study_hits else 0
    if dnc_entry.key in (study.memory_key or ''):
        return False
    return dnc_score > study_score


def answers(question, route, permissions, *, db=None, organization_id=None):
    """Return None for non-operations questions so costing intents are unchanged."""
    q = question.casefold()
    contextual = route == '/operations' or route.startswith('/operations/')
    explicit = re.search(
        r'\b(?:openwells|well operations|operation summary|operations summary|ddr|dcr|dmr|rmr|'
        r'codes?\s+correlations?|correlat(?:e|ed|ing)\s+(?:printed\s+|workspace\s+|operations?\s+|activity\s+|npt\s+)?codes?|'
        r'source[- ]marks?\b|batch\s+correlat\w*|code\s+links?|code\s+library|tree\s+schematic|multi[- ]criteria\s+codes?|'
        r'completion\s+rop|time\s+vs\s+(?:measured\s+depth|completion)|'
        r'stuck pipe|lost circulation|kill mud|sidpp|sicp|maasp|dogleg|dls|well\s+path|trajectory|'
        r'vertical\s+section|casing\s+schematic|survey\s+station|unsurveyed|scssv|gravel pack|'
        r'packer|xmas tree|mud motor|bha|plastic viscosity|yield point|ecd|hole cleaning|tvd)\b',
        q,
    )
    cost_explicit = re.search(r'\b(?:costing|cost of|total cost|afe|invoice|idvs|catalogue|budget|spend|usd|ngn)\b', q)
    if cost_explicit and not contextual:
        return None
    # A study-book question is answered from the book itself — the derivation, the
    # symbol list, what it applies to, and the page — before any manual topic or
    # model is consulted. The arithmetic is the answer; prose adds nothing to it.
    # It runs ahead of the operations-only gate because a drilling-engineering
    # question ("what is kick tolerance?") is legitimate from any screen, while a
    # costing question stays with the costing modules.
    study = _study_answer(question, permissions)
    if study is not None:
        # A term the printed glossary defines *exactly* is still the shorter, more
        # direct answer: "what is mud weight" is a definition, not a kick-tolerance
        # discussion. Only a term the reader named verbatim earns that precedence.
        exact_term = _reference_answer(question, q, permissions)
        if exact_term is not None and exact_term.memory_key in (
            'operations-glossary',
            'operations-abbreviations',
        ):
            return exact_term
        # The study books and the DNC knowledge base cover overlapping ground, and
        # neither is always the better answer. "How do I prevent pack-off and
        # differential stuck pipe?" names *two* mechanisms: the DNC entry answers
        # both, while the top study entry covers only the mechanical one. A study
        # entry therefore only pre-empts the knowledge base when it matches more
        # strongly; otherwise the two are compared on their scores below.
        if _dnc_outscores_study(question, study):
            study = None
    if study is not None:
        return study
    if not explicit and (not contextual or re.search(r'\b(?:costing|afe|invoice|catalogue)\b', q)):
        return None
    topics = manual(permissions)
    if re.search(r'\bsource[- ]marks?\s+rules?\b', q):
        topic = next((t for t in topics if t['id'] == 'source-marks'), None)
        if topic is None:
            return AssistantAnswer(answer='Source mark rules need ops-master:read.', intent='permission', confidence='high')
        return AssistantAnswer(answer=topic['body'], steps=list(topic['steps']), intent='knowledge',
                               confidence='high', category='workflow', memory_key='operations-source-marks',
                               sources=[AssistantSource(label=topic['title'], route=topic['route'])])
    # Direct manual lookup for Codes Correlation & multi-criteria code linking.
    if re.search(
        r'\b(?:correlat(?:e|ed|ing|ion|ions)|code\s+links?|link\s+(?:workspace\s+)?codes?|'
        r'multi[- ]criteria|tree\s+schematic|unlink\s+codes?)\b',
        q,
    ):
        corr_topic = next((t for t in topics if t['id'] == 'correlations'), None)
        if corr_topic is None:
            return AssistantAnswer(
                answer='Permission denied. Code library and correlation details need ops-master:read.',
                intent='permission',
                confidence='high',
            )
        return AssistantAnswer(
            answer=corr_topic['body'],
            intent='knowledge',
            confidence='high',
            category='workflow',
            memory_key='ops-code-correlations',  # the seeded assistant memory this answer expands
            steps=list(corr_topic['steps']),
            sources=[
                AssistantSource(label='Code library — Correlations', route='/operations/library?tab=correlations'),
                AssistantSource(label='Default Codes', route='/operations/library?tab=default-codes'),
                AssistantSource(label='Operations guide', route='/operations/guide'),
            ],
            follow_ups=[
                'What do OpenWells codes and source marks mean?',
                'How do I review or reopen a daily report?',
                'How are ROP, chart axes, time balance and lead or lag calculated?',
            ],
        )
    code = re.search(r'\b(?:code|mark)\s+(?:\[\s*\d+\s*\]|[a-z0-9-]+)', q)
    if code:
        token = code[0].split(maxsplit=1)[1]
        families = ('OpenWells phase', 'Programme phase') if 'phase' in q else (
            ('Operation',) if 'operation code' in q else ('OpenWells code token',) if 'openwells' in q else ('Activity', 'Source mark', 'Allocation', 'Trouble / NPT', 'OpenWells phase', 'Programme phase', 'Cause', 'Operation')
        )
        if match := find_code(token, *families):
            if not any(t['id'] == 'codes' for t in topics):
                return AssistantAnswer(answer='Permission denied. Default code details need ops-master:read.', intent='permission', confidence='high')
            return AssistantAnswer(
                answer=f'{token.upper()} means {match.name} ({match.family.lower()}). {match.description}'.strip(),
                intent='knowledge', category='calculation', confidence='high', memory_key='operations-codes',
                sources=[AssistantSource(label='Default Codes', route='/operations/library?tab=default-codes')],
            )
    # Printed reference lookups answer without a model: the supplied abbreviation
    # sheet and glossary are evidence, and a deterministic answer cannot invent one.
    reference = _reference_answer(question, q, permissions)
    if reference is not None:
        return reference

    # Search live workspace Well Operations database under caller RBAC.
    if db is not None and organization_id:
        from app.services.operations.ops_ai import answer_ops_database

        db_answer = answer_ops_database(db, organization_id, question, set(permissions))
        if db_answer is not None:
            return db_answer

    # Match authoritative Drilling & Completion engineering knowledge base.
    dnc_hits = match_dnc_entries(question, limit=2)
    words = set(re.findall(r'[a-z0-9]+', q))
    ranked = sorted(topics, key=lambda t: -len(words & set(t['keywords'].split())))
    top_topic_overlap = len(words & set(ranked[0]['keywords'].split())) if ranked else 0
    if dnc_hits and (dnc_hits[0][0] >= 7 or top_topic_overlap <= 1):
        entry = dnc_hits[0][1]
        return AssistantAnswer(
            answer=entry.summary,
            intent='knowledge',
            confidence='high',
            category='calculation' if entry.category in ('drilling', 'completion') else 'workflow',
            memory_key=entry.key,
            steps=list(entry.key_points),
            sources=[
                AssistantSource(label='Operations guide', route='/operations/guide'),
                *(
                    [AssistantSource(label='Operation summary', route='/operations/summary')]
                    if '*' in permissions or 'ops-report:read' in permissions
                    else []
                ),
            ],
            follow_ups=list(entry.follow_ups) or [row['question'] for row in topics[:3]],
        )

    if ranked and top_topic_overlap > 0:
        topic = ranked[0]
        return AssistantAnswer(answer=topic['body'], intent='knowledge', confidence='high', category='workflow',
                               memory_key=f"operations-{topic['id']}", steps=list(topic['steps']),
                               sources=[AssistantSource(label=topic['title'], route=topic['route'])],
                               follow_ups=[row['question'] for row in ranked[1:4]])
    return AssistantAnswer(
        answer='I can search recorded Well Operations reports, timelines, depths (MD/TVD), ROP, NPT/UPA and surveys, '
               'and explain Drilling & Completion engineering principles, OpenWells codes and module workflows. '
               'Name a well (or enable Offline AI) to run a deeper analysis.',
        intent='knowledge', confidence='low', category='faq', memory_key='operations-guide',
        follow_ups=[
            *(
                ['How many daily operation reports are in the workspace?', 'What are MD, TVD, bit depth and DLS?']
                if '*' in permissions or 'ops-report:read' in permissions
                else []
            ),
            *[row['question'] for row in topics[:2]],
        ],
    )
