from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from .config import Config
from .db import Database


class UserMiddleware(BaseMiddleware):
    """Сохраняет пользователя в базу и передаёт в хендлеры флаг is_admin."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        config: Config = data["config"]
        if user is not None:
            db: Database = data["db"]
            await db.upsert_user(user.id, user.username, user.full_name)
            data["is_admin"] = user.id in config.admin_ids
        else:
            data["is_admin"] = False
        return await handler(event, data)
