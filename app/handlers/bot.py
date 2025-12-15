from __future__ import annotations

from typing import Any

from aiogram import Bot, F, Router, html
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.scene import Scene, SceneRegistry, on
from aiogram.types import KeyboardButton, Message, ReplyKeyboardRemove, User
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from app.data.config import ARCHIVE_CHANNEL
from app.database.models.course import CourseMaterial

router = Router(name=__name__)
router.message.filter(F.chat.type == "private")

# --- Constants & Config ---
BTN_BACK = "🔙 Back"
BTN_RESTART = "🔄 Restart"
BTN_EXIT = "🚫 Exit"

STEPS_CONFIG = [
    ("level_word", "اختر المستوى:"),
    ("term_word", "اختر الترم:"),
    ("course", "اختر المقرر:"),
    ("title", "اختر المادة:"),
]


class BrowseScene(Scene, state="browse"):
    async def get_materials(self, state: FSMContext) -> list[CourseMaterial]:
        """Load all needed data once, and reuse it in all next steps."""
        data = await state.get_data()
        step = data.get("step", 0)

        if step == 0 or "materials" not in data:
            materials = await CourseMaterial.find().to_list()
            await state.update_data(materials=materials)
            return materials
        return data["materials"]

    def build_keyboard(self, options: list[str], step: int) -> ReplyKeyboardBuilder:
        kb = ReplyKeyboardBuilder()
        for opt in options:
            kb.row(KeyboardButton(text=opt))

        navs = []
        if step > 0:
            navs.extend(
                [KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_RESTART)]
            )
        kb.row(*navs)
        kb.row(KeyboardButton(text=BTN_EXIT))
        return kb

    def get_valid_options(
        self, materials: list, answers: dict, current_field: str
    ) -> list[str | int]:
        return sorted(
            {
                getattr(m, current_field)
                for m in materials
                if all(getattr(m, key) == val for key, val in answers.items())
            }
        )

    @on.message.enter()
    async def on_enter(
        self, message: Message, bot: Bot, state: FSMContext, step: int = 0
    ) -> Any:
        data = await state.get_data()
        answers = data.get("answers", {})
        materials = await self.get_materials(state)

        if step >= len(STEPS_CONFIG):
            final_files: list[int] = self.get_valid_options(  # pyright: ignore[reportAssignmentType]
                materials, answers, "message_id"
            )
            return await bot.copy_messages(
                message.chat.id, ARCHIVE_CHANNEL, final_files, remove_caption=True
            )

        field_name, prompt_text = STEPS_CONFIG[step]
        options: list[str] = self.get_valid_options(materials, answers, field_name)  # pyright: ignore[reportAssignmentType]
        await message.answer(
            prompt_text,
            reply_markup=self.build_keyboard(options, step).as_markup(
                resize_keyboard=True
            ),
        )
        await state.update_data(step=step)

    @on.message(F.text.in_({BTN_BACK, BTN_RESTART, BTN_EXIT}))
    async def navigation(self, message: Message, state: FSMContext) -> None:
        text = message.text
        if text == BTN_EXIT:
            await self.wizard.exit()
        elif text == BTN_RESTART:
            await state.update_data(answers={})
            await self.wizard.back(step=0)
        elif text == BTN_BACK:
            data = await state.get_data()
            step = data.get("step", 0)

            if step > 0:
                answers: dict[str, str] = data.get("answers", {})
                prev_field = STEPS_CONFIG[step - 1][0]
                answers.pop(prev_field, None)
                await state.update_data(answers=answers)

            await self.wizard.back(step=step - 1)

    @on.message(F.text)
    async def answer(self, message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        step = data.get("step", 0)
        answers = data.get("answers", {})

        materials = await self.get_materials(state)
        current_field = STEPS_CONFIG[step][0]
        valid_options = self.get_valid_options(materials, answers, current_field)

        if message.text not in valid_options:
            await self.unknown_message(message)
            return await self.wizard.retake(step=step)

        if current_field != STEPS_CONFIG[3][0]:
            answers[current_field] = message.text

        await state.update_data(answers=answers)
        await self.wizard.retake(step=step + 1)

    @on.message()
    async def unknown_message(self, message: Message) -> None:
        await message.answer("الرجاء اختيار خيار من القائمة فقط.")

    @on.message.exit()
    async def exit(self, message: Message) -> None:
        await message.answer("تم الخروج.", reply_markup=ReplyKeyboardRemove())


SceneRegistry(router).add(BrowseScene)
router.message.register(BrowseScene.as_handler(), Command("browse"))


@router.message(CommandStart())
async def start(message: Message, event_from_user: User) -> None:
    await message.answer(
        f"Hello, {html.bold(event_from_user.full_name)}! Use /browse to start browsing.",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
