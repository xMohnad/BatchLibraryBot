import hashlib
import re

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultCachedAudio,
    InlineQueryResultCachedDocument,
    InlineQueryResultCachedVideo,
)

from app.database.models.course import Course, MessageType

router = Router()

LIMIT = 20


def get_result_class(message_type: MessageType):
    """Return the correct InlineQueryResult class based on Mess."""
    if MessageType.AUDIO == message_type:
        return InlineQueryResultCachedAudio
    elif MessageType.VIDEO == message_type:
        return InlineQueryResultCachedVideo
    else:
        return InlineQueryResultCachedDocument


@router.inline_query()
async def search_course_files(query: InlineQuery):
    if not (text := query.query.strip()):
        return

    regex_pattern = re.escape(text)

    offset = int(query.offset) if query.offset else 0

    results_data = await Course.aggregate(
        [
            {"$unwind": "$files"},
            {
                "$match": {
                    "$or": [
                        {"courseName": {"$regex": regex_pattern, "$options": "i"}},
                        {"tutorName": {"$regex": regex_pattern, "$options": "i"}},
                        {"files.title": {"$regex": regex_pattern, "$options": "i"}},
                        {
                            "files.originalName": {
                                "$regex": regex_pattern,
                                "$options": "i",
                            }
                        },
                    ]
                }
            },
            {
                "$sort": {
                    "files.title": 1,
                    "files.createdAt": -1,
                }
            },
            {"$skip": offset},
            {"$limit": LIMIT},
            {
                "$project": {
                    "_id": 0,
                    "courseName": 1,
                    "tutorName": 1,
                    "semester": 1,
                    "title": "$files.title",
                    "fileId": "$files.fileId",
                    "fileName": "$files.originalName",
                    "type": "$files.telegramMessageType",
                }
            },
        ]
    ).to_list(length=LIMIT)

    results = []

    for item in results_data:
        file_id = item["fileId"]
        title = item["title"]
        ttype = item["type"]

        results.append(
            get_result_class(ttype)(
                **{
                    "id": hashlib.md5(f"{file_id}:{title}".encode()).hexdigest(),
                    f"{ttype}_file_id": file_id,
                    "title": f"{item.get('courseName')} {title}",
                    "description": (
                        f"{item.get('tutorName')} - الفصل {item.get('semester')} "
                        f"- {item.get('fileName')}"
                    ),
                }
            )
        )

    next_offset = str(offset + LIMIT) if len(results) >= LIMIT else ""

    await query.answer(
        results=results,
        is_personal=False,
        next_offset=next_offset,
    )
