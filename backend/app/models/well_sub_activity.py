"""Tenant-scoped well sub activities.

A sub activity belongs to one well and one configuration scope (drilling or
completion) and references an active Activity from the workspace's Master Data
register. Its code is unique within that well and scope.

The responsible party is a Master Data **vendor** whenever the workspace has one
to name: ``vendor_id`` carries the link and ``responsible_party`` keeps the
vendor's own name as a snapshot, so sub activity reports, search and the
daily-cost drill-through read the same column whether the party was picked from
the vendor register or typed for a company that is not a vendor.
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.master_data import Activity
from app.models.rig_well import Well
from app.models.vendor_master import Vendor


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


# Where the responsible party came from, so the register can tell a tracked
# vendor from a hand-typed company name.
RESPONSIBLE_PARTY_SOURCES = ("vendor", "manual", "import")


class WellSubActivity(Base):
    """A well-and-scope task classified under a Master Data Activity."""

    __tablename__ = "well_sub_activities"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "well_id",
            "scope",
            "sub_activity_code",
            name="uq_well_sub_activities_org_well_code",
        ),
        CheckConstraint("scope IN ('drilling', 'completion')", name="ck_well_sub_activities_scope"),
        CheckConstraint(
            "responsible_party_source IN ('vendor', 'manual', 'import')",
            name="ck_well_sub_activities_party_source",
        ),
        Index("ix_well_sub_activities_org_deleted", "organization_id", "is_deleted"),
        Index("ix_well_sub_activities_org_activity", "organization_id", "activity_id"),
        Index("ix_well_sub_activities_well_scope", "organization_id", "well_id", "scope"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    well_id: Mapped[str] = mapped_column(
        ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(
        String(20), default="drilling", server_default="drilling", nullable=False
    )
    sub_activity_code: Mapped[str] = mapped_column(String(50), nullable=False)
    sub_activity_name: Mapped[str] = mapped_column(String(150), nullable=False)
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("activities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    responsible_party: Mapped[str] = mapped_column(String(200), nullable=False)
    # Master Data vendor behind the responsible party. SET NULL keeps a removed
    # vendor from erasing who performs the work: the name and code stay on the row.
    vendor_id: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vendor_code_snapshot: Mapped[str] = mapped_column(
        String(50), default="", server_default="", nullable=False
    )
    responsible_party_source: Mapped[str] = mapped_column(
        String(20), default="manual", server_default="manual", nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )

    well: Mapped[Well] = relationship(back_populates="sub_activities", lazy="joined")
    activity: Mapped[Activity] = relationship(lazy="joined")
    vendor: Mapped[Vendor | None] = relationship(lazy="joined", passive_deletes=True)
