"""The in-application guide: its durable memory and the questions it answers.

The assistant is deliberately *not* a general-purpose chatbot. It carries a
constant, curated memory of how this application works — workflows, data-entry
rules, calculation formulas, navigation and the standing conventions — and it
answers from that memory plus the workspace's own data, under the caller's
permissions. Nothing is generated that is not traceable to a memory entry or a
computed figure, so the same question always gives the same, checkable answer.

Every column is typed; there are no JSON blobs, matching the platform's
column-wise storage convention.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import now, uid

MEMORY_CATEGORIES = (
    "workflow", "calculation", "data-entry", "navigation", "faq", "policy",
)


class AssistantMemory(Base):
    """One durable fact the assistant is allowed to reason and answer from.

    ``is_system`` entries are the shipped application memory (seeded per
    workspace, read-only). Workspace entries let an organisation record its own
    conventions — a company-specific approval rule, a naming standard, a
    definition of a cost code — and the assistant cites them the same way.
    """

    __tablename__ = "assistant_memory"
    __table_args__ = (UniqueConstraint("organization_id", "memory_key", name="uq_assistant_memory_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True,
    )
    memory_key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(20), default="faq", nullable=False)
    # Space-separated trigger words, folded to lower case on save.
    keywords: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # One step per line; rendered as a numbered list.
    steps: Mapped[str] = mapped_column(Text, default="", nullable=False)
    route: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    permission: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_by_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class AssistantConversation(Base):
    """A short, user-owned record of what was asked, so follow-ups stay in context.

    The transcript is the user's own; it is tenant-scoped, capped in the service
    layer, and never used to train or infer anything. Only the question, the
    matched memory key and the created time are kept — not the rendered answer,
    which is recomputed from live data on every ask.
    """

    __tablename__ = "assistant_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True,
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    intent: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    memory_key: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    route: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
