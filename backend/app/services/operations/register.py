"""Rig/well discovery without downloading activity logs, timelines or document bytes."""

from fastapi import HTTPException
from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import defer

from app.models.operations import OpsActivityBlock, OpsDailyReport, OpsDocument, OpsPlanVersion
from app.models.rig_well import Rig, Well

READ_PERMISSIONS = {'plans': 'ops-plan:read', 'reports': 'ops-report:read', 'documents': 'ops-doc:read'}


def _base(resource, org, deleted):
    model = {'plans': OpsPlanVersion, 'reports': OpsDailyReport, 'documents': OpsDocument}[resource]
    # Plans use the well's rig. Reports and documents preserve their filing rig;
    # a legacy unassigned record remains reachable by its historical snapshot.
    plan = resource == 'plans'
    rig_id = Well.rig_id if plan else model.rig_id
    rig_snapshot = literal('') if plan else model.rig_code_snapshot
    well_snapshot = literal('') if plan else model.well_code_snapshot
    name_snapshot = literal('') if plan else model.well_name_snapshot
    q = (
        select(model)
        .outerjoin(Well, (Well.id == model.well_id) & (Well.organization_id == org))
        .outerjoin(Rig, (Rig.id == rig_id) & (Rig.organization_id == org))
        .where(model.organization_id == org, model.is_deleted.is_(deleted))
    )
    return model, q, rig_id, rig_snapshot, well_snapshot, name_snapshot


def _folder_key(id_col, snapshot_col):
    return case((id_col.is_not(None), literal('id:') + id_col), else_=literal('snapshot:') + func.coalesce(snapshot_col, ''))


def _match(id_col, snapshot_col, key):
    if key.startswith('id:') and key[3:]:
        return id_col == key[3:]
    if key.startswith('snapshot:'):
        return id_col.is_(None) & (func.coalesce(snapshot_col, '') == key[9:])
    raise HTTPException(422, 'Choose a rig and well from the operations directory.')


def folders(db, org, resource, deleted):
    model, q, rig_id, rig_snapshot, well_snapshot, name_snapshot = _base(resource, org, deleted)
    rig_key = _folder_key(rig_id, rig_snapshot)
    well_key = _folder_key(model.well_id, well_snapshot)
    stmt = q.with_only_columns(
        rig_key.label('rig_key'), well_key.label('well_key'),
        rig_id.label('rig_id'), model.well_id.label('well_id'), model.scope,
        func.max(func.coalesce(Rig.rig_code, rig_snapshot, '')).label('rig_code'),
        func.max(func.coalesce(Well.well_code, well_snapshot, '')).label('well_code'),
        func.max(func.coalesce(Well.well_name, name_snapshot, '')).label('well_name'),
        func.count(model.id).label('record_count'),
    ).group_by(rig_key, well_key, rig_id, model.well_id, model.scope)
    return db.execute(stmt.order_by('rig_code', 'well_code', model.scope)).mappings().all()


def records(db, org, resource, deleted, rig_key, well_key, scope):
    model, q, rig_id, rig_snapshot, well_snapshot, _name_snapshot = _base(resource, org, deleted)
    q = q.where(_match(rig_id, rig_snapshot, rig_key), _match(model.well_id, well_snapshot, well_key))
    if scope:
        q = q.where(model.scope == scope)
    if resource == 'plans':
        rows = []
        for plan, well_code, well_name in db.execute(q.add_columns(Well.well_code, Well.well_name).order_by(model.created_at.desc())):
            plan._items, plan._well_code, plan._well_name = [], well_code or '', well_name or ''
            rows.append(plan)
        return rows
    if resource == 'documents':
        return db.scalars(q.options(defer(OpsDocument.content)).order_by(model.created_at.desc())).all()
    totals = (
        select(func.coalesce(func.sum(OpsActivityBlock.duration_minutes), 0))
        .where(OpsActivityBlock.organization_id == org, OpsActivityBlock.report_id == model.id,
               OpsActivityBlock.is_deleted.is_(False))
        .scalar_subquery()
    )
    rows = []
    for report, minutes in db.execute(q.add_columns(totals).order_by(model.report_date.desc(), model.created_at.desc())):
        report._total_block_minutes = minutes
        rows.append(report)
    return rows
