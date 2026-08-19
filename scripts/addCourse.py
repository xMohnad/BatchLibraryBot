from __future__ import annotations

import asyncio

from beanie import init_beanie

from app.database.base import database
from app.database.models import Ordinal
from app.database.models.course import Course


async def main():
    await init_beanie(
        database=database,
        document_models=[Course],
    )

    print("Starting Adding...")
    await Course(
        courseName="",
        tutorName="",
        semester=Ordinal(3),
        isPractical=True,
        files=[],
    ).insert()

    print("Adding Completed Successfully!")


if __name__ == "__main__":
    asyncio.run(main())
