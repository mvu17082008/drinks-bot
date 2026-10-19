from html import escape

from .db import TIERS, Drink, Review

TIER_EMOJI = {"S": "🟥", "A": "🟧", "B": "🟨", "C": "🟩", "D": "🟦", "F": "⬜"}

HELP = """<b>Бот для оценки напитков</b> 🥤

Оценивайте напитки по шкале от 1 до 10, пишите отзывы и собирайте тир-листы.

<b>Команды</b>
/add — добавить напиток
/drinks — все напитки
/search <i>текст</i> — найти напиток
/top — лучшие по средней оценке
/mytier — мой тир-лист
/tier — общий тир-лист (его ведут админы)
/cancel — отменить текущее действие

Чтобы оценить напиток, откройте его через /drinks или /search и нажмите «⭐ Оценить»."""

ADMIN_HELP = """

<b>Для админов</b>
В карточке напитка есть кнопка «🏆 В общий тир-лист».
/deldrink <i>id</i> — удалить напиток со всеми оценками"""


def format_score(drink: Drink) -> str:
    if not drink.ratings_count:
        return "оценок пока нет"
    return f"{drink.avg_score:.1f}/10 ({drink.ratings_count} {plural(drink.ratings_count, 'оценка', 'оценки', 'оценок')})"


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def drink_card(
    drink: Drink,
    my_score: int | None,
    my_review: str | None,
    my_tier: str | None,
    global_tier: str | None,
    my_photo: bool = False,
) -> str:
    lines = [f"🥤 <b>{escape(drink.name)}</b>  <code>#{drink.id}</code>"]
    if drink.category:
        lines.append(f"Категория: {escape(drink.category)}")
    lines.append(f"⭐ Средняя оценка: {format_score(drink)}")
    lines.append(f"🏆 Общий тир-лист: {global_tier or '—'}")
    lines.append("")
    lines.append(f"Ваша оценка: {my_score if my_score is not None else '—'}")
    lines.append(f"Ваш тир: {my_tier or '—'}")
    if my_review:
        lines.append(f"Ваш отзыв: <i>{escape(my_review)}</i>")
        if my_photo:
            lines.append("📷 К отзыву приложено фото — смотрите в «💬 Отзывы».")
    return "\n".join(lines)


def tier_list(title: str, tiers: dict[str, list[str]]) -> str:
    if not any(tiers.values()):
        return f"<b>{title}</b>\n\nПока пусто."
    lines = [f"<b>{title}</b>", ""]
    for tier in TIERS:
        names = ", ".join(escape(n) for n in tiers[tier]) or "—"
        lines.append(f"{TIER_EMOJI[tier]} <b>{tier}</b>: {names}")
    return "\n".join(lines)


def reviews(drink: Drink, items: list[Review], page: int, total: int) -> str:
    head = f"💬 Отзывы о <b>{escape(drink.name)}</b> ({total})"
    if not items:
        return head + "\n\nОтзывов пока нет. Будьте первым!"
    parts = [head, ""]
    for r in items:
        score = f" — {r.score}/10" if r.score is not None else ""
        photo = " 📷" if r.photo_id else ""
        parts.append(f"<b>{escape(r.author)}</b>{score}{photo}\n{escape(r.text)}\n")
    return "\n".join(parts)


def review_caption(drink: Drink, review: Review) -> str:
    score = f" — {review.score}/10" if review.score is not None else ""
    return truncate(
        f"🥤 <b>{escape(drink.name)}</b>\n<b>{escape(review.author)}</b>{score}\n{escape(review.text)}",
        1024,  # лимит подписи к фото в Telegram
    )


def truncate(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
