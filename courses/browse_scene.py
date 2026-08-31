from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

from aiogram import Bot, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.scene import Scene, on
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from config import ARCHIVE_CHANNEL
from courses.models import Course, CourseType
from courses.ordinal import Ordinal
from telegram.actions import Action

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)


class BrowseScene(Scene, state="browse"):
    """Scene for browsing courses and files, one question at a time.

    Each entry in `STEPS` names an answer key; the matching `_prompt_<key>_selection`
    method returns the prompt text and the options to show for that step. Once every
    step has an answer, the extra "virtual" step triggers `_handle_file_download`.
    """

    STEPS: ClassVar[tuple[str, ...]] = ("level", "term", "type", "course", "file")
    NAVIGATION_ACTIONS: ClassVar[set[Action]] = {Action.back, Action.restart, Action.exit}

    def _step_prompt(self, step_key: str) -> Callable[[dict], Awaitable[tuple[str, list[str]]]]:
        return getattr(self, f"_prompt_{step_key}_selection")

    @staticmethod
    async def _go_back(state: FSMContext, answers: dict) -> None:
        """Drop the most recent answer, returning the user to the previous step."""
        answers.popitem()
        await state.update_data(answers=answers)

    async def _get_matching_courses(self, answers: dict, course_name: str | None = None) -> list[Course]:
        """Resolve semester/type from `answers` and fetch matching courses."""
        semester, is_practical = (
            Ordinal.to_semester(
                Ordinal.get_value(answers["level"]),
                Ordinal.get_value(answers["term"]),
            ),
            answers["type"] == CourseType.PRACTICAL.value,
        )
        return await Course.get_courses(semester, is_practical, course_name)

    def build_keyboard(self, options: list[str], step: int) -> ReplyKeyboardMarkup:
        """Build a reply keyboard with the given options plus navigation buttons."""
        kb = ReplyKeyboardBuilder()

        for opt in options:
            kb.row(KeyboardButton(text=opt))

        if step > 0:
            kb.row(
                KeyboardButton(text=Action.back),
                KeyboardButton(text=Action.restart),
            )

        kb.row(KeyboardButton(text=Action.exit))
        return kb.as_markup(resize_keyboard=True)

    async def _prompt_level_selection(self, _: dict) -> tuple[str, list[str]]:
        return "اختر المستوى:", Ordinal.available_levels()

    async def _prompt_term_selection(self, _: dict) -> tuple[str, list[str]]:
        return "اختر الفصل:", Ordinal.available_terms()

    async def _prompt_type_selection(self, _: dict) -> tuple[str, list[str]]:
        return "اختر النوع:", [option.value for option in CourseType]

    async def _prompt_course_selection(self, answers: dict) -> tuple[str, list[str]]:
        """Return available courses for the chosen level/term/type."""
        courses = await self._get_matching_courses(answers)
        options = [course.courseName for course in courses if course.files]

        if not options:
            return "لم يتم إضافة مواد لهذا الاختيار بعد.", []
        return "اختر المقرر:", options

    async def _prompt_file_selection(self, answers: dict) -> tuple[str, list[str]]:
        """Return available files for the selected course."""
        courses = await self._get_matching_courses(answers, answers["course"])

        if not courses or not courses[0].files:
            return "لا توجد ملفات للمقرر المحدد.", []

        options = {file.title for file in courses[0].files}
        return "اختر المادة:", sorted(options)

    async def _handle_file_download(self, message: Message, bot: Bot, answers: dict) -> None:
        """Send the selected file's messages to the user."""
        course, title = answers["course"], answers["file"]
        courses = await self._get_matching_courses(answers, course)
        if not courses:
            await message.answer("المقرر غير موجود.")
            return

        files = [file for file in courses[0].files if file.title == title]
        if not files:
            await message.answer("الملف غير موجود.")
            return

        try:
            message_ids = [file.archiveTelegramMessageId for file in files]
            await bot.copy_messages(message.chat.id, ARCHIVE_CHANNEL, message_ids, remove_caption=True)
        except TelegramBadRequest:
            logger.exception("Failed to copy files | course=%s | title=%s", course, title)
            await message.answer("حدث خطأ أثناء جلب الملفات. الرجاء المحاولة لاحقاً.")
            lines = ["Details:"] + [
                (
                    f"  [{i}] "
                    f"archiveId={f.archiveTelegramMessageId} | "
                    f"fileId={f.fileId} | "
                    f"src=({f.fromChatId}:{f.originalTelegramMessageId}) | "
                )
                for i, f in enumerate(files, 1)
            ]
            logger.error("\n".join(lines))

    @on.message.enter()
    async def on_enter(self, message: Message, bot: Bot, state: FSMContext) -> None:
        """Show the prompt for the current step, or run the download once all steps are answered."""
        answers = await state.get_value("answers", {})
        step = len(answers)

        if step == len(self.STEPS):
            await self._handle_file_download(message, bot, answers)
            await self._go_back(state, answers)  # let the user pick another file from the same course
            return

        if step > len(self.STEPS):
            logger.warning("Invalid step %d, resetting", step)
            await state.clear()
            return await self.wizard.retake()

        prompt, options = await self._step_prompt(self.STEPS[step])(answers)

        if not options:
            # This answer led to a dead end (e.g. no files for the chosen course) - undo it.
            if step > 0:
                await self._go_back(state, answers)
            await message.answer(prompt)
            return await self.wizard.retake()

        await state.update_data(preoptions=options)
        await message.answer(prompt, reply_markup=self.build_keyboard(options, step))

    @on.message(F.text.in_(NAVIGATION_ACTIONS))
    async def on_navigation(self, message: Message, state: FSMContext) -> None:
        """Handle back / restart / exit actions."""
        text = message.text

        if text == Action.exit:
            return await self.wizard.exit()

        if text == Action.restart:
            await state.clear()
            return await self.wizard.retake()

        # Action.back
        if answers := await state.get_value("answers", {}):
            await self._go_back(state, answers)
            await self.wizard.retake()

    @on.message(F.text.as_("text"))
    async def on_answer(self, message: Message, text: str, state: FSMContext) -> None:
        """Store the user's answer for the current step and move on."""
        answers = await state.get_value("answers", {})
        preoptions = await state.get_value("preoptions", [])
        step = len(answers)

        if step >= len(self.STEPS) or text not in preoptions:
            return await self.on_unknown_message(message)

        answers[self.STEPS[step]] = text
        await state.update_data(answers=answers)
        await self.wizard.retake()

    @on.message()
    async def on_unknown_message(self, message: Message) -> None:
        """Reject free-text input that doesn't match any offered option."""
        await message.answer("الرجاء اختيار خيار من القائمة فقط.")

    @on.message.exit()
    async def on_exit(self, message: Message, state: FSMContext) -> None:
        """Clean up on scene exit."""
        await state.clear()

        if message and message.text == Action.exit:
            await message.answer("تم الخروج.", reply_markup=ReplyKeyboardRemove())
