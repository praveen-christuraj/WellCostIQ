"""Entry checks: what was reviewed, and what each item usually carries.

The entry checks compare a daily cost sheet with its own history and point out
values that look mistyped (ten times the usual quantity, a rate entered the
other way round, a depth shallower than yesterday's). Two small tables support
them:

* ``daily_cost_check_reviews`` records that a user looked at one finding and
  kept the value as entered. The review is tied to the exact value it accepted
  (``fingerprint``), so a later change to that value brings the finding back.
* ``daily_cost_item_profiles`` holds, per workspace and item, the usual value
  and its spread across the workspace's recent sheets. It lets a new well be
  checked against the workspace's own experience from its first sheet. It is a
  summary of the cost ledger, rebuilt from the ledger whenever it is stale,
  and is never authoritative: deleting every row only delays the next check.

Every attribute is an ordinary typed column; nothing is stored as JSON. A
profile never crosses a workspace boundary.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.rig_well import now, uid

# What a profile describes. ``quantity`` is the quantity recorded per sheet,
# ``rate`` is the unit rate a line was priced at.
PROFILE_METRICS = ("quantity", "rate")
PROFILE_SUBJECT_KINDS = ("service", "consumable", "tangible")


class DailyCostCheckReview(Base):
    """A user kept the value behind one entry check as entered."""

    __tablename__ = "daily_cost_check_reviews"
    # One review per finding of a sheet. The constraint's index also serves
    # every read, which is always "the reviews of these sheets".
    __table_args__ = (
        UniqueConstraint("entry_id", "check_key", name="uq_daily_cost_check_reviews_entry_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Reviews belong to their sheet and are removed with it.
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_entries.id", ondelete="CASCADE"), nullable=False
    )
    # Which finding on the sheet: the check code and the item or line it is about.
    check_key: Mapped[str] = mapped_column(String(240), nullable=False)
    check_code: Mapped[str] = mapped_column(String(40), nullable=False)
    # The value that was accepted. A different value is a different finding.
    fingerprint: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_label: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    value_label: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    note: Mapped[str] = mapped_column(String(300), default="", server_default="", nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class DailyCostItemProfile(Base):
    """The usual value of one item across a workspace's recent daily sheets."""

    __tablename__ = "daily_cost_item_profiles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "subject_kind", "subject_id", "variant", "metric", "unit",
            name="uq_daily_cost_item_profiles_subject",
        ),
        Index("ix_daily_cost_item_profiles_org_subject", "organization_id", "subject_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Master Data record id of the service, consumable item or tangible.
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # What distinguishes one way of charging the item from another (a service's
    # charging basis and category, a consumable's catalogue).
    variant: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    metric: Mapped[str] = mapped_column(String(20), nullable=False)
    # Quantity unit for a quantity profile, currency for a rate profile. As wide
    # as the widest unit of measure a cost line can carry.
    unit: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    # Zero means "looked for, nothing recorded yet": it stops the same search
    # from being repeated until the profile goes stale.
    sample_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    well_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    median_value: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    # Robust standard deviation of ln(value).
    spread: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    low_value: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    high_value: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    # The value that keeps recurring, when there is one.
    common_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    last_observed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
