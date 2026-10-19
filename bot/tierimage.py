"""Рисует тир-лист картинкой-таблицей: строка на тир, в ячейках фото и название."""

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .db import TIERS

FONTS = Path(__file__).parent / "fonts"

# Цвета ячеек с буквой тира.
TIER_COLORS = {
    "S": (255, 127, 127),
    "A": (255, 191, 127),
    "B": (255, 223, 127),
    "C": (191, 255, 127),
    "D": (127, 191, 255),
    "F": (200, 160, 255),
}

BG = (255, 255, 255)
HEADER_BG = (240, 240, 244)
GRID = (225, 225, 230)
GRID_STRONG = (210, 210, 215)
TEXT = (30, 30, 30)
TEXT_MUTED = (120, 120, 120)
NO_PHOTO_BG = (235, 235, 238)
NO_PHOTO_FG = (170, 170, 170)

COLUMNS = 5  # напитков в одной строке таблицы
PHOTO = 130  # сторона фото
PAD = 12
CAPTION = 48  # место под название и оценку
LABEL_W = 120  # ширина колонки с буквой тира
TITLE_H = 80
HEADER_H = 50
CELL = PHOTO + 2 * PAD
ROW_H = PHOTO + CAPTION + 2 * PAD


@dataclass
class Item:
    name: str
    score: float | None  # что подписать под фото; None — без оценки
    photo: bytes | None  # картинка как есть (jpeg из Telegram)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    """Обрезает строку с многоточием, чтобы влезла в ячейку."""
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _contrast(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """Тёмная буква на светлой плашке, белая — на тёмной."""
    r, g, b = color
    return TEXT if 0.299 * r + 0.587 * g + 0.114 * b > 140 else (255, 255, 255)


def _placeholder(name: str) -> Image.Image:
    """Что рисовать вместо фото, если его нет."""
    im = Image.new("RGB", (PHOTO, PHOTO), NO_PHOTO_BG)
    ImageDraw.Draw(im).text((PHOTO / 2, PHOTO / 2), "нет фото", font=_font(18, True),
                            fill=NO_PHOTO_FG, anchor="mm")
    return im


def _thumb(data: bytes | None, name: str) -> Image.Image:
    if data:
        try:
            with Image.open(io.BytesIO(data)) as src:
                return ImageOps.fit(src.convert("RGB"), (PHOTO, PHOTO))
        except Exception:  # битая картинка — рисуем как без фото
            pass
    return _placeholder(name)


def _rounded_mask() -> Image.Image:
    mask = Image.new("L", (PHOTO, PHOTO), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, PHOTO - 1, PHOTO - 1], radius=14, fill=255)
    return mask


def _draw_item(im: Image.Image, draw: ImageDraw.ImageDraw, item: Item, x: int, y: int) -> None:
    """Одна ячейка: фото со скруглёнными углами, под ним название и оценка."""
    name_font, score_font = _font(15, True), _font(14)
    im.paste(_thumb(item.photo, item.name), (x + PAD, y + PAD), _rounded_mask())
    draw.text((x + CELL / 2, y + PAD + PHOTO + 14), _fit(draw, item.name, name_font, CELL - 8),
              font=name_font, fill=TEXT, anchor="mm")
    if item.score is not None:
        draw.text((x + CELL / 2, y + PAD + PHOTO + 34), f"★ {item.score:.1f}",
                  font=score_font, fill=TEXT_MUTED, anchor="mm")


def render(title: str, tiers: dict[str, list[Item]]) -> tuple[bytes, tuple[int, int]]:
    """Возвращает PNG и его размер. Пустые тиры тоже рисуются — так видно всю шкалу."""
    rows = {t: max(1, (len(tiers.get(t, [])) + COLUMNS - 1) // COLUMNS) for t in TIERS}
    width = LABEL_W + COLUMNS * CELL
    top = TITLE_H + HEADER_H
    height = top + sum(rows.values()) * ROW_H

    im = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(im)

    draw.text((width / 2, TITLE_H / 2), _fit(draw, title, _font(38, True), width - 40),
              font=_font(38, True), fill=TEXT, anchor="mm")
    draw.rectangle([0, TITLE_H, width, top], fill=HEADER_BG)
    draw.text((LABEL_W / 2, TITLE_H + HEADER_H / 2), "Тир", font=_font(22, True),
              fill=(60, 60, 60), anchor="mm")
    draw.text((LABEL_W + 20, TITLE_H + HEADER_H / 2), "Напитки", font=_font(22, True),
              fill=(60, 60, 60), anchor="lm")

    for i in range(1, COLUMNS + 1):
        x = LABEL_W + i * CELL
        draw.line([x, top, x, height], fill=GRID, width=1)

    y = top
    for tier in TIERS:
        block_h = rows[tier] * ROW_H
        draw.rectangle([0, y, LABEL_W - 1, y + block_h - 1], fill=TIER_COLORS[tier])
        draw.text((LABEL_W / 2, y + block_h / 2), tier, font=_font(56, True),
                  fill=_contrast(TIER_COLORS[tier]), anchor="mm")
        for n, item in enumerate(tiers.get(tier, [])):
            x = LABEL_W + (n % COLUMNS) * CELL
            cy = y + (n // COLUMNS) * ROW_H
            _draw_item(im, draw, item, x, cy)
        y += block_h
        draw.line([0, y - 1, width, y - 1], fill=GRID_STRONG, width=2)
    draw.line([LABEL_W, TITLE_H, LABEL_W, height], fill=GRID_STRONG, width=2)

    out = io.BytesIO()
    im.save(out, format="PNG", optimize=True)
    return out.getvalue(), im.size
