"""Wire shapes for the in-application guide."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MemoryCategory = Literal["workflow", "calculation", "data-entry", "navigation", "faq", "policy"]
Confidence = Literal["high", "medium", "low"]


class AssistantFact(BaseModel):
    """One checkable figure or finding, shown as a labelled row."""

    label: str
    value: str
    hint: str = ""
    route: str = ""
    permission: str = ""


class AssistantSource(BaseModel):
    """Where the answer comes from, as a page the user can open."""

    label: str
    route: str


class AssistantAnswer(BaseModel):
    """One answer: a sentence or two, the facts behind it, and where to go next."""

    answer: str
    intent: str
    confidence: Confidence
    category: MemoryCategory = "faq"
    memory_key: str = ""
    facts: list[AssistantFact] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    sources: list[AssistantSource] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)


class AssistantAskIn(BaseModel):
    """One question, optionally carrying the page the user is looking at."""

    question: str = Field(min_length=1, max_length=500)
    route: str = Field(default="", max_length=200)


class AssistantMemoryOut(BaseModel):
    id: str
    memory_key: str
    title: str
    category: MemoryCategory
    keywords: str
    body: str
    steps: list[str]
    route: str
    permission: str
    is_system: bool
    is_active: bool
    sort_order: int
    created_by_name: str
    updated_at: datetime


class AssistantMemoryIn(BaseModel):
    """A workspace memory entry: the assistant's constant, local knowledge."""

    title: str = Field(min_length=3, max_length=180)
    category: MemoryCategory = "faq"
    memory_key: str = Field(default="", max_length=80)
    keywords: str = Field(default="", max_length=400)
    body: str = Field(min_length=10, max_length=4000)
    steps: list[str] = Field(default_factory=list)
    route: str = Field(default="", max_length=200)
    permission: str = Field(default="", max_length=80)
    is_active: bool = True
    sort_order: int = 200


class AssistantMemoryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=180)
    category: MemoryCategory | None = None
    keywords: str | None = Field(default=None, max_length=400)
    body: str | None = Field(default=None, min_length=10, max_length=4000)
    steps: list[str] | None = None
    route: str | None = Field(default=None, max_length=200)
    permission: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None
    sort_order: int | None = None


class AssistantConversationOut(BaseModel):
    question: str
    intent: str
    memory_key: str
    route: str
    created_at: datetime


class AssistantOverview(BaseModel):
    enabled: bool
    can_manage: bool
    memory_entries: int
    workspace_entries: int
    outstanding_checks: int
    checks: list[AssistantFact] = Field(default_factory=list)
    quick_prompts: list[str] = Field(default_factory=list)
    recent_questions: list[str] = Field(default_factory=list)
