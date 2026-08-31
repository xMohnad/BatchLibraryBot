from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

import cloudinary
import cloudinary.uploader

from config import CLOUDINARY_URL, TMP
from telegram.bot import bot

if TYPE_CHECKING:
    from aiogram import Bot
    from beanie import PydanticObjectId

    from courses.models import Course, CourseFile


logger = logging.getLogger(__name__)

CLOUDINARY_LIMIT = 10 * 1024 * 1024  # 10 MB

TMP_DIR = TMP / "uploads"
TMP_DIR.mkdir(parents=True, exist_ok=True)

_upload_locks: dict[PydanticObjectId, asyncio.Lock] = defaultdict(asyncio.Lock)


async def _upload_file(bot: Bot, folder: str, file: CourseFile) -> bool:
    """Download `file` from Telegram and upload it to Cloudinary."""
    local_path = TMP_DIR / f"{file.archiveTelegramMessageId}.{file.extension}"

    if file.sizeBytes > CLOUDINARY_LIMIT:
        return False

    try:
        await bot.download(file.fileId, local_path)
        result = await asyncio.to_thread(
            cloudinary.uploader.upload,
            str(local_path),
            resource_type="auto",
            folder=folder,
            filename=file.originalName,
            use_filename=True,
            unique_filename=True,
        )

        file.url = result["secure_url"]
        file.publicId = result["public_id"]
        file.resourceType = result["resource_type"]
        return True
    except Exception:
        logger.exception("Failed to upload/download file %s (%s)", file.archiveTelegramMessageId, file.originalName)
        return False
    finally:
        local_path.unlink(missing_ok=True)


async def ensure_files_uploaded(course: Course) -> None:
    """Ensure every file in `course` has been uploaded to Cloudinary."""
    if CLOUDINARY_URL is None:
        logger.warning("Missing CLOUDINARY_URL; uploads to Cloudinary are disabled.")

    if not any(f.url is None for f in course.files):
        return

    assert course.id is not None
    async with _upload_locks[course.id]:
        folder = f"{course.id}"
        # someone else finished uploading while we waited for the lock
        if not (pending := [_upload_file(bot, folder, f) for f in course.files if f.url is None]):
            return

        uploaded = await asyncio.gather(*pending)
        if any(uploaded):
            await course.save()
