"""Folder isolation, code provenance, and opt-in wording for Well Operations."""
from types import SimpleNamespace

from test_rig_well import create_rig, create_well, fresh_database, login  # noqa: F401
from test_operations_workflow import MODELS, OPS, good, scoped_login

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.main import app
from app.models import AuditLog
from app.models.rig_well import Well
from app.services import ollama
from app.services.operations.workbooks import timeline_preview


def test_folder_counts_and_scoped_records():
    with TestClient(app) as c:
        h = login(c)
        south = login(c, 'south')
        rig = create_rig(c, h)
        wells = [create_well(c, h, rig['id'], f'FOLDER-{i}') for i in (1, 2)]
        with SessionLocal() as db:
            for w in wells:
                model = db.get(Well, w['id'])
                model.config_status = 'configured'
                model.completion_config_status = 'configured'
            db.commit()
        by_well = dict(rig=f"id:{rig['id']}", well=f"id:{wells[0]['id']}")
        for i, (w, scope) in enumerate([(wells[0], 'drilling'), (wells[0], 'completion'), (wells[1], 'drilling')]):
            folder = {'well_id': w['id'], 'scope': scope}
            plan = good(c.post(OPS + '/plans', json={**folder, 'label': f'Programme {i}'}, headers=h))
            good(c.put(OPS + f"/plans/{plan['id']}/items", json=[{'description': 'Drill ahead', 'planned_hours': '2.508', 'sequence_no': 1}], headers=h))
            good(c.post(OPS + '/reports', json={**folder, 'report_date': '2026-01-01'}, headers=h))
            good(c.post(OPS + '/documents/upload', data={**folder, 'document_type': 'DDR'}, files={'file': ('source.csv', b'from,to,activity\n', 'text/csv')}, headers=h))
        reader = scoped_login(c, 'plan-reader', ['ops-plan:read'])
        for resource in ('plans', 'reports', 'documents'):
            prefix = OPS + f'/directory/{resource}'
            folders = good(c.get(prefix, headers=h))
            assert len(folders) == 3 and sum(r['record_count'] for r in folders) == 3
            assert good(c.get(prefix + '/records', params=by_well, headers=south)) == []
            assert c.get(prefix + '/records', headers=h).status_code == 422
            response = c.get(prefix + '/records', params=by_well, headers=reader)
            assert response.status_code == (200 if resource == 'plans' else 403), response.text
            picked = good(c.get(prefix + '/records', params={**by_well, 'scope': 'completion'}, headers=h))
            assert len(picked) == 1 and picked[0]['well_id'] == wells[0]['id'] and picked[0]['scope'] == 'completion'
            if resource == 'plans':
                assert picked[0]['items'] == []
                assert len(good(c.get(OPS + f"/plans/{picked[0]['id']}", headers=h))['items']) == 1
                good(c.delete(OPS + f"/plans/{picked[0]['id']}", headers=h))
                deleted = good(c.get(prefix + '/records', params={**by_well, 'deleted': True}, headers=h))
                assert [p['id'] for p in deleted] == [picked[0]['id']]
            if resource == 'reports':
                assert not picked[0]['blocks']


def test_review_studies_and_guide_permissions(monkeypatch):
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content='The programme covers hole conditioning and pressure testing.', model='fixture-model', endpoint='local')

    monkeypatch.setattr(ollama, 'chat', chat)
    with TestClient(app) as c:
        h = login(c)
        rig = create_rig(c, h)
        well = create_well(c, h, rig['id'])
        with SessionLocal() as db:
            db.get(Well, well['id']).config_status = 'configured'
            db.commit()
        plan = good(c.post(OPS + '/plans', json={'well_id': well['id'], 'label': 'Programme'}, headers=h))
        pid = plan['id']
        report_read = scoped_login(c, 'report-reader', ['ops-report:read', 'assistant:read'])
        plan_read = scoped_login(c, 'read-plan-study', ['ops-plan:read'])
        library = good(c.get(OPS + '/default-codes', headers=h))
        by_id = {row['id']: row for row in library}
        assert len(library) == len(by_id)
        assert by_id['Activity:06']['name'] == 'Wiper trip and reaming'
        assert by_id['Source mark:P']['allocation'] == ''
        assert by_id['Activity:02']['name'] != by_id['OpenWells code token:02']['name']
        assert 'workbook' in by_id['Operation:E']['source'].lower()
        ask = '/api/v1/assistant/ask'
        question = {'route': '/operations/guide', 'question': 'What does code 06 mean?'}
        assert 'Wiper trip and reaming' in good(c.post(ask, json={**question, 'use_ai': True}, headers=h))['answer']
        assert good(c.post(ask, json=question, headers=report_read))['intent'] == 'permission'
        assert c.get(OPS + '/default-codes', headers=report_read).status_code == 403
        assert {t['id'] for t in good(c.get(OPS + '/guide', headers=report_read))} == {'workflow', 'calculations'}
        draft = [{'description': 'Make a wiper trip and pressure test the BOP', 'planned_hours': '2.508', 'sequence_no': 1}]
        study_path = OPS + f'/plans/{pid}/study'
        report_path = next(MODELS.glob('DDR- 55*'))
        doc = good(c.post(OPS + '/documents/upload', data={'well_id': well['id'], 'document_type': 'DDR'},
                          files={'file': (report_path.name, report_path.read_bytes(), 'application/pdf')}, headers=h))
        report = good(c.post(OPS + '/reports/from-document', json={'document_id': doc['id']}, headers=h))
        assert any(b['source_activity_code'] == '02' and 'Drill' in b['source_activity_label'] for b in report['blocks'])
        brief_path = OPS + f"/reports/{report['id']}/brief"
        brief = good(c.get(brief_path, headers=h))
        assert 'Measured depth' in brief['summary'] and 'Rotating ROP' in brief['summary']
        assert c.post(study_path, json={'items': draft}, headers=plan_read).status_code == 403
        assert 'No timeline' in good(c.post(study_path, json={}, headers=plan_read))['summary']
        rules = good(c.post(study_path, json={'items': draft}, headers=h))
        assert '0.105 planned days' in rules['summary'] and 'Wiper trip / reaming' in rules['summary']
        assert not calls and not rules['ai_text']
        aided = good(c.post(study_path, json={'items': draft, 'use_ai': True}, headers=h))
        assert aided['summary'] == rules['summary'] and aided['ai_model'] == 'fixture-model' and aided['ai_text']
        assert len(calls) == 1
        monkeypatch.setattr(ollama, 'chat', lambda **_: SimpleNamespace(content='Invented 99 hours.', model='fixture-model', endpoint='local'))
        fallback = good(c.post(brief_path, json={'use_ai': True}, headers=h))
        assert fallback['summary'] == brief['summary'] and not fallback['ai_text'] and fallback['ai_error_code'] == 'invalid_response'
        assert good(c.get(OPS + f'/plans/{pid}', headers=h))['items'] == []
        with SessionLocal() as db:
            assert len(db.scalars(select(AuditLog).where(AuditLog.action == 'ai-query')).all()) == 2


def test_timeline_csv_units_round_after_conversion():
    from decimal import Decimal
    preview = timeline_preview('programme.csv', b'Description,Duration minutes,Target depth (ft)\nWiper trip,150.501,1312.3419\n')
    row = preview['items'][0]
    assert row['planned_hours'] == Decimal('2.508')
    assert row['target_depth_m'] == Decimal('399.982')


def test_legacy_evidence_retains_code_and_its_meaning():
    from app.api.operations import _block_source_codes

    block = SimpleNamespace(source_activity_code='', classification_evidence='Programme v1 · Code 06',
                            source_page=0, source_operation_code='', phase_raw='', source_mark='', source_cause_code='')
    assert _block_source_codes(block)['source_activity_label'] == '06 — Wiper trip and reaming'
    assert block.classification_evidence == 'Programme v1 · Code 06'


def test_a_question_sharing_only_domain_vocabulary_is_not_answered_from_a_study_entry():
    """A live-workspace question must not be captured by a loosely related entry.

    "What is the drilling depth and NPT summary for <well>?" shares the words
    *drilling*, *depth*, *well* and *npt* with the time-depth/cost entry. Those
    are the vocabulary of the whole discipline, not evidence of the subject, so
    no study entry may claim the question. The live database answer (which needs
    the request's db) is the one that should serve it.
    """
    from app.domain.operations.study_knowledge import match_study_entries
    from app.services.operations.guide import answers

    question = "What is the drilling depth and NPT summary for AI-WELL-01?"
    assert match_study_entries(question, limit=3) == []
    answer = answers(question, '/operations/guide', {'ops-report:read'})
    assert answer is None or not (answer.memory_key or '').startswith('study-')


def test_a_study_entry_does_not_shadow_a_stronger_dnc_answer():
    """The study books and the DNC knowledge base must compete on merit.

    "How do I prevent pack-off and differential stuck pipe?" names two
    mechanisms. The DNC entry covers both; the strongest study entry covers only
    the mechanical one. Before the arbitration the study step returned first and
    the DNC answer could never be reached, however well it matched.
    """
    from app.domain.operations.dnc_knowledge import match_dnc_entries
    from app.domain.operations.study_knowledge import match_study_entries
    from app.services.operations.guide import answers

    question = "How do I prevent pack-off and differential stuck pipe?"
    dnc = match_dnc_entries(question, limit=1)
    study = match_study_entries(question, limit=1, minimum=0)
    assert dnc and study and dnc[0][0] > study[0][0]

    answer = answers(question, '/operations/guide', {'ops-report:read'})
    assert answer is not None
    assert answer.memory_key == dnc[0][1].key
    # A subject the book covers better still comes from the book.
    assert answers("what is kick tolerance?", '/operations/guide', {'ops-report:read'}).memory_key == (
        'study-kick-tolerance'
    )
