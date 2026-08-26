from fastapi import APIRouter

from .routers import courses

router = APIRouter(prefix="/api")


router.include_router(courses.router)
