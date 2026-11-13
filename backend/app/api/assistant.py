"""In-application guide endpoints.

`assistant:read` opens the guide; `assistant:manage` lets a workspace record its
own memory entries. The guide never answers outside the caller's other
capabilities: it reads the same services the pages do.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.deps import Current, Db, require
from app.schemas.assistant import (
    AssistantAnswer,
    AssistantAskIn,
    AssistantConversationOut,
    AssistantMemoryIn,
    AssistantMemoryOut,
    AssistantMemoryUpdate,
    AssistantOverview,
)
from app.services import assistant as service
from app.services import audit

router = APIRouter(prefix="/assistant", tags=["In-application guide"])


@router.get("/overview", response_model=AssistantOverview)
def overview(db: Db, user: Current) -> AssistantOverview:
    """Whether the guide is available, what is outstanding, and what to ask it."""
    return service.overview(db, user.organization_id, user)


@router.post("/ask", response_model=AssistantAnswer)
def ask(payload: AssistantAskIn, db: Db, user: Current) -> AssistantAnswer:
    """Answer one question from the constant memory and the workspace's own figures."""
    answer = service.ask(
        db, user.organization_id, user, payload.question, route=payload.route,
    )
    db.commit()
    return answer


@router.get("/memory", response_model=list[AssistantMemoryOut])
def list_memory(db: Db, user: Current) -> list[AssistantMemoryOut]:
    """The assistant's memory: shipped application knowledge plus workspace entries."""
    return service.list_memory(db, user.organization_id)


@router.post(
    "/memory", response_model=AssistantMemoryOut, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("assistant:manage"))],
)
def create_memory(
    payload: AssistantMemoryIn, db: Db, user: Current, request: Request,
) -> AssistantMemoryOut:
    """Record a workspace memory entry the assistant must follow."""
    try:
        row = service.create_memory(db, user.organization_id, payload, user)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    audit.record(
        db, organization_id=user.organization_id, action="create", entity_type="assistant_memory",
        actor=user, entity_id=row.id, entity_label=row.title,
        summary=f"Added assistant memory '{row.title}' ({row.category})", request=request,
    )
    db.commit()
    return row


@router.patch(
    "/memory/{memory_id}", response_model=AssistantMemoryOut,
    dependencies=[Depends(require("assistant:manage"))],
)
def update_memory(
    memory_id: str, payload: AssistantMemoryUpdate, db: Db, user: Current, request: Request,
) -> AssistantMemoryOut:
    try:
        row = service.update_memory(db, user.organization_id, memory_id, payload, user)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    audit.record(
        db, organization_id=user.organization_id, action="update", entity_type="assistant_memory",
        actor=user, entity_id=row.id, entity_label=row.title,
        summary=f"Updated assistant memory '{row.title}'", request=request,
    )
    db.commit()
    return row


@router.delete(
    "/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("assistant:manage"))],
)
def delete_memory(memory_id: str, db: Db, user: Current, request: Request) -> None:
    try:
        service.delete_memory(db, user.organization_id, memory_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    audit.record(
        db, organization_id=user.organization_id, action="delete", entity_type="assistant_memory",
        actor=user, entity_id=memory_id, entity_label=memory_id,
        summary="Removed a workspace assistant memory entry", request=request,
    )
    db.commit()


@router.get("/history", response_model=list[AssistantConversationOut])
def history(db: Db, user: Current, limit: int = Query(default=20, ge=1, le=40)) -> list[AssistantConversationOut]:
    """The caller's own recent questions, newest first."""
    return [
        AssistantConversationOut(**row)
        for row in service.conversation_history(db, user.organization_id, user)[:limit]
    ]
