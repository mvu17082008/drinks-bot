from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..db import TIERS, Database
from ..keyboards import DrinkCb, TierCb, tier_kb
from .drinks import render_card

router = Router()


@router.message(Command("mytier"))
async def cmd_mytier(message: Message, db: Database) -> None:
    tiers = await db.personal_tier_list(message.from_user.id)
    text = texts.tier_list("📊 Мой тир-лист", tiers)
    if not any(tiers.values()):
        text += "\n\nОткройте напиток через /drinks и нажмите «📊 В мой тир-лист»."
    await message.answer(texts.truncate(text))


@router.message(Command("tier"))
async def cmd_tier(message: Message, db: Database) -> None:
    tiers = await db.global_tier_list()
    await message.answer(texts.truncate(texts.tier_list("🏆 Общий тир-лист", tiers)))


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
