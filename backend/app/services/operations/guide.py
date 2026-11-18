"""One set of Well Operations manual topics for the guide page and Ask."""

from dataclasses import asdict, dataclass
import re

from app.domain.operations.default_codes import find_code
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
    Topic('workflow', 'Review and submit daily reports', 'How do I review an extracted daily report?',
          'workflow extract extraction review source draft submit approve daily report ddr dcr dmr rmr',
          'ops-report:read', '/operations/reports',
          'File the original, extract or enter a draft, then review and submit the time log. Only submitted and approved operational reports count in analytics.',
          ('Open the rig, well and optional drilling or completion scope. Choose a filed document or upload and extract a PDF or Excel report.',
           'Check the source date/event, measured depths and activity clocks. A DMR can supplement an existing draft without adding time; an RMR may cover a partial day.',
           'Review the printed codes, classifications, allocations and vendors. Confirm remaining suggestions, save, then submit. Approval uses a separate permission.')),
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
           'Save the reviewed timeline, then activate it when ready. Active and superseded versions are read-only; previously reviewed daily reports retain their saved baseline.')),
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


def answers(question, route, permissions):
    """Return None for non-operations questions so costing intents are unchanged."""
    q = question.casefold()
    contextual = route == '/operations' or route.startswith('/operations/')
    explicit = re.search(r'\b(?:openwells|well operations|ddr|dcr|dmr|rmr)\b', q)
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
    words = set(re.findall(r'[a-z0-9]+', q))
    ranked = sorted(topics, key=lambda t: -len(words & set(t['keywords'].split())))
    if ranked and words & set(ranked[0]['keywords'].split()):
        topic = ranked[0]
        return AssistantAnswer(answer=topic['body'], intent='knowledge', confidence='high', category='workflow',
                               memory_key=f"operations-{topic['id']}", steps=list(topic['steps']),
                               sources=[AssistantSource(label=topic['title'], route=topic['route'])],
                               follow_ups=[row['question'] for row in ranked[1:4]])
    return AssistantAnswer(
        answer='I can explain the Well Operations workflow, codes and calculations your role can read. '
               'Open the actual report or timeline to inspect a specific well’s data.',
        intent='knowledge', confidence='low', category='faq', memory_key='operations-guide', follow_ups=[row['question'] for row in topics],
    )
