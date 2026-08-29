from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from aiogram.exceptions import TelegramBadRequest
from beanie import Document
from pydantic import Field
from pymongo import IndexModel

from api.core.security import generate_registration_code, hash_code
from config import (
    CHANNEL_ID,
    REGISTRATION_CODE_RESEND_COOLDOWN_SECONDS,
    REGISTRATION_CODE_TTL_MINUTES,
    REGISTRATION_MAX_CODE_SENDS,
)
from database.models.user import Gender, User

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import User as TelegramUser

TELEGRAM_VERIFY_LINK = "https://t.me/{username}?start=reg_{token}"


class PendingRegistration(Document):
    """Temporary registration record awaiting Telegram verification."""

    token: str
    """Unique, URL-safe token used in the bot deep link."""

    username: str
    """Desired username."""

    passwordHash: str
    """Hashed password."""

    fullName: str
    """User full name."""

    gender: Gender
    """User gender."""

    telegramId: int | None = None
    """Telegram user ID after verification."""

    telegramUsername: str | None = None
    """Telegram @username after verification."""

    codeHash: str | None = None
    """Hashed verification code."""

    codeExpiresAt: datetime | None = None
    """Verification code expiration time."""

    codeAttempts: int = 0
    """Number of entered code attempts."""

    codeSendCount: int = 0
    """Number of times code was sent."""

    lastCodeSentAt: datetime | None = None
    """Last code send timestamp."""

    createdAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Creation time (UTC)."""

    expiresAt: datetime
    """Overall expiration time (TTL)."""

    class Settings:
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("token", 1)], unique=True),
            IndexModel([("expiresAt", 1)], expireAfterSeconds=0),
        ]

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expiresAt

    @property
    def code_is_expired(self) -> bool:
        return self.codeExpiresAt is None or datetime.now(UTC) >= self.codeExpiresAt

    @property
    def is_in_cooldown(self) -> bool:
        """Return True if resend cooldown has not passed yet."""
        return (
            self.lastCodeSentAt is not None
            and (datetime.now(UTC) - self.lastCodeSentAt).total_seconds() < REGISTRATION_CODE_RESEND_COOLDOWN_SECONDS
        )

    @property
    async def verify_link(self) -> str | None:
        from app.bot import bot

        user = await bot.me()
        return TELEGRAM_VERIFY_LINK.format(username=user.username, token=self.token) if user.username else None

    async def validate_for_telegram(self, *, bot: Bot, telegram_user: TelegramUser) -> str | None:
        # Already registered
        if await User.get_by_telegram_id(telegram_user.id):
            return "حسابك مسجّل بالفعل، يمكنك تسجيل الدخول مباشرة."

        # Token bound to another user
        if self.telegramId is not None and self.telegramId != telegram_user.id:
            return "هذا الرابط مرتبط بحساب مختلف."

        # Channel membership
        try:
            member = await bot.get_chat_member(CHANNEL_ID, telegram_user.id)
        except TelegramBadRequest:
            return "تعذر التحقق من عضويتك، حاول لاحقًا."

        if member.status not in {"creator", "administrator", "member", "restricted"}:
            return "يجب أن تكون عضوًا في قناة الدفعة لإتمام التسجيل."

        # Rate limit (resend cooldown)

        if self.is_in_cooldown:
            return "الرجاء الانتظار قليلًا قبل طلب رمز جديد."

        # Max sends
        if self.codeSendCount >= REGISTRATION_MAX_CODE_SENDS:
            return "تجاوزت الحد الأقصى لطلب رمز التحقق لهذا التسجيل. الرجاء التسجيل من جديد."

        return None

    def issue_code(self, *, telegram_user: TelegramUser) -> str:
        now = datetime.now(UTC)
        code = generate_registration_code()

        self.telegramId = telegram_user.id
        self.telegramUsername = telegram_user.username
        self.codeHash = hash_code(code)
        self.codeExpiresAt = now + timedelta(minutes=REGISTRATION_CODE_TTL_MINUTES)
        self.codeAttempts = 0
        self.codeSendCount += 1
        self.lastCodeSentAt = now

        return code
