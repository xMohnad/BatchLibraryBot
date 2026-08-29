from fastapi import APIRouter

from api.routers import admin, auth, courses

router = APIRouter(prefix="/api")


router.include_router(auth.router)
router.include_router(admin.router)
router.include_router(courses.router)
