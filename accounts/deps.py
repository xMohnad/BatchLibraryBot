from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

import jwt
from beanie import PydanticObjectId
from fastapi import Cookie, Depends, HTTPException, status
from jwt.exceptions import InvalidTokenError

from accounts.models import Role, User
from config import JWT_ALGORITHM, JWT_SECRET_KEY

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


async def get_current_user(access_token: Annotated[str | None, Cookie()] = None) -> User:
    if not access_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )

    try:
        payload = jwt.decode(access_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except InvalidTokenError as exc:
        raise credentials_exception from exc

    user = await User.get(PydanticObjectId(payload["sub"]))
    if user is None or not user.isActive:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled.")

    return user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role is not Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin privileges required.")
    return user


def require_course_permission(action: Literal["add", "edit"]) -> Callable[..., Awaitable[User]]:
    """Build a dependency gating a `{course_id}` path param behind admin or a per-course grant."""

    async def _check(course_id: PydanticObjectId, user: Annotated[User, Depends(get_current_user)]) -> User:
        allowed = user.can_add(course_id) if action == "add" else user.can_edit(course_id)
        if not allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"You don't have '{action}' permission for this course.")
        return user

    return _check
