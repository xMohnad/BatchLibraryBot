import hashlib
import re

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultCachedDocument,
)

from app.database.models.course import Course

router = Router()


@router.inline_query()
async def search_course_files(query: InlineQuery):
    if not (text := query.query.strip()):
        return

    regex_pattern = re.escape(text)

    offset = int(query.offset) if query.offset else 0
    limit = 20
    results_data = await Course.aggregate(
        [
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
            {"$unwind": "$files"},
            {
                "$match": {
                    "$or": [
                        {"files.title": {"$regex": regex_pattern, "$options": "i"}},
                        {
                            "files.originalName": {
                                "$regex": regex_pattern,
                                "$options": "i",
                            }
                        },
                        {"courseName": {"$regex": regex_pattern, "$options": "i"}},
                        {"tutorName": {"$regex": regex_pattern, "$options": "i"}},
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
            {"$limit": limit},
            {
                "$project": {
                    "_id": 0,
                    "courseName": 1,
                    "tutorName": 1,
                    "semester": 1,
                    "title": "$files.title",
                    "fileId": "$files.fileId",
                }
            },
        ]
    ).to_list(length=limit)

    results = []

    for item in results_data:
        file_id = item.get("fileId")
        title = item.get("title")
        if not file_id or not title:
            continue

        results.append(
            InlineQueryResultCachedDocument(
                id=hashlib.md5(
                    f"{file_id}:{item.get('courseName')}:{title}".encode()
                ).hexdigest(),
                title=f"{item.get('courseName')} {title}",
                document_file_id=file_id,
                description=f"{item.get('tutorName')} - الفصل {item.get('semester')}",
            )
        )

    next_offset = str(offset + limit) if len(results) >= limit else ""

    await query.answer(
        results=results,
        cache_time=60,
        is_personal=False,
        next_offset=next_offset,
    )
