from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Iterable

from aiogram import Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.scene import Scene, on
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    PhotoSize,
    ReplyKeyboardRemove,
)
from PIL import Image

from app.database.models import Action, File


class Img2PdfScene(Scene, state="img2pdf"):
    """Scene for converting images to PDF."""

    TMP = Path(tempfile.gettempdir())
    """Temporary directory."""

    PDF_KEYBOARD: InlineKeyboardMarkup = InlineKeyboardMarkup(
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
    """Inline keyboard for image-to-PDF actions."""

    EDIT_KEYBOARD: InlineKeyboardMarkup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ تغيير اسم الملف",
                    callback_data=Action.filename,
                ),
                InlineKeyboardButton(
                    text="📝 تغيير الوصف",
                    callback_data=Action.caption,
                ),
            ]
        ]
    )
    """Inline keyboard for editing generated PDF."""

    async def send_pdf_result(self, message: Message, state: FSMContext, file: File):
        """Send the generated PDF to the user."""
        answer = await message.answer_document(
            BufferedInputFile.from_file(file.filepath, file.filename),
            caption=file.caption,
            reply_markup=self.EDIT_KEYBOARD,
        )

        await self._delete_previous_answer(state)
        await state.update_data(answer=answer, file=file)

    async def _store_images(
        self, state: FSMContext, new_ids: Iterable[str]
    ) -> list[str]:
        """Store image file_ids in state while preserving order."""
        images: list[str] = await state.get_value("images", [])

        for file_id in new_ids:
            if file_id not in images:
                images.append(file_id)

        await state.update_data(images=images)
        return images

    async def _send_status(self, message: Message, state: FSMContext, count: int):
        """Send a status message showing current image count."""
        await self._delete_previous_answer(state)
        answer = await message.answer(
            f"🖼 عدد الصور الحالي: {count}\n\n"
            "💡 ملاحظة: سيتم ترتيب الصور حسب الترتيب الذي أرسلتها به",
            reply_markup=self.PDF_KEYBOARD,
        )
        await state.update_data(answer=answer)

    async def _delete_previous_answer(self, state: FSMContext):
        """Delete the previously sent bot message if it exists."""
        if pre_answer := await state.get_value("answer"):
            await pre_answer.delete()
            await state.update_data(answer=None)

    @on.callback_query.enter()
    @on.message.enter()
    async def on_enter_any(self, event: Message | CallbackQuery, state: FSMContext):
        """Initialize the scene."""
        if message := event.message if isinstance(event, CallbackQuery) else event:
            await state.set_data({})
            answer = await message.answer(
                "قم بإرسال الصور المراد تحويلها إلى PDF.\n\n"
                "💡 ملاحظة: سيتم ترتيب الصور حسب الترتيب الذي أرسلتها به",
                reply_markup=ReplyKeyboardRemove(),
            )
            await state.update_data(answer=answer)

    @on.message(F.photo, F.media_group_id)
    async def on_album(
        self, message: Message, media_events: list[Message], state: FSMContext
    ) -> None:
        """Handle photo albums."""
        new_ids = [event.photo[-1].file_id for event in media_events if event.photo]
        images = await self._store_images(state, new_ids)
        await self._send_status(message, state, len(images))

    @on.message(F.photo.as_("photo"))
    async def on_single_photo(
        self,
        message: Message,
        state: FSMContext,
        photo: list[PhotoSize],
    ) -> None:
        """Handle a single photo."""
        images = await self._store_images(state, [photo[-1].file_id])
        await self._send_status(message, state, len(images))

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

        imgs: list[Path] = []
        for id in stored_images:
            img: Path = self.TMP / id
            if not img.is_file():
                await bot.download(id, img)
            imgs.append(img)

        pdf_path = self.TMP / f"{callback.from_user.id}.pdf"
        pil_images = [Image.open(img).convert("RGB") for img in imgs]
        pil_images[0].save(
            pdf_path,
            format="PDF",
            save_all=True,
            append_images=pil_images[1:],
        )

        await self.send_pdf_result(message, state, File(filepath=pdf_path))

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
