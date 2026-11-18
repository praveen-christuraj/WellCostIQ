"""One set of Well Operations manual topics for the guide page and Ask."""

from dataclasses import asdict, dataclass
import re

from app.domain.operations.default_codes import find_code
from app.domain.operations.dnc_knowledge import match_dnc_entries
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
          'openwells code codes marks phase classification allocation pt upa npt sp library default mapping',
          'ops-master:read', '/operations/library?tab=default-codes',
          'Default Codes is a read-only dictionary based on supported OpenWells layouts and the engineering code sheet, not an official vendor-wide list. Workspace codes are managed on separate tabs.',
          ('Workbook Activity 06 means Wiper trip and reaming. The same token is seen on several kinds of trips in OpenWells. Printed codes do not by themselves say whether work was planned.',
           'Printed P suggests Planned; U suggests UPA (unplanned activity); D suggests NPT (nonproductive time). PT, UPA, NPT and SP (slow progress) form the separate allocation column.',
           'A workspace mark can override classification. Printed Excel allocations stay separate. An unknown code stays visible for review rather than being assigned a generic name.')),
    Topic('timeline', 'Import, study and activate a programme', 'How do I import and activate a timeline?',
          'timeline plan programme program baseline planned import activate preview sheet target duration hours',
          'ops-plan:read', '/operations/plans',
          'Operations planned days equal the sum of planned activity hours divided by 24. The timeline is versioned per well and scope; it does not change a costing plan.',
          ('Create a draft version and enter a programme start if known. Import a timeline sheet or enter its rows in the editor.',
           'Review each description, planned duration and optional target measured depth. The study flags repeated or missing target depths and missing start dates. It does not assume a speed or set one.',
           'Save the reviewed timeline, then activate it when ready. Authorized users holding ops-plan:reopen can reopen an active or superseded timeline back to draft with audit remarks, update its items or start time (WAT), and re-activate it while preserving historical baseline references.')),
    Topic('calculations', 'Time balance, ROP and lead/lag', 'How are ROP, time balance and lead or lag calculated?',
          'rop lead lag compare calculation elapsed time balance footage measured depth rotating checkpoint progress days',
          'ops-report:read', '/operations/reports',
          'The period balance is report-period minutes minus logged minutes, not always 24 hours. Lead/lag is comparable actual elapsed days minus planned days: positive means behind.',
          ('Use only comparable measured-depth gain divided by matching rotating hours for rotating ROP. A trip may change bit depth without drilling any new hole.',
           'Use a confirmed completed programme activity when depth stays flat, reverses or is ambiguous. Otherwise the engine compares depth only where the programme gives an unambiguous result.',
           'Use programme start, or confirmed drilling days from spud when appropriate. Without a usable time origin or corresponding checkpoint, lead/lag is left unavailable.')),
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


def answers(question, route, permissions, *, db=None, organization_id=None):
    """Return None for non-operations questions so costing intents are unchanged."""
    q = question.casefold()
    contextual = route == '/operations' or route.startswith('/operations/')
    explicit = re.search(
        r'\b(?:openwells|well operations|operation summary|operations summary|ddr|dcr|dmr|rmr|'
        r'stuck pipe|lost circulation|kill mud|sidpp|sicp|maasp|dogleg|dls|scssv|gravel pack|'
        r'packer|xmas tree|mud motor|bha|plastic viscosity|yield point|ecd|hole cleaning|tvd)\b',
        q,
    )
    cost_explicit = re.search(r'\b(?:costing|cost of|total cost|afe|invoice|idvs|catalogue|budget|spend|usd|ngn)\b', q)
    if cost_explicit and not contextual:
        return None
    if not explicit and (not contextual or re.search(r'\b(?:costing|afe|invoice|catalogue)\b', q)):
        return None
    topics = manual(permissions)
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
