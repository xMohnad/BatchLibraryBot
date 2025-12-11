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


def build_keyboard(
    options: list[str], add_back: bool, add_exit: bool, add_restart: bool = False
) -> ReplyKeyboardBuilder:
    keyboard = ReplyKeyboardBuilder()

    # Each option gets its own row
    for opt in options:
        keyboard.row(KeyboardButton(text=opt))

    # Navigation row at the bottom
    nav_buttons = []

    if add_back:
        nav_buttons.append(KeyboardButton(text="🔙 Back"))

    if add_restart:
        nav_buttons.append(KeyboardButton(text="🔄 Restart"))

    if nav_buttons:
        keyboard.row(*nav_buttons)

    if add_exit:
        keyboard.row(KeyboardButton(text="🚫 Exit"))

    return keyboard


def get_step_options(
    step: int, answers: dict[str, int | str], materials: list[CourseMaterial]
) -> list[str]:
    if step == 0:
        return sorted({m.level_word for m in materials})

    if step == 1:
        return sorted(
            {m.term_word for m in materials if m.level_word == answers.get("level")}
        )

    if step == 2:
        return sorted(
            {
                m.course
                for m in materials
                if m.level_word == answers.get("level")
                and m.term_word == answers.get("term")
            }
        )

    if step == 3:
        return sorted(
            {
                m.title
                for m in materials
                if m.level_word == answers.get("level")
                and m.term_word == answers.get("term")
                and m.course == answers.get("course")
            }
        )

    return []


class BrowseScene(Scene, state="browse"):
    async def get_filtered_materials(
        self, state: FSMContext, step: int
    ) -> list[CourseMaterial]:
        """
        Load all needed data once, and reuse it in all next steps.
        """
        data = await state.get_data()
        if step == 0 or "materials" not in data:
            materials = await CourseMaterial.find().to_list()
            await state.update_data(materials=materials)
            return materials
        return data["materials"]

    async def display_step(
        self, message: Message, state: FSMContext, step: int, answers: dict
    ):
        materials = await self.get_filtered_materials(state, step)

        options = get_step_options(step, answers, materials)
        texts = [
            "اختر المستوى:",
            "اختر الترم:",
            "اختر المقرر:",
            "اختر المادة:",
        ]
        text = texts[step]

        keyboard = build_keyboard(
            options=options,
            add_back=step > 0,
            add_exit=True,
            add_restart=step > 0,
        )

        await message.answer(
            text,
            reply_markup=keyboard.as_markup(resize_keyboard=True),
        )

        await state.update_data(step=step)

    @on.message.enter()
    async def on_enter(
        self, message: Message, bot: Bot, state: FSMContext, step: int = 0
    ) -> Any:
        data = await state.get_data()
        answers = data.get("answers", {})

        if step == 4:
            materials = await self.get_filtered_materials(state, step)
            return await bot.copy_messages(
                message.chat.id,
                ARCHIVE_CHANNEL,
                [
                    m.message_id
                    for m in materials
                    if m.level_word == answers.get("level")
                    and m.term_word == answers.get("term")
                    and m.course == answers.get("course")
                    and m.title == message.text
                ],
                remove_caption=True,
            )

        await self.display_step(message, state, step, answers)

    @on.message(F.text == "🔄 Restart")
    async def restart(self, message: Message) -> None:
        await self.wizard.back(step=0)

    @on.message(F.text == "🔙 Back")
    async def back(self, message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        step = data.get("step", 0)

        if step <= 0:
            return await self.wizard.exit()

        await self.wizard.back(step=step - 1)

    @on.message(F.text == "🚫 Exit")
    @on.message.exit()
    async def exit(self, message: Message) -> None:
        await message.answer(
            "خروج، يمكنك العودة عبر /browse",
            reply_markup=ReplyKeyboardRemove(),
        )

    @on.message(F.text)
    async def answer(self, message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        step = data.get("step", 0)
        answers = data.get("answers", {})

        materials = await self.get_filtered_materials(state, step)
        valid_options = get_step_options(step, answers, materials)

        if message.text not in valid_options:
            await self.unknown_message(message)
            return await self.display_step(message, state, step, answers)

        if step == 0:
            answers["level"] = message.text
        elif step == 1:
            answers["term"] = message.text
        elif step == 2:
            answers["course"] = message.text

        await state.update_data(answers=answers)
        await self.wizard.retake(step=step + 1)

    @on.message()
    async def unknown_message(self, message: Message) -> None:
        await message.answer("الرجاء اختيار خيار من القائمة فقط.")


SceneRegistry(router).add(BrowseScene)
router.message.register(BrowseScene.as_handler(), Command("browse"))


@router.message(CommandStart())
async def start(message: Message, event_from_user: User) -> None:
    await message.answer(
        f"Hello, {html.bold(event_from_user.full_name)}! Use /browse to start browsing.",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
