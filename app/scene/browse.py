from __future__ import annotations

from typing import Any

from aiogram import Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.scene import Scene, SceneWizard, on
from aiogram.types import KeyboardButton, Message, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from async_lru import alru_cache

from app.data.config import ARCHIVE_CHANNEL
from app.database.models import Action
from app.database.models.course import Course, CourseType
from app.utils import (
    WORDS,
    get_available_levels,
    get_available_terms,
    logger,
    to_semester,
)


class BrowseScene(Scene, state="browse"):
    """Scene for browsing courses and files."""

    def __init__(self, wizard: SceneWizard) -> None:
        super().__init__(wizard)
        # Step handlers mapping
        self.STEP_HANDLERS = [
            ("level", self._prompt_level_selection),
            ("term", self._prompt_term_selection),
            ("type", self._prompt_type_selection),
            ("course", self._prompt_courses_selection),
            ("file", self._prompt_files_selection),
        ]

    # Navigation actions
    NAVIGATION_ACTIONS = {Action.back, Action.restart, Action.exit}

    @staticmethod
    def get_semester_and_type(answers: dict) -> tuple[int, bool]:
        """Convert user's answers to semester and practical flag."""
        semester = to_semester(
            WORDS[answers["level"]],
            WORDS[answers["term"]],
        )
        is_practical = answers["type"] == CourseType.PRACTICAL.value
        return semester, is_practical

    @alru_cache(maxsize=128)
    async def get_courses(
        self,
        semester: int,
        is_practical: bool,
        course_name: str | None = None,
    ) -> list[Course]:
        """Fetch courses with caching."""
        query = {Course.semester: semester, Course.isPractical: is_practical}
        if course_name:
            query[Course.courseName] = course_name.strip()

        return await Course.find(query).to_list()

    def build_keyboard(self, options: list[str], step: int) -> ReplyKeyboardBuilder:
        """Build reply keyboard with options and navigation buttons."""
        kb = ReplyKeyboardBuilder()

        for opt in options:
            kb.row(KeyboardButton(text=opt))

        if step > 0:
            kb.row(
                KeyboardButton(text=Action.back),
                KeyboardButton(text=Action.restart),
            )

        kb.row(KeyboardButton(text=Action.exit))
        return kb

    async def _prompt_level_selection(self, _: dict) -> tuple[str, list[str]]:
        return "اختر المستوى:", get_available_levels()

    async def _prompt_term_selection(self, _: dict) -> tuple[str, list[str]]:
        return "اختر الفصل:", get_available_terms()

    async def _prompt_type_selection(self, _: dict) -> tuple[str, list[str]]:
        return "اختر النوع:", [option.value for option in CourseType]

    async def _prompt_courses_selection(self, answers: dict) -> tuple[str, list[str]]:
        """Return available courses for selection."""
        semester, is_practical = self.get_semester_and_type(answers)
        courses = await self.get_courses(semester, is_practical)

        if not courses:
            return "لم يتم إضافة مواد لهذا الاختيار بعد.", []

        options = [f"{course.courseName}" for course in courses]
        return "اختر المقرر:", options

    async def _prompt_files_selection(self, answers: dict) -> tuple[str, list[str]]:
        """Return available files for the selected course."""
        semester, is_practical = self.get_semester_and_type(answers)
        selected_course = answers["course"]

        courses = await self.get_courses(semester, is_practical, selected_course)
        if not courses or not courses[0].files:
            return "لا توجد ملفات للمقرر المحدد.", []

        options = [file.title for file in courses[0].files]
        return "اختر المادة:", options

    async def _handle_file_download(
        self, message: Message, bot: Bot, state: FSMContext, answers: dict
    ) -> Any:
        """Handle file download process."""
        semester, is_practical = self.get_semester_and_type(answers)
        selected_course = answers["course"]
        selected_title = answers["file"]

        try:
            courses = await self.get_courses(semester, is_practical, selected_course)
            if not courses:
                await message.answer("المقرر غير موجود.")
                return

            # Find the specific file
            file_ids = []
            for file in courses[0].files:
                if file.title == selected_title:
                    file_ids.append(file.archiveTelegramMessageId)
                    break

            if not file_ids:
                await message.answer("الملف غير موجود.")
                return

            # Send files
            await bot.copy_messages(
                message.chat.id,
                ARCHIVE_CHANNEL,
                file_ids,
                remove_caption=True,
            )

        except Exception as e:
            logger.exception("خطأ أثناء جلب الملفات: %s", e)
            await message.answer("حدث خطأ أثناء جلب الملفات. الرجاء المحاولة لاحقاً.")

    @on.message.enter()
    async def on_enter(self, message: Message, bot: Bot, state: FSMContext) -> Any:
        """Handle scene entry and step progression."""
        answers = await state.get_value("answers", {})
        step = len(answers)

        # Handle file download (final step)
        if step == len(self.STEP_HANDLERS):
            await self._handle_file_download(message, bot, state, answers)
            answers.popitem()
            await state.update_data(answers=answers)
            return

        # Validate step
        if step >= len(self.STEP_HANDLERS):
            logger.warning(f"Invalid step {step}, resetting")
            await state.clear()
            return await self.wizard.retake()

        # Get current step handler
        _, handler = self.STEP_HANDLERS[step]
        prompt, options = await handler(answers)

        # Handle empty options
        if not options:
            if step > 0:
                answers.popitem()
                await state.update_data(answers=answers)
            await message.answer(prompt)
            await self.wizard.retake()
            return

        # Store options and show keyboard
        await state.update_data(preoptions=options)

        await message.answer(
            prompt,
            reply_markup=self.build_keyboard(options, step).as_markup(
                resize_keyboard=True
            ),
        )

    @on.message(F.text.in_(NAVIGATION_ACTIONS))
    async def navigation(self, message: Message, state: FSMContext) -> None:
        """Handle navigatioN actions."""
        text = message.text

        if text == Action.exit:
            return await self.wizard.exit()

        if text == Action.restart:
            await state.clear()
            self.get_courses.cache_clear()
            return await self.wizard.retake()

        # BTN_BACK
        if answers := await state.get_value("answers", {}):
            answers.popitem()
            await state.update_data(answers=answers)
            await self.wizard.retake()

    @on.message(F.text.as_("text"))
    async def answer(self, message: Message, text: str, state: FSMContext) -> None:
        """Process user's answer."""
        answers = await state.get_value("answers", {})
        preoptions = await state.get_value("preoptions", [])
        step = len(answers)

        # Validate input
        if step >= len(self.STEP_HANDLERS) or text not in preoptions:
            return await self.unknown_message(message)

        # Store answer
        step_key, _ = self.STEP_HANDLERS[step]
        answers[step_key] = text
        await state.update_data(answers=answers)

        # Move to next step
        await self.wizard.retake()

    @on.message()
    async def unknown_message(self, message: Message) -> None:
        """Handle unknown messages."""
        await message.answer("الرجاء اختيار خيار من القائمة فقط.")

    @on.message.exit()
    async def exit(self, message: Message, state: FSMContext) -> None:
        """Clean up on scene exit."""
        await state.clear()
        self.get_courses.cache_clear()

        if message and message.text == Action.exit:
            await message.answer("تم الخروج.", reply_markup=ReplyKeyboardRemove())
