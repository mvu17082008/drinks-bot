from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..db import Database

router = Router()


@router.message(Command("deldrink"))
async def cmd_deldrink(message: Message, command: CommandObject, db: Database, is_admin: bool) -> None:
    if not is_admin:
        await message.answer("Эта команда только для админов.")
        return
    if not command.args or not command.args.strip().lstrip("#").isdigit():
        await message.answer("Укажите номер напитка: /deldrink 12 (номер есть в карточке напитка).")
        return
    drink_id = int(command.args.strip().lstrip("#"))
    drink = await db.get_drink(drink_id)
    if drink is None:
        await message.answer("Напиток с таким номером не найден.")
        return
    await db.delete_drink(drink_id)
    await message.answer(f"🗑 Напиток «{escape(drink.name)}» удалён вместе с оценками и отзывами.")


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    await message.answer(
        f"Ваш Telegram id: <code>{message.from_user.id}</code>\n"
        "Чтобы стать админом, добавьте его в ADMIN_IDS в файле .env и перезапустите бота."
    )
