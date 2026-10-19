"""Шаблон игральных карт: рендер карт из фото пользователя и раскладка на листы A4.

Все размеры считаются при 300 DPI. Карта стандартного покерного размера 63×88 мм,
на лист A4 помещается 3×3 = 9 карт, карты стоят вплотную — резать по меткам.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

DPI = 300


def mm(value: float) -> int:
    return round(value / 25.4 * DPI)


A4 = (mm(210), mm(297))
CARD_W, CARD_H = mm(63), mm(88)
COLS, ROWS = 3, 3
PER_SHEET = COLS * ROWS

FONTS_DIR = Path("C:/Windows/Fonts")
MASCOT = Path(__file__).resolve().parent / "assets" / "tyusha_logo.webp"

SUITS = {
    "spades": ("♠", (20, 20, 20)),
    "hearts": ("♥", (200, 20, 40)),
    "diamonds": ("♦", (200, 20, 40)),
    "clubs": ("♣", (20, 20, 20)),
}
SUIT_ORDER = ["spades", "hearts", "diamonds", "clubs"]


@dataclass(frozen=True)
class DeckTemplate:
    key: str
    title: str
    ranks: tuple[str, ...]
    jokers: int


DECKS = {
    "deck36": DeckTemplate("deck36", "Колода 36 карт (6 – Туз)",
                           ("6", "7", "8", "9", "10", "В", "Д", "К", "Т"), 0),
    "deck54": DeckTemplate("deck54", "Колода 54 карты (2 – Туз + 2 джокера)",
                           ("2", "3", "4", "5", "6", "7", "8", "9", "10", "В", "Д", "К", "Т"), 2),
}


@dataclass(frozen=True)
class Card:
    rank: str            # "Т", "10", ... или "JOKER"
    suit: str | None     # None у джокера


def deck_cards(template: DeckTemplate) -> list[Card]:
    cards = [Card(rank, suit) for suit in SUIT_ORDER for rank in template.ranks]
    cards += [Card("JOKER", None) for _ in range(template.jokers)]
    return cards


def sheets_needed(template: DeckTemplate) -> int:
    return math.ceil(len(deck_cards(template)) / PER_SHEET)


# ---------- шрифты ----------

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font(names: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    key = (names[0], size)
    if key not in _font_cache:
        for name in names:
            path = FONTS_DIR / name
            if path.exists():
                _font_cache[key] = ImageFont.truetype(str(path), size)
                break
        else:
            _font_cache[key] = ImageFont.load_default(size)
    return _font_cache[key]


def rank_font(size: int):
    return _font(("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"), size)


def suit_font(size: int):
    return _font(("seguisym.ttf", "arial.ttf", "DejaVuSans.ttf"), size)


# ---------- рендер одной карты ----------

def load_photo(path: Path) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # фото с телефона часто повернуты через EXIF
    return img.convert("RGB")


def _round_mask(diameter: int) -> Image.Image:
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    return mask


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


def _draw_index(card: Card, color) -> Image.Image:
    """Угловой индекс (ранг над мастью) на прозрачном фоне."""
    w, h = mm(9), mm(17)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if card.suit is None:
        f = rank_font(mm(3.2))
        for i, ch in enumerate("JOKER"):
            d.text((w // 2, mm(1) + i * mm(3.2)), ch, font=f, fill=color, anchor="mt")
        return layer
    text = card.rank
    f = rank_font(mm(6) if len(text) == 1 else mm(4.8))
    d.text((w // 2, mm(0.5)), text, font=f, fill=color, anchor="mt")
    symbol, _ = SUITS[card.suit]
    d.text((w // 2, mm(7.2)), symbol, font=suit_font(mm(6)), fill=color, anchor="mt")
    return layer


def render_card(card: Card, photo: Image.Image) -> Image.Image:
    color = SUITS[card.suit][1] if card.suit else (150, 20, 120)
    img = Image.new("RGB", (CARD_W, CARD_H), "white")
    d = ImageDraw.Draw(img)

    # Окно под фото между угловыми индексами
    margin_x, margin_y = mm(9.5), mm(5)
    win = (margin_x, margin_y, CARD_W - margin_x, CARD_H - margin_y)
    win_size = (win[2] - win[0], win[3] - win[1])
    fitted = ImageOps.fit(photo, win_size, Image.LANCZOS, centering=(0.5, 0.4))
    img.paste(fitted, win[:2], _rounded_mask(win_size, mm(2.5)))
    d.rounded_rectangle(win, mm(2.5), outline=color, width=mm(0.5))

    # Масть-«медальон» внизу окна фото
    if card.suit:
        symbol, _ = SUITS[card.suit]
        cx, cy, r = CARD_W // 2, win[3] - mm(1), mm(4.2)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill="white", outline=color, width=mm(0.4))
        d.text((cx, cy + mm(0.3)), symbol, font=suit_font(mm(5.6)), fill=color, anchor="mm")
    else:
        f = rank_font(mm(4))
        cx, cy = CARD_W // 2, win[3] - mm(1)
        tw = d.textlength("JOKER", font=f)
        d.rounded_rectangle((cx - tw / 2 - mm(2), cy - mm(3), cx + tw / 2 + mm(2), cy + mm(3)),
                            mm(3), fill="white", outline=color, width=mm(0.4))
        d.text((cx, cy), "JOKER", font=f, fill=color, anchor="mm")

    # Угловые индексы: левый верхний и повёрнутый правый нижний
    index = _draw_index(card, color)
    img.paste(index, (mm(0.5), mm(2)), index)
    flipped = index.rotate(180)
    img.paste(flipped, (CARD_W - index.width - mm(0.5), CARD_H - index.height - mm(2)), flipped)

    # Тонкая рамка по контуру — помогает при резке
    d.rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), mm(3), outline=(200, 200, 200), width=2)
    return img


def render_back(color=(25, 45, 110)) -> Image.Image:
    """Рубашка: ромбовидный узор с рамкой (симметрична — не важно, как перевернуть лист)."""
    img = Image.new("RGB", (CARD_W, CARD_H), "white")
    d = ImageDraw.Draw(img)
    inset = mm(3)
    inner = (inset, inset, CARD_W - inset, CARD_H - inset)
    d.rounded_rectangle(inner, mm(2), fill=color)
    light = tuple(min(255, c + 70) for c in color)
    step = mm(5)
    for x in range(-CARD_H, CARD_W + CARD_H, step):
        d.line((x, inner[1], x + CARD_H, inner[1] + CARD_H), fill=light, width=3)
        d.line((x, inner[3], x + CARD_H, inner[3] - CARD_H), fill=light, width=3)
    # обрезаем узор, вылезший за рамку
    frame = Image.new("RGB", (CARD_W, CARD_H), "white")
    frame.paste(img.crop(inner), inner[:2], _rounded_mask((inner[2] - inner[0], inner[3] - inner[1]), mm(2)))
    img = frame
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(inner, mm(2), outline="white", width=mm(0.8))
    d.rounded_rectangle((inner[0] + mm(1.6), inner[1] + mm(1.6), inner[2] - mm(1.6), inner[3] - mm(1.6)),
                        mm(1.5), outline=light, width=mm(0.3))
    cx, cy = CARD_W // 2, CARD_H // 2
    if MASCOT.exists():
        # фирменный медальон с Тюшей
        r = mm(14)
        face = Image.open(MASCOT).convert("RGB").crop((235, 95, 965, 825)).resize((2 * r, 2 * r), Image.LANCZOS)
        d.ellipse((cx - r - mm(1), cy - r - mm(1), cx + r + mm(1), cy + r + mm(1)), fill="white")
        img.paste(face, (cx - r, cy - r), _round_mask(2 * r))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=light, width=mm(0.5))
    else:
        r = mm(9)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color, outline="white", width=mm(0.8))
        d.text((cx, cy), "♠♥\n♦♣", font=suit_font(mm(5.5)), fill="white", anchor="mm", align="center",
               spacing=mm(0.5))
    d.rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), mm(3), outline=(200, 200, 200), width=2)
    return img


# ---------- раскладка на листы ----------

def _grid_origin() -> tuple[int, int]:
    return (A4[0] - COLS * CARD_W) // 2, (A4[1] - ROWS * CARD_H) // 2


def _draw_crop_marks(sheet: Image.Image) -> None:
    d = ImageDraw.Draw(sheet)
    ox, oy = _grid_origin()
    length, gap = mm(5), mm(1.5)
    xs = [ox + i * CARD_W for i in range(COLS + 1)]
    ys = [oy + j * CARD_H for j in range(ROWS + 1)]
    bottom, right = ys[-1], xs[-1]
    for x in xs:
        d.line((x, oy - gap - length, x, oy - gap), fill="black", width=2)
        d.line((x, bottom + gap, x, bottom + gap + length), fill="black", width=2)
    for y in ys:
        d.line((ox - gap - length, y, ox - gap, y), fill="black", width=2)
        d.line((right + gap, y, right + gap + length, y), fill="black", width=2)


def layout_sheet(cards: list[Image.Image], mirror: bool = False) -> Image.Image:
    """mirror=True — для оборотной стороны: столбцы в зеркальном порядке,
    чтобы рубашка совпала с лицом при перевороте листа по длинной стороне."""
    sheet = Image.new("RGB", A4, "white")
    ox, oy = _grid_origin()
    for i, card in enumerate(cards):
        col, row = i % COLS, i // COLS
        if mirror:
            col = COLS - 1 - col
        sheet.paste(card, (ox + col * CARD_W, oy + row * CARD_H))
    _draw_crop_marks(sheet)
    return sheet


def build_deck(template: DeckTemplate, photo_paths: list[Path], out_dir: Path,
               with_backs: bool = True) -> list[Path]:
    """Рендерит всю колоду. Фото распределяются по картам по кругу.
    Возвращает пути к листам в порядке печати: сначала все лицевые, затем рубашки."""
    out_dir.mkdir(parents=True, exist_ok=True)
    photos = [load_photo(p) for p in photo_paths]
    cards = deck_cards(template)
    faces = [render_card(card, photos[i % len(photos)]) for i, card in enumerate(cards)]

    paths: list[Path] = []
    for s in range(0, len(faces), PER_SHEET):
        path = out_dir / f"sheet_{s // PER_SHEET + 1:02d}_face.png"
        layout_sheet(faces[s:s + PER_SHEET]).save(path, dpi=(DPI, DPI))
        paths.append(path)
    if with_backs:
        back = render_back()
        for s in range(0, len(faces), PER_SHEET):
            count = len(faces[s:s + PER_SHEET])
            path = out_dir / f"sheet_{s // PER_SHEET + 1:02d}_back.png"
            layout_sheet([back] * count, mirror=True).save(path, dpi=(DPI, DPI))
            paths.append(path)
    return paths


def make_preview(sheet_path: Path, out_path: Path, max_side: int = 1280) -> Path:
    """Уменьшенное превью листа с водяным знаком «ОБРАЗЕЦ»."""
    img = Image.open(sheet_path).convert("RGB")
    img.thumbnail((max_side, max_side))
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    f = rank_font(img.width // 9)
    for y in range(img.height // 6, img.height, img.height // 3):
        d.text((img.width // 2, y), "ОБРАЗЕЦ", font=f, fill=(255, 255, 255, 110), anchor="mm",
               stroke_width=2, stroke_fill=(0, 0, 0, 60))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    img.save(out_path, quality=85)
    return out_path
