from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from beanie import PydanticObjectId  # noqa: TC002
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.deps import require_admin, require_course_permission
from app.services.uploads import ensure_files_uploaded
from core.text_matching import fuzzy_score
from database.models.course import Course
from database.models.ordinal import Ordinal
from database.models.user import User  # noqa: TC001

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


class CourseCreateRequest(BaseModel):
    courseName: str
    tutorName: str
    semester: int
    isPractical: bool


class CourseUpdateRequest(BaseModel):
    courseName: str | None = None
    tutorName: str | None = None
    isPractical: bool | None = None


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


async def _get_course_or_404(course_id: PydanticObjectId) -> Course:
    course = await Course.get(course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found.")
    return course


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

    find_query = Course.find(query)

    if search:
        candidates = await find_query.to_list()
        scored = [
            (score, course)
            for course in candidates
            if (score := fuzzy_score(search, course.courseName, course.tutorName)) is not None
        ]
        scored.sort(key=lambda item: item[0], reverse=True)

        total = len(scored)
        start = (page - 1) * pageSize
        courses = [course for _, course in scored[start : start + pageSize]]
    else:
        total = await find_query.count()
        courses = await find_query.sort(DEFAULT_SORT).skip((page - 1) * pageSize).limit(pageSize).to_list()

    items = [CourseSummary.from_course(course) for course in courses]
    return CourseListResponse(items=items, total=total, page=page, pageSize=pageSize)


@router.post("", response_model=CourseSummary)
async def create_course(payload: CourseCreateRequest, _admin: Annotated[User, Depends(require_admin)]) -> CourseSummary:
    course = Course(
        courseName=payload.courseName.strip(),
        tutorName=payload.tutorName.strip(),
        semester=Ordinal(payload.semester),
        isPractical=payload.isPractical,
    )
    await course.insert()
    return CourseSummary.from_course(course)


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


@router.patch("/{course_id}", response_model=CourseSummary)
async def update_course(
    course_id: PydanticObjectId,
    payload: CourseUpdateRequest,
    _user: Annotated[User, Depends(require_course_permission("edit"))],
) -> CourseSummary:
    course = await _get_course_or_404(course_id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(course, field, value)

    await course.save()
    return CourseSummary.from_course(course)


@router.delete("/{course_id}", status_code=204)
async def delete_course(course_id: PydanticObjectId, _admin: Annotated[User, Depends(require_admin)]) -> None:
    course = await _get_course_or_404(course_id)
    await course.delete()


# TODO: add add_course_file


@router.patch("/{course_id}/files/{file_id}", response_model=CourseFileSummary)
async def rename_course_file(
    course_id: PydanticObjectId,
    file_id: int,
    title: Annotated[str, Query(min_length=1)],
    _user: Annotated[User, Depends(require_course_permission("edit"))],
) -> CourseFileSummary:
    course = await _get_course_or_404(course_id)
    file = course.find_file_by_archive_id(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="File not found on this course.")

    file.title = title
    await course.save()
    return CourseFileSummary.from_course_file(file)


@router.delete("/{course_id}/files/{file_id}", status_code=204)
async def delete_course_file(
    course_id: PydanticObjectId,
    file_id: int,
    _user: Annotated[User, Depends(require_course_permission("edit"))],
) -> None:
    course = await _get_course_or_404(course_id)
    remaining = [f for f in course.files if f.archiveTelegramMessageId != file_id]
    if len(remaining) == len(course.files):
        raise HTTPException(status_code=404, detail="File not found on this course.")

    course.files = remaining
    await course.save()
