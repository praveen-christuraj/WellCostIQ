"""Reusable record templates: build, list, apply.

Three kinds share this service because the workflow is the same:

    AFE estimate template  → open a new AFE estimate, pick the template, fill the
                              values that differ for this well, save.
    Well plan template     → configure a well, pick the template, adjust the
                              depth/days, save the plan.
    Daily sheet template   → open a new daily sheet, pick the template and the
                              standard lines are already there.

Nothing is copied blindly: catalogue references and plan scopes are matched
against what this workspace still has, and anything missing is reported as
unavailable instead of being silently dropped.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    CementAdditive,
    DrillBit,
    FuelType,
    HoleSection,
    MudChemical,
    Phase,
    RecordTemplate,
    Service,
    Tangible,
    TemplateConsumableLine,
    TemplateServiceLine,
    TemplateTangibleLine,
    TemplateWellPhase,
    TemplateWellSection,
    Well,
    WellPhase,
    WellSection,
)
from app.models.record_template import scope_key
from app.schemas.record_template import (
    TemplateApplyLineOut,
    TemplateApplyPreviewOut,
    TemplateConsumableLineOut,
    TemplateCreate,
    TemplateOut,
    TemplateServiceLineOut,
    TemplateSummaryOut,
    TemplateTangibleLineOut,
    TemplateWellPhaseOut,
    TemplateWellSectionOut,
)
from app.services import audit

KIND_LABELS = {"afe": "AFE estimate", "well": "well plan", "daily-cost": "daily sheet"}


def actor_name(user: Any) -> str:
    return getattr(user, "full_name", "") or getattr(user, "email", "") or ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A template with this name already exists. Choose another name or edit the existing template.",
        ) from error


def _visible(db: Session, user: Any):
    """Templates this user may see: their own, plus anything shared in the workspace."""
    return select(RecordTemplate).where(
        RecordTemplate.organization_id == user.organization_id,
        RecordTemplate.is_deleted.is_(False),
        or_(RecordTemplate.user_id == user.id, RecordTemplate.is_shared.is_(True)),
    )


def _load(db: Session, user: Any, template_id: str) -> RecordTemplate:
    template = db.scalar(
        _visible(db, user)
        .options(
            selectinload(RecordTemplate.services),
            selectinload(RecordTemplate.consumables),
            selectinload(RecordTemplate.tangibles),
            selectinload(RecordTemplate.sections).selectinload(TemplateWellSection.phases),
        )
        .where(RecordTemplate.id == template_id)
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found in this workspace")
    return template


def _codes(db: Session, model: Any, ids: set[str], organization_id: str) -> dict[str, Any]:
    if not ids:
        return {}
    rows = db.scalars(
        select(model).where(model.organization_id == organization_id, model.id.in_(ids))
    ).all()
    return {row.id: row for row in rows}


class _Lookups:
    """Everything the templates reference, read once per request.

    Two kinds of reference are resolved together: catalogue *ids* (services,
    tangibles, drill bits) and plan *codes* (a service line belongs to a hole
    section and phase by code, so the same AFE template applies to any well whose
    plan names them the same way).
    """

    def __init__(self, db: Session, organization_id: str, templates: list[RecordTemplate]):
        service_ids, tangible_ids, bit_ids = set(), set(), set()
        section_ids, phase_ids = set(), set()
        section_codes, phase_codes = set(), set()
        for template in templates:
            service_ids.update(line.service_id for line in template.services)
            tangible_ids.update(line.tangible_id for line in template.tangibles)
            bit_ids.update(line.drill_bit_id for line in template.consumables if line.drill_bit_id)
            for line in [*template.services, *template.consumables]:
                if line.section_code:
                    section_codes.add(line.section_code)
                if line.phase_code:
                    phase_codes.add(line.phase_code)
            for section in template.sections:
                section_ids.add(section.hole_section_id)
                if section.section_code:
                    section_codes.add(section.section_code)
                for phase in section.phases:
                    phase_ids.add(phase.phase_id)
                    if phase.phase_code:
                        phase_codes.add(phase.phase_code)
        ids_by_section_code = self._ids_by_code(db, HoleSection, organization_id, "section_code", section_codes)
        ids_by_phase_code = self._ids_by_code(db, Phase, organization_id, "phase_code", phase_codes)
        self.services = _codes(db, Service, service_ids, organization_id)
        self.tangibles = _codes(db, Tangible, tangible_ids, organization_id)
        self.drill_bits = _codes(db, DrillBit, bit_ids, organization_id)
        self.sections = _codes(db, HoleSection, section_ids | ids_by_section_code, organization_id)
        self.phases = _codes(db, Phase, phase_ids | ids_by_phase_code, organization_id)

    @staticmethod
    def _ids_by_code(db: Session, model: Any, organization_id: str, code_attr: str, codes: set[str]) -> set[str]:
        if not codes:
            return set()
        column = getattr(model, code_attr)
        return set(db.scalars(
            select(model.id).where(model.organization_id == organization_id, column.in_(codes))
        ).all())

    @staticmethod
    def _alive(row: Any) -> bool:
        return row is not None and not getattr(row, "is_deleted", False)

    def section_label(self, code: str) -> str:
        if not code:
            return ""
        for section in self.sections.values():
            if section.section_code == code and self._alive(section):
                return f"{section.section_code} · {section.section_name}"
        return code

    def phase_label(self, code: str) -> str:
        if not code:
            return ""
        for phase in self.phases.values():
            if phase.phase_code == code and self._alive(phase):
                return f"{phase.phase_code} · {phase.phase_name}"
        return code

    def section_known(self, code: str) -> bool:
        return not code or any(
            section.section_code == code and self._alive(section) for section in self.sections.values()
        )

    def phase_known(self, code: str) -> bool:
        return not code or any(
            phase.phase_code == code and self._alive(phase) for phase in self.phases.values()
        )


def decimal_text(value: Any) -> str:
    """A stored decimal as an operator reads it.

    The columns keep ten decimals, so a depth of zero would otherwise arrive as
    ``0E-10`` — which no numeric input accepts — and twelve days as
    ``12.0000000000``. Trailing zeros are trimmed and exponent notation is never
    produced, so every value can be typed straight into the field it came from.
    """
    if value in (None, ""):
        return "0"
    text = format(Decimal(str(value)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _line_count(template: RecordTemplate) -> int:
    if template.template_kind == "well":
        return sum(len(section.phases) for section in template.sections)
    return len(template.services) + len(template.consumables) + len(template.tangibles)


def _unavailable_count(template: RecordTemplate, lookups: "_Lookups") -> int:
    missing = 0
    for line in template.services:
        if not lookups._alive(lookups.services.get(line.service_id)):
            missing += 1
    for line in template.tangibles:
        if not lookups._alive(lookups.tangibles.get(line.tangible_id)):
            missing += 1
    for line in template.consumables:
        if line.drill_bit_id and not lookups._alive(lookups.drill_bits.get(line.drill_bit_id)):
            missing += 1
    for section in template.sections:
        if not lookups._alive(lookups.sections.get(section.hole_section_id)):
            missing += 1
        missing += sum(1 for phase in section.phases if not lookups._alive(lookups.phases.get(phase.phase_id)))
    return missing


def summary(spec: RecordTemplate, lookups: _Lookups, user: Any) -> TemplateSummaryOut:
    return TemplateSummaryOut(
        id=spec.id,
        owner_id=spec.user_id,
        owner_name=spec.created_by,
        template_kind=spec.template_kind,
        name=spec.name,
        description=spec.description,
        scope=spec.scope,
        afe_type=spec.afe_type,
        standard_currency=spec.standard_currency,
        is_shared=spec.is_shared,
        is_owner=spec.user_id == user.id,
        use_count=spec.use_count,
        last_used_at=spec.last_used_at,
        line_count=_line_count(spec),
        unavailable_count=_unavailable_count(spec, lookups),
        updated_at=spec.updated_at,
    )


def detail(spec: RecordTemplate, lookups: _Lookups, user: Any) -> TemplateOut:
    services = [
        TemplateServiceLineOut(
            service_id=line.service_id,
            service_code=line.service_code or (lookups.services.get(line.service_id).service_code if lookups.services.get(line.service_id) else ""),
            service_name=line.service_name or (lookups.services.get(line.service_id).service_name if lookups.services.get(line.service_id) else ""),
            charging_basis=line.charging_basis,
            section_code=line.section_code,
            section_label=lookups.section_label(line.section_code) if line.section_code else "All sections",
            phase_code=line.phase_code,
            phase_label=lookups.phase_label(line.phase_code) if line.phase_code else "",
            currency=line.currency,
            service_amount=line.service_amount,
            operation_rate=line.operation_rate,
            standby_rate=line.standby_rate,
            repair_rate=line.repair_rate,
            operation_days=line.operation_days,
            standby_days=line.standby_days,
            repair_days=line.repair_days,
            quantity_unit=line.quantity_unit,
            remarks=line.remarks,
            is_available=lookups._alive(lookups.services.get(line.service_id)),
        )
        for line in spec.services
    ]
    consumables = [
        TemplateConsumableLineOut(
            category=line.category,
            section_code=line.section_code,
            section_label=lookups.section_label(line.section_code) if line.section_code else "All sections",
            phase_code=line.phase_code,
            phase_label=lookups.phase_label(line.phase_code) if line.phase_code else "",
            drill_bit_id=line.drill_bit_id,
            drill_bit_code=line.drill_bit_code,
            drill_bit_name=line.drill_bit_name,
            quantity=line.quantity,
            estimated_amount=line.estimated_amount,
            currency=line.currency,
            remarks=line.remarks,
            is_available=not line.drill_bit_id or lookups._alive(lookups.drill_bits.get(line.drill_bit_id)),
        )
        for line in spec.consumables
    ]
    tangibles = [
        TemplateTangibleLineOut(
            tangible_id=line.tangible_id,
            tangible_code=line.tangible_code,
            tangible_name=line.tangible_name,
            quantity=line.quantity,
            remarks=line.remarks,
            is_available=lookups._alive(lookups.tangibles.get(line.tangible_id)),
        )
        for line in spec.tangibles
    ]
    sections = [
        TemplateWellSectionOut(
            hole_section_id=section.hole_section_id,
            section_code=section.section_code,
            section_name=section.section_name,
            from_depth=decimal_text(section.from_depth),
            to_depth=decimal_text(section.to_depth),
            depth_unit=section.depth_unit,
            remarks=section.remarks,
            phases=[
                TemplateWellPhaseOut(
                    phase_id=phase.phase_id,
                    phase_code=phase.phase_code,
                    phase_name=phase.phase_name,
                    days=decimal_text(phase.days),
                    remarks=phase.remarks,
                    is_available=lookups._alive(lookups.phases.get(phase.phase_id)),
                )
                for phase in section.phases
            ],
            is_available=lookups._alive(lookups.sections.get(section.hole_section_id)),
        )
        for section in spec.sections
    ]
    base = summary(spec, lookups, user)
    return TemplateOut(
        **base.model_dump(),
        services=services,
        consumables=consumables,
        tangibles=tangibles,
        sections=sections,
        created_at=spec.created_at,
    )


def list_templates(db: Session, user: Any, kind: str = "") -> list[TemplateSummaryOut]:
    statement = _visible(db, user).options(
        selectinload(RecordTemplate.services),
        selectinload(RecordTemplate.consumables),
        selectinload(RecordTemplate.tangibles),
        selectinload(RecordTemplate.sections).selectinload(TemplateWellSection.phases),
    )
    if kind:
        statement = statement.where(RecordTemplate.template_kind == kind)
    templates = list(db.scalars(statement.order_by(RecordTemplate.updated_at.desc())).unique().all())
    lookups = _Lookups(db, user.organization_id, templates)
    return [summary(template, lookups, user) for template in templates]


def get_template(db: Session, user: Any, template_id: str) -> TemplateOut:
    template = _load(db, user, template_id)
    return detail(template, _Lookups(db, user.organization_id, [template]), user)


def _require_owner(template: RecordTemplate, user: Any) -> None:
    if template.user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="This template is shared by another user. Duplicate it to make your own changes.",
        )


def _describe(kind: str, data: TemplateCreate) -> str:
    """A short, human count for the audit trail."""
    if kind == "well":
        sections = len(data.sections)
        phases = sum(len(section.phases) for section in data.sections)
        return f"{sections} hole section{'s' if sections != 1 else ''}, {phases} phase{'s' if phases != 1 else ''}"
    parts = []
    for count, noun in (
        (len(data.services), "service line"), (len(data.consumables), "consumable line"),
        (len(data.tangibles), "tangible line"),
    ):
        if count:
            parts.append(f"{count} {noun}{'s' if count != 1 else ''}")
    return ", ".join(parts) or "no lines"


def _write_lines(db: Session, organization_id: str, template: RecordTemplate, data: TemplateCreate) -> None:
    """Replace every line, keeping readable code/name snapshots on each one.

    Codes are copied at save time on purpose: a template must still read
    correctly years later, after a service has been renamed or retired. The id
    stays the link, the snapshot is what the user sees.
    """
    service_rows = _codes(db, Service, {line.service_id for line in data.services}, organization_id)
    bit_rows = _codes(db, DrillBit, {line.drill_bit_id for line in data.consumables if line.drill_bit_id}, organization_id)
    tangible_rows = _codes(db, Tangible, {line.tangible_id for line in data.tangibles}, organization_id)
    section_rows = _codes(db, HoleSection, {section.hole_section_id for section in data.sections}, organization_id)
    phase_rows = _codes(
        db, Phase,
        {phase.phase_id for section in data.sections for phase in section.phases}, organization_id,
    )

    template.services = [
        TemplateServiceLine(
            organization_id=organization_id,
            service_id=line.service_id,
            service_code=getattr(service_rows.get(line.service_id), "service_code", ""),
            service_name=getattr(service_rows.get(line.service_id), "service_name", ""),
            charging_basis=line.charging_basis,
            section_code=line.section_code,
            phase_code=line.phase_code,
            currency=line.currency.upper(),
            service_amount=line.service_amount or "0",
            operation_rate=line.operation_rate,
            standby_rate=line.standby_rate,
            repair_rate=line.repair_rate,
            operation_days=line.operation_days,
            standby_days=line.standby_days,
            repair_days=line.repair_days,
            quantity_unit=line.quantity_unit,
            remarks=line.remarks,
            sort_order=index,
        )
        for index, line in enumerate(data.services)
    ]
    template.consumables = [
        TemplateConsumableLine(
            organization_id=organization_id,
            category=line.category,
            section_code=line.section_code,
            phase_code=line.phase_code,
            drill_bit_id=line.drill_bit_id,
            drill_bit_code=getattr(bit_rows.get(line.drill_bit_id), "bit_code", ""),
            drill_bit_name=getattr(bit_rows.get(line.drill_bit_id), "bit_name", ""),
            quantity=line.quantity or "1",
            estimated_amount=line.estimated_amount,
            currency=line.currency.upper(),
            remarks=line.remarks,
            sort_order=index,
        )
        for index, line in enumerate(data.consumables)
    ]
    template.tangibles = [
        TemplateTangibleLine(
            organization_id=organization_id,
            tangible_id=line.tangible_id,
            tangible_code=getattr(tangible_rows.get(line.tangible_id), "tangible_code", ""),
            tangible_name=getattr(tangible_rows.get(line.tangible_id), "tangible_name", ""),
            quantity=line.quantity or "1",
            remarks=line.remarks,
            sort_order=index,
        )
        for index, line in enumerate(data.tangibles)
    ]
    template.sections = [
        TemplateWellSection(
            organization_id=organization_id,
            hole_section_id=section.hole_section_id,
            section_code=getattr(section_rows.get(section.hole_section_id), "section_code", ""),
            section_name=getattr(section_rows.get(section.hole_section_id), "section_name", ""),
            from_depth=section.from_depth or "0",
            to_depth=section.to_depth or "0",
            remarks=section.remarks,
            sort_order=index,
            phases=[
                TemplateWellPhase(
                    organization_id=organization_id,
                    phase_id=phase.phase_id,
                    phase_code=getattr(phase_rows.get(phase.phase_id), "phase_code", ""),
                    phase_name=getattr(phase_rows.get(phase.phase_id), "phase_name", ""),
                    days=phase.days or "0",
                    remarks=phase.remarks,
                    sort_order=phase_index,
                )
                for phase_index, phase in enumerate(section.phases)
            ],
        )
        for index, section in enumerate(data.sections)
    ]


def create_template(db: Session, user: Any, data: TemplateCreate, request: Any) -> TemplateOut:
    _validate_kind_lines(data)
    template = RecordTemplate(
        organization_id=user.organization_id,
        user_id=user.id,
        template_kind=data.template_kind,
        name=data.name,
        name_key=scope_key(data.name).casefold(),
        description=data.description,
        scope=scope_key(data.scope),
        afe_type=data.afe_type,
        standard_currency=data.standard_currency.upper(),
        is_shared=data.is_shared,
        created_by=actor_name(user),
        updated_by=actor_name(user),
    )
    _write_lines(db, user.organization_id, template, data)
    db.add(template)
    audit.record(
        db, organization_id=user.organization_id, actor=user, action="create",
        entity_type="record_template", entity_id=template.id, entity_label=template.name,
        summary=(
            f"Created {KIND_LABELS[data.template_kind]} template {template.name} "
            f"({_describe(data.template_kind, data)})"
            + (" — shared with the workspace" if data.is_shared else " — private")
        ),
        request=request,
    )
    _commit(db)
    db.refresh(template)
    return get_template(db, user, template.id)


def update_template(db: Session, user: Any, template_id: str, data: TemplateCreate, request: Any) -> TemplateOut:
    template = _load(db, user, template_id)
    _require_owner(template, user)
    _validate_kind_lines(data)
    if data.template_kind != template.template_kind:
        raise HTTPException(
            status_code=422,
            detail=f"An {KIND_LABELS[template.template_kind]} template cannot become an {KIND_LABELS[data.template_kind]} template. Create a new template instead.",
        )
    template.name = data.name
    template.name_key = scope_key(data.name).casefold()
    template.description = data.description
    template.scope = scope_key(data.scope)
    template.afe_type = data.afe_type
    template.standard_currency = data.standard_currency.upper()
    template.is_shared = data.is_shared
    template.updated_by = actor_name(user)
    template.updated_at = _now()
    _write_lines(db, user.organization_id, template, data)
    audit.record(
        db, organization_id=user.organization_id, actor=user, action="update",
        entity_type="record_template", entity_id=template.id, entity_label=template.name,
        summary=f"Updated {KIND_LABELS[template.template_kind]} template {template.name} ({_describe(data.template_kind, data)})",
        request=request,
    )
    _commit(db)
    return get_template(db, user, template.id)


def _validate_kind_lines(data: TemplateCreate) -> None:
    """A template may only carry the lines its record type understands."""
    if data.template_kind == "well":
        if data.services or data.consumables or data.tangibles:
            raise HTTPException(
                status_code=422,
                detail="A well plan template holds hole sections and phases only. Save the cost lines in an AFE estimate template instead.",
            )
        if not data.sections:
            raise HTTPException(status_code=422, detail="Add at least one hole section to this well plan template.")
        codes = [section.hole_section_id for section in data.sections]
        if len(codes) != len(set(codes)):
            raise HTTPException(status_code=422, detail="The same hole section appears more than once in this template.")
        for section in data.sections:
            phase_ids = [phase.phase_id for phase in section.phases]
            if len(phase_ids) != len(set(phase_ids)):
                raise HTTPException(status_code=422, detail="The same phase appears more than once in one hole section.")
        return
    if data.sections:
        raise HTTPException(
            status_code=422,
            detail="Only a well plan template holds hole sections. An AFE or daily sheet template points at a well's own plan.",
        )
    if data.template_kind == "afe" and not (data.services or data.consumables or data.tangibles):
        raise HTTPException(status_code=422, detail="Add at least one line to this AFE estimate template.")
    duplicated = _duplicate_service_scope(data)
    if duplicated:
        raise HTTPException(
            status_code=422,
            detail=f"{duplicated} appears twice for the same hole section and phase. Remove one of the lines.",
        )


def _duplicate_service_scope(data: TemplateCreate) -> str:
    seen: set[tuple[str, str, str]] = set()
    for line in data.services:
        key = (line.service_id, line.section_code, line.phase_code)
        if key in seen:
            return "A service line"
        seen.add(key)
    return ""


def delete_template(db: Session, user: Any, template_id: str, request: Any) -> None:
    """Soft delete: a template is recoverable like every other record here."""
    template = _load(db, user, template_id)
    _require_owner(template, user)
    template.is_deleted = True
    template.deleted_at = _now()
    template.deleted_by = actor_name(user)
    template.updated_by = actor_name(user)
    audit.record(
        db, organization_id=user.organization_id, actor=user, action="soft_delete",
        entity_type="record_template", entity_id=template.id, entity_label=template.name,
        summary=f"Moved {KIND_LABELS[template.template_kind]} template {template.name} to deleted entries",
        request=request,
    )
    _commit(db)


def duplicate_template(db: Session, user: Any, template_id: str, request: Any) -> TemplateOut:
    """Copy a shared template into the user's own list so they can edit it."""
    source = _load(db, user, template_id)
    data = TemplateCreate(
        template_kind=source.template_kind,
        name=f"{source.name} (copy)"[:120],
        description=source.description,
        scope=source.scope,
        afe_type=source.afe_type,
        standard_currency=source.standard_currency,
        is_shared=False,
        services=[{
            "service_id": line.service_id, "charging_basis": line.charging_basis,
            "section_code": line.section_code, "phase_code": line.phase_code,
            "currency": line.currency, "service_amount": line.service_amount,
            "operation_rate": line.operation_rate, "standby_rate": line.standby_rate,
            "repair_rate": line.repair_rate, "operation_days": line.operation_days,
            "standby_days": line.standby_days, "repair_days": line.repair_days,
            "quantity_unit": line.quantity_unit, "remarks": line.remarks,
        } for line in source.services],
        consumables=[{
            "category": line.category, "section_code": line.section_code, "phase_code": line.phase_code,
            "drill_bit_id": line.drill_bit_id, "quantity": line.quantity,
            "estimated_amount": line.estimated_amount, "currency": line.currency, "remarks": line.remarks,
        } for line in source.consumables],
        tangibles=[{
            "tangible_id": line.tangible_id, "quantity": line.quantity, "remarks": line.remarks,
        } for line in source.tangibles],
        sections=[{
            "hole_section_id": section.hole_section_id,
            "from_depth": decimal_text(section.from_depth), "to_depth": decimal_text(section.to_depth),
            "remarks": section.remarks,
            "phases": [{
                "phase_id": phase.phase_id, "days": decimal_text(phase.days), "remarks": phase.remarks,
            } for phase in section.phases],
        } for section in source.sections],
    )
    copy = RecordTemplate(
        organization_id=user.organization_id,
        user_id=user.id,
        template_kind=data.template_kind,
        name=data.name,
        name_key=scope_key(data.name).casefold(),
        description=data.description,
        scope=scope_key(data.scope),
        afe_type=data.afe_type,
        standard_currency=data.standard_currency,
        is_shared=False,
        created_by=actor_name(user),
        updated_by=actor_name(user),
    )
    _write_lines(db, user.organization_id, copy, data)
    db.add(copy)
    audit.record(
        db, organization_id=user.organization_id, actor=user, action="create",
        entity_type="record_template", entity_id=copy.id, entity_label=copy.name,
        summary=f"Copied {KIND_LABELS[source.template_kind]} template {source.name}",
        request=request,
    )
    _commit(db)
    db.refresh(copy)
    return get_template(db, user, copy.id)


def preview_template(db: Session, user: Any, template_id: str, well_id: str = "") -> TemplateApplyPreviewOut:
    """Exactly what applying this template will add, and what is missing.

    Nothing is written. The user sees the lines and any warning before the
    template touches the record they are editing.
    """
    template = _load(db, user, template_id)
    lookups = _Lookups(db, user.organization_id, [template])
    warnings: list[str] = []
    services: list[TemplateApplyLineOut] = []
    consumables: list[TemplateApplyLineOut] = []
    tangibles: list[TemplateApplyLineOut] = []
    sections: list[TemplateApplyLineOut] = []

    for line in template.services:
        available = lookups._alive(lookups.services.get(line.service_id))
        label = line.service_name or line.service_code or "Service no longer in Master Data"
        scope = " · ".join(filter(None, [
            lookups.section_label(line.section_code) if line.section_code else "",
            lookups.phase_label(line.phase_code) if line.phase_code else "",
        ]))
        services.append(TemplateApplyLineOut(
            kind="service", label=label, is_available=available, note=scope,
        ))
        if not available:
            warnings.append(f"{label} is no longer in Master Data and will be skipped.")
        if not lookups.section_known(line.section_code):
            warnings.append(f"Hole section {line.section_code} is no longer in Master Data; {label} will be applied without a section you must choose.")
        if not lookups.phase_known(line.phase_code):
            warnings.append(f"Phase {line.phase_code} is no longer in Master Data; {label} will be applied without a phase.")

    for line in template.consumables:
        available = not line.drill_bit_id or lookups._alive(lookups.drill_bits.get(line.drill_bit_id))
        label = line.drill_bit_name if line.drill_bit_id else f"{line.category} budget"
        consumables.append(TemplateApplyLineOut(
            kind="consumable", label=label, is_available=available,
            note=" · ".join(filter(None, [line.category, lookups.section_label(line.section_code) if line.section_code else ""])),
        ))
        if not available:
            warnings.append(f"Drill bit {label} is no longer in Master Data and will be skipped.")

    for line in template.tangibles:
        available = lookups._alive(lookups.tangibles.get(line.tangible_id))
        label = line.tangible_name or line.tangible_code or "Tangible no longer in Master Data"
        tangibles.append(TemplateApplyLineOut(kind="tangible", label=label, is_available=available))
        if not available:
            warnings.append(f"{label} is no longer in Master Data and will be skipped.")

    if template.template_kind == "well":
        well = None
        if well_id:
            well = db.scalar(select(Well).where(
                Well.id == well_id, Well.organization_id == user.organization_id, Well.is_deleted.is_(False),
            ))
            if well is None:
                warnings.append("Choose the well this plan template is for, so its sections can be matched.")
        plan_phases: dict[str, dict[str, list[str]]] = {}
        if well is not None:
            rows = db.scalars(
                select(WellPhase)
                .join(WellSection, WellPhase.section_id == WellSection.id)
                .where(WellSection.well_id == well.id, WellPhase.organization_id == user.organization_id)
            ).all()
            for row in rows:
                plan_phases.setdefault(row.section_id, {})[row.phase_id] = row.phase_name
        for section in template.sections:
            available = lookups._alive(lookups.sections.get(section.hole_section_id))
            label = f"{section.section_code} · {section.section_name}".strip(" ·")
            day_total = sum(float(phase.days or 0) for phase in section.phases)
            sections.append(TemplateApplyLineOut(
                kind="section", label=label, is_available=available,
                note=(
                    f"{decimal_text(section.from_depth)}–{decimal_text(section.to_depth)} {section.depth_unit}"
                    f" · {len(section.phases)} phase{'' if len(section.phases) == 1 else 's'}"
                    f" · {day_total:g} days"
                ),
            ))
            if not available:
                warnings.append(f"Hole section {label} is no longer in Master Data and will be skipped.")
                continue
            if well is not None and section.hole_section_id not in plan_phases:
                warnings.append(f"The well plan does not use {label} yet; the section will be added with the template's phases.")
            for phase in section.phases:
                if not lookups._alive(lookups.phases.get(phase.phase_id)):
                    warnings.append(f"Phase {phase.phase_code or phase.phase_id} is no longer in Master Data and will be skipped.")

    if template.template_kind != "well" and well_id and not any(services) and not any(consumables) and not any(tangibles):
        warnings.append("This template has no lines.")

    return TemplateApplyPreviewOut(
        template_id=template.id,
        template_kind=template.template_kind,
        name=template.name,
        services=services,
        consumables=consumables,
        tangibles=tangibles,
        sections=sections,
        warnings=warnings,
        can_apply=bool(services or consumables or tangibles or sections) and any(
            line.is_available for line in [*services, *consumables, *tangibles, *sections]
        ),
    )


def record_use(db: Session, user: Any, template_id: str, request: Any) -> TemplateSummaryOut:
    """Count one apply. The template itself is not changed."""
    template = _load(db, user, template_id)
    template.use_count += 1
    template.last_used_at = _now()
    audit.record(
        db, organization_id=user.organization_id, actor=user, action="apply",
        entity_type="record_template", entity_id=template.id, entity_label=template.name,
        summary=f"Applied {KIND_LABELS[template.template_kind]} template {template.name}",
        request=request,
    )
    _commit(db)
    return summary(template, _Lookups(db, user.organization_id, [template]), user)


def export_rows(db: Session, user: Any, kind: str) -> list[dict[str, str]]:
    """Templates as spreadsheet rows — the same columns for every kind.

    One row per line, in the order the editor shows them, and every row can be
    read on its own: which template it belongs to, what kind of line it is, the
    item it names, its quantity and money. A consumable line keeps its own code
    column, so a mud chemical never appears as a drill bit.
    """
    templates = list(db.scalars(
        _visible(db, user)
        .options(
            selectinload(RecordTemplate.services),
            selectinload(RecordTemplate.consumables),
            selectinload(RecordTemplate.tangibles),
            selectinload(RecordTemplate.sections).selectinload(TemplateWellSection.phases),
        )
        .where(RecordTemplate.template_kind == kind if kind else True)
        .order_by(RecordTemplate.name)
    ).unique().all())
    rows: list[dict[str, str]] = []

    def row(template: RecordTemplate, line_type: str, **values: str) -> dict[str, str]:
        return {
            "template": template.name,
            "kind": KIND_LABELS[template.template_kind],
            "scope": template.scope,
            "line_type": line_type,
            **{
                key: values.get(key, "")
                for key in ("section_code", "from_depth", "to_depth", "phase_code", "days",
                            "item_code", "item_name", "quantity", "currency", "amount", "remarks")
            },
        }

    for template in templates:
        if template.template_kind == "well":
            for section in template.sections:
                for phase in section.phases:
                    rows.append(row(
                        template, "Phase",
                        section_code=section.section_code,
                        from_depth=decimal_text(section.from_depth),
                        to_depth=decimal_text(section.to_depth),
                        phase_code=phase.phase_code, days=decimal_text(phase.days),
                        item_code=phase.phase_code, item_name=phase.phase_name,
                        remarks=phase.remarks or section.remarks,
                    ))
            continue
        for line in template.services:
            rows.append(row(
                template, "Service",
                section_code=line.section_code, phase_code=line.phase_code,
                days=line.operation_days or "",
                item_code=line.service_code, item_name=line.service_name,
                currency=line.currency, amount=decimal_text(line.service_amount),
                remarks=line.remarks,
            ))
        for line in template.consumables:
            rows.append(row(
                template, "Consumable",
                section_code=line.section_code, phase_code=line.phase_code,
                item_code=line.drill_bit_code or line.category,
                item_name=line.drill_bit_name or line.category,
                quantity=decimal_text(line.quantity), currency=line.currency,
                amount=decimal_text(line.estimated_amount) if line.estimated_amount is not None else "",
                remarks=line.remarks,
            ))
        for line in template.tangibles:
            rows.append(row(
                template, "Tangible",
                item_code=line.tangible_code, item_name=line.tangible_name,
                quantity=decimal_text(line.quantity), remarks=line.remarks,
            ))
    return rows


def catalog_models() -> tuple[Any, ...]:
    """Catalogue models templates may point at, for workspace checks."""
    return (Service, Tangible, DrillBit, MudChemical, CementAdditive, FuelType)
