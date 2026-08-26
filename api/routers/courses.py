from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated

from beanie import PydanticObjectId  # noqa: TC002
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.uploads import ensure_files_uploaded
from database.models.course import Course
from database.models.ordinal import Ordinal

if TYPE_CHECKING:
    from database.models.course import CourseFile

router = APIRouter(prefix="/courses", tags=["courses"])

DEFAULT_SORT = "-createdAt"


class CourseSummary(BaseModel):
    id: str
    courseName: str
    tutorName: str
    level: int
    term: int
    isPractical: bool
    fileCount: int

    @classmethod
    def from_course(cls, course: Course) -> CourseSummary:
        return cls(
            id=str(course.id),
            courseName=course.courseName,
            tutorName=course.tutorName,
            level=Ordinal.current_level(course.semester),
            term=Ordinal.current_term(course.semester),
            isPractical=course.isPractical,
            fileCount=len(course.files),
        )


class CourseListResponse(BaseModel):
    items: list[CourseSummary]
    total: int
    page: int
    pageSize: int


class CourseFileSummary(BaseModel):
    id: int
    title: str
    originalName: str
    mimeType: str
    extension: str
    sizeBytes: int
    url: str | None

    @classmethod
    def from_course_file(cls, file: CourseFile) -> CourseFileSummary:
        return cls(
            id=file.archiveTelegramMessageId,
            title=file.title,
            originalName=file.originalName,
            mimeType=file.mimeType,
            extension=file.extension,
            sizeBytes=file.sizeBytes,
            url=file.url,
        )


class CourseDetail(CourseSummary):
    files: list[CourseFileSummary]

    @classmethod
    def from_course(cls, course: Course) -> CourseDetail:
        summary = CourseSummary.from_course(course)
        sorted_files = sorted(course.files, key=lambda f: f.title)
        return cls(
            **summary.model_dump(),
            files=[CourseFileSummary.from_course_file(f) for f in sorted_files],
        )


@router.get("", response_model=CourseListResponse)
async def list_courses(
    level: Annotated[int | None, Query(ge=1, le=4)] = None,
    term: Annotated[int | None, Query(ge=1, le=2)] = None,
    isPractical: bool | None = None,
    search: Annotated[str | None, Query(min_length=1)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CourseListResponse:
    """List courses, optionally filtered by level/term/isPractical/search.

    If only level or term is provided, the other defaults to the current value.
    """
    query: dict[str, object] = {}

    if level is not None or term is not None:
        semester = Ordinal.to_semester(
            level or Ordinal.current_level(),
            term or Ordinal.current_term(),
        )
        query["semester"] = semester

    if isPractical is not None:
        query["isPractical"] = isPractical

    if search:
        pattern = {"$regex": re.escape(search), "$options": "i"}
        query["$or"] = [
            {"courseName": pattern},
            {"tutorName": pattern},
        ]

    find_query = Course.find(query)
    total = await find_query.count()
    courses = await find_query.sort(DEFAULT_SORT).skip((page - 1) * pageSize).limit(pageSize).to_list()

    items = [CourseSummary.from_course(course) for course in courses]
    return CourseListResponse(items=items, total=total, page=page, pageSize=pageSize)


@router.get("/current", response_model=list[CourseSummary])
async def current_courses() -> list[CourseSummary]:
    """List all courses for the current semester."""
    courses = await Course.find(Course.semester == Ordinal.current_semester()).sort(DEFAULT_SORT).to_list()
    return [CourseSummary.from_course(course) for course in courses]


@router.get("/{course_id}", response_model=CourseDetail)
async def get_course(course_id: PydanticObjectId) -> CourseDetail:
    """Fetch a single course along with its associated files."""
    course = await Course.get(course_id)

    if course is None:
        raise HTTPException(status_code=404, detail="Course not found.")

    await ensure_files_uploaded(course)
    return CourseDetail.from_course(course)
