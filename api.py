from fastapi import APIRouter

from accounts.admin_api import router as admin_router
from accounts.auth_api import router as auth_router
from courses.api import router as courses_router

router = APIRouter(prefix="/api")

router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(courses_router)
