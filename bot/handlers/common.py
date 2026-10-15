from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .. import texts

router = Router()


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message, is_admin: bool) -> None:
    text = texts.HELP + (texts.ADMIN_HELP if is_admin else "")
    await message.answer(text)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Отменять нечего.")
        return
    await state.clear()
    await message.answer("Отменено.")
