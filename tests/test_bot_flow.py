"""Прогон бота целиком через Dispatcher без обращения к Telegram."""

import itertools
from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.config import Config
from bot.db import Database
from bot.handlers import build_router
from bot.middlewares import UserMiddleware

ADMIN = User(id=100, is_bot=False, first_name="Админ", username="admin")
USER = User(id=200, is_bot=False, first_name="Вася")

_ids = itertools.count(1)


class FakeSession(BaseSession):
    """Запоминает все запросы к API и отвечает правдоподобными заглушками."""

    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(
                message_id=next(_ids),
                date=datetime.now(),
                chat=Chat(id=method.chat_id or 0, type="private"),
                text=method.text,
            )
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


# Роутеры aiogram можно подключить только к одному диспетчеру, поэтому он общий.
_dp = Dispatcher(config=Config(bot_token="42:TEST", admin_ids=frozenset({ADMIN.id}), db_path=""))
_dp.message.outer_middleware(UserMiddleware())
_dp.callback_query.outer_middleware(UserMiddleware())
_dp.include_router(build_router())


@pytest.fixture
async def env(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    await db.connect()
    _dp["db"] = db
    session = FakeSession()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    yield bot, _dp, session, db
    await db.close()


async def send(env, user: User, text: str) -> list:
    bot, dp, session, _ = env
    session.calls.clear()
    msg = Message(message_id=next(_ids), date=datetime.now(),
                  chat=Chat(id=user.id, type="private"), from_user=user, text=text)
    await dp.feed_update(bot, Update(update_id=next(_ids), message=msg))
    return list(session.calls)


async def press(env, user: User, data: str, message_text: str = "карточка") -> list:
    bot, dp, session, _ = env
    session.calls.clear()
    msg = Message(message_id=next(_ids), date=datetime.now(),
                  chat=Chat(id=user.id, type="private"), text=message_text)
    call = CallbackQuery(id=str(next(_ids)), from_user=user, chat_instance="x",
                         message=msg, data=data)
    await dp.feed_update(bot, Update(update_id=next(_ids), callback_query=call))
    return list(session.calls)


def texts_of(calls) -> str:
    return "\n".join(c.text for c in calls if isinstance(c, (SendMessage, EditMessageText)))


def kb_data(calls) -> list[str]:
    result = []
    for c in calls:
        markup = getattr(c, "reply_markup", None)
        if markup is not None:
            result += [b.callback_data for row in markup.inline_keyboard for b in row]
    return result


async def test_full_flow(env):
    _, _, _, db = env

    assert "Команды" in texts_of(await send(env, USER, "/start"))

    # добавление напитка в два шага
    assert "Как называется" in texts_of(await send(env, USER, "/add"))
    assert "категорию" in texts_of(await send(env, USER, "Добрый Кола"))
    out = await send(env, USER, "газировка")
    assert "Напиток добавлен" in texts_of(out)
    drink = await db.find_drink_by_name("добрый кола")
    assert drink.category == "газировка"
    # обычный пользователь не видит кнопку общего тир-листа
    assert f"d:gtier:{drink.id}:0" not in kb_data(out)

    # дубликат
    await send(env, USER, "/add добрый кола")
    assert "уже есть" in texts_of(await send(env, USER, "/skip"))

    # оценка
    out = await press(env, USER, f"d:rate:{drink.id}:0")
    assert f"s:{drink.id}:10" in kb_data(out)
    out = await press(env, USER, f"s:{drink.id}:9")
    assert "Ваша оценка: 9" in texts_of(out)
    assert any(isinstance(c, AnswerCallbackQuery) and "9/10" in c.text for c in out)

    # отзыв
    await press(env, USER, f"d:review:{drink.id}:0")
    out = await send(env, USER, "Вкусно, но <сладко>")
    assert "Отзыв сохранён" in texts_of(out)
    assert "&lt;сладко&gt;" in texts_of(out)
    assert "Вкусно" in texts_of(await press(env, USER, f"d:reviews:{drink.id}:0"))

    # личный тир-лист
    await press(env, USER, f"d:mytier:{drink.id}:0")
    out = await press(env, USER, f"t:my:{drink.id}:A")
    assert "Ваш тир: A" in texts_of(out)
    assert "<b>A</b>: Добрый Кола" in texts_of(await send(env, USER, "/mytier"))

    # общий тир-лист: пользователю нельзя, админу можно
    out = await press(env, USER, f"t:global:{drink.id}:S")
    assert any(isinstance(c, AnswerCallbackQuery) and c.show_alert for c in out)
    assert await db.get_global_tier(drink.id) is None
    out = await press(env, ADMIN, f"d:open:{drink.id}:0")
    assert f"d:gtier:{drink.id}:0" in kb_data(out)
    await press(env, ADMIN, f"t:global:{drink.id}:S")
    assert "<b>S</b>: Добрый Кола" in texts_of(await send(env, USER, "/tier"))
    # личный тир админа не задет
    assert "Пока пусто" in texts_of(await send(env, ADMIN, "/mytier"))

    # списки и поиск
    assert "Все напитки: 1" in texts_of(await send(env, USER, "/drinks"))
    assert "Найдено: 1" in texts_of(await send(env, USER, "/search ДОБР"))
    assert "9.0/10" in texts_of(await send(env, USER, "/top"))

    # удаление: только админ
    assert "только для админов" in texts_of(await send(env, USER, f"/deldrink {drink.id}"))
    assert "удалён" in texts_of(await send(env, ADMIN, f"/deldrink {drink.id}"))
    assert await db.get_drink(drink.id) is None


async def test_cancel(env):
    await send(env, USER, "/add")
    assert "Отменено" in texts_of(await send(env, USER, "/cancel"))
    assert "Отменять нечего" in texts_of(await send(env, USER, "/cancel"))
