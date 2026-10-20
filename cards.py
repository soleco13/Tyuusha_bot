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
    # состав, рубашки и рисунок UNO — в uno.py
    "uno": DeckTemplate("uno", "Колода UNO (108 карт, фото на картах с цифрами)", (), 0),
}


@dataclass(frozen=True)
class Card:
    rank: str            # "Т", "10", ... или "JOKER"
    suit: str | None     # None у джокера


def deck_cards(template: DeckTemplate) -> list[Card]:
    if template.key == "uno":
        import uno
        return uno.deck()
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


# --- общие фигуры для рубашек ---

def _star_pts(cx: float, cy: float, R: float, r: float, n: int = 5, rot: float = 0) -> list[tuple[float, float]]:
    pts = []
    for i in range(n * 2):
        a = math.radians(-90 + rot + i * 180 / n)
        rad = R if i % 2 == 0 else r
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    return pts


def _sparkle_pts(cx: float, cy: float, rx: float, ry: float, steps: int = 72,
                 power: float = 3) -> list[tuple[float, float]]:
    """Четырёхлучевая «искра» с вогнутыми сторонами (астроида); чем больше power, тем тоньше лучи."""
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, sn = math.cos(t), math.sin(t)
        pts.append((cx + rx * math.copysign(abs(c) ** power, c), cy + ry * math.copysign(abs(sn) ** power, sn)))
    return pts


def _bow(d: ImageDraw.ImageDraw, x: float, y: float, size: float, color, line: float = 0, rot: float = 0) -> None:
    """Бантик: две петли (лемниската Жероно), узелок и два хвостика. line=0 — залитый, иначе контур."""
    ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))

    def tr(px, py):
        return x + px * ca - py * sa, y + px * sa + py * ca

    loop = [tr(size * math.cos(t) * .5, size * math.sin(t) * math.cos(t) * .55 - size * .02)
            for t in (2 * math.pi * i / 80 for i in range(80))]
    tails = [[tr(-size * .04, size * .02), tr(-size * .2, size * .32), tr(-size * .3, size * .62)],
             [tr(size * .04, size * .02), tr(size * .16, size * .34), tr(size * .3, size * .6)]]
    if line:
        d.line(loop + [loop[0]], fill=color, width=round(line), joint="curve")
        for t in tails:
            d.line(t, fill=color, width=round(line), joint="curve")
        k = size * .07
        d.ellipse((x - k, y - k, x + k, y + k), fill=color)
    else:
        d.polygon(loop, fill=color)
        for t in tails:
            d.line(t, fill=color, width=round(size * .11), joint="curve")
        k = size * .1
        d.ellipse((x - k, y - k, x + k, y + k), fill=color)


def _paste_shape(img: Image.Image, fn, cx: float, cy: float, size: int, color) -> None:
    sh = _shape(size, fn, (0, 0, 0))
    img.paste(Image.new("RGB", (size, size), color), (round(cx - size / 2), round(cy - size / 2)), sh.getchannel("A"))


def _radial(size: tuple[int, int], inner, outer, power: float = 1.0) -> Image.Image:
    """Радиальный градиент от центра к краям (по форме карты)."""
    g = Image.radial_gradient("L").resize(size, Image.BICUBIC)  # 0 в центре, 255 по краю
    if power != 1:
        g = g.point(lambda v: round(255 * min(1, v / 255) ** power))
    return Image.composite(Image.new("RGB", size, outer), Image.new("RGB", size, inner), g)


def _pairs(rnd: random.Random, n: int, W: float, H: float):
    """Случайные точки парами, симметричными относительно центра — рубашка одинакова при повороте."""
    for _ in range(n):
        x, y = rnd.uniform(0, W), rnd.uniform(0, H / 2)
        yield (x, y), (W - x, H - y)


# --- рубашки по референсам ---

def back_bows() -> Image.Image:
    img, d, s = _canvas((74, 12, 14))
    for x, y, r, c in _grid(mm(11) * s, img.width, img.height):
        _bow(d, x, y, mm(4.2) * s, (236, 214, 200, 235), line=mm(.28) * s, rot=-8 if (r + c) % 2 else 6)
    return _finish(img)


def back_bows_mint() -> Image.Image:
    img, d, s = _canvas((214, 236, 214))
    glow = Image.new("L", img.size, 0)
    gd = ImageDraw.Draw(glow)
    for (x, y) in ((img.width * .78, img.height * .2), (img.width * .22, img.height * .8),
                   (img.width * .2, img.height * .36), (img.width * .8, img.height * .64)):
        R = mm(8) * s
        gd.ellipse((x - R, y - R, x + R, y + R), fill=230)
    img.paste(Image.new("RGB", img.size, (250, 255, 248)), (0, 0), glow.filter(ImageFilter.GaussianBlur(mm(5) * s)))
    d = ImageDraw.Draw(img, "RGBA")
    for x, y, r, c in _grid(mm(10.5) * s, img.width, img.height):
        _bow(d, x, y, mm(3.8) * s, (110, 170, 120, 240), line=mm(.3) * s, rot=-10 if (r + c) % 2 else 8)
    return _finish(img)


def back_bows_lilac() -> Image.Image:
    img, d, s = _canvas((226, 216, 242))
    for x, y, r, c in _grid(mm(10) * s, img.width, img.height):
        size = mm(5.4) * s
        rot = -14 if (r + c) % 2 else 10
        _bow(d, x + mm(.25) * s, y + mm(.35) * s, size, (70, 30, 130, 150), rot=rot)  # тень-контур
        _bow(d, x, y, size, (128, 78, 200, 255), rot=rot)
        _bow(d, x, y, size * .62, (160, 118, 225, 255), rot=rot)
    for x, y, _, _ in _grid(mm(10) * s, img.width, img.height):
        k = mm(.45) * s
        x2, y2 = x + mm(5) * s, y + mm(2.5) * s
        d.ellipse((x2 - k, y2 - k, x2 + k, y2 + k), fill=(110, 60, 180, 220))
    return _finish(img)


def back_heartwave() -> Image.Image:
    W, H = CARD_W, CARD_H
    img = Image.new("RGB", (W, H), (234, 243, 252))
    cols = [(64, 120, 196), (154, 196, 236), (234, 243, 252)]
    size = round(W * 1.9)
    k = 0
    while size > mm(4):
        _paste_shape(img, _heart, W / 2, H / 2 + size * .02, size, cols[k % 3])
        size -= mm(3.6)
        k += 1
    return img


def back_celestial(bg=(10, 10, 12), ink=(208, 156, 122)) -> Image.Image:
    img, d, s = _canvas(bg)
    W, H = img.width, img.height
    lw = max(2, round(mm(.22) * s))
    m1, m2 = mm(3.2) * s, mm(4.2) * s
    d.rounded_rectangle((m1, m1, W - m1, H - m1), mm(3) * s, outline=ink, width=lw)
    d.rounded_rectangle((m2, m2, W - m2, H - m2), mm(2.2) * s, outline=ink, width=max(1, lw // 2))
    cx, cy = W / 2, H / 2
    R = mm(17) * s
    d.line(_star_pts(cx, cy, R, R * .5, 6) + [_star_pts(cx, cy, R, R * .5, 6)[0]], fill=ink, width=lw)
    d.line(_star_pts(cx, cy, R * .82, R * .42, 6, 30) + [_star_pts(cx, cy, R * .82, R * .42, 6, 30)[0]],
           fill=ink, width=max(1, lw // 2))
    r0 = R * .2
    d.ellipse((cx - r0, cy - r0, cx + r0, cy + r0), outline=ink, width=lw)
    for i in range(8):  # бусины вокруг
        a = math.radians(i * 45)
        bx, by, br = cx + math.cos(a) * r0 * 1.45, cy + math.sin(a) * r0 * 1.45, r0 * .16
        d.ellipse((bx - br, by - br, bx + br, by + br), fill=ink)
    moon = Image.new("L", img.size, 0)
    ImageDraw.Draw(moon).ellipse((cx - r0 * .6, cy - r0 * .6, cx + r0 * .6, cy + r0 * .6), fill=255)
    cut = Image.new("L", img.size, 0)
    ImageDraw.Draw(cut).ellipse((cx - r0 * .3, cy - r0 * .75, cx + r0 * .85, cy + r0 * .5), fill=255)
    img.paste(Image.new("RGB", img.size, ink), (0, 0), ImageChops.subtract(moon, cut))
    d = ImageDraw.Draw(img, "RGBA")
    for sign in (-1, 1):  # вертикальная ось с искрами и точками
        y0 = cy + sign * R * 1.12
        y1 = cy + sign * (H / 2 - mm(9) * s)
        steps = 14
        for i in range(steps + 1):
            y = y0 + (y1 - y0) * i / steps
            k = mm(.22) * s
            d.ellipse((cx - k, y - k, cx + k, y + k), fill=ink)
        for f, size in ((.4, mm(2.8)), (.78, mm(1.9))):
            y = y0 + (y1 - y0) * f
            d.polygon(_sparkle_pts(cx, y, size * s, size * s * 1.3, power=4), fill=ink)
            k = size * s * .5
            d.ellipse((cx - k, y - k, cx + k, y + k), outline=ink, width=max(1, lw // 2))
        y = y1 + sign * mm(1.6) * s
        d.polygon(_star_pts(cx, y, mm(1.7) * s, mm(.75) * s, 5, 0 if sign < 0 else 180), outline=ink, width=lw)
    rnd = random.Random(5)
    for a, b in _pairs(rnd, 26, W, H):
        for px, py in (a, b):
            if abs(px - cx) < R * 1.1 and abs(py - cy) < R * 1.1 or px < m2 * 1.4 or px > W - m2 * 1.4 \
                    or py < m2 * 1.4 or py > H - m2 * 1.4:
                continue
            if rnd.random() < .3:
                sz = mm(1.1) * s
                d.polygon(_sparkle_pts(px, py, sz, sz), fill=ink)
            else:
                k = mm(.28) * s
                d.ellipse((px - k, py - k, px + k, py + k), fill=ink)
    return _finish(img)


def back_celestial_rose() -> Image.Image:
    return back_celestial((246, 206, 212), (182, 112, 96))


def back_cherries() -> Image.Image:
    img, d, s = _canvas((244, 246, 236))
    for x, y, r, c in _grid(mm(10) * s, img.width, img.height):
        k = s * mm(1)
        flip = -1 if (r + c) % 2 else 1
        top = (x + flip * .8 * k, y - 3.4 * k)
        berries = [(x - 1.4 * k, y + 1.1 * k), (x + 1.5 * k, y + .6 * k)]
        for bx, by in berries:
            d.line([(bx, by - k), ((bx + top[0]) / 2 + flip * .3 * k, (by + top[1]) / 2 - .4 * k), top],
                   fill=(110, 80, 40, 255), width=round(.28 * k), joint="curve")
        leaf = [(top[0] + flip * (math.cos(t) * 1.6 + 1.5) * k, top[1] + math.sin(t) * .6 * k - .3 * k)
                for t in (2 * math.pi * i / 30 for i in range(30))]
        d.polygon(leaf, fill=(104, 160, 70, 255))
        for bx, by in berries:
            R = 1.25 * k
            d.ellipse((bx - R, by - R, bx + R, by + R), fill=(204, 30, 40, 255))
            h = .35 * k
            d.ellipse((bx - R * .45 - h, by - R * .45 - h, bx - R * .45 + h, by - R * .45 + h), fill=(255, 210, 210, 210))
    return _finish(img)


def back_stars_beige() -> Image.Image:
    img, d, s = _canvas((214, 204, 184))
    W, H = img.width, img.height
    rnd = random.Random(8)
    spec = [(.18, .1, mm(13), (78, 66, 56)), (.84, .3, mm(8), (150, 120, 76)), (.2, .55, mm(5), (150, 120, 76)),
            (.6, .1, mm(4), (150, 120, 76)), (.45, .38, mm(6.5), (78, 66, 56)), (.92, .05, mm(3), (78, 66, 56))]
    for fx, fy, R, col in spec:
        rot = rnd.uniform(-20, 20)
        for (x, y, r) in ((fx * W, fy * H, rot), (W - fx * W, H - fy * H, rot + 180)):
            d.polygon(_star_pts(x, y, R * s, R * s * .45, 5, r), fill=col)
    return _finish(img)


def back_glow(inner=(150, 14, 26), outer=(255, 255, 255), dots=((196, 40, 52), (255, 255, 255)), seed=3) -> Image.Image:
    s = 2
    W, H = CARD_W * s, CARD_H * s
    img = _radial((W, H), inner, outer, power=.85)
    d = ImageDraw.Draw(img, "RGBA")
    rnd = random.Random(seed)
    for a, b in _pairs(rnd, 6, W, H):
        for px, py in (a, b):
            size = rnd.choice([mm(1.6), mm(2.4), mm(3.6)]) * s
            col = dots[rnd.random() < .4]
            d.polygon(_sparkle_pts(px, py, size * .7, size), fill=col + (215,))
    return _finish(img)


def back_glow_red() -> Image.Image:
    return back_glow()


def back_glow_blue() -> Image.Image:
    s = 2
    W, H = CARD_W * s, CARD_H * s
    img = _radial((W, H), (64, 104, 196), (242, 246, 252), power=.8)
    d = ImageDraw.Draw(img, "RGBA")
    rnd = random.Random(21)
    for a, b in _pairs(rnd, 9, W, H):
        size = rnd.choice([mm(1.4), mm(2.2), mm(3.4)]) * s
        col = (255, 255, 255, 230) if rnd.random() < .6 else (34, 60, 140, 230)
        rot = rnd.uniform(-25, 25)
        for (px, py), r in ((a, rot), (b, rot + 180)):
            d.polygon(_star_pts(px, py, size, size * .42, 5, r), fill=col)
    return _finish(img)


def back_sparkle() -> Image.Image:
    s = 2
    W, H = CARD_W * s, CARD_H * s
    img = Image.new("RGB", (W, H), (6, 4, 6))
    star = Image.new("L", (W, H), 0)
    ImageDraw.Draw(star).polygon(_sparkle_pts(W / 2, H / 2, W * .36, H * .4, 400, power=5), fill=255)
    halo = star.filter(ImageFilter.GaussianBlur(mm(3) * s)).point(lambda v: round(v * .55))
    img.paste(Image.new("RGB", (W, H), (150, 10, 24)), (0, 0), halo)
    core = _radial((W, H), (236, 46, 62), (130, 8, 22), power=.6)
    img.paste(core, (0, 0), star)
    return _finish(img)


def back_gold_stars() -> Image.Image:
    img, d, s = _canvas((12, 8, 6))
    W, H = img.width, img.height
    rnd = random.Random(14)
    for x, y, r, c in _grid(mm(10.5) * s, W, H):
        R = rnd.uniform(mm(4), mm(6.2)) * s
        rot = rnd.uniform(-30, 30)
        jx, jy = rnd.uniform(-1.6, 1.6) * mm(1) * s, rnd.uniform(-1.6, 1.6) * mm(1) * s
        for (px, py) in ((x + jx, y + jy),):
            d.polygon(_star_pts(px, py, R * 1.08, R * .5, 5, rot), fill=(120, 34, 20))
            d.polygon(_star_pts(px, py, R, R * .46, 5, rot), fill=(250, 214, 96))
            d.line(_star_pts(px, py, R * .58, R * .27, 5, rot) + [_star_pts(px, py, R * .58, R * .27, 5, rot)[0]],
                   fill=(150, 50, 24), width=max(2, round(mm(.3) * s)), joint="curve")
    return _finish(img)


def back_gingham() -> Image.Image:
    img, d, s = _canvas((255, 255, 255))
    W, H = img.width, img.height
    band = mm(3.2) * s
    cx, cy = W / 2, H / 2
    n = int(max(W, H) / band / 2) + 2
    for k in range(-n, n + 1):
        if k % 2:
            continue
        x, y = cx + k * band, cy + k * band
        d.rectangle((x - band / 2, 0, x + band / 2, H), fill=(242, 160, 178, 120))
        d.rectangle((0, y - band / 2, W, y + band / 2), fill=(242, 160, 178, 120))
    return _finish(img)


def back_forgetmenot() -> Image.Image:
    img, d, s = _canvas((250, 246, 234))
    W, H = img.width, img.height
    rnd = random.Random(31)
    for a, b in _pairs(rnd, 20, W, H):  # стебли с листиками
        ln = rnd.uniform(mm(4), mm(7)) * s
        ang = rnd.uniform(0, 360)
        for (px, py), r in ((a, ang), (b, ang + 180)):
            ex, ey = px + math.cos(math.radians(r)) * ln, py + math.sin(math.radians(r)) * ln
            d.line([(px, py), ((px + ex) / 2 + mm(.8) * s, (py + ey) / 2), (ex, ey)], fill=(132, 160, 100, 255),
                   width=max(2, round(mm(.25) * s)), joint="curve")
            lx, ly = (px + ex) / 2, (py + ey) / 2
            leaf = [(lx + math.cos(t) * mm(1.3) * s, ly + math.sin(t) * mm(.45) * s)
                    for t in (2 * math.pi * i / 24 for i in range(24))]
            d.polygon(leaf, fill=(150, 176, 112, 255))
    for x, y, r, c in _grid(mm(6.4) * s, W, H):
        jx = ((r * 7 + c * 13) % 5 - 2) * mm(.6) * s
        jy = ((r * 11 + c * 3) % 5 - 2) * mm(.6) * s
        R = (mm(1.5) if (r + c) % 3 else mm(1.1)) * s
        px, py = x + jx, y + jy
        for i in range(5):
            a = math.radians(i * 72 + (r * 17 + c * 29) % 72)
            qx, qy, pr = px + math.cos(a) * R * .55, py + math.sin(a) * R * .55, R * .48
            d.ellipse((qx - pr, qy - pr, qx + pr, qy + pr), fill=(122, 160, 214, 255))
        k = R * .22
        d.ellipse((px - k, py - k, px + k, py + k), fill=(246, 214, 110, 255))
    return _finish(img)


def back_red_hearts() -> Image.Image:
    img, d, s = _canvas((244, 232, 216))
    for x, y, r, c in _grid(mm(9) * s, img.width, img.height):
        _paste_shape(img, _heart, x, y, round(mm(3.8) * s), (150, 14, 20))
    return _finish(img)


BACKS = {  # ключ: (название для клиента, функция)
    "hearts": ("Сердечки", back_hearts),
    "heartwave": ("Сердечный тоннель", back_heartwave),
    "red_hearts": ("Красные сердца", back_red_hearts),
    "bows": ("Бантики на бордо", back_bows),
    "bows_lilac": ("Сиреневые банты", back_bows_lilac),
    "bows_mint": ("Мятные банты", back_bows_mint),
    "cherries": ("Вишенки", back_cherries),
    "gingham": ("Розовая клетка", back_gingham),
    "forgetmenot": ("Незабудки", back_forgetmenot),
    "flowers": ("Ромашки", back_flowers),
    "dots": ("Мятный горошек", back_dots),
    "plaid": ("Шотландка", back_plaid),
    "celestial": ("Звезда таро", back_celestial),
    "celestial_rose": ("Розовое таро", back_celestial_rose),
    "night": ("Звёздная ночь", back_night),
    "stars_beige": ("Большие звёзды", back_stars_beige),
    "gold_stars": ("Золотые звёзды", back_gold_stars),
    "glow_blue": ("Голубое сияние", back_glow_blue),
    "glow_red": ("Алое сияние", back_glow_red),
    "sparkle": ("Красная искра", back_sparkle),
}
DEFAULT_BACK = "hearts"


def backs_for(deck_key: str) -> dict:
    """Рубашки, доступные для колоды: у UNO свои."""
    if deck_key == "uno":
        import uno
        return uno.BACKS
    return BACKS


def default_back(deck_key: str) -> str:
    if deck_key == "uno":
        import uno
        return uno.DEFAULT_BACK
    return DEFAULT_BACK


def render_back(key: str = DEFAULT_BACK) -> Image.Image:
    import uno
    if key in uno.BACKS:
        return uno.render_back(key)
    return BACKS.get(key, BACKS[DEFAULT_BACK])[1]()


def back_title(key: str | None) -> str:
    import uno
    if key in uno.BACKS:
        return uno.BACKS[key][0]
    return BACKS[key][0] if key in BACKS else "Классическая"


def save_back_previews(folder: Path, width: int = 240) -> list[Path]:
    """Картинки рубашек для выбора в Mini App."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    import uno
    for key in uno.BACKS:  # у UNO ещё «пустая» рубашка: в Mini App на неё кладутся свой текст и фото
        img = uno.render_back(key, blank=True).resize((width, round(width * CARD_H / CARD_W)), Image.LANCZOS)
        path = folder / f"{key}_blank.png"
        img.save(path, optimize=True)
        out.append(path)
    for key in [*BACKS, *uno.BACKS]:
        img = render_back(key)
        img = img.resize((width, round(width * CARD_H / CARD_W)), Image.LANCZOS)
        path = folder / f"{key}.png"
        img.save(path, optimize=True)
        out.append(path)
    return out


# ---------- оформление «Фото на всю карту» ----------
# Фото занимает всю карту, в левом верхнем углу — маленький минималистичный индекс (ранг над мастью),
# только чёрный или белый. Пики и трефы — чёрным, черви и бубны — белым. Фото раскладываются так,
# чтобы под чёрным индексом было светлое место, а под белым — тёмное.

STYLES = {"classic": "Классическая", "full": "Фото на всю карту", "vintage": "Старинная"}
DEFAULT_STYLE = "classic"

FULL_INDEX_BOX = (0, 0, mm(17), mm(23))   # угол, где стоит индекс: по нему меряем яркость фото
INK_BLACK, INK_WHITE = (16, 16, 20), (255, 255, 255)


def serif_regular(size: int):
    return _font(("PTSerif-Regular.ttf", "georgia.ttf", "DejaVuSerif.ttf"), size)


def ink_for(card: Card) -> str | None:
    """Цвет индекса по масти; у джокера — подбирается по фото."""
    if card.suit in ("spades", "clubs"):
        return "black"
    if card.suit in ("hearts", "diamonds"):
        return "white"
    return None


def fit_full(photo: Image.Image) -> Image.Image:
    return ImageOps.fit(photo, (CARD_W, CARD_H), Image.LANCZOS, centering=(0.5, 0.45))


def corner_luminance(fitted: Image.Image) -> float:
    """Средняя яркость угла под индексом, 0 — чёрный, 1 — белый."""
    corner = fitted.crop(FULL_INDEX_BOX).convert("L")
    hist = corner.histogram()
    total = sum(hist) or 1
    return sum(i * n for i, n in enumerate(hist)) / total / 255


def assign_by_light(deck: list[Card], lums: list[float]) -> list[int]:
    """Какое фото на какой карте. Каждое фото используется почти одинаково часто;
    самые светлые варианты уходят чёрным мастям, самые тёмные — белым, джокерам — середина."""
    n, p = len(deck), len(lums)
    base, extra = divmod(n, p)
    # «лишние» использования достаются фото с самым явным светом или тенью — их проще всего поставить удачно
    decisive = set(sorted(range(p), key=lambda i: -abs(lums[i] - 0.5))[:extra])
    slots = []
    for i in range(p):
        slots += [i] * (base + (1 if i in decisive else 0))
    slots.sort(key=lambda i: -lums[i])  # от светлых к тёмным
    black = [k for k, c in enumerate(deck) if ink_for(c) == "black"]
    white = [k for k, c in enumerate(deck) if ink_for(c) == "white"]
    other = [k for k, c in enumerate(deck) if ink_for(c) is None]
    groups = [(black, slots[:len(black)]),
              (other, slots[len(black):len(black) + len(other)]),
              (white, slots[len(black) + len(other):])]
    result = [0] * n
    for cards_idx, group_slots in groups:
        # внутри группы разносим повторы: сначала каждое фото по разу, потом по второму кругу и т. д.
        seen: dict[int, int] = {}
        keyed = []
        for i in group_slots:
            keyed.append((seen.get(i, 0), -lums[i], i))
            seen[i] = seen.get(i, 0) + 1
        for k, (_, _, i) in zip(cards_idx, sorted(keyed)):
            result[k] = i
    return result


def _full_index(card: Card, ink: tuple) -> Image.Image:
    """Ранг над мастью, по центру друг под другом — тонкий засечный шрифт и небольшая масть."""
    rank = "J" if card.suit is None else card.rank
    layer = Image.new("RGBA", (mm(12), mm(16)), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = serif_regular(mm(7.4) if len(rank) == 1 else mm(6.4))
    cx = layer.width // 2
    d.text((cx, mm(0.2)), rank, font=f, fill=ink, anchor="mt")
    suit = suit_image(card.suit or "joker", mm(4.3), ink)
    top = mm(0.2) + (d.textbbox((cx, mm(0.2)), rank, font=f, anchor="mt")[3] - mm(0.2)) + mm(1.1)
    layer.alpha_composite(suit, (cx - suit.width // 2, round(top)))
    return layer


def render_card_full(card: Card, fitted: Image.Image, lum: float) -> Image.Image:
    ink_name = ink_for(card) or ("black" if lum >= 0.5 else "white")
    ink = INK_BLACK if ink_name == "black" else INK_WHITE
    img = fitted.convert("RGBA")
    # знак чистый, без теней и подложек: контраст обеспечивает раскладка фото (assign_by_light)
    img.alpha_composite(_full_index(card, ink), (mm(3.2), mm(3.0)))
    return img.convert("RGB")


# ---------- оформление «Старинная» ----------
# Как типографская колода: кремовая бумага, тонкая рамка по центру, крупный засечный индекс (ранг над мастью).
# В рамке у валета, дамы и короля — фигуры из открытой колоды SaulSpatz/SVGCards (public domain,
# фигуры Byron Knoll), заранее растеризованные в assets/vintage; у остальных карт — фото клиента.

VINTAGE_DIR = Path(__file__).resolve().parent / "assets" / "vintage"
VINTAGE_PAPER = (253, 252, 238)
VINTAGE_FRAME = (mm(13.5), round((CARD_H - mm(36) * 707 / 425) / 2), CARD_W - mm(13.5),
                 round((CARD_H + mm(36) * 707 / 425) / 2))   # рамка 36 мм, пропорции фигур колоды
COURT_FILES = {"В": "J", "Д": "Q", "К": "K"}


def is_court(card: Card) -> bool:
    return card.suit is not None and card.rank in COURT_FILES


def _vintage_index(card: Card, color) -> Image.Image:
    """Крупный индекс: ранг, под ним масть — как на картах для пасьянса и покера с «jumbo index»."""
    rank = "J" if card.suit is None else card.rank
    layer = Image.new("RGBA", (mm(11), mm(19)), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = serif_font(mm(9.4) if len(rank) == 1 else mm(7.4))
    cx = layer.width // 2
    d.text((cx, 0), rank, font=f, fill=color, anchor="mt")
    bottom = d.textbbox((cx, 0), rank, font=f, anchor="mt")[3]
    suit = suit_image(card.suit or "joker", mm(6.6), color)
    layer.alpha_composite(suit, (cx - suit.width // 2, bottom + mm(1)))
    return layer


def render_card_vintage(card: Card, photo: Image.Image | None) -> Image.Image:
    color = (RED if card.suit in ("hearts", "diamonds") else BLACK) if card.suit else JOKER_RED
    img = Image.new("RGB", (CARD_W, CARD_H), VINTAGE_PAPER)
    box = VINTAGE_FRAME
    size = (box[2] - box[0], box[3] - box[1])
    art = None
    if is_court(card):
        path = VINTAGE_DIR / f"{card.suit}_{COURT_FILES[card.rank]}.png"
        if path.exists():
            art = Image.open(path).convert("RGB").resize(size, Image.LANCZOS)
    if art is None and photo is not None:
        art = ImageOps.fit(photo, size, Image.LANCZOS, centering=(0.5, 0.42))
    if art is not None:
        img.paste(art, box[:2])
    d = ImageDraw.Draw(img)
    d.rectangle((box[0] - mm(.25), box[1] - mm(.25), box[2] + mm(.25) - 1, box[3] + mm(.25) - 1),
                outline=(20, 20, 20), width=mm(.3))
    index = _vintage_index(card, color)
    img.paste(index, (mm(2.2), mm(2.6)), index)
    flipped = index.rotate(180)
    img.paste(flipped, (CARD_W - flipped.width - mm(2.2), CARD_H - flipped.height - mm(2.6)), flipped)
    return img


def style_title(key: str | None) -> str:
    return STYLES.get(key or DEFAULT_STYLE, STYLES[DEFAULT_STYLE])


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
               with_backs: bool = True, back: str = DEFAULT_BACK, style: str = DEFAULT_STYLE,
               uno_opts: dict | None = None) -> list[Path]:
    """Рендерит всю колоду. Фото распределяются по картам по кругу.
    Возвращает пути к листам в порядке печати: сначала все лицевые, затем рубашки."""
    if template.key == "uno":
        import uno
        return uno.build_deck(photo_paths, out_dir, with_backs, back if back in uno.BACKS else uno.DEFAULT_BACK,
                              **(uno_opts or {}))
    out_dir.mkdir(parents=True, exist_ok=True)
    photos = [load_photo(p) for p in photo_paths]
    cards = deck_cards(template)
    if style == "full":  # фото на всю карту: раскладываем по свету в углу под индексом
        fitted = [fit_full(ph) for ph in photos]
        lums = [corner_luminance(f) for f in fitted]
        order = assign_by_light(cards, lums)
        faces = [render_card_full(card, fitted[k], lums[k]) for card, k in zip(cards, order)]
    elif style == "vintage":  # у фигур — рисунок колоды, фото по очереди на остальных картах
        k = 0
        faces = []
        for card in cards:
            if is_court(card):
                faces.append(render_card_vintage(card, None))
            else:
                faces.append(render_card_vintage(card, photos[k % len(photos)]))
                k += 1
    else:
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
