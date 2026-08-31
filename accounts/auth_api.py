from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from aiogram.utils.deep_linking import create_start_link
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from accounts.deps import get_current_user
from accounts.models import CoursePermission, Gender, PendingRegistration, Session, User
from config import (
    ACCESS_TOKEN_TTL_MINUTES,
    COOKIE_SECURE,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    LOGIN_LOCKOUT_MINUTES,
    LOGIN_MAX_FAILED_ATTEMPTS,
    REFRESH_TOKEN_TTL_DAYS,
    REGISTRATION_MAX_CODE_ATTEMPTS,
    REGISTRATION_PENDING_TTL_MINUTES,
)
from core.rate_limit import login_limiter, register_limiter, verify_limiter
from core.security import (
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    validate_password_strength,
    verify_code,
    verify_password,
)
from telegram.bot import bot

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.]+$")
    password: str
    fullName: str = Field(min_length=2, max_length=100)
    gender: Gender

    @field_validator("username")
    @classmethod
    def _normalize_username(cls, v: str) -> str:
        return v.strip().lower()


class RegisterResponse(BaseModel):
    registrationToken: str
    botDeepLink: str
    expiresInMinutes: int

    @classmethod
    async def from_pending(cls, pending: PendingRegistration) -> RegisterResponse:
        verify_link = await create_start_link(bot, f"reg_{pending.token}")
        return cls(
            registrationToken=pending.token,
            botDeepLink=verify_link,
            expiresInMinutes=REGISTRATION_PENDING_TTL_MINUTES,
        )


class VerifyRequest(BaseModel):
    registrationToken: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class LoginRequest(BaseModel):
    username: str
    password: str


class UserPublic(BaseModel):
    id: str
    username: str
    fullName: str
    gender: Gender
    role: str
    permissions: list[CoursePermission]

    @classmethod
    def from_user(cls, user: User) -> UserPublic:
        assert user.id is not None
        return cls(
            id=str(user.id),
            username=user.username,
            fullName=user.fullName,
            gender=user.gender,
            role=str(user.role),
            permissions=user.permissions,
        )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _issue_session(response: Response, request: Request, user: User) -> Session:
    assert user.id is not None

    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)
    payload = {"sub": str(user.id), "role": str(user.role), "iat": now, "exp": expires_at}
    access_token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    refresh_token = generate_refresh_token()

    session = await Session(
        userId=user.id,
        refreshTokenHash=hash_refresh_token(refresh_token),
        userAgent=request.headers.get("user-agent"),
        ip=_client_ip(request),
        expiresAt=now + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
    ).insert()

    response.set_cookie(
        "access_token",
        access_token,
        max_age=ACCESS_TOKEN_TTL_MINUTES * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )

    response.set_cookie(
        "refresh_token",
        refresh_token,
        max_age=REFRESH_TOKEN_TTL_DAYS * 24 * 3600,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/api/auth",
    )

    return session


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth")


@router.post("/register", response_model=RegisterResponse)
async def register(payload: RegisterRequest, request: Request) -> RegisterResponse:
    if not register_limiter.hit(_client_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many registration attempts.")

    if error := validate_password_strength(payload.password, username=payload.username):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, error)

    if await User.get_by_username(payload.username):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username is already taken.")

    existing_pending = await PendingRegistration.find_one(PendingRegistration.username == payload.username)
    if existing_pending and not existing_pending.is_expired:
        raise HTTPException(status.HTTP_409_CONFLICT, "This username already has a registration in progress.")

    if existing_pending:
        await existing_pending.delete()

    pending = await PendingRegistration(
        token=secrets.token_urlsafe(24),
        username=payload.username,
        passwordHash=hash_password(payload.password),
        fullName=payload.fullName.strip(),
        gender=payload.gender,
        expiresAt=datetime.now(UTC) + timedelta(minutes=REGISTRATION_PENDING_TTL_MINUTES),
    ).insert()

    return await RegisterResponse.from_pending(pending)


@router.post("/register/verify", response_model=UserPublic)
async def verify_registration(payload: VerifyRequest, request: Request, response: Response) -> UserPublic:
    if not verify_limiter.hit(_client_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again shortly.")

    pending = await PendingRegistration.find_one(PendingRegistration.token == payload.registrationToken)
    if pending is None or pending.is_expired:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Registration link is invalid or has expired.")

    if pending.codeHash is None or pending.code_is_expired:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "No active code for this registration. Request a new one from the bot."
        )

    if pending.codeAttempts >= REGISTRATION_MAX_CODE_ATTEMPTS:
        await pending.delete()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Too many incorrect attempts. Please register again.")

    if not verify_code(payload.code, pending.codeHash):
        pending.codeAttempts += 1
        await pending.save()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect code.")

    if pending.telegramId is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Telegram verification was not completed.")

    if await User.get_by_telegram_id(pending.telegramId):
        await pending.delete()
        raise HTTPException(status.HTTP_409_CONFLICT, "This Telegram account is already registered.")

    user = await User(
        username=pending.username,
        passwordHash=pending.passwordHash,
        fullName=pending.fullName,
        gender=pending.gender,
        telegramId=pending.telegramId,
        telegramUsername=pending.telegramUsername,
    ).insert()

    await pending.delete()
    await _issue_session(response, request, user)
    return UserPublic.from_user(user)


@router.post("/login", response_model=UserPublic)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> UserPublic:
    if not login_limiter.hit(_client_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts. Try again shortly.")

    user = await User.get_by_username(payload.username)

    if user is not None and user.isActive and user.is_locked:
        raise HTTPException(
            status.HTTP_423_LOCKED, "Account temporarily locked due to repeated failed attempts. Try again later."
        )

    valid = verify_password(payload.password, user.passwordHash if user else None)
    if user is None or not valid or not user.isActive:
        if user is not None and user.isActive:
            user.failedLoginAttempts += 1
            if user.failedLoginAttempts >= LOGIN_MAX_FAILED_ATTEMPTS:
                user.lockedUntil = datetime.now(UTC) + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
            await user.save()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password.")

    user.failedLoginAttempts = 0
    user.lockedUntil = None
    await user.save()
    await _issue_session(response, request, user)
    return UserPublic.from_user(user)


@router.post("/refresh")
async def refresh(
    request: Request, response: Response, refresh_token: Annotated[str | None, Cookie()] = None
) -> dict[str, bool]:
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token.")

    token_hash = hash_refresh_token(refresh_token)
    session = await Session.find_one(Session.refreshTokenHash == token_hash)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown session.")

    if session.revoked:
        logger.warning("Refresh token reuse detected for user %s; revoking all sessions.", session.userId)
        await Session.revoke_all_for_user(session.userId)
        clear_auth_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked.")

    if session.expiresAt <= datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired.")

    user = await User.get(session.userId)
    if user is None or not user.isActive:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled.")

    new_session = await _issue_session(response, request, user)
    session.revoked = True
    session.replacedBy = new_session.id
    await session.save()

    return {"ok": True}


@router.post("/logout")
async def logout(response: Response, refresh_token: Annotated[str | None, Cookie()] = None) -> dict[str, bool]:
    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        if session := await Session.find_one(Session.refreshTokenHash == token_hash):
            session.revoked = True
            await session.save()

    clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=UserPublic)
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserPublic:
    return UserPublic.from_user(user)
