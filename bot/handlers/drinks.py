from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..db import Database
from ..keyboards import (
    DrinkCb,
    ListCb,
    PhotoCb,
    ScoreCb,
    confirm_kb,
    drink_card_kb,
    drinks_list_kb,
    reviews_kb,
    score_kb,
)

router = Router()

PAGE_SIZE = 10
REVIEWS_PAGE_SIZE = 5
MAX_NAME_LEN = 100
MAX_REVIEW_LEN = 1000


class AddDrink(StatesGroup):
    name = State()
    category = State()


class WriteReview(StatesGroup):
    text = State()
    photo = State()


async def render_card(db: Database, drink_id: int, user_id: int, is_admin: bool):
    drink = await db.get_drink(drink_id)
    if drink is None:
        return None, None
    score, _ = await db.get_user_rating(user_id, drink_id)
    review = await db.get_review(user_id, drink_id)
    text = texts.drink_card(
        drink,
        my_score=score,
        my_review=review.text if review else None,
        my_tier=await db.get_personal_tier(user_id, drink_id),
        global_tier=await db.get_global_tier(drink_id),
        my_photo=bool(review and review.photo_id),
    )
    return text, drink_card_kb(drink_id, is_admin, has_review=review is not None)


async def show_card(message: Message, db: Database, drink_id: int, user_id: int, is_admin: bool) -> None:
    text, kb = await render_card(db, drink_id, user_id, is_admin)
    if text is None:
        await message.answer("Напиток не найден.")
        return
    await message.answer(text, reply_markup=kb)


# --- добавление напитка ---


async def _save_drink(message: Message, state: FSMContext, db: Database, is_admin: bool,
                      name: str, category: str | None) -> None:
    await state.clear()
    drink_id = await db.add_drink(name, category, message.from_user.id)
    if drink_id is None:
        existing = await db.find_drink_by_name(name)
        await message.answer("Такой напиток уже есть 👇")
        if existing:
            await show_card(message, db, existing.id, message.from_user.id, is_admin)
        return
    await message.answer("✅ Напиток добавлен!")
    await show_card(message, db, drink_id, message.from_user.id, is_admin)


@router.message(Command("add"))
async def cmd_add(message: Message, command: CommandObject, state: FSMContext) -> None:
    if command.args:
        await _start_category(message, state, command.args)
        return
    await state.set_state(AddDrink.name)
    await message.answer("Как называется напиток? (/cancel — отмена)")


async def _start_category(message: Message, state: FSMContext, raw_name: str) -> None:
    name = " ".join(raw_name.split())
    if not name or len(name) > MAX_NAME_LEN:
        await message.answer(f"Название должно быть от 1 до {MAX_NAME_LEN} символов. Попробуйте ещё раз.")
        await state.set_state(AddDrink.name)
        return
    await state.update_data(name=name)
    await state.set_state(AddDrink.category)
    await message.answer(
        "Укажите категорию (например: газировка, чай, кофе, энергетик, пиво) "
        "или отправьте /skip, чтобы пропустить."
    )


@router.message(AddDrink.name, F.text, ~F.text.startswith("/"))
async def add_name(message: Message, state: FSMContext) -> None:
    await _start_category(message, state, message.text)


@router.message(AddDrink.category, Command("skip"))
async def add_skip_category(message: Message, state: FSMContext, db: Database, is_admin: bool) -> None:
    data = await state.get_data()
    await _save_drink(message, state, db, is_admin, data["name"], None)


@router.message(AddDrink.category, F.text, ~F.text.startswith("/"))
async def add_category(message: Message, state: FSMContext, db: Database, is_admin: bool) -> None:
    data = await state.get_data()
    category = " ".join(message.text.split())[:50] or None
    await _save_drink(message, state, db, is_admin, data["name"], category)


# --- просмотр ---


async def _list_page(db: Database, page: int):
    total = await db.count_drinks()
    drinks = await db.list_drinks(page * PAGE_SIZE, PAGE_SIZE)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    text = f"🥤 Все напитки: {total}. Страница {page + 1}/{pages}"
    has_next = (page + 1) * PAGE_SIZE < total
    return total, text, drinks_list_kb(drinks, page, has_next)


@router.message(Command("drinks"))
async def cmd_drinks(message: Message, db: Database) -> None:
    total, text, kb = await _list_page(db, 0)
    if not total:
        await message.answer("Напитков пока нет. Добавьте первый через /add")
        return
    await message.answer(text, reply_markup=kb)


@router.callback_query(ListCb.filter())
async def cb_list(call: CallbackQuery, callback_data: ListCb, db: Database) -> None:
    _, text, kb = await _list_page(db, max(0, callback_data.page))
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject, db: Database) -> None:
    if not command.args:
        await message.answer("Напишите, что искать: /search кола")
        return
    found = await db.search_drinks(command.args.strip())
    if not found:
        await message.answer("Ничего не нашлось. Можно добавить напиток через /add")
        return
    await message.answer(f"🔎 Найдено: {len(found)}", reply_markup=drinks_list_kb(found))


@router.message(Command("top"))
async def cmd_top(message: Message, db: Database) -> None:
    top = await db.top_drinks(10)
    if not top:
        await message.answer("Пока никто ничего не оценил.")
        return
    lines = ["🏅 <b>Топ по средней оценке</b>", ""]
    for i, d in enumerate(top, 1):
        lines.append(f"{i}. {escape(d.name)} — {texts.format_score(d)}")
    await message.answer("\n".join(lines), reply_markup=drinks_list_kb(top))


@router.callback_query(DrinkCb.filter(F.action.in_({"open", "back"})))
async def cb_open(call: CallbackQuery, callback_data: DrinkCb, db: Database, is_admin: bool) -> None:
    text, kb = await render_card(db, callback_data.drink_id, call.from_user.id, is_admin)
    if text is None:
        await call.answer("Напиток не найден — возможно, его удалили.", show_alert=True)
        return
    # Из списка открываем карточку новым сообщением, чтобы список остался;
    # кнопка «Назад» из подменю карточки возвращает карточку на место.
    if callback_data.action == "back":
        await call.message.edit_text(text, reply_markup=kb)
    else:
        await call.message.answer(text, reply_markup=kb)
    await call.answer()


# --- оценки ---


@router.callback_query(DrinkCb.filter(F.action == "rate"))
async def cb_rate(call: CallbackQuery, callback_data: DrinkCb, db: Database) -> None:
    drink = await db.get_drink(callback_data.drink_id)
    if drink is None:
        await call.answer("Напиток не найден.", show_alert=True)
        return
    await call.message.edit_text(
        f"⭐ Оцените <b>{escape(drink.name)}</b> от 1 до 10:",
        reply_markup=score_kb(drink.id),
    )
    await call.answer()


@router.callback_query(ScoreCb.filter())
async def cb_score(call: CallbackQuery, callback_data: ScoreCb, db: Database, is_admin: bool) -> None:
    if not 1 <= callback_data.score <= 10 or await db.get_drink(callback_data.drink_id) is None:
        await call.answer("Не получилось сохранить оценку.", show_alert=True)
        return
    await db.set_score(call.from_user.id, callback_data.drink_id, callback_data.score)
    text, kb = await render_card(db, callback_data.drink_id, call.from_user.id, is_admin)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer(f"Оценка {callback_data.score}/10 сохранена")


# --- отзывы ---


@router.callback_query(DrinkCb.filter(F.action == "review"))
async def cb_review(call: CallbackQuery, callback_data: DrinkCb, db: Database, state: FSMContext) -> None:
    drink = await db.get_drink(callback_data.drink_id)
    if drink is None:
        await call.answer("Напиток не найден.", show_alert=True)
        return
    await state.set_state(WriteReview.text)
    await state.update_data(drink_id=drink.id)
    await call.message.answer(
        f"✍️ Напишите отзыв о <b>{escape(drink.name)}</b> одним сообщением "
        f"(до {MAX_REVIEW_LEN} символов). /cancel — отмена."
    )
    await call.answer()


@router.message(WriteReview.text, F.text, ~F.text.startswith("/"))
async def review_text(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if len(text) > MAX_REVIEW_LEN:
        await message.answer(f"Слишком длинно: {len(text)} символов из {MAX_REVIEW_LEN}. Сократите, пожалуйста.")
        return
    await state.update_data(text=text)
    await state.set_state(WriteReview.photo)
    await message.answer(
        "📷 Хотите прикрепить фото напитка? Пришлите его сюда "
        "или отправьте /skip, чтобы сохранить отзыв без фото."
    )


@router.message(WriteReview.text, F.photo)
async def review_photo_first(message: Message) -> None:
    await message.answer("Сначала напишите отзыв текстом, фото можно будет прикрепить следующим сообщением.")


@router.message(WriteReview.photo, F.photo)
async def review_photo(message: Message, state: FSMContext, db: Database, is_admin: bool) -> None:
    # Telegram присылает несколько размеров, последний — самый крупный.
    await _save_review(message, state, db, is_admin, message.photo[-1].file_id)


@router.message(WriteReview.photo, Command("skip"))
async def review_skip_photo(message: Message, state: FSMContext, db: Database, is_admin: bool) -> None:
    await _save_review(message, state, db, is_admin, None)


@router.message(WriteReview.photo, ~F.text.startswith("/"))
async def review_photo_wrong(message: Message) -> None:
    await message.answer("Пришлите фото (как картинку, не файлом) или /skip, чтобы обойтись без него.")


async def _save_review(message: Message, state: FSMContext, db: Database, is_admin: bool,
                       photo_id: str | None) -> None:
    data = await state.get_data()
    await state.clear()
    if await db.get_drink(data["drink_id"]) is None:
        await message.answer("Напиток не найден — возможно, его удалили.")
        return
    await db.set_review(message.from_user.id, data["drink_id"], data["text"], photo_id)
    await message.answer("✅ Отзыв с фото сохранён!" if photo_id else "✅ Отзыв сохранён!")
    await show_card(message, db, data["drink_id"], message.from_user.id, is_admin)


@router.callback_query(DrinkCb.filter(F.action == "reviews"))
async def cb_reviews(call: CallbackQuery, callback_data: DrinkCb, db: Database) -> None:
    drink = await db.get_drink(callback_data.drink_id)
    if drink is None:
        await call.answer("Напиток не найден.", show_alert=True)
        return
    page = max(0, callback_data.page)
    total = await db.count_reviews(drink.id)
    items = await db.get_reviews(drink.id, page * REVIEWS_PAGE_SIZE, REVIEWS_PAGE_SIZE)
    has_next = (page + 1) * REVIEWS_PAGE_SIZE < total
    await call.message.edit_text(
        texts.truncate(texts.reviews(drink, items, page, total)),
        reply_markup=reviews_kb(drink.id, page, has_next, items),
    )
    await call.answer()


@router.callback_query(PhotoCb.filter())
async def cb_review_photo(call: CallbackQuery, callback_data: PhotoCb, db: Database) -> None:
    drink = await db.get_drink(callback_data.drink_id)
    review = await db.get_review(callback_data.user_id, callback_data.drink_id)
    if drink is None or review is None or not review.photo_id:
        await call.answer("Фото не найдено — возможно, отзыв изменили.", show_alert=True)
        return
    await call.message.answer_photo(review.photo_id, caption=texts.review_caption(drink, review))
    await call.answer()


# --- удаление ---


@router.callback_query(DrinkCb.filter(F.action == "delreview"))
async def cb_delreview(call: CallbackQuery, callback_data: DrinkCb, db: Database) -> None:
    drink = await db.get_drink(callback_data.drink_id)
    if drink is None or await db.get_review(call.from_user.id, callback_data.drink_id) is None:
        await call.answer("Отзыв не найден.", show_alert=True)
        return
    await call.message.edit_text(
        f"🗑 Удалить ваш отзыв о <b>{escape(drink.name)}</b> вместе с фото? Оценка останется.",
        reply_markup=confirm_kb(drink.id, "delreview_yes"),
    )
    await call.answer()


@router.callback_query(DrinkCb.filter(F.action == "delreview_yes"))
async def cb_delreview_yes(call: CallbackQuery, callback_data: DrinkCb, db: Database, is_admin: bool) -> None:
    deleted = await db.delete_review(call.from_user.id, callback_data.drink_id)
    text, kb = await render_card(db, callback_data.drink_id, call.from_user.id, is_admin)
    if text is None:
        await call.answer("Напиток не найден — возможно, его удалили.", show_alert=True)
        return
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Отзыв удалён" if deleted else "Отзыв уже был удалён")


@router.callback_query(DrinkCb.filter(F.action == "deldrink"))
async def cb_deldrink(call: CallbackQuery, callback_data: DrinkCb, db: Database, is_admin: bool) -> None:
    if not is_admin:
        await call.answer("Удалять напитки могут только админы.", show_alert=True)
        return
    drink = await db.get_drink(callback_data.drink_id)
    if drink is None:
        await call.answer("Напиток не найден.", show_alert=True)
        return
    await call.message.edit_text(
        f"❌ Удалить напиток <b>{escape(drink.name)}</b> насовсем? "
        "Пропадут все его оценки, отзывы и места в тир-листах.",
        reply_markup=confirm_kb(drink.id, "deldrink_yes"),
    )
    await call.answer()


@router.callback_query(DrinkCb.filter(F.action == "deldrink_yes"))
async def cb_deldrink_yes(call: CallbackQuery, callback_data: DrinkCb, db: Database, is_admin: bool) -> None:
    if not is_admin:
        await call.answer("Удалять напитки могут только админы.", show_alert=True)
        return
    drink = await db.get_drink(callback_data.drink_id)
    if drink is None:
        await call.answer("Напиток уже удалён.", show_alert=True)
        return
    await db.delete_drink(drink.id)
    await call.message.edit_text(f"🗑 Напиток «{escape(drink.name)}» удалён вместе с оценками и отзывами.")
    await call.answer("Удалено")
