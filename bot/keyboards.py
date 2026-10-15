from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .db import TIERS, Drink


class DrinkCb(CallbackData, prefix="d"):
    action: str  # open | back | rate | review | reviews | mytier | gtier
    drink_id: int
    page: int = 0


class ScoreCb(CallbackData, prefix="s"):
    drink_id: int
    score: int


class TierCb(CallbackData, prefix="t"):
    scope: str  # my | global
    drink_id: int
    tier: str  # S..F или "-" чтобы убрать


class ListCb(CallbackData, prefix="l"):
    page: int


def drink_card_kb(drink_id: int, is_admin: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ Оценить", callback_data=DrinkCb(action="rate", drink_id=drink_id))
    kb.button(text="✍️ Отзыв", callback_data=DrinkCb(action="review", drink_id=drink_id))
    kb.button(text="💬 Отзывы", callback_data=DrinkCb(action="reviews", drink_id=drink_id))
    kb.button(text="📊 В мой тир-лист", callback_data=DrinkCb(action="mytier", drink_id=drink_id))
    if is_admin:
        kb.button(text="🏆 В общий тир-лист", callback_data=DrinkCb(action="gtier", drink_id=drink_id))
    kb.adjust(3, 1, 1)
    return kb.as_markup()


def score_kb(drink_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for score in range(1, 11):
        kb.button(text=str(score), callback_data=ScoreCb(drink_id=drink_id, score=score))
    kb.button(text="« Назад", callback_data=DrinkCb(action="back", drink_id=drink_id))
    kb.adjust(5, 5, 1)
    return kb.as_markup()


def tier_kb(drink_id: int, scope: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for tier in TIERS:
        kb.button(text=tier, callback_data=TierCb(scope=scope, drink_id=drink_id, tier=tier))
    kb.button(text="🗑 Убрать", callback_data=TierCb(scope=scope, drink_id=drink_id, tier="-"))
    kb.button(text="« Назад", callback_data=DrinkCb(action="back", drink_id=drink_id))
    kb.adjust(6, 2)
    return kb.as_markup()


def reviews_kb(drink_id: int, page: int, has_next: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    nav = 0
    if page > 0:
        kb.button(text="◀️", callback_data=DrinkCb(action="reviews", drink_id=drink_id, page=page - 1))
        nav += 1
    if has_next:
        kb.button(text="▶️", callback_data=DrinkCb(action="reviews", drink_id=drink_id, page=page + 1))
        nav += 1
    kb.button(text="« К напитку", callback_data=DrinkCb(action="back", drink_id=drink_id))
    kb.adjust(*([nav] if nav else []), 1)
    return kb.as_markup()


def drinks_list_kb(drinks: list[Drink], page: int | None = None, has_next: bool = False) -> InlineKeyboardMarkup:
    """Список напитков кнопками. page=None — без листания (например, для поиска)."""
    kb = InlineKeyboardBuilder()
    for d in drinks:
        kb.button(text=d.name, callback_data=DrinkCb(action="open", drink_id=d.id))
    sizes = [1] * len(drinks)
    if page is not None:
        nav = 0
        if page > 0:
            kb.button(text="◀️", callback_data=ListCb(page=page - 1))
            nav += 1
        if has_next:
            kb.button(text="▶️", callback_data=ListCb(page=page + 1))
            nav += 1
        if nav:
            sizes.append(nav)
    kb.adjust(*sizes)
    return kb.as_markup()
