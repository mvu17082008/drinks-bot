import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .. import texts, tierimage
from ..db import TIERS, Database, TierEntry
from ..keyboards import DrinkCb, TierCb, tier_kb
from .drinks import render_card

router = Router()
log = logging.getLogger(__name__)

# Telegram не принимает фото, у которых ширина + высота больше 10000 точек.
MAX_PHOTO_SIDES = 10000


async def _download(bot: Bot, file_id: str, limit: asyncio.Semaphore) -> bytes | None:
    async with limit:
        try:
            buf = await bot.download(file_id)
            return buf.read() if buf else None
        except Exception:
            log.warning("Не удалось скачать фото %s для тир-листа", file_id, exc_info=True)
            return None


async def send_tier_image(message: Message, bot: Bot, title: str, entries: list[TierEntry]) -> None:
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
    limit = asyncio.Semaphore(8)
    photo_ids = {e.photo_id for e in entries if e.photo_id}
    photos = dict(zip(photo_ids, await asyncio.gather(*(_download(bot, p, limit) for p in photo_ids))))
    tiers: dict[str, list[tierimage.Item]] = {t: [] for t in TIERS}
    for e in entries:
        tiers[e.tier].append(tierimage.Item(e.name, e.score, photos.get(e.photo_id)))
    png, size = await asyncio.to_thread(tierimage.render, title, tiers)
    file = BufferedInputFile(png, filename="tierlist.png")
    caption = f"<b>{escape(title)}</b>"
    if sum(size) > MAX_PHOTO_SIDES:
        # Слишком длинная картинка: файлом Telegram покажет её без сжатия.
        await message.answer_document(file, caption=caption)
    else:
        await message.answer_photo(file, caption=caption)


@router.message(Command("mytier"))
async def cmd_mytier(message: Message, db: Database, bot: Bot) -> None:
    entries = await db.personal_tier_entries(message.from_user.id)
    if not entries:
        await message.answer(
            "<b>📊 Мой тир-лист</b>\n\nПока пусто.\n\n"
            "Откройте напиток через /drinks и нажмите «📊 В мой тир-лист»."
        )
        return
    await send_tier_image(message, bot, "Мой тир-лист", entries)


@router.message(Command("tier"))
async def cmd_tier(message: Message, db: Database, bot: Bot) -> None:
    entries = await db.global_tier_entries()
    if not entries:
        await message.answer("<b>🏆 Общий тир-лист</b>\n\nПока пусто.")
        return
    await send_tier_image(message, bot, "Общий тир-лист", entries)


@router.callback_query(DrinkCb.filter(F.action.in_({"mytier", "gtier"})))
async def cb_choose_tier(call: CallbackQuery, callback_data: DrinkCb, db: Database, is_admin: bool) -> None:
    is_global = callback_data.action == "gtier"
    if is_global and not is_admin:
        await call.answer("Общий тир-лист могут менять только админы.", show_alert=True)
        return
    drink = await db.get_drink(callback_data.drink_id)
    if drink is None:
        await call.answer("Напиток не найден.", show_alert=True)
        return
    title = "🏆 Общий тир-лист" if is_global else "📊 Мой тир-лист"
    await call.message.edit_text(
        f"{title}: куда поставить <b>{escape(drink.name)}</b>?",
        reply_markup=tier_kb(drink.id, "global" if is_global else "my"),
    )
    await call.answer()


@router.callback_query(TierCb.filter())
async def cb_set_tier(call: CallbackQuery, callback_data: TierCb, db: Database, is_admin: bool) -> None:
    tier = None if callback_data.tier == "-" else callback_data.tier
    if tier is not None and tier not in TIERS:
        await call.answer("Неизвестный тир.", show_alert=True)
        return
    if await db.get_drink(callback_data.drink_id) is None:
        await call.answer("Напиток не найден.", show_alert=True)
        return

    if callback_data.scope == "global":
        if not is_admin:
            await call.answer("Общий тир-лист могут менять только админы.", show_alert=True)
            return
        await db.set_global_tier(callback_data.drink_id, tier, call.from_user.id)
        notice = f"Общий тир: {tier}" if tier else "Убрано из общего тир-листа"
    else:
        await db.set_personal_tier(call.from_user.id, callback_data.drink_id, tier)
        notice = f"Ваш тир: {tier}" if tier else "Убрано из вашего тир-листа"

    text, kb = await render_card(db, callback_data.drink_id, call.from_user.id, is_admin)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer(notice)
