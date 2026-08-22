from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from beanie.operators import ElemMatch
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.bot import bot
from config import TMP
from database.models.course import Course, CourseFile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/file", tags=["file"])

MAX_SIZE = 20 * 1024 * 1024  # 20 MB - the standard Bot API's download limit
ARCHIVE_DIR = TMP / "files"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

_download_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


async def _find_file(message_id: int) -> CourseFile:
    """Find a course file by its archive message id, or raise 404."""
    course = await Course.find_one(ElemMatch(Course.files, {"archiveTelegramMessageId": message_id}))
    if course and (file := course.find_file_by_archive_id(message_id)):
        return file

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found.")


@router.get("/{file_id}/{file_name}")
async def download_file(file_id: int, file_name: str) -> FileResponse:
    """Stream a file from Telegram's archive to the client.

    `file_name` in the path is purely cosmetic (nice, shareable URLs and a
    sensible browser-suggested filename) - it is never used to build a
    filesystem path or to decide what gets served. The file served is always
    resolved strictly from `file_id` against the database.
    """
    file = await _find_file(file_id)
    path = ARCHIVE_DIR / f"{file.archiveTelegramMessageId}.{file.extension}"

    if not path.is_file():
        if file.sizeBytes > MAX_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File is too large (max 20MB).",
            )

        async with _download_locks[file_id]:
            if not path.is_file():  # re-check: another request may have finished downloading while we waited
                tmp_path = path.with_suffix(f"{path.suffix}.part")
                try:
                    await bot.download(file.fileId, tmp_path)
                except Exception as e:
                    logger.exception("Failed to download file from Telegram (message_id=%d)", file_id)
                    tmp_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Failed to fetch the file.",
                    ) from e

                tmp_path.rename(path)  # atomic on the same filesystem - no other request can see a partial file

    return FileResponse(path, filename=file.originalName, media_type=file.mimeType)
