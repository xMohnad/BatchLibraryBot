from __future__ import annotations

from datetime import datetime
from typing import Annotated

from beanie import PydanticObjectId  # noqa: TC002
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from accounts.auth_api import MyPermission, my_permissions
from accounts.deps import require_admin
from accounts.models import CoursePermission, Role, Session, User
from core.audit import ActionType, Actor, AuditLog, EntityType, FieldChange
from core.text_matching import fuzzy_score
from courses.models import Course

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


async def _get_user_or_404(user_id: PydanticObjectId) -> User:
    user = await User.get(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return user


class UserSummary(BaseModel):
    id: str
    username: str
    fullName: str
    role: Role
    isActive: bool
    permissionCount: int

    @classmethod
    def from_user(cls, user: User) -> UserSummary:
        assert user.id is not None
        return cls(
            id=str(user.id),
            username=user.username,
            fullName=user.fullName,
            role=user.role,
            isActive=user.isActive,
            permissionCount=len(user.permissions),
        )


class GrantPermissionRequest(BaseModel):
    canAdd: bool = False
    canEdit: bool = False


class SetActiveRequest(BaseModel):
    isActive: bool


@router.get("/users", response_model=list[UserSummary])
async def list_users(
    isActive: bool | None = None,
    search: Annotated[str | None, Query(min_length=1)] = None,
) -> list[UserSummary]:
    """Return users with role USER and optional filters."""
    users = await User.list_by_role(Role.USER, is_active=isActive)

    if search:
        scored: list[tuple[float, User]] = []
        for user in users:
            if (score := fuzzy_score(search, user.username, user.fullName)) is not None:
                scored.append((score, user))

        scored.sort(key=lambda item: item[0], reverse=True)
        users = [user for _, user in scored]

    return [UserSummary.from_user(u) for u in users]


@router.patch("/users/{user_id}/active", response_model=UserSummary)
async def set_user_active(user_id: PydanticObjectId, payload: SetActiveRequest) -> UserSummary:
    """Enable/disable an account. Immediately invalidates its ability to log in or refresh."""
    user = await _get_user_or_404(user_id)
    if user.role is Role.ADMIN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot deactivate an admin account through the API.")

    before = {"isActive": user.isActive}
    user.isActive = payload.isActive
    await user.save()

    if not payload.isActive:
        await Session.revoke_all_for_user(user_id)

    if changes := FieldChange.diff(before, user, before.keys()):
        await AuditLog.record(
            action=ActionType.UPDATE,
            entity_type=EntityType.ACCOUNT,
            entity_id=user.id,
            parent_label=user.username,
            changes=changes,
        )
    return UserSummary.from_user(user)


@router.get("/users/{user_id}/permissions", response_model=list[MyPermission])
async def user_permissions(user_id: PydanticObjectId) -> list[MyPermission]:
    """Return the user's per-course permissions with the course details resolved."""
    user = await _get_user_or_404(user_id)
    return await my_permissions(user)


@router.put("/users/{user_id}/permissions/{course_id}", response_model=UserSummary)
async def grant_course_permission(
    user_id: PydanticObjectId,
    course_id: PydanticObjectId,
    payload: GrantPermissionRequest,
) -> UserSummary:
    """Grant (or update) add/edit permission for one course. Upsert semantics."""
    course = await Course.get_cached(course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found.")

    user = await _get_user_or_404(user_id)
    if user.role is Role.ADMIN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admins already have full access; nothing to grant.")

    existing = user.permission_for(course_id)
    before = existing.model_copy() if existing else None

    if existing:
        existing.canAdd = payload.canAdd
        existing.canEdit = payload.canEdit
    else:
        user.permissions.append(CoursePermission(courseId=course_id, canAdd=payload.canAdd, canEdit=payload.canEdit))

    await user.save()

    after = user.permission_for(course_id)
    if changes := FieldChange.diff(before, after, ["canAdd", "canEdit"]):
        await AuditLog.record(
            action=ActionType.CREATE if existing is None else ActionType.UPDATE,
            entity_type=EntityType.PERMISSION,
            entity_id=course_id,
            parent_id=user.id,
            parent_label=user.username,
            changes=changes,
        )
    return UserSummary.from_user(user)


@router.delete("/users/{user_id}/permissions/{course_id}", response_model=UserSummary)
async def revoke_course_permission(user_id: PydanticObjectId, course_id: PydanticObjectId) -> UserSummary:
    """Remove a user's access to a specific course and return updated summary."""
    user = await _get_user_or_404(user_id)
    existing = user.permission_for(course_id)
    user.permissions = [p for p in user.permissions if p.courseId != course_id]
    await user.save()

    if existing:
        await AuditLog.record(
            action=ActionType.DELETE,
            entity_type=EntityType.PERMISSION,
            entity_id=course_id,
            parent_id=user.id,
            parent_label=user.username,
            changes=FieldChange.diff(existing, None, ["canAdd", "canEdit"]),
        )

    return UserSummary.from_user(user)


class AuditLogSummary(BaseModel):
    id: str
    action: ActionType
    entityType: EntityType
    actor: Actor
    entityId: str | None
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


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    entityType: EntityType | None = None,
    action: ActionType | None = None,
    relatedId: str | None = None,
    userId: PydanticObjectId | None = None,
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

    find_query = AuditLog.find(query)
    total = await find_query.count()
    logs = await find_query.sort("-createdAt").skip((page - 1) * pageSize).limit(pageSize).to_list()

    return AuditLogListResponse(
        items=[AuditLogSummary.from_log(log) for log in logs],
        total=total,
        page=page,
        pageSize=pageSize,
    )
