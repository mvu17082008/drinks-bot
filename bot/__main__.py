import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .config import load_config
from .db import Database
from .handlers import build_router
from .middlewares import UserMiddleware

COMMANDS = [
    BotCommand(command="drinks", description="Все напитки"),
    BotCommand(command="add", description="Добавить напиток"),
    BotCommand(command="search", description="Найти напиток"),
    BotCommand(command="top", description="Лучшие по оценкам"),
    BotCommand(command="mytier", description="Мой тир-лист"),
    BotCommand(command="tier", description="Общий тир-лист"),
    BotCommand(command="help", description="Помощь"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()

    db = Database(config.db_path)
    await db.connect()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(config=config, db=db)
    dp.message.outer_middleware(UserMiddleware())
    dp.callback_query.outer_middleware(UserMiddleware())
    dp.include_router(build_router())

    await bot.set_my_commands(COMMANDS)
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
