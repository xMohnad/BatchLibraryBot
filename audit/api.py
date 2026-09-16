from __future__ import annotations

from datetime import datetime
from typing import Annotated

from beanie import PydanticObjectId  # noqa: TC002
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from accounts.deps import require_admin
from audit.models import ActionType, Actor, AuditLog, EntityType, FieldChange

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(require_admin)],
)


class AuditLogSummary(BaseModel):
    id: str
    action: ActionType
    entityType: EntityType
    actor: Actor
    entityId: str
    entityLabel: str | None
    parentId: str | None
    parentLabel: str | None
    changes: list[FieldChange]
    createdAt: datetime

    @classmethod
    def from_log(cls, log: AuditLog) -> AuditLogSummary:
        assert log.id is not None
        return cls(
            id=str(log.id),
            action=log.action,
            entityType=log.entityType,
            actor=log.actor,
            entityId=log.entityId,
            entityLabel=log.entityLabel,
            parentId=log.parentId,
            parentLabel=log.parentLabel,
            changes=log.changes,
            createdAt=log.createdAt,
        )


class AuditLogListResponse(BaseModel):
    items: list[AuditLogSummary]
    total: int
    page: int
    pageSize: int


@router.get("/logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    entityType: EntityType | None = None,
    action: ActionType | None = None,
    relatedId: str | None = None,
    userId: PydanticObjectId | None = None,
    dateFrom: datetime | None = None,
    dateTo: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditLogListResponse:
    """List audit-trail entries (who added/edited/deleted what), newest first."""
    query: dict[str, object] = {}
    if entityType is not None:
        query[AuditLog.entityType] = entityType
    if action is not None:
        query[AuditLog.action] = action
    if relatedId is not None:
        query["$or"] = [{AuditLog.entityId: relatedId}, {AuditLog.parentId: relatedId}]
    if userId is not None:
        query["actor.userId"] = userId
    if dateFrom is not None or dateTo is not None:
        date_filter: dict[str, datetime] = {}
        if dateFrom is not None:
            date_filter["$gte"] = dateFrom
        if dateTo is not None:
            date_filter["$lte"] = dateTo
        query["createdAt"] = date_filter

    find_query = AuditLog.find(query)
    total = await find_query.count()
    logs = await find_query.sort("-createdAt").skip((page - 1) * pageSize).limit(pageSize).to_list()

    return AuditLogListResponse(
        items=[AuditLogSummary.from_log(log) for log in logs],
        total=total,
        page=page,
        pageSize=pageSize,
    )
