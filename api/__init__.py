from fastapi import APIRouter

from .routers import courses, file

router = APIRouter(prefix="/api")


router.include_router(courses.router)
router.include_router(file.router)
