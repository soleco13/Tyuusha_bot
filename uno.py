"""Конструктор колоды в стиле UNO: 108 карт, цвета на выбор, фото клиента в наклонном овале карт с цифрами,
рубашка со своим текстом и фото.

Состав как в классической игре: в каждом из 4 цветов один 0, по две карты 1–9, по две «Пропуск»,
«Разворот» и «+2»; плюс 4 «Смены цвета» и 4 «+4». Фото ставятся только на карты с цифрами (76 шт.),
карты действий — с крупным знаком, чтобы их было видно издалека.
"""
from __future__ import annotations

import math
import random
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from cards import (ASSET_FONTS, CARD_H, CARD_W, DPI, PER_SHEET, Card, _heart, _shape, layout_sheet, load_photo,
                   mm)

# ---------- палитры ----------

PALETTES = {  # ключ: (название, 4 цвета карт)
    "pastel": ("Пастель", ["#4CBED4", "#9CCE4A", "#F69EBE", "#B89CE8"]),
    "classic": ("Классика", ["#E8413A", "#F6C431", "#3DAA4B", "#2F7BD9"]),
    "candy": ("Конфетная", ["#FF8FAB", "#FFC46B", "#7ED6C1", "#A79BFF"]),
    "berry": ("Ягодная", ["#D64570", "#F2A541", "#3FA796", "#6C5CE7"]),
}
DEFAULT_PALETTE = "pastel"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def clean_colors(colors) -> list[str]:
    """Четыре цвета #RRGGBB; всё неверное заменяется цветами палитры по умолчанию."""
    base = PALETTES[DEFAULT_PALETTE][1]
    if not isinstance(colors, (list, tuple)):
        return list(base)
    given = (list(colors) + [None] * 4)[:4]
    return [c.upper() if isinstance(c, str) and HEX.match(c) else base[i] for i, c in enumerate(given)]


def palette(colors: list[str] | None = None) -> list[tuple[tuple, tuple, tuple]]:
    """(основной, тёмный для контуров, светлый) для каждого из 4 цветов — оттенки считаются сами."""
    out = []
    for h in clean_colors(colors):
        base = _rgb(h)
        lum = (0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2]) / 255
        dark = _mix(base, (12, 10, 20), 0.5 + 0.18 * lum)   # у светлых цветов контур темнее — иначе не читается
        out.append((base, dark, _mix(base, (255, 255, 255), 0.82)))
    return out


SLOTS = ["0", "1", "2", "3"]   # Card.suit у цветных карт — номер цвета в палитре
WILD_BG, WILD_DARK = (44, 40, 54), (16, 14, 22)
NUMBERS = [str(n) for n in range(10)]
ACTIONS = {"skip": "Пропуск", "reverse": "Разворот", "draw2": "+2", "wild": "Смена цвета", "wild4": "+4"}
MAX_PHOTOS = 76


def deck() -> list[Card]:
    """Card.rank — «0»…«9», skip, reverse, draw2, wild, wild4; Card.suit — номер цвета (у смены цвета None)."""
    out = []
    for c in SLOTS:
        out.append(Card("0", c))
        for r in NUMBERS[1:] + ["skip", "reverse", "draw2"]:
            out += [Card(r, c), Card(r, c)]
    out += [Card("wild", None) for _ in range(4)] + [Card("wild4", None) for _ in range(4)]
    return out


# ---------- шрифт ----------

_fonts: dict[tuple[int, str], ImageFont.FreeTypeFont] = {}


def heavy_font(size: int, weight: str = "Black") -> ImageFont.FreeTypeFont:
    """Unbounded (OFL, лежит в assets/fonts): Black — цифры и надписи, Bold — подписи. Есть кириллица."""
    key = (size, weight)
    if key not in _fonts:
        path = ASSET_FONTS / "Unbounded.ttf"
        if path.exists():
            f = ImageFont.truetype(str(path), size)
            try:
                f.set_variation_by_name(weight)
            except (OSError, ValueError):
                pass
        else:  # запасной вариант, если файла нет
            from cards import rank_font
            f = rank_font(size)
        _fonts[key] = f
    return _fonts[key]


# ---------- геометрия овала ----------

OVAL_A, OVAL_B, OVAL_TILT = mm(21), mm(40), -28  # полуоси и наклон (по часовой)


def dilate(mask: Image.Image, r: float) -> Image.Image:
    """Утолщение маски на r пикселей. Толстые контуры считаем на уменьшенной маске (быстро),
    затем возвращаем размер и порогом делаем край снова чётким."""
    if r <= 0:
        return mask
    f = 1 if r <= 6 else max(1, round(r / 6))
    small = mask.resize((max(1, mask.width // f), max(1, mask.height // f)), Image.BILINEAR) if f > 1 else mask
    grown = small.filter(ImageFilter.MaxFilter(2 * math.ceil(r / f) + 1))
    if f > 1:
        grown = grown.resize(mask.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(f / 2))
        grown = grown.point(lambda v: 0 if v < 100 else 255 if v > 156 else (v - 100) * 255 // 56)
    return ImageChops.lighter(grown, mask)


@lru_cache(maxsize=32)
def _oval_mask(a: int, b: int, size=(CARD_W, CARD_H), tilt: float = OVAL_TILT) -> Image.Image:
    k = 3
    big = Image.new("L", (size[0] * k, size[1] * k), 0)
    cx, cy = big.width / 2, big.height / 2
    ImageDraw.Draw(big).ellipse((cx - a * k, cy - b * k, cx + a * k, cy + b * k), fill=255)
    return big.rotate(tilt, resample=Image.BICUBIC).resize(size, Image.LANCZOS)


def _ring(mask: Image.Image, width: int) -> Image.Image:
    """Контур снаружи маски шириной width (в пикселях)."""
    return ImageChops.subtract(dilate(mask, width), mask)


def _fill(img: Image.Image, mask: Image.Image, color) -> None:
    img.paste(Image.new("RGB", img.size, color[:3]), (0, 0), mask)


# ---------- значки (рисуются стоя, крупно, потом уменьшаются) ----------

def _arrow_pts(cx: float, cy: float, L: float, w: float, ang: float) -> list[tuple[float, float]]:
    """Толстая стрелка длиной L с центром (cx, cy), направление ang (градусы, 0 — вверх)."""
    a = math.radians(ang)
    ux, uy = math.sin(a), -math.cos(a)        # вдоль стрелки
    vx, vy = -uy, ux                           # поперёк
    head = L * .46
    tail = (cx - ux * L / 2, cy - uy * L / 2)
    neck = (cx + ux * (L / 2 - head), cy + uy * (L / 2 - head))
    tip = (cx + ux * L / 2, cy + uy * L / 2)
    return [(tail[0] + vx * w / 2, tail[1] + vy * w / 2), (neck[0] + vx * w / 2, neck[1] + vy * w / 2),
            (neck[0] + vx * w * 1.3, neck[1] + vy * w * 1.3), tip,
            (neck[0] - vx * w * 1.3, neck[1] - vy * w * 1.3), (neck[0] - vx * w / 2, neck[1] - vy * w / 2),
            (tail[0] - vx * w / 2, tail[1] - vy * w / 2)]


def _outlined(parts: list[tuple[Image.Image, tuple]], outline, ow: int) -> Image.Image:
    """Собирает значок из масок одного цвета или разных: общий контур вокруг всего, без внутренних линий."""
    S = parts[0][0].size
    union = Image.new("L", S, 0)
    for m, _ in parts:
        union = ImageChops.lighter(union, m)
    layer = Image.new("RGBA", S, (0, 0, 0, 0))
    if ow > 0:
        grown = dilate(union, ow)
        layer.paste(Image.new("RGBA", S, tuple(outline[:3]) + (255,)), (0, 0), grown)
    for m, col in parts:
        layer.paste(Image.new("RGBA", S, tuple(col[:3]) + (255,)), (0, 0), m)
    return layer


def _mask(S: int, draw) -> Image.Image:
    m = Image.new("L", (S, S), 0)
    draw(ImageDraw.Draw(m))
    return m


def symbol(kind: str, size: int, fill, outline, ow: float = 0.07, colors: list | None = None) -> Image.Image:
    """Значок действия в квадрате size×size: skip, reverse, draw2, wild4 (карты), wild (четыре цвета)."""
    S = size * 2  # рисуем вдвое крупнее и уменьшаем — контуры гладкие
    o = max(1, round(S * ow / 2))
    c = S / 2
    if kind == "skip":
        R, w = S * .36, S * .12
        ring = _mask(S, lambda d: (d.ellipse((c - R, c - R, c + R, c + R), fill=255),
                                   d.ellipse((c - R + w, c - R + w, c + R - w, c + R - w), fill=0)))
        bar = _mask(S, lambda d: d.rectangle((c - R + w / 2, c - w * .48, c + R - w / 2, c + w * .48), fill=255))
        mask = ImageChops.lighter(ring, bar.rotate(45, resample=Image.BICUBIC))
        layer = _outlined([(mask, fill)], outline, o)
    elif kind == "reverse":
        L, w = S * .56, S * .12
        # две параллельные стрелки в разные стороны, разнесённые поперёк — как знак «Разворот»
        ux, uy, vx, vy = .7071, -.7071, .7071, .7071   # вдоль (вверх-вправо) и поперёк
        dv, du = S * .15, S * .07
        up = _mask(S, lambda d: d.polygon(_arrow_pts(c - vx * dv + ux * du, c - vy * dv + uy * du, L, w, 45), fill=255))
        down = _mask(S, lambda d: d.polygon(_arrow_pts(c + vx * dv - ux * du, c + vy * dv - uy * du, L, w, 225),
                                            fill=255))
        layer = _outlined([(up, fill), (down, fill)], outline, o)
    elif kind in ("draw2", "wild4"):
        n = 2 if kind == "draw2" else 4
        cw, ch = S * (.34 if n == 2 else .25), S * (.48 if n == 2 else .36)
        fills = fill if isinstance(fill, list) else [fill] * n
        offs = [(-.09, .07), (.09, -.07)] if n == 2 else [(-.21, .15), (-.07, .05), (.07, -.05), (.21, -.15)]
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        for (dx, dy), f in zip(offs, fills):  # каждая карточка со своим контуром — видно, что их несколько
            x, y = c + dx * S, c + dy * S
            m = _mask(S, lambda d: d.rounded_rectangle((x - cw / 2, y - ch / 2, x + cw / 2, y + ch / 2), S * .04,
                                                       fill=255))
            layer.alpha_composite(_outlined([(m, f)], outline, o))
        layer = layer.rotate(-12, resample=Image.BICUBIC)
    elif kind == "wild":
        R = S * .42
        parts = []
        cols = colors or [p[0] for p in palette()]
        for i, col in enumerate(cols):
            parts.append((_mask(S, lambda d, i=i: d.pieslice((c - R, c - R, c + R, c + R), -90 + i * 90, i * 90,
                                                              fill=255)), col))
        layer = _outlined(parts, outline, o).rotate(OVAL_TILT, resample=Image.BICUBIC)
    else:
        raise ValueError(kind)
    return layer.resize((size, size), Image.LANCZOS)


# ---------- лицевая сторона ----------

def _pattern(img: Image.Image, slot: str | None) -> None:
    """Мелкий узор на цветном поле, у каждого из 4 цветов свой: клетка, горошек, сердечки, полоски."""
    d = ImageDraw.Draw(img, "RGBA")
    W, H = img.size
    step = mm(2.2)
    tint = (255, 255, 255, 34) if slot else (255, 255, 255, 14)
    if slot in ("0", None):
        for y in range(0, H, step):
            for x in range((y // step) % 2 * step, W, step * 2):
                d.rectangle((x, y, x + step - 1, y + step - 1), fill=tint)
    elif slot == "1":
        r = mm(.45)
        for y in range(0, H + step, step):
            for x in range((y // step) % 2 * step // 2, W + step, step):
                d.ellipse((x - r, y - r, x + r, y + r), fill=tint)
    elif slot == "2":
        hs = mm(1.3)
        heart = _shape(hs, _heart, (255, 255, 255)).getchannel("A").point(lambda v: v * 50 // 255)
        white = Image.new("RGB", (hs, hs), (255, 255, 255))
        for y in range(0, H + step * 2, step * 2):
            for x in range((y // (step * 2)) % 2 * step, W + step, step * 2):
                img.paste(white, (x - hs // 2, y - hs // 2), heart)
    else:
        for x in range(0, W, step):
            d.rectangle((x, 0, x + step // 2 - 1, H), fill=tint)


def _corner(card: Card, dark, light=(255, 255, 255)) -> Image.Image:
    """Угловой индекс: цифра или маленький значок, белый с тёмным контуром."""
    box = mm(13)
    layer = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    r = card.rank
    if r.isdigit() or r in ("draw2", "wild4"):
        text = {"draw2": "+2", "wild4": "+4"}.get(r, r)
        f = heavy_font(mm(8.6) if len(text) == 1 else mm(6.4))
        ImageDraw.Draw(layer).text((box / 2, box / 2), text, font=f, fill=light, anchor="mm",
                                   stroke_width=mm(.55), stroke_fill=dark)
    else:
        sym = symbol(r, mm(10.5), light, dark, ow=.1, colors=_CURRENT_BASES)
        layer.alpha_composite(sym, ((box - sym.width) // 2, (box - sym.height) // 2))
    return layer


_CURRENT_BASES: list = []


def _fit_into(photo: Image.Image, mask: Image.Image, img: Image.Image) -> None:
    bbox = mask.getbbox()
    fitted = ImageOps.fit(photo, (bbox[2] - bbox[0], bbox[3] - bbox[1]), Image.LANCZOS, centering=(0.5, 0.42))
    holder = Image.new("RGB", img.size)
    holder.paste(fitted, bbox[:2])
    img.paste(holder, (0, 0), mask)


def render_face(card: Card, photo: Image.Image | None, pal: list | None = None) -> Image.Image:
    global _CURRENT_BASES
    pal = pal or palette()
    _CURRENT_BASES = [p[0] for p in pal]
    if card.suit is not None:
        base, dark, light = pal[int(card.suit)]
    else:
        base, dark, light = WILD_BG, WILD_DARK, (250, 248, 252)
    img = Image.new("RGB", (CARD_W, CARD_H), base)
    _pattern(img, card.suit)
    d = ImageDraw.Draw(img)
    inset = mm(2.4)
    d.rounded_rectangle((inset, inset, CARD_W - inset, CARD_H - inset), mm(2.6), outline=dark, width=mm(.45))

    oval = _oval_mask(OVAL_A, OVAL_B)
    _fill(img, _ring(oval, mm(.55)), dark)
    _fill(img, oval, (255, 255, 255) if card.suit is not None else (250, 248, 252))

    r = card.rank
    if r.isdigit() and photo is not None:
        inner = _oval_mask(OVAL_A - mm(1.4), OVAL_B - mm(1.4))
        _fit_into(photo, inner, img)
        _fill(img, _ring(inner, mm(.3)), light)
    elif r.isdigit():  # без фото — крупная цифра в овале
        ImageDraw.Draw(img).text((CARD_W / 2, CARD_H / 2), r, font=heavy_font(mm(30)), fill=base, anchor="mm",
                                 stroke_width=mm(1), stroke_fill=dark)
    else:
        if r == "wild":
            big = symbol("wild", mm(33), None, dark, ow=.04, colors=_CURRENT_BASES)
        elif r == "wild4":
            big = symbol("wild4", mm(42), list(_CURRENT_BASES), dark)
        else:
            big = symbol(r, mm(36), base, dark)
        img.paste(big, ((CARD_W - big.width) // 2, (CARD_H - big.height) // 2), big)

    corner = _corner(card, dark)
    img.paste(corner, (mm(2.4), mm(2.6)), corner)
    flipped = corner.rotate(180)
    img.paste(flipped, (CARD_W - flipped.width - mm(2.4), CARD_H - flipped.height - mm(2.6)), flipped)
    return img


# ---------- рубашки: свой текст и своё фото ----------
# У каждой рубашки — фон, овал, цвета надписи и центральный рисунок по умолчанию (надпись UWU или знак «Разворот»).
# Клиент может написать своё слово (до 10 знаков) и подпись под ним (до 22 знаков) и поставить фото в овал.

TEXT_MAX, CAPTION_MAX = 12, 22
_ALLOWED = re.compile(r"[^0-9A-Za-zА-Яа-яЁё !?.,&+\-'’♥]")


def clean_text(value, limit: int) -> str:
    """Только буквы, цифры и простые знаки (их точно есть в шрифте), без лишних пробелов, не длиннее limit."""
    if not isinstance(value, str):
        return ""
    value = _ALLOWED.sub("", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit].strip()


BACK_OVAL = (mm(23.5), mm(41.5))
BACK_PHOTO_OVAL = (mm(21.3), mm(39.3))   # фото на рубашке: внутри светлого ободка

# ink — (заливка надписи, объём, контур), sym — цвета знака «Разворот» (заливка, контур)
BACK_SPECS = {
    "uwu_blush": dict(title="Пудровая UWU", bg=(216, 186, 172), oval=(247, 240, 234), ring=(247, 240, 234), ring_w=2.2,
                      outline=None, ink=((150, 140, 142), (60, 54, 56), (24, 20, 22)), center="text"),
    "uwu_sky": dict(title="Небесная UWU", bg=(206, 234, 246), oval=(255, 255, 255), ring=(246, 212, 222), ring_w=2.2,
                    outline=(40, 40, 52), ink=((196, 228, 246), (40, 60, 80), (20, 24, 34)), center="text",
                    deco="hearts3"),
    "uwu_hot": dict(title="Малиновая UWU", bg=(240, 76, 160), oval=(252, 172, 214), ring=(252, 172, 214), ring_w=2.2,
                    outline=(110, 20, 70), ink=((252, 204, 28), (226, 120, 20), (110, 40, 20)), center="text"),
    "reverse_lilac": dict(title="Сиреневый разворот", bg=(194, 164, 234), oval=(194, 164, 234), ring=(250, 248, 254),
                          ring_w=2, outline=None, ink=((255, 255, 255), (96, 64, 160), (20, 18, 26)),
                          sym=((255, 255, 255), (20, 18, 26)), center="reverse", corners=True),
    "reverse_hearts": dict(title="Разворот с сердечками", bg=(242, 214, 214), oval=(250, 232, 230),
                           ring=(255, 252, 250), ring_w=2, outline=None,
                           ink=((255, 255, 255), (208, 96, 116), (40, 24, 30)), sym=((255, 255, 255), (24, 20, 24)),
                           center="reverse", corners=True, deco="hearts"),
    "reverse_noir": dict(title="Чёрный разворот", bg=(14, 14, 16), oval=(138, 142, 138), ring=(222, 228, 222),
                         ring_w=1.8, outline=None, ink=((236, 240, 236), (96, 100, 96), (8, 8, 10)),
                         sym=((222, 228, 222), (10, 10, 12)), center="reverse", corners=True),
}
DEFAULT_BACK = "reverse_lilac"
TEXT_TILT = 24


def _text_block(text: str, caption: str, size: int, ink) -> Image.Image:
    """Слово крупно, объёмно, с контуром; подпись под ним — тоньше, белая с контуром. Без наклона."""
    fill, shade, outline = ink
    f = heavy_font(size)
    sw = max(2, size // 16)
    depth = max(2, round(size * .13))
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t, r, b = probe.textbbox((0, 0), text, font=f, anchor="ls", stroke_width=sw) if text else (0, 0, 0, 0)
    tw, th = r - l, b - t
    cap_f = heavy_font(max(mm(3.2), round(size * .3)), "Bold")
    cap_sw = max(2, cap_f.size // 9)
    cl, ct, cr, cb = probe.textbbox((0, 0), caption, font=cap_f, anchor="ls", stroke_width=cap_sw) if caption else (0, 0, 0, 0)
    gap = round(size * .16) if caption and text else 0
    W = max(tw + depth, cr - cl) + 8
    H = th + depth + gap + (cb - ct) + 8
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if text:
        x0, y0 = (W - tw - depth) / 2 - l, 4 - t
        for k in range(depth, 0, -max(1, depth // 14)):
            d.text((x0 + k * .6, y0 + k), text, font=f, fill=shade, anchor="ls", stroke_width=sw, stroke_fill=outline)
        d.text((x0, y0), text, font=f, fill=fill, anchor="ls", stroke_width=sw, stroke_fill=outline)
    if caption:
        y = 4 + th + depth + gap - ct
        d.text(((W - (cr - cl)) / 2 - cl, y), caption, font=cap_f, fill=(255, 255, 255), anchor="ls",
               stroke_width=cap_sw, stroke_fill=outline)
    return layer


def wordmark(text: str, caption: str, ink, max_w: int = CARD_W - mm(7), max_h: int = mm(56)) -> Image.Image:
    """Подбирает размер, чтобы надпись с наклоном точно поместилась на рубашку, и наклоняет её вдоль овала."""
    size = mm(17) if len(text) <= 4 else mm(15)
    while True:
        block = _text_block(text, caption, size, ink)
        rot = block.rotate(TEXT_TILT, resample=Image.BICUBIC, expand=True)
        if (rot.width <= max_w and rot.height <= max_h) or size <= mm(5):
            return rot
        size = max(mm(5), round(size * .93))


def _back_base(spec: dict) -> tuple[Image.Image, Image.Image]:
    img = Image.new("RGB", (CARD_W, CARD_H), spec["bg"])
    a, b = BACK_OVAL
    outer = _oval_mask(a, b)
    if spec.get("outline"):
        _fill(img, _ring(outer, mm(.45)), spec["outline"])
    _fill(img, outer, spec["ring"])
    inner = _oval_mask(a - mm(spec["ring_w"]), b - mm(spec["ring_w"]))
    _fill(img, inner, spec["oval"])
    if spec.get("outline"):
        _fill(img, _ring(inner, mm(.35)), spec["outline"])
    return img, inner


def _put_center(img: Image.Image, layer: Image.Image, dx: int = 0, dy: int = 0) -> None:
    img.paste(layer, ((img.width - layer.width) // 2 + dx, (img.height - layer.height) // 2 + dy), layer)


def _corner_arrows(img: Image.Image, fill, outline) -> None:
    sym = symbol("reverse", mm(11), fill, outline, ow=.1)
    img.paste(sym, (mm(3), mm(3)), sym)
    img.paste(sym, (CARD_W - sym.width - mm(3), CARD_H - sym.height - mm(3)), sym)


def _hearts(img: Image.Image, spec: dict) -> None:
    if spec.get("deco") == "hearts3":
        hs = mm(4)
        for (x, y, col) in ((.3, .74, (248, 170, 196)), (.68, .27, (250, 220, 120)), (.36, .66, (170, 210, 246))):
            img.paste(Image.new("RGB", (hs, hs), col), (round(CARD_W * x), round(CARD_H * y)),
                      _shape(hs, _heart, (0, 0, 0)).getchannel("A"))
    elif spec.get("deco") == "hearts":
        rnd = random.Random(4)
        inner = _oval_mask(mm(21), mm(39))
        for _ in range(46):
            x, y = rnd.uniform(0, CARD_W - 1), rnd.uniform(0, CARD_H - 1)
            if inner.getpixel((int(x), int(y))) < 250:
                continue
            hs = round(rnd.uniform(mm(1.6), mm(3)))
            img.paste(Image.new("RGB", (hs, hs), (222, 110, 120)), (round(x - hs / 2), round(y - hs / 2)),
                      _shape(hs, _heart, (0, 0, 0)).getchannel("A"))


def render_back(key: str = DEFAULT_BACK, text: str | None = None, caption: str | None = None,
                photo: Image.Image | None = None, blank: bool = False) -> Image.Image:
    """blank=True — только фон, овал и уголки (для превью в Mini App, куда текст и фото кладутся поверх)."""
    spec = BACK_SPECS.get(key, BACK_SPECS[DEFAULT_BACK])
    text = clean_text(text, TEXT_MAX).upper()
    caption = clean_text(caption, CAPTION_MAX)
    img, _ = _back_base(spec)
    if photo is not None:
        hole = _oval_mask(*BACK_PHOTO_OVAL)
        _fit_into(photo, hole, img)
        _fill(img, _ring(hole, mm(.35)), spec.get("outline") or spec["ring"])
    elif not blank:
        _hearts(img, spec)
    if spec.get("corners"):
        _corner_arrows(img, *spec["sym"])
    if blank:
        return img
    if text or caption:
        _put_center(img, wordmark(text, caption, spec["ink"]))
    elif photo is None:      # рисунок по умолчанию
        if spec["center"] == "text":
            _put_center(img, wordmark("UWU", "", spec["ink"]))
        else:
            _put_center(img, symbol("reverse", mm(34), *spec["sym"]))
    return img


BACKS = {k: (s["title"], (lambda k=k: render_back(k))) for k, s in BACK_SPECS.items()}


def assign_photos(cards: list[Card], n: int) -> list[int | None]:
    """Номер фото для каждой карты: только карты с цифрами, по кругу."""
    out: list[int | None] = []
    k = 0
    for c in cards:
        if c.rank.isdigit() and n:
            out.append(k % n)
            k += 1
        else:
            out.append(None)
    return out


def build_deck(photo_paths: list[Path], out_dir: Path, with_backs: bool = True, back: str = DEFAULT_BACK,
               colors: list[str] | None = None, back_text: str = "", back_caption: str = "",
               back_photo: Path | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    photos = [load_photo(p) for p in photo_paths]
    pal = palette(colors)
    cards = deck()
    order = assign_photos(cards, len(photos))
    faces = [render_face(c, photos[i] if i is not None else None, pal) for c, i in zip(cards, order)]
    paths: list[Path] = []
    for s in range(0, len(faces), PER_SHEET):
        path = out_dir / f"sheet_{s // PER_SHEET + 1:02d}_face.png"
        layout_sheet(faces[s:s + PER_SHEET], bleed=mm(1.2)).save(path, dpi=(DPI, DPI))
        paths.append(path)
    if with_backs:
        back_img = render_back(back, back_text, back_caption, load_photo(back_photo) if back_photo else None)
        for s in range(0, len(faces), PER_SHEET):
            count = len(faces[s:s + PER_SHEET])
            path = out_dir / f"sheet_{s // PER_SHEET + 1:02d}_back.png"
            layout_sheet([back_img] * count, mirror=True, bleed=mm(1.2)).save(path, dpi=(DPI, DPI))
            paths.append(path)
    return paths
