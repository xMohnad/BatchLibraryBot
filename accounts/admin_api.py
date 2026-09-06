from __future__ import annotations

from typing import Annotated

from beanie import PydanticObjectId  # noqa: TC002
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from accounts.auth_api import MyPermission, my_permissions
from accounts.deps import require_admin
from accounts.models import CoursePermission, Role, Session, User
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
    query: dict[str, object] = {"role": Role.USER}
    if isActive is not None:
        query["isActive"] = isActive

    users = await User.find(query).to_list()

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

    user.isActive = payload.isActive
    await user.save()

    if not payload.isActive:
        await Session.revoke_all_for_user(user_id)

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
    if await Course.get(course_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found.")

    user = await _get_user_or_404(user_id)
    if user.role is Role.ADMIN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admins already have full access; nothing to grant.")

    existing = user.permission_for(course_id)
    if existing:
        existing.canAdd = payload.canAdd
        existing.canEdit = payload.canEdit
    else:
        user.permissions.append(CoursePermission(courseId=course_id, canAdd=payload.canAdd, canEdit=payload.canEdit))

    await user.save()
    return UserSummary.from_user(user)


@router.delete("/users/{user_id}/permissions/{course_id}", response_model=UserSummary)
async def revoke_course_permission(user_id: PydanticObjectId, course_id: PydanticObjectId) -> UserSummary:
    """Remove a user's access to a specific course and return updated summary."""
    user = await _get_user_or_404(user_id)
    user.permissions = [p for p in user.permissions if p.courseId != course_id]
    await user.save()
    return UserSummary.from_user(user)
