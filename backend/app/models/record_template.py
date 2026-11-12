"""Reusable starting points: AFE estimate templates, well plan templates and daily sheet templates.

A template is a *starting point*, never a live record. It holds column-wise
values only — no JSON blobs — so a template can be listed, filtered and audited
like any other table, and an edited template never changes a saved AFE, well or
daily sheet.

Each template is scoped to one workspace (organization) and owned by one user.
It may be shared with the whole workspace (`is_shared`), which is how a costing
team hands a standard drilling AFE to everyone. Catalogue references are plain
ids, deliberately *not* foreign keys: removing a service from Master Data must
never delete or block somebody's template. A missing reference is reported as
unavailable when the template is applied.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.entities import now

TEMPLATE_KINDS = ("afe", "well", "daily-cost")


def uid() -> str:
    return str(uuid4())


def scope_key(value: str | None) -> str:
    """Normalise a scope so one name can only exist once per kind and scope."""
    return " ".join(str(value or "General").split()) or "General"


class RecordTemplate(Base):
    """A named starting point for one record type."""

    __tablename__ = "record_templates"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", "template_kind", "name_key",
            name="uq_record_templates_owner_name",
        ),
        CheckConstraint(
            "template_kind IN ('afe', 'well', 'daily-cost')", name="ck_record_templates_kind",
        ),
        Index("ix_record_templates_org_kind_scope", "organization_id", "template_kind", "scope"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    # The AFE type ("Drilling"/"Completion"), the scope a plan or sheet belongs to,
    # or the template's group. Kept short and normalised so it can be grouped on.
    scope: Mapped[str] = mapped_column(String(60), default="General", server_default="General", nullable=False)
    afe_type: Mapped[str] = mapped_column(String(20), default="Drilling", server_default="Drilling", nullable=False)
    standard_currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    # Using a template must not silently change a record: every apply is counted.
    use_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    deleted_by: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)

    services: Mapped[list["TemplateServiceLine"]] = relationship(
        back_populates="template", cascade="all, delete-orphan",
        order_by="TemplateServiceLine.sort_order", passive_deletes=True,
    )
    consumables: Mapped[list["TemplateConsumableLine"]] = relationship(
        back_populates="template", cascade="all, delete-orphan",
        order_by="TemplateConsumableLine.sort_order", passive_deletes=True,
    )
    tangibles: Mapped[list["TemplateTangibleLine"]] = relationship(
        back_populates="template", cascade="all, delete-orphan",
        order_by="TemplateTangibleLine.sort_order", passive_deletes=True,
    )
    sections: Mapped[list["TemplateWellSection"]] = relationship(
        back_populates="template", cascade="all, delete-orphan",
        order_by="TemplateWellSection.sort_order", passive_deletes=True,
    )


class TemplateServiceLine(Base):
    """One service line of an AFE estimate template."""

    __tablename__ = "record_template_services"
    __table_args__ = (Index("ix_record_template_services_template", "template_id", "sort_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("record_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[str] = mapped_column(String(36), nullable=False)
    service_code: Mapped[str] = mapped_column(String(60), default="", server_default="", nullable=False)
    service_name: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    charging_basis: Mapped[str] = mapped_column(String(30), default="Day Rate", server_default="Day Rate", nullable=False)
    # Scopes are matched by code, not by id: an AFE template must apply to wells
    # whose plan was configured separately.
    section_code: Mapped[str] = mapped_column(String(60), default="", server_default="", nullable=False)
    phase_code: Mapped[str] = mapped_column(String(60), default="", server_default="", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    service_amount: Mapped[str] = mapped_column(String(40), default="0", server_default="0", nullable=False)
    operation_rate: Mapped[str | None] = mapped_column(String(40), nullable=True)
    standby_rate: Mapped[str | None] = mapped_column(String(40), nullable=True)
    repair_rate: Mapped[str | None] = mapped_column(String(40), nullable=True)
    operation_days: Mapped[str | None] = mapped_column(String(40), nullable=True)
    standby_days: Mapped[str | None] = mapped_column(String(40), nullable=True)
    repair_days: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quantity_unit: Mapped[str] = mapped_column(String(10), default="days", server_default="days", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    template: Mapped[RecordTemplate] = relationship(back_populates="services")


class TemplateConsumableLine(Base):
    """One budget consumable (or drill bit) line of an AFE estimate template."""

    __tablename__ = "record_template_consumables"
    __table_args__ = (Index("ix_record_template_consumables_template", "template_id", "sort_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("record_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    section_code: Mapped[str] = mapped_column(String(60), default="", server_default="", nullable=False)
    phase_code: Mapped[str] = mapped_column(String(60), default="", server_default="", nullable=False)
    drill_bit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    drill_bit_code: Mapped[str] = mapped_column(String(60), default="", server_default="", nullable=False)
    drill_bit_name: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    quantity: Mapped[str] = mapped_column(String(40), default="1", server_default="1", nullable=False)
    estimated_amount: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    template: Mapped[RecordTemplate] = relationship(back_populates="consumables")


class TemplateTangibleLine(Base):
    """One tangible line of an AFE estimate template."""

    __tablename__ = "record_template_tangibles"
    __table_args__ = (Index("ix_record_template_tangibles_template", "template_id", "sort_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("record_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tangible_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tangible_code: Mapped[str] = mapped_column(String(60), default="", server_default="", nullable=False)
    tangible_name: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    quantity: Mapped[str] = mapped_column(String(40), default="1", server_default="1", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    template: Mapped[RecordTemplate] = relationship(back_populates="tangibles")


class TemplateWellSection(Base):
    """One hole section (with its phases and their planned days) of a well plan template."""

    __tablename__ = "record_template_well_sections"
    __table_args__ = (Index("ix_record_template_well_sections_template", "template_id", "sort_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("record_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hole_section_id: Mapped[str] = mapped_column(String(36), nullable=False)
    section_code: Mapped[str] = mapped_column(String(60), default="", server_default="", nullable=False)
    section_name: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    from_depth: Mapped[float] = mapped_column(Numeric(28, 10), default=0, server_default="0", nullable=False)
    to_depth: Mapped[float] = mapped_column(Numeric(28, 10), default=0, server_default="0", nullable=False)
    depth_unit: Mapped[str] = mapped_column(String(4), default="m", server_default="m", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    template: Mapped[RecordTemplate] = relationship(back_populates="sections")
    phases: Mapped[list["TemplateWellPhase"]] = relationship(
        back_populates="section", cascade="all, delete-orphan",
        order_by="TemplateWellPhase.sort_order", passive_deletes=True,
    )


class TemplateWellPhase(Base):
    """One phase of a hole section in a well plan template, with its planned days."""

    __tablename__ = "record_template_well_phases"
    __table_args__ = (Index("ix_record_template_well_phases_section", "section_id", "sort_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    section_id: Mapped[str] = mapped_column(
        ForeignKey("record_template_well_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phase_id: Mapped[str] = mapped_column(String(36), nullable=False)
    phase_code: Mapped[str] = mapped_column(String(60), default="", server_default="", nullable=False)
    phase_name: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    days: Mapped[float] = mapped_column(Numeric(28, 10), default=0, server_default="0", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    section: Mapped[TemplateWellSection] = relationship(back_populates="phases")
