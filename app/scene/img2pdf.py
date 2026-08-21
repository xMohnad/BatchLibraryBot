from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot, F
from aiogram.fsm.scene import Scene, on
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)
from PIL import Image

from app.config import TMP
from app.scene.models import Action, File

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aiogram.fsm.context import FSMContext


class Img2PdfScene(Scene, state="img2pdf"):
    """Scene for converting images to PDF."""

    PDF_KEYBOARD: InlineKeyboardMarkup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 حذف الكل", callback_data=Action.clear),
                InlineKeyboardButton(text="📄 تحويل إلى PDF", callback_data=Action.convert),
            ]
        ]
    )
    """Inline keyboard for image-to-PDF actions."""

    EDIT_KEYBOARD: InlineKeyboardMarkup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ تغيير اسم الملف", callback_data=Action.filename),
                InlineKeyboardButton(text="📝 تغيير الوصف", callback_data=Action.caption),
            ]
        ]
    )
    """Inline keyboard for editing the generated PDF."""

    async def _respond(
        self,
        message: Message | InaccessibleMessage,
        *,
        text: str | None = None,
        document: BufferedInputFile | None = None,
        caption: str | None = None,
        reply_markup: InlineKeyboardMarkup | ReplyKeyboardRemove | None = None,
    ) -> Message:
        """Delete the previous bot message, send a new one, and store it in state."""
        if pre_answer := await self.wizard.state.get_value("answer"):
            await pre_answer.delete()

        if document is not None:
            answer = await message.answer_document(document, caption=caption, reply_markup=reply_markup)
        else:
            answer = await message.answer(text or "", reply_markup=reply_markup)

        await self.wizard.state.update_data(answer=answer)
        return answer

    async def _store_images(self, new_ids: Iterable[str]) -> list[str]:
        """Append new image file_ids to state while preserving order and uniqueness."""
        images: list[str] = await self.wizard.state.get_value("images", [])

        for file_id in new_ids:
            if file_id not in images:
                images.append(file_id)

        await self.wizard.state.update_data(images=images)
        return images

    async def send_pdf_result(self, message: Message, file: File) -> None:
        """Send the generated PDF to the user and offer editing options."""
        await self._respond(
            message,
            document=BufferedInputFile.from_file(file.filepath, file.filename),
            caption=file.caption,
            reply_markup=self.EDIT_KEYBOARD,
        )
        await self.wizard.state.update_data(file=file)

    @on.callback_query.enter()
    @on.message.enter()
    async def on_enter_any(self, event: InaccessibleMessage | CallbackQuery, state: FSMContext) -> None:
        """Reset scene state and prompt the user to start sending images."""
        message = event.message if isinstance(event, CallbackQuery) else event
        if message is None:
            return

        await state.set_data({})
        text = "📤 أرسل الصور التي تريد تحويلها إلى PDF.\n\n💡 سيتم ترتيبها حسب ترتيب إرسالها."
        await self._respond(message, text=text, reply_markup=ReplyKeyboardRemove())

    @on.message(F.photo)
    async def on_photos(self, message: Message, media_events: list[Message]) -> None:
        """Handle incoming photos."""
        new_ids = [event.photo[-1].file_id for event in media_events if event.photo]
        images = await self._store_images(new_ids)
        text = f"🖼 تم استلام {len(images)} صورة حتى الآن.\n\n💡 سيتم ترتيب الصور حسب ترتيب إرسالها في ملف PDF."
        await self._respond(message, text=text, reply_markup=self.PDF_KEYBOARD)

    @on.callback_query(F.data == Action.clear, F.message.as_("message"))
    async def on_clear(self, callback: CallbackQuery, message: Message) -> None:
        """Clear all stored images and restart the scene."""
        await callback.answer("🗑 تم حذف جميع الصور")
        await message.delete()
        await self.wizard.retake()

    @on.callback_query(F.data == Action.convert, F.message.as_("message"))
    async def on_convert(self, callback: CallbackQuery, message: Message, state: FSMContext, bot: Bot) -> None:
        """Convert all stored images into a single PDF and send it back."""
        stored_images: list[str] = await state.get_value("images", [])
        if not stored_images:
            await callback.answer("❌ لا توجد صور للتحويل")
            return

        await callback.answer("⏳ جاري التحويل...")

        image_paths = [TMP / file_id for file_id in stored_images]
        for file_id, path in zip(stored_images, image_paths, strict=True):
            if not path.exists():
                await bot.download(file_id, path)

        pdf_path = TMP / f"{callback.from_user.id}.pdf"
        images: list[Image.Image] = []
        try:
            for path in image_paths:
                with Image.open(path) as img:
                    images.append(img.convert("RGB"))

            images[0].save(pdf_path, format="PDF", save_all=True, append_images=images[1:])
        finally:
            for path in image_paths:
                path.unlink(missing_ok=True)
            for img in images:
                img.close()

        await self.send_pdf_result(message, File(filepath=pdf_path))

    @on.callback_query(F.data.in_({Action.caption, Action.filename}))
    async def on_edit_request(self, callback: CallbackQuery, state: FSMContext) -> None:
        """Prompt the user for a new filename or caption."""
        action = callback.data
        prompt: str = "أرسل اسم الملف الجديد:" if action == Action.filename else "أرسل الوصف الجديد:"

        if callback.message:
            await callback.message.answer(prompt)

        await state.update_data(edit_mode=action)
        await callback.answer()

    @on.message()
    async def on_edit_input(self, message: Message, state: FSMContext) -> None:
        """Apply the user's filename/caption input while in edit mode."""
        edit_mode: Action | None = await state.get_value("edit_mode")
        file: File | None = await state.get_value("file")

        if not file or not edit_mode:
            return

        if edit_mode == Action.filename:
            file.filename = message.text or file.filename
        elif edit_mode == Action.caption:
            file.caption = message.text or file.caption

        await state.update_data(edit_mode=None)
        await self.send_pdf_result(message, file)
