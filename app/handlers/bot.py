from __future__ import annotations

import io
from typing import Any, BinaryIO

from aiogram import Bot, F, Router, html
from aiogram.dispatcher.event.bases import NextMiddlewareType
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.scene import Scene, on
from aiogram.fsm.scene import SceneRegistry as _SceneRegistry
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    PhotoSize,
    ReplyKeyboardRemove,
    TelegramObject,
    User,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from PIL import Image

from app.data.config import ARCHIVE_CHANNEL
from app.database.models import Action, CourseMaterial, File

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


class Img2PdfScene(Scene, state="img2pdf"):
    async def send_pdf_result(self, message: Message, state: FSMContext, file: File):
        """Send the generated PDF to the user."""
        answer = await message.answer_document(
            BufferedInputFile(file.data, file.filename),
            caption=file.caption,
            reply_markup=self.edit_keyboard(),
        )

        await self.delete_prev(state)
        await state.update_data(answer=answer)

    async def process_images(
        self, message: Message, state: FSMContext, new_file_ids: list[str]
    ):
        """Add new image file_ids to state while preserving order."""
        images: list[str] = await state.get_value("images", [])

        for f_id in new_file_ids:
            if f_id not in images:
                images.append(f_id)

        await state.update_data(images=images)

        answer = await message.answer(
            f"🖼 عدد الصور الحالي: {len(images)}\n\n"
            "💡 ملاحظة: سيتم ترتيب الصور حسب الترتيب الذي أرسلتها به",
            reply_markup=self.pdf_keyboard(),
        )
        await self.delete_prev(state)
        await state.update_data(answer=answer)

    # --- Keyboards ---

    def pdf_keyboard(self) -> InlineKeyboardMarkup:
        """Create inline keyboard for image to PDF actions."""
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑 حذف الكل",
                        callback_data=Action.clear,
                    ),
                    InlineKeyboardButton(
                        text="📄 تحويل إلى PDF",
                        callback_data=Action.convert,
                    ),
                ]
            ]
        )

    def edit_keyboard(self) -> InlineKeyboardMarkup:
        """Build the edit keyboard for the generated PDF."""
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ تغيير اسم الملف", callback_data=Action.filename
                    ),
                    InlineKeyboardButton(
                        text="📝 تغيير الوصف", callback_data=Action.caption
                    ),
                ]
            ]
        )

    async def delete_prev(self, state: FSMContext):
        """Delete the previously sent bot message if it exists."""
        if pre_answer := await state.get_value("answer"):
            await pre_answer.delete()
            await state.update_data(answer=None)

    @on.callback_query.enter()
    @on.message.enter()
    async def on_enter_any(self, event: Message | CallbackQuery, state: FSMContext):
        """Initialize the scene."""
        if message := event.message if isinstance(event, CallbackQuery) else event:
            await state.update_data(images=[])
            answer = await message.answer(
                "قم بإرسال الصور المراد تحويلها إلى PDF.\n\n"
                "💡 ملاحظة: سيتم ترتيب الصور حسب الترتيب الذي أرسلتها به"
            )
            await state.update_data(answer=answer)

    @on.message(F.photo, F.media_group_id)
    async def on_send_group(
        self, message: Message, media_events: list[Message], state: FSMContext
    ):
        """Handle grouped photo messages (albums)."""
        new_ids = [event.photo[-1].file_id for event in media_events if event.photo]
        await self.process_images(message, state, new_ids)

    @on.message(F.photo.as_("photo"))
    async def on_send(
        self, message: Message, state: FSMContext, photo: list[PhotoSize]
    ):
        """Handle a single photo message."""
        await self.process_images(message, state, [photo[-1].file_id])

    @on.callback_query(F.data == Action.clear, F.message.as_("message"))
    async def on_clear(self, callback: CallbackQuery, message: Message):
        """Clear all stored images and restart the scene."""
        await callback.answer("تم حذف جميع الصور")
        await message.delete()
        await self.wizard.retake()

    @on.callback_query(F.data == Action.convert, F.message.as_("message"))
    async def on_convert(
        self, callback: CallbackQuery, message: Message, state: FSMContext, bot: Bot
    ):
        """Convert stored images into a single PDF."""
        stored_images = await state.get_value("images", [])
        if not stored_images:
            return await callback.answer("لا توجد صور للتحويل")

        await callback.answer("يتم التحويل...")

        images_io: list[BinaryIO] = []
        for image_id in stored_images:
            if file := await bot.download(image_id):
                images_io.append(file)

        pdf_buffer = io.BytesIO()
        try:
            pil_images = [Image.open(img).convert("RGB") for img in images_io]
            pil_images[0].save(
                pdf_buffer,
                format="PDF",
                save_all=True,
                append_images=pil_images[1:],
            )
            pdf_buffer.seek(0)
            file = File(data=pdf_buffer.read())

            await self.send_pdf_result(message, state, file)
            await state.update_data(file=file)
            await message.delete()
        finally:
            pdf_buffer.close()
            for img in images_io:
                img.close()

    @on.callback_query(F.data.in_({Action.caption, Action.filename}))
    async def on_edit_request(self, callback: CallbackQuery, state: FSMContext):
        """Enter edit mode for the generated PDF."""
        action = callback.data
        prompt: str = (
            "أرسل اسم الملف الجديد:"
            if action == Action.filename
            else "أرسل الوصف الجديد:"
        )

        if callback.message:
            await callback.message.answer(prompt)

        await state.update_data(edit_mode=action)
        await callback.answer()

    @on.message()
    async def on_edit_input(self, message: Message, state: FSMContext):
        """Handle user input while in edit mode."""
        edit_mode: Action | None = await state.get_value("edit_mode")
        file: File | None = await state.get_value("file")

        if not file or not edit_mode:
            return

        if edit_mode == Action.filename:
            file.filename = message.text or file.filename
        elif edit_mode == Action.caption:
            file.caption = message.text or file.caption

        await self.send_pdf_result(message, state, file)
        await state.update_data(edit_mode=None)


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
            answers = {**data.get("answers", {}), "title": message.text}
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
            await self.wizard.retake(step=0)
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
    async def exit(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        if message.text == BTN_EXIT:
            await message.answer("تم الخروج.", reply_markup=ReplyKeyboardRemove())


class SceneRegistry(_SceneRegistry):
    async def _middleware(
        self,
        handler: NextMiddlewareType[TelegramObject],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # we don't need aiogram Scene handle all events issues/1743
        if "state" in data:
            return await super()._middleware(handler, event, data)

        return await handler(event, data)


registry = SceneRegistry(router)
registry.add(BrowseScene)
registry.add(Img2PdfScene)
router.message.register(BrowseScene.as_handler(), Command("browse"))
router.message.register(Img2PdfScene.as_handler(), Command("img2pdf"))


@router.message(CommandStart())
async def start(message: Message, event_from_user: User) -> None:
    await message.answer(
        f"Hello, {html.bold(event_from_user.full_name)}! Use /browse to start browsing.",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
