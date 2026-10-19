"""Шаблон игральных карт: рендер карт из фото пользователя и раскладка на листы A4.

Все размеры считаются при 300 DPI. Карта стандартного покерного размера 63×88 мм,
на лист A4 помещается 3×3 = 9 карт, карты стоят вплотную — резать по меткам.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

DPI = 300


def mm(value: float) -> int:
    return round(value / 25.4 * DPI)


A4 = (mm(210), mm(297))
CARD_W, CARD_H = mm(63), mm(88)
COLS, ROWS = 3, 3
PER_SHEET = COLS * ROWS

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
# Свои шрифты лежат в assets/fonts (лицензия OFL) — карты одинаковые на Windows и на Linux-сервере.

ASSET_FONTS = Path(__file__).resolve().parent / "assets" / "fonts"
FONT_DIRS = [ASSET_FONTS, Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"),
             Path("/usr/share/fonts/TTF"), Path("/usr/share/fonts/dejavu")]
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font(names: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    key = (names[0], size)
    if key not in _font_cache:
        for name in names:
            path = next((d / name for d in FONT_DIRS if (d / name).exists()), None)
            if path:
                _font_cache[key] = ImageFont.truetype(str(path), size)
                break
        else:
            _font_cache[key] = ImageFont.load_default(size)
    return _font_cache[key]


def rank_font(size: int):
    """Рубленый жирный — для служебных надписей (пробный лист, «ОБРАЗЕЦ»)."""
    return _font(("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"), size)


def serif_font(size: int):
    """Засечный жирный — ранги на картах, как в классической колоде."""
    return _font(("PTSerif-Bold.ttf", "georgiab.ttf", "DejaVuSerif-Bold.ttf"), size)


def suit_font(size: int):
    return _font(("seguisym.ttf", "arial.ttf", "DejaVuSans.ttf"), size)


# ---------- масти: векторные фигуры (не зависят от шрифтов) ----------

SS = 4  # сглаживание: рисуем крупнее и уменьшаем


def _shape(size: int, draw_fn, color) -> Image.Image:
    big = Image.new("L", (size * SS, size * SS), 0)
    draw_fn(ImageDraw.Draw(big), size * SS / 100)
    mask = big.resize((size, size), Image.LANCZOS)
    layer = Image.new("RGBA", (size, size), color + (0,) if len(color) == 3 else color)
    layer.putalpha(mask)
    return layer


def _heart(d: ImageDraw.ImageDraw, k: float) -> None:
    for cx in (28, 72):
        d.ellipse(((cx - 25) * k, 6 * k, (cx + 25) * k, 56 * k), fill=255)
    d.polygon([(4.5 * k, 40 * k), (95.5 * k, 40 * k), (50 * k, 97 * k)], fill=255)


def _diamond(d: ImageDraw.ImageDraw, k: float) -> None:
    pts = []
    for t in range(0, 360, 3):  # ромб с чуть вогнутыми сторонами
        a = math.radians(t)
        x, y = math.cos(a), math.sin(a)
        r = 1 / (abs(x) ** 0.85 + abs(y) ** 0.85) ** (1 / 0.85)
        pts.append(((50 + 40 * x * r) * k, (50 + 50 * y * r) * k))
    d.polygon(pts, fill=255)


def _spade(d: ImageDraw.ImageDraw, k: float) -> None:
    for cx in (29, 71):
        d.ellipse(((cx - 23) * k, 38 * k, (cx + 23) * k, 84 * k), fill=255)
    d.polygon([(6 * k, 62 * k), (94 * k, 62 * k), (50 * k, 2 * k)], fill=255)
    d.polygon([(50 * k, 66 * k), (63 * k, 99 * k), (37 * k, 99 * k)], fill=255)


def _club(d: ImageDraw.ImageDraw, k: float) -> None:
    for cx, cy in ((50, 27), (26, 60), (74, 60)):
        d.ellipse(((cx - 22) * k, (cy - 22) * k, (cx + 22) * k, (cy + 22) * k), fill=255)
    d.ellipse((38 * k, 42 * k, 62 * k, 66 * k), fill=255)
    d.polygon([(50 * k, 58 * k), (63 * k, 99 * k), (37 * k, 99 * k)], fill=255)


def _star(d: ImageDraw.ImageDraw, k: float) -> None:
    pts = []
    for i in range(10):
        a = math.radians(-90 + i * 36)
        r = 48 if i % 2 == 0 else 20
        pts.append(((50 + r * math.cos(a)) * k, (54 + r * math.sin(a)) * k))
    d.polygon(pts, fill=255)


SUIT_SHAPES = {"spades": _spade, "hearts": _heart, "diamonds": _diamond, "clubs": _club, "joker": _star}
RED, BLACK, JOKER_RED = (206, 28, 46), (24, 24, 30), (176, 30, 120)


def suit_image(suit: str, size: int, color) -> Image.Image:
    return _shape(size, SUIT_SHAPES[suit], color)


# ---------- лицевая сторона ----------

def load_photo(path: Path) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # фото с телефона часто повернуты через EXIF
    return img.convert("RGB")


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


def _feather_mask(size: tuple[int, int], feather: int) -> Image.Image:
    """Прямоугольник с мягко растворяющимися краями."""
    mask = Image.new("L", size, 0)
    inset = feather
    ImageDraw.Draw(mask).rounded_rectangle((inset, inset, size[0] - inset, size[1] - inset), feather, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(feather * 0.55))


PHOTO_BOX = (mm(10.5), mm(13.5), CARD_W - mm(10.5), CARD_H - mm(13.5))  # окно фото на карте


def _index(card: Card, color) -> Image.Image:
    """Угловой индекс как в классической колоде: крупный ранг, справа большая масть, под рангом маленькая."""
    layer = Image.new("RGBA", (mm(24), mm(17)), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rank = "J" if card.suit is None else card.rank
    f = serif_font(mm(10.5) if len(rank) == 1 else mm(8.6))
    d.text((mm(0.2), mm(-0.4)), rank, font=f, fill=color, anchor="lt")
    rank_w = d.textlength(rank, font=f)
    suit = card.suit or "joker"
    big = suit_image(suit, mm(7.6), color)
    layer.alpha_composite(big, (round(rank_w + mm(1)), mm(1.1)))
    small = suit_image(suit, mm(4.4), color)
    layer.alpha_composite(small, (round(rank_w / 2 - small.width / 2) + mm(0.2), mm(10.6)))
    return layer


def render_card(card: Card, photo: Image.Image) -> Image.Image:
    color = (RED if card.suit in ("hearts", "diamonds") else BLACK) if card.suit else JOKER_RED
    img = Image.new("RGBA", (CARD_W, CARD_H), (255, 255, 255, 255))

    # фото по центру с мягкими краями, без рамки
    box = PHOTO_BOX
    size = (box[2] - box[0], box[3] - box[1])
    fitted = ImageOps.fit(photo, size, Image.LANCZOS, centering=(0.5, 0.42)).convert("RGBA")
    fitted.putalpha(_feather_mask(size, mm(2.4)))
    img.alpha_composite(fitted, box[:2])

    index = _index(card, color)
    img.alpha_composite(index, (mm(3.2), mm(2.6)))
    flipped = index.rotate(180)
    img.alpha_composite(flipped, (CARD_W - flipped.width - mm(3.2), CARD_H - flipped.height - mm(2.6)))
    return img.convert("RGB")


# ---------- рубашки: на всю карту, без рамок ----------

def _canvas(color, scale: int = 2) -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    img = Image.new("RGB", (CARD_W * scale, CARD_H * scale), color)
    return img, ImageDraw.Draw(img, "RGBA"), scale


def _finish(img: Image.Image) -> Image.Image:
    return img.resize((CARD_W, CARD_H), Image.LANCZOS)


def _grid(step: float, w: int, h: int, stagger: bool = True):
    """Точки сетки, симметричной относительно центра карты (рубашка одинакова при повороте на 180°)."""
    cx, cy = w / 2, h / 2
    rows = int(h / step / 2) + 2
    cols = int(w / step / 2) + 2
    for r in range(-rows, rows + 1):
        shift = step / 2 if stagger and r % 2 else 0
        for c in range(-cols, cols + 1):
            yield cx + c * step + shift, cy + r * step, r, c


def back_hearts() -> Image.Image:
    img, d, s = _canvas((247, 200, 210))
    step = mm(8.5) * s
    for x, y, r, c in _grid(step, img.width, img.height):
        col = (225, 62, 88) if (r + c) % 2 == 0 else (255, 255, 255)
        size = round(mm(4.6) * s)
        img.paste(Image.new("RGB", (size, size), col), (round(x - size / 2), round(y - size / 2)),
                  _shape(size, _heart, (0, 0, 0)).getchannel("A"))
    return _finish(img)


def back_plaid() -> Image.Image:
    img, d, s = _canvas((26, 96, 52))
    W, H = img.width, img.height
    unit = mm(9) * s
    cx, cy = W / 2, H / 2
    bands = [(0, mm(3.6) * s, (12, 62, 32, 150)), (unit / 2, mm(0.5) * s, (255, 255, 255, 170)),
             (unit / 2 + mm(1.1) * s, mm(0.35) * s, (242, 200, 64, 190)),
             (unit / 2 - mm(1.1) * s, mm(0.35) * s, (242, 200, 64, 190))]
    n = int(max(W, H) / unit) + 2
    for k in range(-n, n + 1):
        for off, width, col in bands:
            x = cx + k * unit + off
            y = cy + k * unit + off
            d.rectangle((x - width / 2, 0, x + width / 2, H), fill=col)
            d.rectangle((0, y - width / 2, W, y + width / 2), fill=col)
    # мелкая диагональная «ткань»
    for t in range(-H, W + H, max(2, round(mm(0.9) * s))):
        d.line((t, 0, t - H, H), fill=(0, 0, 0, 18), width=max(1, s))
    return _finish(img)


def back_night() -> Image.Image:
    img, d, s = _canvas((30, 38, 92))
    W, H = img.width, img.height
    top, bottom = (24, 32, 82), (70, 46, 118)
    for y in range(H // 2 + 1):  # градиент к центру и обратно — симметрично
        k = y / (H / 2)
        col = tuple(round(a + (b - a) * k) for a, b in zip(top, bottom))
        d.line((0, y, W, y), fill=col)
        d.line((0, H - 1 - y, W, H - 1 - y), fill=col)
    rnd = random.Random(11)
    for _ in range(70):  # звёзды в верхней половине, зеркально — в нижней
        x, y = rnd.uniform(0, W), rnd.uniform(0, H / 2)
        r = rnd.choice([0.25, 0.35, 0.5]) * mm(1) * s
        for px, py in ((x, y), (W - x, H - y)):
            if rnd.random() < 0.18:
                R = r * 4
                d.polygon([(px, py - R), (px + R * .22, py - R * .22), (px + R, py), (px + R * .22, py + R * .22),
                           (px, py + R), (px - R * .22, py + R * .22), (px - R, py), (px - R * .22, py - R * .22)],
                          fill=(255, 236, 170, 235))
            else:
                d.ellipse((px - r, py - r, px + r, py + r), fill=(255, 255, 255, rnd.randint(150, 255)))
    # месяц по центру
    R = mm(9) * s
    moon = Image.new("L", img.size, 0)
    ImageDraw.Draw(moon).ellipse((W / 2 - R, H / 2 - R, W / 2 + R, H / 2 + R), fill=255)
    cut = Image.new("L", img.size, 0)
    ImageDraw.Draw(cut).ellipse((W / 2 - R * .4, H / 2 - R * 1.1, W / 2 + R * 1.5, H / 2 + R * .8), fill=255)
    crescent = ImageChops.subtract(moon, cut)  # серп: круг минус смещённый круг — фон под ним не трогаем
    img.paste(Image.new("RGB", img.size, (255, 232, 160)), (0, 0), crescent)
    return _finish(img)


def back_dots() -> Image.Image:
    img, d, s = _canvas((176, 224, 205))
    r = mm(1.9) * s
    for x, y, _, _ in _grid(mm(7) * s, img.width, img.height):
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 235))
    small = mm(0.7) * s
    for x, y, _, _ in _grid(mm(7) * s, img.width, img.height):
        x2, y2 = x + mm(3.5) * s / 2, y + mm(7) * s / 2
        d.ellipse((x2 - small, y2 - small, x2 + small, y2 + small), fill=(120, 190, 165, 200))
    return _finish(img)


def back_flowers() -> Image.Image:
    img, d, s = _canvas((255, 228, 150))
    step = mm(11) * s
    for x, y, r, c in _grid(step, img.width, img.height):
        R = mm(3.2) * s
        for i in range(8):  # лепестки
            a = math.radians(i * 45 + (22.5 if (r + c) % 2 else 0))
            px, py = x + math.cos(a) * R * .62, y + math.sin(a) * R * .62
            pr = R * .42
            d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=(255, 255, 255, 255))
        cr = R * .36
        d.ellipse((x - cr, y - cr, x + cr, y + cr), fill=(244, 160, 40, 255))
    for x, y, _, _ in _grid(step, img.width, img.height):  # маленькие листики между цветами
        lx, ly = x + step / 2, y + step / 2
        lr = mm(0.9) * s
        d.ellipse((lx - lr * 1.6, ly - lr, lx + lr * 1.6, ly + lr), fill=(150, 196, 110, 220))
    return _finish(img)


BACKS = {  # ключ: (название для клиента, функция)
    "hearts": ("Сердечки", back_hearts),
    "plaid": ("Шотландка", back_plaid),
    "night": ("Звёздная ночь", back_night),
    "dots": ("Мятный горошек", back_dots),
    "flowers": ("Ромашки", back_flowers),
}
DEFAULT_BACK = "hearts"


def render_back(key: str = DEFAULT_BACK) -> Image.Image:
    return BACKS.get(key, BACKS[DEFAULT_BACK])[1]()


def back_title(key: str | None) -> str:
    return BACKS[key][0] if key in BACKS else "Классическая"


def save_back_previews(folder: Path, width: int = 240) -> list[Path]:
    """Картинки рубашек для выбора в Mini App."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for key in BACKS:
        img = render_back(key)
        img = img.resize((width, round(width * CARD_H / CARD_W)), Image.LANCZOS)
        path = folder / f"{key}.png"
        img.save(path, optimize=True)
        out.append(path)
    return out


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


def layout_sheet(cards: list[Image.Image], mirror: bool = False, bleed: int = 0) -> Image.Image:
    """mirror=True — для оборотной стороны: столбцы в зеркальном порядке,
    чтобы рубашка совпала с лицом при перевороте листа по длинной стороне.
    bleed — на сколько узор выходит за внешнюю линию реза (чтобы при неточном резе не было белой каймы)."""
    sheet = Image.new("RGB", A4, "white")
    ox, oy = _grid_origin()
    spots = []
    for i, card in enumerate(cards):
        col, row = i % COLS, i // COLS
        if mirror:
            col = COLS - 1 - col
        spots.append((card, col, row, ox + col * CARD_W, oy + row * CARD_H))
    for card, _, _, x, y in spots:
        sheet.paste(card, (x, y))
    if bleed:  # вылет — зеркальное отражение края карты, шов не виден
        rows = max(r for _, _, r, _, _ in spots)
        W, H, b = CARD_W, CARD_H, bleed
        FL, FT = Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.FLIP_TOP_BOTTOM
        for card, col, row, x, y in spots:
            left, right, top, bottom = col == 0, col == COLS - 1, row == 0, row == rows
            if left:
                sheet.paste(card.crop((0, 0, b, H)).transpose(FL), (x - b, y))
            if right:
                sheet.paste(card.crop((W - b, 0, W, H)).transpose(FL), (x + W, y))
            if top:
                sheet.paste(card.crop((0, 0, W, b)).transpose(FT), (x, y - b))
            if bottom:
                sheet.paste(card.crop((0, H - b, W, H)).transpose(FT), (x, y + H))
            for cx, cy, ok in ((0, 0, left and top), (W - b, 0, right and top), (0, H - b, left and bottom),
                               (W - b, H - b, right and bottom)):
                if ok:
                    corner = card.crop((cx, cy, cx + b, cy + b)).transpose(FL).transpose(FT)
                    sheet.paste(corner, (x - b if cx == 0 else x + W, y - b if cy == 0 else y + H))
    _draw_crop_marks(sheet)
    return sheet


def build_deck(template: DeckTemplate, photo_paths: list[Path], out_dir: Path,
               with_backs: bool = True, back: str = DEFAULT_BACK) -> list[Path]:
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
        back_img = render_back(back)
        for s in range(0, len(faces), PER_SHEET):
            count = len(faces[s:s + PER_SHEET])
            path = out_dir / f"sheet_{s // PER_SHEET + 1:02d}_back.png"
            layout_sheet([back_img] * count, mirror=True, bleed=mm(1.2)).save(path, dpi=(DPI, DPI))
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
