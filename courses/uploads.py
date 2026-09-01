from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

import cloudinary.uploader

from config import CLOUDINARY_URL, TMP
from telegram.bot import bot as _default_bot

if TYPE_CHECKING:
    from aiogram import Bot
    from beanie import PydanticObjectId

    from courses.models import Course, CourseFile


logger = logging.getLogger(__name__)

CLOUDINARY_SIZE_LIMIT = 10 * 1024 * 1024  # 10 MB

TMP_DIR = TMP / "uploads"
TMP_DIR.mkdir(parents=True, exist_ok=True)

_upload_locks: dict[PydanticObjectId, asyncio.Lock] = defaultdict(asyncio.Lock)


async def _upload_file(bot: Bot, folder: str, file: CourseFile) -> bool:
    """Download `file` from Telegram and upload it to Cloudinary. Mutates `file` in place on success."""
    if file.sizeBytes > CLOUDINARY_SIZE_LIMIT:
        logger.warning("Skipping %s: exceeds Cloudinary size limit", file.originalName)
        return False

    local_path = TMP_DIR / f"{file.archiveTelegramMessageId}.{file.extension}"

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
    except Exception:
        logger.exception("Failed to upload/download file %s (%s)", file.archiveTelegramMessageId, file.originalName)
        return False
    finally:
        local_path.unlink(missing_ok=True)

    file.url = result["secure_url"]
    file.publicId = result["public_id"]
    file.resourceType = result["resource_type"]
    return True


async def ensure_files_uploaded(course: Course, bot: Bot = _default_bot) -> bool:
    """Ensure every file in `course` has been uploaded to Cloudinary."""
    if CLOUDINARY_URL is None:
        logger.warning("Missing CLOUDINARY_URL; uploads to Cloudinary are disabled.")
        return False

    if not any(f.url is None for f in course.files):
        return False

    assert course.id is not None
    async with _upload_locks[course.id]:
        folder = str(course.id)
        # someone else may have finished uploading while we waited for the lock
        pending_files = [f for f in course.files if f.url is None]
        if not pending_files:
            return False

        results = await asyncio.gather(*(_upload_file(bot, folder, f) for f in pending_files))
        if any(results):
            await course.save()
            return True

        return False
