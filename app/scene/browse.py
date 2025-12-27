from __future__ import annotations

from typing import Any, Final

from aiogram import Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.scene import Scene, on
from aiogram.types import KeyboardButton, Message, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from app.data.config import ARCHIVE_CHANNEL
from app.database.models import Action, CourseMaterial

# --- Constants ---
STEPS_CONFIG: Final[list[tuple[str, str]]] = [
    ("level_word", "اختر المستوى:"),
    ("term_word", "اختر الترم:"),
    ("course", "اختر المقرر:"),
    ("title", "اختر المادة:"),
]


class BrowseScene(Scene, state="browse"):
    async def get_materials(self, state: FSMContext) -> list[CourseMaterial]:
        """Load all needed data once, and reuse it in all next steps."""
        step = await state.get_value("step", 0)
        materials = await state.get_value("materials", 0)

        if step == 0 or materials:
            materials = await CourseMaterial.find().to_list()
            await state.update_data(materials=materials)
            return materials

        return materials

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

    def get_valid_options(
        self,
        materials: list[CourseMaterial],
        answers: dict[str, str],
        field: str,
    ) -> list[str]:
        """
        Return sorted unique values for a field,
        filtered by previously selected answers.
        """
        return sorted(
            {
                getattr(m, field)
                for m in materials
                if all(getattr(m, k) == v for k, v in answers.items())
            }
        )

    @on.message.enter()
    async def on_enter(
        self, message: Message, bot: Bot, state: FSMContext, step: int = 0
    ) -> Any:
        answers = await state.get_value("answers", {})
        materials = await self.get_materials(state)

        # Final step → send files
        if step >= len(STEPS_CONFIG):
            answers = {**answers, "title": message.text}
            files = self.get_valid_options(materials, answers, "message_id")
            return await bot.copy_messages(
                message.chat.id,
                ARCHIVE_CHANNEL,
                files,  # pyright: ignore[reportArgumentType]
                remove_caption=True,
            )

        field, prompt = STEPS_CONFIG[step]
        options = self.get_valid_options(materials, answers, field)

        await message.answer(
            prompt,
            reply_markup=self.build_keyboard(options, step).as_markup(
                resize_keyboard=True
            ),
        )
        await state.update_data(step=step)

    @on.message(F.text.in_({Action.back, Action.restart, Action.exit}))
    async def navigation(self, message: Message, state: FSMContext) -> None:
        text = message.text

        if text == Action.exit:
            return await self.wizard.exit()

        if text == Action.restart:
            await state.update_data(answers={})
            return await self.wizard.retake(step=0)

        # BTN_BACK
        step = await state.get_value("step", 0)

        if step > 0:
            answers = await state.get_value("answers", {})
            prev_field = STEPS_CONFIG[step - 1][0]
            answers.pop(prev_field, None)
            await state.update_data(answers=answers)
            await self.wizard.retake(step=step - 1)

    @on.message(F.text)
    async def answer(self, message: Message, state: FSMContext) -> None:
        step = await state.get_value("step", 0)
        answers = await state.get_value("answers", {})

        materials = await self.get_materials(state)
        field = STEPS_CONFIG[step][0]
        valid_options = self.get_valid_options(materials, answers, field)

        if message.text not in valid_options:
            await self.unknown_message(message)
            return await self.wizard.retake(step=step)

        if step < len(STEPS_CONFIG) - 1:
            answers[field] = message.text

        await state.update_data(answers=answers)
        await self.wizard.retake(step=step + 1)

    @on.message()
    async def unknown_message(self, message: Message) -> None:
        await message.answer("الرجاء اختيار خيار من القائمة فقط.")

    @on.message.exit()
    async def exit(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        if message.text == Action.exit:
            await message.answer("تم الخروج.", reply_markup=ReplyKeyboardRemove())
