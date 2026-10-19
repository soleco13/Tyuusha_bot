"""Генерирует GIF-анимации Тюши из двух референсов в assets/.

Запуск: .venv\\Scripts\\python make_animations.py  → файлы в assets/anim/
Анимация процедурная: части картинки (лапка, облачко, лампочка, лист в принтере)
двигаются отдельно, поверх дорисовываются моргание, точки, конфетти.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
ASSETS = BASE / "assets"
OUT = ASSETS / "anim"

SIZE = 480          # сторона квадратной GIF
FRAMES = 24
FRAME_MS = 70
FUR = (254, 250, 244)
INK = (22, 22, 28)
BUBBLE = (52, 133, 232)


# ---------- базовые операции ----------

def load(name: str) -> Image.Image:
    return Image.open(ASSETS / name).convert("RGB")


def cutout(img: Image.Image) -> Image.Image:
    """Убирает белый фон (заливкой от краёв), внутренние белые области остаются."""
    marked = img.copy()
    w, h = img.size
    for x in range(0, w, 40):
        for y in (0, h - 1):
            if min(marked.getpixel((x, y))) > 225:
                ImageDraw.floodfill(marked, (x, y), (255, 0, 255), thresh=60)
    for y in range(0, h, 40):
        for x in (0, w - 1):
            if min(marked.getpixel((x, y))) > 225:
                ImageDraw.floodfill(marked, (x, y), (255, 0, 255), thresh=60)
    diff = ImageChops.difference(marked, Image.new("RGB", img.size, (255, 0, 255))).convert("L")
    alpha = diff.point(lambda v: 255 if v > 0 else 0)
    out = img.convert("RGBA")
    out.putalpha(alpha)
    return out


def region(sprite: Image.Image, polygon: list[tuple[int, int]] | None = None,
           box: tuple[int, int, int, int] | None = None, invert: bool = False) -> Image.Image:
    """Часть спрайта внутри многоугольника/прямоугольника (или всё, кроме неё)."""
    mask = Image.new("L", sprite.size, 0)
    d = ImageDraw.Draw(mask)
    if polygon:
        d.polygon(polygon, fill=255)
    if box:
        d.rectangle(box, fill=255)
    if invert:
        mask = ImageChops.invert(mask)
    part = sprite.copy()
    part.putalpha(ImageChops.multiply(sprite.getchannel("A"), mask))
    return part


def rotated(layer: Image.Image, angle: float, pivot: tuple[float, float],
            offset: tuple[float, float] = (0, 0)) -> Image.Image:
    return layer.rotate(angle, resample=Image.BICUBIC, center=pivot,
                        translate=offset)


def scaled(layer: Image.Image, k: float, pivot: tuple[float, float]) -> Image.Image:
    w, h = layer.size
    big = layer.resize((round(w * k), round(h * k)), Image.BICUBIC)
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    out.paste(big, (round(pivot[0] - pivot[0] * k), round(pivot[1] - pivot[1] * k)), big)
    return out


def faded(layer: Image.Image, opacity: float) -> Image.Image:
    out = layer.copy()
    out.putalpha(out.getchannel("A").point(lambda v: round(v * opacity)))
    return out


def shifted(layer: Image.Image, dx: float = 0, dy: float = 0) -> Image.Image:
    return layer.transform(layer.size, Image.AFFINE, (1, 0, -dx, 0, 1, -dy), resample=Image.BICUBIC)


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("seguibl.ttf", "segoeuib.ttf", "arialbd.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def blink(canvas: Image.Image, eyes: list[tuple[int, int, int, int]], dy: float = 0) -> None:
    """Закрытые глазки-дужки поверх открытых."""
    d = ImageDraw.Draw(canvas)
    for cx, cy, rx, ry in eyes:
        cy += dy
        d.ellipse((cx - rx - 6, cy - ry - 6, cx + rx + 6, cy + ry + 6), fill=FUR)
        d.arc((cx - rx, cy - ry * 0.6, cx + rx, cy + ry * 0.6), 200, 340, fill=INK, width=16)


def finish(frames: list[Image.Image], name: str, size: tuple[int, int] = (SIZE, SIZE),
           durations: list[int] | int = FRAME_MS) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    small = []
    for f in frames:
        bg = Image.new("RGB", f.size, "white")
        bg.paste(f, (0, 0), f if f.mode == "RGBA" else None)
        if bg.size != size:
            # вписываем с полями (для баннера 640×360)
            k = min(size[0] / bg.width, size[1] / bg.height)
            fit = bg.resize((round(bg.width * k), round(bg.height * k)), Image.LANCZOS)
            bg = Image.new("RGB", size, "white")
            bg.paste(fit, ((size[0] - fit.width) // 2, (size[1] - fit.height) // 2))
        small.append(bg.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    path = OUT / f"{name}.gif"
    small[0].save(path, save_all=True, append_images=small[1:], duration=durations, loop=0,
                  optimize=True, disposal=1)
    return path


# ---------- сцены с «Привет»-картинки ----------

HELLO_PAW = [(118, 700), (150, 662), (215, 648), (300, 655), (335, 700), (345, 765),
             (330, 792), (205, 862), (160, 840), (120, 770)]
HELLO_PAW_PIVOT = (262, 828)
HELLO_BUBBLE_OVAL = (716, 52, 1232, 312)
HELLO_BUBBLE_TAIL = [(975, 280), (1070, 280), (1000, 392), (978, 385)]
HELLO_BUBBLE_PIVOT = (1000, 385)
HELLO_DASHES_LEFT = (40, 560, 142, 690)
HELLO_DASHES_RIGHT = (1000, 388, 1145, 515)
HELLO_EYES = [(480, 710, 76, 80), (757, 632, 64, 78)]


def hello_parts(bubble_text: str | None = None, typing: bool = False):
    img = load("tyusha_hello.webp")
    if bubble_text is not None or typing:
        # стираем «Привет!» внутри облачка
        ImageDraw.Draw(img).ellipse((973 - 240, 181 - 110, 973 + 240, 181 + 110), fill=BUBBLE)
    sprite = cutout(img)
    paw = region(sprite, HELLO_PAW)
    # облачко = овал + хвостик (прямоугольник захватил бы край кепки и ухо)
    bubble_mask = Image.new("L", sprite.size, 0)
    bm = ImageDraw.Draw(bubble_mask)
    bm.ellipse(HELLO_BUBBLE_OVAL, fill=255)
    bm.polygon(HELLO_BUBBLE_TAIL, fill=255)
    bubble = sprite.copy()
    bubble.putalpha(ImageChops.multiply(sprite.getchannel("A"), bubble_mask))
    dashes_l = region(sprite, box=HELLO_DASHES_LEFT)
    dashes_r = region(sprite, box=HELLO_DASHES_RIGHT)
    mask = bubble_mask.copy()
    d = ImageDraw.Draw(mask)
    d.polygon(HELLO_PAW, fill=255)
    for b in (HELLO_DASHES_LEFT, HELLO_DASHES_RIGHT):
        d.rectangle(b, fill=255)
    body = sprite.copy()
    body.putalpha(ImageChops.multiply(sprite.getchannel("A"), ImageChops.invert(mask)))
    if bubble_text:
        bd = ImageDraw.Draw(bubble)
        f = font(120 if len(bubble_text) <= 6 else 96)
        bd.text((973, 178), bubble_text, font=f, fill="white", anchor="mm")
    return body, paw, bubble, dashes_l, dashes_r


def scene_hello(name: str = "hello", bubble_text: str | None = None, typing: bool = False,
                wave: float = 16, size=(SIZE, SIZE)) -> Path:
    body, paw, bubble, dl, dr = hello_parts(bubble_text, typing)
    frames = []
    for i in range(FRAMES):
        t = i / FRAMES
        dy = -8 * math.sin(2 * math.pi * t)
        frame = Image.new("RGBA", body.size, (255, 255, 255, 255))
        frame.alpha_composite(shifted(body, 0, dy))
        frame.alpha_composite(rotated(paw, wave * math.sin(4 * math.pi * t), HELLO_PAW_PIVOT, (0, dy)))
        if i in (14, 15):
            blink(frame, HELLO_EYES, dy)
        k = 1 + 0.045 * math.sin(4 * math.pi * t + 1)
        b = scaled(bubble, k, HELLO_BUBBLE_PIVOT)
        if typing:
            bd = ImageDraw.Draw(b)
            for n in range(3):
                phase = math.sin(2 * math.pi * (t * 2 - n * 0.18))
                cx, cy = 973 + (n - 1) * 95 * k, 185 - max(0, phase) * 30
                r = 30 * k
                bd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255 if phase > 0 else 170))
        frame.alpha_composite(b)
        frame.alpha_composite(faded(dl, 0.35 + 0.65 * (i // 3 % 2)))
        frame.alpha_composite(faded(dr, 0.35 + 0.65 * ((i // 3 + 1) % 2)))
        frames.append(frame)
    return finish(frames, name, size)


# ---------- сцены с логотипа (принтер) ----------

LOGO_PAPER = [(921, 664), (1050, 682), (1010, 752), (877, 731)]   # ВЛ, ВП, НП, НЛ
LOGO_LED = (950, 832, 990, 851)
LOGO_DASHES_LEFT = (135, 545, 260, 690)
LOGO_DASHES_RIGHT = (980, 505, 1110, 640)
LOGO_EYES = [(505, 560, 70, 66), (768, 500, 66, 70)]


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def warp_into(pic: Image.Image, quad: list[tuple[float, float]], size: tuple[int, int]) -> Image.Image:
    """Перспективно кладёт прямоугольную картинку в четырёхугольник quad (ВЛ, ВП, НП, НЛ)."""
    w, h = pic.size
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    rows, rhs = [], []
    for (X, Y), (x, y) in zip(quad, src):
        rows.append([X, Y, 1, 0, 0, 0, -x * X, -x * Y]); rhs.append(x)
        rows.append([0, 0, 0, X, Y, 1, -y * X, -y * Y]); rhs.append(y)
    coeffs = _solve(rows, rhs)
    return pic.transform(size, Image.PERSPECTIVE, coeffs, resample=Image.BICUBIC)


def inset_quad(quad, u0, u1, v0, v1):
    def at(u, v):
        (ax, ay), (bx, by), (cx, cy), (dx, dy) = quad
        top = (ax + (bx - ax) * u, ay + (by - ay) * u)
        bot = (dx + (cx - dx) * u, dy + (cy - dy) * u)
        return top[0] + (bot[0] - top[0]) * v, top[1] + (bot[1] - top[1]) * v
    return [at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1)]


def mini_picture() -> Image.Image:
    """Маленькая «фотография», которая печатается на листе."""
    w, h = 300, 200
    pic = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(pic)
    for y in range(h):
        k = y / h
        d.line((0, y, w, y), fill=(int(120 + 100 * k), int(190 + 50 * k), 245, 255))
    d.ellipse((215, 22, 265, 72), fill=(255, 205, 70, 255))
    d.polygon([(0, 150), (70, 60), (140, 150)], fill=(60, 90, 160, 255))
    d.polygon([(70, 60), (52, 84), (88, 84)], fill=(255, 255, 255, 255))
    d.polygon([(90, 160), (180, 45), (275, 160)], fill=(40, 70, 140, 255))
    d.polygon([(180, 45), (156, 76), (204, 76)], fill=(255, 255, 255, 255))
    d.rectangle((0, 150, w, h), fill=(80, 170, 90, 255))
    d.ellipse((60, 160, 240, 195), fill=(90, 160, 230, 255))
    return pic


def sparkle(d: ImageDraw.ImageDraw, x: float, y: float, r: float, color) -> None:
    d.polygon([(x, y - r), (x + r * 0.28, y - r * 0.28), (x + r, y), (x + r * 0.28, y + r * 0.28),
               (x, y + r), (x - r * 0.28, y + r * 0.28), (x - r, y), (x - r * 0.28, y - r * 0.28)],
              fill=color)


def scene_printing(name: str = "printing") -> Path:
    sprite = cutout(load("tyusha_logo.webp"))
    dl = region(sprite, box=LOGO_DASHES_LEFT)
    dr = region(sprite, box=LOGO_DASHES_RIGHT)
    base = region(sprite, box=LOGO_DASHES_LEFT, invert=True)
    base = region(base, box=LOGO_DASHES_RIGHT, invert=True)
    pic = mini_picture()
    area = inset_quad(LOGO_PAPER, 0.1, 0.9, 0.12, 0.92)
    total = 32
    frames = []
    for i in range(total):
        frame = Image.new("RGBA", sprite.size, (255, 255, 255, 255))
        frame.alpha_composite(base)
        progress = min(1.0, i / (total * 0.7))
        # проявляем «фото» строка за строкой, по строке едет печатающая головка
        part = pic.copy()
        rows = round(pic.height * progress)
        ImageDraw.Draw(part).rectangle((0, rows, pic.width, pic.height), fill=(0, 0, 0, 0))
        if progress < 1:
            ImageDraw.Draw(part).rectangle((0, max(0, rows - 6), pic.width, rows + 4), fill=(60, 60, 70, 255))
        frame.alpha_composite(warp_into(part, area, sprite.size))
        d = ImageDraw.Draw(frame)
        on = (i // 2) % 2 == 0 and progress < 1 or progress >= 1
        d.rounded_rectangle(LOGO_LED, 10, fill=(90, 230, 140) if progress >= 1 else
                            ((110, 200, 255) if on else (40, 90, 150)))
        if progress >= 1:
            k = (i - total * 0.7) / (total * 0.3)
            for n, (sx, sy) in enumerate([(870, 640), (1070, 650), (1000, 600), (900, 590)]):
                r = 26 * math.sin(math.pi * min(1, max(0, k * 1.4 - n * 0.15)))
                if r > 1:
                    sparkle(d, sx, sy, r, (255, 196, 40))
        if i in (8, 9):
            blink(frame, LOGO_EYES)
        frame.alpha_composite(faded(dl, 0.35 + 0.65 * (i // 3 % 2)))
        frame.alpha_composite(faded(dr, 0.35 + 0.65 * ((i // 3 + 1) % 2)))
        frames.append(frame)
    durations = [FRAME_MS] * total
    durations[-1] = 600  # пауза на готовом листе
    return finish(frames, name, durations=durations)


def scene_done(name: str = "done") -> Path:
    sprite = cutout(load("tyusha_logo.webp"))
    rnd = random.Random(7)
    colors = [(52, 133, 232), (255, 196, 40), (245, 120, 150), (90, 210, 140), (160, 110, 240)]
    confetti = [(rnd.uniform(60, 1190), rnd.uniform(-1250, 0), rnd.uniform(14, 26), rnd.choice(colors),
                 rnd.uniform(0, 360), rnd.uniform(-1, 1)) for _ in range(70)]
    frames = []
    for i in range(FRAMES):
        t = i / FRAMES
        jump = max(0.0, math.sin(2 * math.pi * t))           # прыжок в первой половине
        squash = max(0.0, -math.sin(2 * math.pi * t)) * 0.05  # приседание во второй
        frame = Image.new("RGBA", sprite.size, (255, 255, 255, 255))
        h = sprite.height
        body = sprite.resize((sprite.width, round(h * (1 - squash))), Image.BICUBIC)
        frame.alpha_composite(body, (0, round(h * squash) - round(70 * jump)))
        d = ImageDraw.Draw(frame)
        for x, y, s, c, a, sway in confetti:
            yy = (y + t * 1250) % 1250
            xx = x + 30 * math.sin(2 * math.pi * t + a)
            ang = math.radians(a + 360 * t * (1 + sway))
            dx, dy = math.cos(ang) * s, math.sin(ang) * s * 0.45
            d.polygon([(xx - dx, yy - dy), (xx + dy, yy - dx * 0.4), (xx + dx, yy + dy), (xx - dy, yy + dx * 0.4)],
                      fill=c)
        if i in (18, 19):
            blink(frame, LOGO_EYES, -70 * jump)
        frames.append(frame)
    return finish(frames, name)


def avatar() -> Path:
    img = load("tyusha_logo.webp").crop((170, 100, 1130, 1060)).resize((640, 640), Image.LANCZOS)
    path = OUT / "avatar.png"
    img.save(path)
    return path


def main() -> None:
    made = [
        scene_hello("hello"),
        scene_hello("thinking", typing=True, wave=6),
        scene_hello("oops", bubble_text="Упс…", wave=4),
        scene_printing("printing"),
        scene_done("done"),
        scene_hello("description", size=(640, 360)),
        avatar(),
    ]
    for p in made:
        print(f"{p.name}: {p.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
