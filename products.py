"""Изделия конструктора на общем движке: мемори, карты для свиданий, карты желаний, наклейки,
календарь, открытки, коробка для колоды и карты для своей настольной игры.

У каждого изделия есть описание полей (по нему Mini App сама строит экран), проверка параметров,
отрисовка листов A4 для печати, быстрый образец лица и оборота для превью, расчёт цены и описание
для оператора. Двусторонние изделия печатаются как колоды: сначала все лицевые листы, затем обороты
в зеркальном порядке столбцов — после переворота стопки они совпадают.
"""
from __future__ import annotations

import calendar
import csv
import datetime as dt
import io
import math
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

import cards
import photoai
import uno
from cards import A4, DPI, load_photo, mm


class ProductError(Exception):
    """Неверные параметры изделия — текст можно показать человеку."""


# ---------- шрифты и текст ----------

def serif(size: int):
    return cards.serif_regular(size)


def serif_bold(size: int):
    return cards.serif_font(size)


def display(size: int, weight: str = "Bold"):
    return uno.heavy_font(size, weight)


def _wrap(d: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words, line = para.split(), ""
        for w in words:
            while d.textlength(w, font=font) > width and len(w) > 1:  # очень длинное слово режем
                cut = len(w)
                while cut > 1 and d.textlength(w[:cut] + "-", font=font) > width:
                    cut -= 1
                if line:
                    lines.append(line)
                    line = ""
                lines.append(w[:cut] + "-")
                w = w[cut:]
            test = f"{line} {w}".strip()
            if d.textlength(test, font=font) <= width:
                line = test
            else:
                lines.append(line)
                line = w
        lines.append(line)
    return [ln for ln in lines] or [""]


def fit_text(text: str, box: tuple[int, int], make_font, max_px: int, min_px: int, spacing: float = 1.22):
    """Подбирает самый крупный кегль, при котором текст помещается в рамку (ширина, высота)."""
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    size = max_px
    while True:
        f = make_font(size)
        lines = _wrap(d, text, f, box[0])
        if len(lines) * size * spacing <= box[1] or size <= min_px:
            return f, lines, size
        size = max(min_px, round(size * .93))


def draw_text(img: Image.Image, box: tuple[int, int, int, int], text: str, make_font, max_px: int, min_px: int,
              fill, align: str = "center", valign: str = "center", spacing: float = 1.22) -> None:
    x1, y1, x2, y2 = box
    f, lines, size = fit_text(text, (x2 - x1, y2 - y1), make_font, max_px, min_px, spacing)
    d = ImageDraw.Draw(img)
    total = len(lines) * size * spacing
    y = y1 + {"top": 0, "center": (y2 - y1 - total) / 2, "bottom": y2 - y1 - total}[valign]
    for ln in lines:
        w = d.textlength(ln, font=f)
        x = {"left": x1, "center": x1 + (x2 - x1 - w) / 2, "right": x2 - w}[align]
        d.text((x, y + size * (spacing - 1) / 2), ln, font=f, fill=fill)
        y += size * spacing


_ALLOWED = re.compile(r"[^0-9A-Za-zА-Яа-яЁё \n!?.,:;«»\"'’()\-–—+&%№#/*♥]")


def clean(value, limit: int, multiline: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    value = _ALLOWED.sub("", value.replace("\r", ""))
    if multiline:
        value = "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in value.split("\n"))
        value = re.sub(r"\n{3,}", "\n\n", value).strip()
    else:
        value = re.sub(r"\s+", " ", value).strip()
    return value[:limit].strip()


def clean_list(value, limit_items: int, limit_chars: int) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").split("\n")
    out = [clean(x, limit_chars) for x in items]
    return [x for x in out if x][:limit_items]


# ---------- раскладка на листы ----------

def _crop_marks(sheet: Image.Image, xs: list[int], ys: list[int]) -> None:
    d = ImageDraw.Draw(sheet)
    length, gap = mm(5), mm(1.5)
    for x in xs:
        d.line((x, ys[0] - gap - length, x, ys[0] - gap), fill="black", width=2)
        d.line((x, ys[-1] + gap, x, ys[-1] + gap + length), fill="black", width=2)
    for y in ys:
        d.line((xs[0] - gap - length, y, xs[0] - gap, y), fill="black", width=2)
        d.line((xs[-1] + gap, y, xs[-1] + gap + length, y), fill="black", width=2)


def layout_grid(items: list[Image.Image], size: tuple[int, int], cols: int, rows: int,
                mirror: bool = False, bleed: int = 0) -> Image.Image:
    """Карточки вплотную сеткой cols×rows по центру A4, с метками реза; mirror — для оборотов."""
    w, h = size
    sheet = Image.new("RGB", A4, "white")
    ox, oy = (A4[0] - cols * w) // 2, (A4[1] - rows * h) // 2
    used_rows = math.ceil(len(items) / cols)
    for i, im in enumerate(items):
        col, row = i % cols, i // cols
        if mirror:
            col = cols - 1 - col
        x, y = ox + col * w, oy + row * h
        if bleed:  # вылет — зеркальный край, чтобы при неточном резе не было белой каймы
            big = Image.new("RGB", (w + 2 * bleed, h + 2 * bleed))
            big.paste(im, (bleed, bleed))
            big.paste(im.crop((0, 0, bleed, h)).transpose(Image.Transpose.FLIP_LEFT_RIGHT), (0, bleed))
            big.paste(im.crop((w - bleed, 0, w, h)).transpose(Image.Transpose.FLIP_LEFT_RIGHT), (w + bleed, bleed))
            top = big.crop((0, bleed, w + 2 * bleed, 2 * bleed)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            bottom = big.crop((0, h, w + 2 * bleed, h + bleed)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            big.paste(top, (0, 0))
            big.paste(bottom, (0, h + bleed))
            # вылет только наружу сетки, внутри — соседние карточки
            left = bleed if col == 0 else 0
            right = bleed if col == cols - 1 else 0
            upper = bleed if row == 0 else 0
            lower = bleed if row == used_rows - 1 else 0
            part = big.crop((bleed - left, bleed - upper, bleed + w + right, bleed + h + lower))
            sheet.paste(part, (x - left, y - upper))
        else:
            sheet.paste(im, (x, y))
    _crop_marks(sheet, [ox + c * w for c in range(cols + 1)], [oy + r * h for r in range(used_rows + 1)])
    return sheet


def save_sheets(faces: list[Image.Image], backs: list[Image.Image] | None, size, cols, rows, out_dir: Path,
                bleed: int = 0) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    per = cols * rows
    paths = []
    for s in range(0, len(faces), per):
        p = out_dir / f"sheet_{s // per + 1:02d}_face.png"
        layout_grid(faces[s:s + per], size, cols, rows, bleed=bleed).save(p, dpi=(DPI, DPI))
        paths.append(p)
    if backs is not None:
        for s in range(0, len(faces), per):
            p = out_dir / f"sheet_{s // per + 1:02d}_back.png"
            layout_grid(backs[s:s + per], size, cols, rows, mirror=True, bleed=bleed).save(p, dpi=(DPI, DPI))
            paths.append(p)
    return paths


def pattern_back(key: str, size: tuple[int, int], title: str = "") -> Image.Image:
    """Рубашка из коллекции обычных колод под нужный размер, по желанию — с надписью на плашке."""
    base = cards.render_back(key if key in cards.BACKS else cards.DEFAULT_BACK)
    img = ImageOps.fit(base, size, Image.LANCZOS)
    if title:
        pill_plate(img, title)
    return img


def pill_plate(img: Image.Image, text: str, rel_w: float = .78, y_rel: float = .5) -> None:
    """Аккуратная светлая плашка с надписью по центру — читается на любом узоре."""
    W, H = img.size
    f, lines, size = fit_text(text, (int(W * rel_w) - mm(6), int(H * .3)), lambda s: display(s, "Bold"),
                              mm(5.2), mm(2.6), 1.18)
    d = ImageDraw.Draw(img, "RGBA")
    widths = [d.textlength(ln, font=f) for ln in lines]
    bw, bh = max(widths) + mm(8), len(lines) * size * 1.18 + mm(5)
    x1, y1 = (W - bw) / 2, H * y_rel - bh / 2
    d.rounded_rectangle((x1, y1, x1 + bw, y1 + bh), radius=min(bh / 2, mm(6)), fill=(255, 255, 255, 236),
                        outline=(40, 34, 48, 60), width=max(1, mm(.2)))
    y = y1 + mm(2.5)
    for ln, w in zip(lines, widths):
        d.text(((W - w) / 2, y + size * .09), ln, font=f, fill=(36, 30, 44))
        y += size * 1.18


# ---------- описания полей (по ним строится экран в Mini App) ----------

def _back_field(default: str = "hearts") -> dict:
    return {"key": "back", "type": "back", "label": "Рубашка", "default": default}


SETS = {  # наборы вопросов для карт свиданий
    "meet": ("Знакомство", (248, 226, 214), [
        "Что тебя сегодня порадовало?", "Какое место в городе — твоё?", "Какую книгу ты бы посоветовал(а) всем?",
        "Каким ты был(а) в детстве?", "Какой навык хочешь освоить в этом году?", "Чай или кофе — и почему?",
        "Лучший подарок, который тебе дарили?", "Куда бы ты поехал(а) прямо завтра?", "Какая песня у тебя на повторе?",
        "Что тебя всегда смешит?", "Идеальное воскресенье — какое оно?", "Что ты умеешь лучше всех?",
        "Какой фильм пересматриваешь снова и снова?", "Сова или жаворонок?", "Чем ты гордишься?",
        "Какое блюдо готовишь лучше всего?", "Кем мечтал(а) стать в детстве?", "Что бы ты сделал(а) с лишним часом в день?"]),
    "couple": ("Для пар", (246, 214, 222), [
        "Когда ты понял(а), что я тебе нравлюсь?", "Наше самое смешное воспоминание?", "Что во мне тебя удивило?",
        "Какой наш день ты вспоминаешь чаще всего?", "Куда мы обязательно поедем вместе?", "Какая песня — про нас?",
        "Что я делаю, от чего тебе становится тепло?", "Какой у нас идеальный вечер дома?", "Что нам стоит попробовать вдвоём?",
        "Чему ты научился(ась) рядом со мной?", "Какое моё качество ты бы хотел(а) себе?", "Наша маленькая традиция?",
        "Что ты помнишь о нашем первом свидании?", "Как бы ты описал(а) нас тремя словами?", "Чем я тебя рассмешил(а) недавно?",
        "О чём ты хочешь, чтобы я спрашивал(а) чаще?", "Какой подарок от меня тебе запомнился?", "Что мы сделаем через 10 лет?"]),
    "deep": ("Глубокие", (220, 226, 244), [
        "Что для тебя значит быть счастливым?", "Какой совет ты дал(а) бы себе пять лет назад?", "Чего ты боишься больше всего?",
        "Что ты никогда не перестанешь ценить?", "Какой момент изменил твою жизнь?", "За что ты благодарен(на) сегодня?",
        "Что ты прощаешь себе с трудом?", "Какая мечта у тебя осталась с детства?", "Кто повлиял на тебя сильнее всех?",
        "Когда ты чувствуешь себя собой?", "Что для тебя дом?", "Какую привычку ты хочешь оставить в прошлом?",
        "О чём ты думаешь перед сном?", "Что делает человека близким?", "Какой урок ты получил(а) недавно?",
        "Что ты хочешь успеть в этой жизни?", "Когда ты последний раз плакал(а) от радости?", "Что тебе важно услышать от близких?"]),
    "fun": ("Весёлые", (226, 240, 214), [
        "Какую суперсилу ты выберешь?", "Если бы ты был(а) едой — какой?", "Самая странная вещь, которую ты покупал(а)?",
        "Твой фирменный танцевальный приём?", "Какое животное тебе подходит и почему?", "Изобрети новый праздник!",
        "Самая нелепая ситуация из твоей жизни?", "Какой мем — это ты?", "Что бы ты сделал(а), став невидимкой на день?",
        "Спой строчку из любимой песни!", "Какую профессию ты бы выбрал(а) на один день?", "Твоё самое бесполезное умение?",
        "Если бы у тебя был остров — как бы ты его назвал(а)?", "Какой предмет ты взял(а) бы на необитаемый остров?",
        "Изобрази любимого героя мультфильма!", "Самый смешной подарок в твоей жизни?", "Пицца с ананасами: да или нет?",
        "Придумай нам общее прозвище!"]),
}

PRODUCTS: dict[str, dict] = {
    "memory": {
        "title": "Мемори с вашими фото", "sub": "Найди пару: от 6 до 24 пар карточек 63×63 мм",
        "duplex": True, "paper": "craft",
        "fields": [
            {"key": "photos", "type": "photos", "label": "Фото — каждое станет парой карточек", "min": 6, "max": 24},
            {"key": "frame", "type": "select", "label": "Карточка", "default": "none",
             "options": [["none", "Фото до краёв"], ["white", "С белой рамкой"]]},
            _back_field("heartwave"),
        ],
    },
    "dates": {
        "title": "Карты для свиданий", "sub": "Вопросы для двоих — готовые наборы и свои",
        "duplex": True, "paper": "craft",
        "fields": [
            {"key": "sets", "type": "multi", "label": "Наборы вопросов", "default": ["meet", "couple"],
             "options": [[k, f"{t} · {len(q)}"] for k, (t, _, q) in SETS.items()]},
            {"key": "own", "type": "lines", "label": "Свои вопросы — каждый с новой строки", "max_items": 27,
             "max_chars": 110, "placeholder": "Что ты помнишь о нашем первом лете?"},
            {"key": "title", "type": "text", "label": "Надпись на рубашке", "max": 24, "default": "Вопросы для двоих"},
            _back_field("red_hearts"),
        ],
    },
    "wishes": {
        "title": "Карты желаний", "sub": "Ваши желания и пустые карточки, чтобы вписать от руки",
        "duplex": True, "paper": "craft",
        "fields": [
            {"key": "wishes", "type": "lines", "label": "Желания — каждое с новой строки", "max_items": 54,
             "max_chars": 120, "placeholder": "Завтрак в постель\nВечер без телефонов"},
            {"key": "blank", "type": "number", "label": "Пустых карточек, чтобы вписать от руки", "min": 0, "max": 27,
             "default": 9},
            {"key": "title", "type": "text", "label": "Надпись на рубашке", "max": 24, "default": "Карта желаний"},
            _back_field("bows"),
        ],
    },
    "stickers": {
        "title": "Наклейки из фото", "sub": "Вырежем фон и сделаем белую обводку",
        "duplex": False, "paper": "stickers",
        "fields": [
            {"key": "photos", "type": "photos", "label": "Фото для наклеек", "min": 1, "max": 20},
            {"key": "shape", "type": "select", "label": "Форма", "default": "cut",
             "options": [["cut", "По контуру"], ["circle", "Круг"], ["rounded", "Скруглённый квадрат"]]},
            {"key": "size", "type": "select", "label": "Размер", "default": "m",
             "options": [["s", "Маленькие · 4 см"], ["m", "Средние · 6 см"], ["l", "Большие · 8 см"]]},
            {"key": "copies", "type": "number", "label": "Копий каждой наклейки", "min": 1, "max": 6, "default": 2},
        ],
    },
    "calendar": {
        "title": "Фотокалендарь", "sub": "12 месяцев и обложка, листы A4",
        "duplex": False, "paper": "calendar",
        "fields": [
            {"key": "photos", "type": "photos", "label": "Фото: по одному на месяц, первое — на обложку", "min": 1, "max": 13},
            {"key": "year", "type": "select", "label": "Год", "default": "next", "options": "years"},
            {"key": "start", "type": "select", "label": "С какого месяца", "default": "1",
             "options": [[str(i + 1), m] for i, m in enumerate(
                 ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь",
                  "Ноябрь", "Декабрь"])]},
            {"key": "title", "type": "text", "label": "Надпись на обложке", "max": 30, "default": "Наш год"},
            {"key": "accent", "type": "select", "label": "Цвет акцентов", "default": "rose",
             "options": [["rose", "Розовый"], ["sky", "Голубой"], ["sage", "Шалфей"], ["mono", "Графит"]]},
        ],
    },
    "postcards": {
        "title": "Открытки", "sub": "Фото на лицевой стороне, на обороте — ваш текст",
        "duplex": True, "paper": "craft",
        "fields": [
            {"key": "photos", "type": "photos", "label": "Фото — каждое станет открыткой", "min": 1, "max": 20},
            {"key": "greeting", "type": "text", "label": "Надпись на фото (необязательно)", "max": 34,
             "placeholder": "С днём рождения!"},
            {"key": "message", "type": "textarea", "label": "Текст на обороте (необязательно)", "max": 300,
             "placeholder": "Пусть этот год будет самым тёплым…"},
            {"key": "copies", "type": "number", "label": "Копий каждой открытки", "min": 1, "max": 10, "default": 1},
        ],
    },
    "box": {
        "title": "Коробка для колоды", "sub": "Развёртка из картона: вырезать, согнуть, склеить",
        "duplex": False, "paper": "craft",
        "fields": [
            {"key": "photos", "type": "photos", "label": "Фото на лицевую сторону", "min": 1, "max": 1},
            {"key": "deck", "type": "select", "label": "Для какой колоды", "default": "deck36",
             "options": [["deck36", "36 карт"], ["deck54", "54 карты"]]},
            {"key": "title", "type": "text", "label": "Надпись", "max": 22, "default": "Наша колода"},
            {"key": "copies", "type": "number", "label": "Сколько коробок", "min": 1, "max": 5, "default": 1},
            _back_field("hearts"),
        ],
    },
    "game": {
        "title": "Карты для своей игры", "sub": "Из таблицы CSV: название, текст, картинка, количество",
        "duplex": True, "paper": "craft",
        "fields": [
            {"key": "csv", "type": "csv", "label": "Таблица карт (CSV)", "sample": "sample_game.csv"},
            {"key": "photos", "type": "photos", "label": "Картинки для карт (имена файлов — как в таблице)",
             "min": 0, "max": 60},
            {"key": "title", "type": "text", "label": "Название игры на рубашке", "max": 24, "default": ""},
            _back_field("celestial"),
        ],
    },
}


def schema() -> list[dict]:
    """Описание изделий для Mini App: поля, подсказки, выбор бумаги."""
    import materials
    year = dt.date.today().year
    out = []
    for key, p in PRODUCTS.items():
        fields = []
        for f in p["fields"]:
            f = dict(f)
            if f.get("options") == "years":
                f["options"] = [["this", str(year)], ["next", str(year + 1)]]
            fields.append(f)
        out.append({"key": key, "title": p["title"], "sub": p["sub"], "duplex": p["duplex"], "fields": fields,
                    "papers": materials.choices_for("craft", p["paper"] if p["paper"] != "craft" else None)})
    return out


# ---------- проверка параметров ----------

def validate(product: str, meta: dict, n_photos: int, csv_text: str | None = None) -> dict:
    if product not in PRODUCTS:
        raise ProductError("Неизвестное изделие")
    spec = PRODUCTS[product]
    params: dict = {"product": product}
    for f in spec["fields"]:
        k, t, v = f["key"], f["type"], meta.get(f["key"])
        if t == "photos":
            if not f["min"] <= n_photos <= f["max"]:
                raise ProductError(f"Нужно от {f['min']} до {f['max']} фото" if f["max"] > 1 else "Нужно одно фото")
        elif t == "select":
            opts = [o[0] for o in (f["options"] if f["options"] != "years" else [["this"], ["next"]])]
            params[k] = v if v in opts else f["default"]
        elif t == "multi":
            opts = [o[0] for o in f["options"]]
            params[k] = [x for x in (v or []) if x in opts] if isinstance(v, list) else list(f["default"])
        elif t == "lines":
            params[k] = clean_list(v, f["max_items"], f["max_chars"])
        elif t == "text":
            params[k] = clean(v if v is not None else f.get("default", ""), f["max"])
        elif t == "textarea":
            params[k] = clean(v or "", f["max"], multiline=True)
        elif t == "number":
            try:
                params[k] = min(f["max"], max(f["min"], int(v if v is not None else f["default"])))
            except (TypeError, ValueError):
                params[k] = f["default"]
        elif t == "back":
            params[k] = v if v in cards.BACKS else f["default"]
        elif t == "csv":
            params["rows"] = parse_csv(csv_text or "")
    if product == "dates" and not (params["sets"] or params["own"]):
        raise ProductError("Выберите хотя бы один набор или напишите свои вопросы")
    if product == "wishes" and not (params["wishes"] or params["blank"]):
        raise ProductError("Напишите хотя бы одно желание или добавьте пустые карточки")
    if product == "game" and not params["rows"]:
        raise ProductError("В таблице нет ни одной карты: проверьте, что есть столбец «название» или «текст»")
    params["count"] = item_count(params, n_photos)
    params["sheets"] = sheet_count(params, n_photos)
    return params


def item_count(params: dict, n_photos: int) -> int:
    p = params["product"]
    if p == "memory":
        return n_photos * 2
    if p == "dates":
        return len(_questions(params))
    if p == "wishes":
        return len(params["wishes"]) + params["blank"]
    if p == "stickers":
        return n_photos * params["copies"]
    if p == "calendar":
        return 13
    if p == "postcards":
        return n_photos * params["copies"]
    if p == "box":
        return params["copies"]
    if p == "game":
        return sum(r["count"] for r in params["rows"])
    return 0


def sheet_count(params: dict, n_photos: int) -> int:
    p, n = params["product"], params.get("count") or item_count(params, n_photos)
    if p == "memory":
        return math.ceil(n / 12)
    if p in ("dates", "wishes", "game"):
        return math.ceil(n / 9)
    if p == "stickers":
        return params.get("sticker_sheets") or max(1, math.ceil(n / STICKERS_PER_SHEET[params["size"]]))
    if p == "calendar":
        return 13
    if p == "postcards":
        return math.ceil(n / 4)
    if p == "box":
        return n
    return 1


def sides(params: dict) -> int:
    return params["sheets"] * (2 if PRODUCTS[params["product"]]["duplex"] else 1)


def price(params: dict, prices: dict) -> tuple[int, str]:
    p, n, sheets = params["product"], params["count"], params["sheets"]
    title = PRODUCTS[p]["title"]
    if p == "memory":
        pairs = n // 2
        rub = prices["memory_base"] + prices["memory_pair"] * pairs
        return rub, f"{title}: {pairs} пар — {rub} ₽"
    if p in ("dates", "wishes", "game"):
        unit = prices[f"{p}_sheet"]
        return unit * sheets, f"{title}: {n} карт, {sheets} л. × {unit} ₽"
    if p == "stickers":
        unit = prices["stickers_sheet"]
        return unit * sheets, f"{title}: {n} шт., {sheets} л. × {unit} ₽"
    if p == "calendar":
        return prices["calendar"], f"{title} — {prices['calendar']} ₽"
    if p == "postcards":
        unit = prices["postcard"]
        return unit * n, f"{title}: {n} × {unit} ₽"
    if p == "box":
        unit = prices["box"]
        return unit * n, f"{title}: {n} × {unit} ₽"
    return 0, title


def describe(params: dict) -> list[str]:
    p = params["product"]
    lines = [f"{PRODUCTS[p]['title']}: {params['count']} шт."]
    if p == "memory":
        lines.append(f"Пар: {params['count'] // 2}, карточка: {'с белой рамкой' if params['frame'] == 'white' else 'фото до краёв'}")
    if p == "dates":
        lines.append("Наборы: " + (", ".join(SETS[s][0] for s in params["sets"]) or "—") +
                     (f"; своих вопросов: {len(params['own'])}" if params["own"] else ""))
    if p == "wishes":
        lines.append(f"Желаний: {len(params['wishes'])}, пустых: {params['blank']}")
    if p == "stickers":
        lines.append(f"Форма: {dict(PRODUCTS['stickers']['fields'][1]['options'])[params['shape']]}, "
                     f"размер: {STICKER_MM[params['size']]} мм, копий: {params['copies']}")
    if p == "calendar":
        lines.append(f"Год: {_year(params)}, с месяца: {params['start']}, обложка: «{params['title']}»")
    if p == "postcards":
        lines.append(f"Надпись: «{params['greeting']}»" if params["greeting"] else "Без надписи на фото")
    if p == "box":
        lines.append(f"Для колоды: {'36' if params['deck'] == 'deck36' else '54'} карты, надпись: «{params['title']}»")
    if params.get("title") and p in ("dates", "wishes", "game"):
        lines.append(f"Надпись на рубашке: «{params['title']}»")
    if params.get("back"):
        lines.append(f"Рубашка: {cards.back_title(params['back'])}")
    return lines


# ---------- мемори ----------

MEMO = (mm(63), mm(63))


def memory_face(photo: Image.Image | None, frame: str) -> Image.Image:
    w, h = MEMO
    if frame == "white":
        img = Image.new("RGB", MEMO, "white")
        inner = (w - mm(7), h - mm(7))
        pic = photoai.fit(photo, inner) if photo else Image.new("RGB", inner, (230, 232, 238))
        mask = cards._rounded_mask(inner, mm(2.4))
        img.paste(pic, (mm(3.5), mm(3.5)), mask)
        return img
    return photoai.fit(photo, MEMO) if photo else Image.new("RGB", MEMO, (230, 232, 238))


def build_memory(params, photos, out_dir):
    faces, backs = [], []
    back = pattern_back(params["back"], MEMO)
    for ph in photos:
        face = memory_face(ph, params["frame"])
        faces += [face, face]
        backs += [back, back]
    return save_sheets(faces, backs, MEMO, 3, 4, out_dir, bleed=mm(1.2) if params["frame"] == "none" else 0)


# ---------- карты с текстом: свидания и желания ----------

CARD = (cards.CARD_W, cards.CARD_H)


def _questions(params: dict) -> list[tuple[str, str]]:
    out = [(s, q) for s in params.get("sets", []) for q in SETS[s][2]]
    out += [("own", q) for q in params.get("own", [])]
    return out


def question_face(text: str, set_key: str, n: int, total: int) -> Image.Image:
    title, color = (SETS[set_key][0], SETS[set_key][1]) if set_key in SETS else ("Свой вопрос", (240, 232, 214))
    img = Image.new("RGB", CARD, color)
    d = ImageDraw.Draw(img)
    W, H = CARD
    d.rounded_rectangle((mm(3.5), mm(3.5), W - mm(3.5), H - mm(3.5)), mm(3), outline=(255, 255, 255), width=mm(.6))
    lab = display(mm(2.6), "Bold")
    d.text((W / 2, mm(9)), title.upper(), font=lab, fill=(70, 60, 80), anchor="mm")
    d.text((W / 2, mm(19)), "“", font=serif_bold(mm(16)), fill=(255, 255, 255), anchor="mm")
    draw_text(img, (mm(8), mm(24), W - mm(8), H - mm(16)), text, serif_bold, mm(6.4), mm(3.4), (40, 34, 48))
    d.text((W / 2, H - mm(9)), f"{n} / {total}", font=display(mm(2.4), "Medium"), fill=(110, 100, 120), anchor="mm")
    return img


def wish_face(text: str) -> Image.Image:
    img = Image.new("RGB", CARD, (252, 246, 238))
    d = ImageDraw.Draw(img)
    W, H = CARD
    d.rounded_rectangle((mm(3.5), mm(3.5), W - mm(3.5), H - mm(3.5)), mm(3), outline=(232, 196, 196), width=mm(.6))
    heart = cards.suit_image("hearts", mm(6), (222, 96, 112))
    img.paste(heart, ((W - heart.width) // 2, mm(9)), heart)
    d.text((W / 2, mm(20)), "Я ЖЕЛАЮ", font=display(mm(2.8), "Bold"), fill=(150, 90, 100), anchor="mm")
    if text:
        draw_text(img, (mm(8), mm(26), W - mm(8), H - mm(12)), text, serif_bold, mm(6.8), mm(3.4), (60, 40, 48))
    else:  # пустая карточка с линейками — вписать от руки
        for i in range(6):
            y = mm(34) + i * mm(8)
            for x in range(mm(9), W - mm(9), mm(2.2)):
                d.line((x, y, x + mm(1.1), y), fill=(214, 184, 188), width=mm(.25))
    return img


def build_textcards(params, out_dir):
    title = params.get("title") or ""
    if params["product"] == "dates":
        qs = _questions(params)
        faces = [question_face(q, s, i + 1, len(qs)) for i, (s, q) in enumerate(qs)]
    else:
        faces = [wish_face(t) for t in params["wishes"]] + [wish_face("") for _ in range(params["blank"])]
    back = pattern_back(params["back"], CARD, title)
    return save_sheets(faces, [back] * len(faces), CARD, 3, 3, out_dir, bleed=mm(1.2))


# ---------- наклейки ----------

STICKER_MM = {"s": 40, "m": 60, "l": 80}
STICKERS_PER_SHEET = {"s": 20, "m": 9, "l": 6}
STICKER_MARGIN, STICKER_GAP = mm(9), mm(3)


def sticker(photo: Image.Image, shape: str, size_mm: int) -> Image.Image:
    """Наклейка RGBA: фото, белая обводка 2 мм и тонкая серая линия реза снаружи."""
    side = mm(size_mm)
    border, line = mm(2), max(2, mm(.25))
    if shape == "cut":
        mask = photoai.cutout_mask(photo)
        if mask is None or mask.getbbox() is None or sum(mask.histogram()[128:]) < mask.width * mask.height * .03:
            shape = "rounded"  # не нашли объект — делаем аккуратный квадрат
        else:
            box = mask.getbbox()
            photo, mask = photo.crop(box), mask.crop(box)
            k = (side - 2 * border) / max(photo.size)
            size = (max(1, round(photo.width * k)), max(1, round(photo.height * k)))
            photo, mask = photo.resize(size, Image.LANCZOS), mask.resize(size, Image.LANCZOS)
            pad = border + line + 2
            canvas_size = (size[0] + 2 * pad, size[1] + 2 * pad)
            m = Image.new("L", canvas_size, 0)
            m.paste(mask, (pad, pad))
            # обводка: утолщаем маску и сглаживаем, чтобы контур был плавным, без «зубчиков»
            white = uno.dilate(m, border).filter(ImageFilter.GaussianBlur(border / 3)).point(lambda v: 255 if v > 110 else 0)
            white = white.filter(ImageFilter.GaussianBlur(1))
            cut = uno.dilate(white, line)
            img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            img.paste((178, 178, 184, 255), (0, 0), cut)
            img.paste((255, 255, 255, 255), (0, 0), white)
            holder = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            holder.paste(photo.convert("RGBA"), (pad, pad))
            img.paste(holder, (0, 0), m)
            return img
    inner = side - 2 * border
    if shape == "circle":
        pic = photoai.fit(photo, (inner, inner))
        mask = Image.new("L", (inner * 4, inner * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, inner * 4 - 1, inner * 4 - 1), fill=255)
        mask = mask.resize((inner, inner), Image.LANCZOS)
        radius_outer = None
    else:
        ratio = min(1.5, max(1 / 1.5, photo.width / photo.height))
        w, h = (inner, round(inner / ratio)) if ratio >= 1 else (round(inner * ratio), inner)
        pic = photoai.fit(photo, (w, h))
        mask = cards._rounded_mask((w, h), mm(3))
        radius_outer = mm(3) + border
    pw, ph = pic.size
    full = (pw + 2 * border + 2 * line, ph + 2 * border + 2 * line)
    img = Image.new("RGBA", full, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if shape == "circle":
        d.ellipse((0, 0, full[0] - 1, full[1] - 1), fill=(178, 178, 184, 255))
        d.ellipse((line, line, full[0] - 1 - line, full[1] - 1 - line), fill=(255, 255, 255, 255))
    else:
        d.rounded_rectangle((0, 0, full[0] - 1, full[1] - 1), radius_outer + line, fill=(178, 178, 184, 255))
        d.rounded_rectangle((line, line, full[0] - 1 - line, full[1] - 1 - line), radius_outer, fill=(255, 255, 255, 255))
    img.paste(pic.convert("RGBA"), (border + line, border + line), mask)
    return img


def pack_stickers(items: list[Image.Image]) -> list[Image.Image]:
    """Раскладка «полками»: ряд за рядом, крупные сначала; не влезло — новый лист."""
    area_w, area_h = A4[0] - 2 * STICKER_MARGIN, A4[1] - 2 * STICKER_MARGIN
    order = sorted(items, key=lambda im: -im.height)
    sheets, placed = [], []
    x = y = row_h = 0
    for im in order:
        if x + im.width > area_w:
            x, y, row_h = 0, y + row_h + STICKER_GAP, 0
        if y + im.height > area_h:
            sheets.append(placed)
            placed, x, y, row_h = [], 0, 0, 0
        placed.append((im, x, y))
        x += im.width + STICKER_GAP
        row_h = max(row_h, im.height)
    if placed:
        sheets.append(placed)
    pages = []
    for group in sheets:
        page = Image.new("RGB", A4, "white")
        # выравниваем ряды по центру листа по горизонтали
        for im, px, py in group:
            page.paste(im, (STICKER_MARGIN + px, STICKER_MARGIN + py), im)
        pages.append(page)
    return pages


def build_stickers(params, photos, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for ph in photos:
        st = sticker(ph, params["shape"], STICKER_MM[params["size"]])
        items += [st] * params["copies"]
    pages = pack_stickers(items)
    paths = []
    for i, page in enumerate(pages):
        p = out_dir / f"page_{i + 1:02d}.png"
        page.save(p, dpi=(DPI, DPI))
        paths.append(p)
    params["sticker_sheets"] = len(paths)
    params["sheets"] = len(paths)
    return paths


# ---------- календарь ----------

MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь",
          "Декабрь"]
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
HOLIDAYS = {(1, d) for d in range(1, 9)} | {(2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)}
ACCENTS = {"rose": (214, 92, 120), "sky": (64, 132, 196), "sage": (104, 140, 104), "mono": (52, 52, 60)}


def _year(params: dict) -> int:
    return dt.date.today().year + (1 if params.get("year") == "next" else 0)


def calendar_cover(photo, title: str, year: int, accent) -> Image.Image:
    page = Image.new("RGB", A4, "white")
    margin = mm(10)
    box = (margin, margin, A4[0] - margin, A4[1] - mm(62))
    size = (box[2] - box[0], box[3] - box[1])
    pic = photoai.fit(photo, size) if photo else Image.new("RGB", size, (232, 232, 236))
    page.paste(pic, box[:2], cards._rounded_mask(size, mm(5)))
    d = ImageDraw.Draw(page)
    d.text((A4[0] / 2, A4[1] - mm(38)), str(year), font=display(mm(22), "Black"), fill=accent, anchor="mm")
    if title:
        draw_text(page, (margin, A4[1] - mm(26), A4[0] - margin, A4[1] - mm(12)), title, lambda s: display(s, "Bold"),
                  mm(8), mm(4), (40, 36, 48))
    return page


def calendar_month(photo, year: int, month: int, accent) -> Image.Image:
    page = Image.new("RGB", A4, "white")
    margin = mm(10)
    photo_h = mm(150)
    size = (A4[0] - 2 * margin, photo_h)
    pic = photoai.fit(photo, size) if photo else Image.new("RGB", size, (232, 232, 236))
    page.paste(pic, (margin, margin), cards._rounded_mask(size, mm(5)))
    d = ImageDraw.Draw(page)
    top = margin + photo_h + mm(9)
    d.text((margin, top), MONTHS[month - 1], font=display(mm(10), "Bold"), fill=(36, 32, 44), anchor="ls")
    d.text((A4[0] - margin, top), str(year), font=display(mm(7), "Medium"), fill=accent, anchor="rs")
    grid_top = top + mm(6)
    cell_w = (A4[0] - 2 * margin) / 7
    cell_h = (A4[1] - margin - grid_top - mm(8)) / 6
    for i, wd in enumerate(WEEKDAYS):
        d.text((margin + cell_w * (i + .5), grid_top + mm(3)), wd, font=display(mm(3.2), "Bold"),
               fill=accent if i >= 5 else (120, 116, 130), anchor="mm")
    d.line((margin, grid_top + mm(6.5), A4[0] - margin, grid_top + mm(6.5)), fill=(226, 224, 232), width=mm(.3))
    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    num_font = display(mm(6), "Medium")
    for r, week in enumerate(weeks):
        for c, day in enumerate(week):
            if not day:
                continue
            cx, cy = margin + cell_w * (c + .5), grid_top + mm(8) + cell_h * (r + .5)
            red = c >= 5 or (month, day) in HOLIDAYS
            if (month, day) in HOLIDAYS:
                rr = min(cell_w, cell_h) * .36
                light = tuple(round(v + (255 - v) * .82) for v in accent)
                d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=light)
            d.text((cx, cy), str(day), font=num_font, fill=accent if red else (40, 36, 48), anchor="mm")
    return page


def build_calendar(params, photos, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    accent = ACCENTS[params["accent"]]
    year, start = _year(params), int(params["start"])
    pick = (lambda i: photos[i % len(photos)]) if photos else (lambda i: None)
    pages = [calendar_cover(pick(0), params["title"], year, accent)]
    for k in range(12):
        m = (start - 1 + k) % 12 + 1
        y = year + (start - 1 + k) // 12
        pages.append(calendar_month(pick(k + 1 if len(photos) > 1 else 0), y, m, accent))
    paths = []
    for i, page in enumerate(pages):
        p = out_dir / f"page_{i + 1:02d}.png"
        page.save(p, dpi=(DPI, DPI))
        paths.append(p)
    return paths


# ---------- открытки ----------

POSTCARD = (mm(100), mm(140))


def postcard_face(photo, greeting: str) -> Image.Image:
    img = photoai.fit(photo, POSTCARD) if photo else Image.new("RGB", POSTCARD, (232, 232, 236))
    if greeting:
        W, H = POSTCARD
        f, lines, size = fit_text(greeting, (W - mm(22), mm(26)), lambda s: display(s, "Bold"), mm(7.5), mm(4), 1.15)
        d = ImageDraw.Draw(img, "RGBA")
        widths = [d.textlength(ln, font=f) for ln in lines]
        bw, bh = max(widths) + mm(10), len(lines) * size * 1.15 + mm(6)
        x1, y1 = (W - bw) / 2, H - mm(10) - bh
        d.rounded_rectangle((x1, y1, x1 + bw, y1 + bh), radius=min(bh / 2, mm(7)), fill=(255, 255, 255, 228))
        y = y1 + mm(3)
        for ln, w in zip(lines, widths):
            d.text(((W - w) / 2, y + size * .07), ln, font=f, fill=(40, 34, 48))
            y += size * 1.15
    return img


def postcard_back(message: str) -> Image.Image:
    W, H = POSTCARD
    img = Image.new("RGB", POSTCARD, (253, 251, 247))
    d = ImageDraw.Draw(img)
    mid = W * .56
    d.line((mid, mm(14), mid, H - mm(14)), fill=(214, 208, 200), width=mm(.3))
    # марка и строки адреса
    sx, sy = W - mm(8) - mm(20), mm(8)
    for i in range(0, mm(20), mm(2)):
        d.line((sx + i, sy, sx + i + mm(1), sy), fill=(196, 188, 180), width=mm(.25))
        d.line((sx + i, sy + mm(24), sx + i + mm(1), sy + mm(24)), fill=(196, 188, 180), width=mm(.25))
    for i in range(0, mm(24), mm(2)):
        d.line((sx, sy + i, sx, sy + i + mm(1)), fill=(196, 188, 180), width=mm(.25))
        d.line((sx + mm(20), sy + i, sx + mm(20), sy + i + mm(1)), fill=(196, 188, 180), width=mm(.25))
    lab = display(mm(2.3), "Medium")
    for i, label in enumerate(["Кому", "Куда", "", ""]):
        y = mm(52) + i * mm(13)
        if label:
            d.text((mid + mm(5), y - mm(2.5)), label, font=lab, fill=(150, 142, 136), anchor="ls")
        d.line((mid + mm(5) + (mm(11) if label else 0), y, W - mm(7), y), fill=(214, 208, 200), width=mm(.3))
    if message:
        draw_text(img, (mm(7), mm(10), mid - mm(5), H - mm(10)), message, serif, mm(4.6), mm(2.6), (52, 44, 56),
                  align="left", valign="top", spacing=1.32)
    else:
        for i in range(9):
            y = mm(22) + i * mm(11)
            d.line((mm(7), y, mid - mm(6), y), fill=(226, 220, 212), width=mm(.25))
    return img


def build_postcards(params, photos, out_dir):
    faces, backs = [], []
    back = postcard_back(params["message"])
    for ph in photos:
        face = postcard_face(ph, params["greeting"])
        faces += [face] * params["copies"]
        backs += [back] * params["copies"]
    return save_sheets(faces, backs, POSTCARD, 2, 2, out_dir, bleed=mm(1.2))


# ---------- коробка для колоды ----------

BOX_DEPTH = {"deck36": 14, "deck54": 20}


def box_page(photo, title: str, back_key: str, deck: str) -> Image.Image:
    """Развёртка коробки с клапанами: сплошная линия — резать, пунктир — сгибать."""
    W, H, D, T, G = 66, 91, BOX_DEPTH[deck], 13, 9  # мм: ширина, высота, глубина, язычок, клапан для клея
    total_w, total_h = G + 2 * D + 2 * W, H + 2 * (D + T)
    ox, oy = (A4[0] - mm(total_w)) // 2, mm(22)
    X = lambda v: ox + mm(v)  # noqa: E731
    Y = lambda v: oy + mm(v)  # noqa: E731
    xs = [0, G, G + D, G + D + W, G + 2 * D + W, G + 2 * D + 2 * W]
    top, bottom = D + T, D + T + H
    shapes = []  # многоугольники панелей в мм
    shapes.append([(0, top + 4), (G, top), (G, bottom), (0, bottom - 4)])                     # клапан для клея
    for i in range(1, 5):
        shapes.append([(xs[i], top), (xs[i + 1], top), (xs[i + 1], bottom), (xs[i], bottom)])  # стенки
    for x1, x2 in ((xs[1], xs[2]), (xs[3], xs[4])):                                          # пылевые клапаны
        shapes.append([(x1, top), (x1 + 2, top - D * .85), (x2 - 1, top - D * .85), (x2, top)])
        shapes.append([(x1, bottom), (x1 + 2, bottom + D * .85), (x2 - 1, bottom + D * .85), (x2, bottom)])
    bx1, bx2 = xs[4], xs[5]
    for sign, edge in ((-1, top), (1, bottom)):                                               # крышки и язычки
        lid = edge + sign * D
        shapes.append([(bx1, edge), (bx2, edge), (bx2, lid), (bx1, lid)])
        tip = lid + sign * T
        shapes.append([(bx1, lid), (bx2, lid), (bx2 - 3, tip), (bx1 + 3, tip)])

    mask = Image.new("L", A4, 0)
    md = ImageDraw.Draw(mask)
    for s in shapes:
        md.polygon([(X(a), Y(b)) for a, b in s], fill=255)
    # вырез под палец на лицевой стенке
    fx1, fx2 = X(xs[2]), X(xs[3])
    notch_r = mm(9)
    md.pieslice(((fx1 + fx2) / 2 - notch_r, Y(top) - notch_r, (fx1 + fx2) / 2 + notch_r, Y(top) + notch_r), 0, 180, fill=0)

    art = Image.new("RGB", A4, "white")
    pattern = cards.render_back(back_key if back_key in cards.BACKS else cards.DEFAULT_BACK)
    tile = pattern.resize((mm(66), round(mm(66) * pattern.height / pattern.width)), Image.LANCZOS)
    for ty in range(0, A4[1], tile.height):
        for tx in range(0, A4[0], tile.width):
            art.paste(tile, (tx, ty))
    # лицевая стенка — фото и надпись
    face_size = (fx2 - fx1, Y(bottom) - Y(top))
    face = photoai.fit(photo, face_size) if photo else Image.new("RGB", face_size, (232, 232, 236))
    if title:
        pill_plate(face, title, rel_w=.86, y_rel=.82)
    art.paste(face, (fx1, Y(top)))
    page = Image.new("RGB", A4, "white")
    page.paste(art, (0, 0), mask)
    d = ImageDraw.Draw(page)
    outline = ImageChops.subtract(uno.dilate(mask, mm(.25)), mask)
    page.paste((60, 60, 66), (0, 0), outline)
    for x in xs[1:5]:  # сгибы между стенками
        _dashed(d, (X(x), Y(top)), (X(x), Y(bottom)))
    for x1, x2 in ((xs[1], xs[2]), (xs[3], xs[4]), (xs[4], xs[5])):
        _dashed(d, (X(x1), Y(top)), (X(x2), Y(top)))
        _dashed(d, (X(x1), Y(bottom)), (X(x2), Y(bottom)))
    for sign, edge in ((-1, top), (1, bottom)):
        _dashed(d, (X(bx1), Y(edge + sign * D)), (X(bx2), Y(edge + sign * D)))
    _dashed(d, (X(xs[1]), Y(top)), (X(xs[1]), Y(bottom)))
    note = display(mm(3), "Medium")
    d.text((A4[0] / 2, Y(total_h) + mm(12)), "Вырежьте по сплошной линии, согните по пунктиру и склейте узкий клапан",
           font=note, fill=(120, 116, 130), anchor="mm")
    return page


def _dashed(d: ImageDraw.ImageDraw, p1, p2, dash: float = mm(2), gap: float = mm(1.5)) -> None:
    (x1, y1), (x2, y2) = p1, p2
    length = math.hypot(x2 - x1, y2 - y1)
    if not length:
        return
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    t = 0.0
    while t < length:
        e = min(length, t + dash)
        d.line((x1 + ux * t, y1 + uy * t, x1 + ux * e, y1 + uy * e), fill=(150, 150, 158), width=max(2, mm(.25)))
        t = e + gap


def build_box(params, photos, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    page = box_page(photos[0] if photos else None, params["title"], params["back"], params["deck"])
    paths = []
    for i in range(params["copies"]):
        p = out_dir / f"page_{i + 1:02d}.png"
        page.save(p, dpi=(DPI, DPI))
        paths.append(p)
    return paths


# ---------- карты для своей игры (CSV) ----------

COLUMNS = {
    "title": ("title", "name", "название", "имя", "заголовок"),
    "text": ("text", "description", "текст", "описание", "эффект"),
    "image": ("image", "picture", "img", "картинка", "фото", "изображение", "файл"),
    "count": ("count", "qty", "copies", "количество", "кол-во", "копий", "штук"),
    "color": ("color", "colour", "цвет"),
    "type": ("type", "kind", "тип", "категория"),
}
MAX_GAME_CARDS = 270
COLOR_NAMES = {"красный": "#D84B4B", "синий": "#3D6FD1", "зелёный": "#3F9E5B", "зеленый": "#3F9E5B",
               "жёлтый": "#E7B53C", "желтый": "#E7B53C", "фиолетовый": "#8457C9", "оранжевый": "#E7883C",
               "розовый": "#E06C9A", "чёрный": "#2E2B36", "черный": "#2E2B36", "серый": "#7B7886", "голубой": "#3FA9CC"}


def parse_csv(text: str) -> list[dict]:
    text = text.lstrip("﻿")
    if not text.strip():
        return []
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]
    idx = {k: next((i for i, h in enumerate(head) if h in names), None) for k, names in COLUMNS.items()}
    if idx["title"] is None and idx["text"] is None:
        raise ProductError("В первой строке таблицы нужны заголовки столбцов: «название», «текст», «картинка», «количество»")
    out, total = [], 0
    for r in rows[1:]:
        get = lambda k: (r[idx[k]].strip() if idx[k] is not None and idx[k] < len(r) else "")  # noqa: E731
        title, body = clean(get("title"), 40), clean(get("text"), 260, multiline=True)
        if not (title or body):
            continue
        try:
            count = min(30, max(1, int(get("count") or 1)))
        except ValueError:
            count = 1
        color = get("color").lower()
        color = COLOR_NAMES.get(color, color if re.fullmatch(r"#[0-9a-f]{6}", color) else "#4C5E9E")
        total += count
        if total > MAX_GAME_CARDS:
            raise ProductError(f"Слишком много карт: не больше {MAX_GAME_CARDS} за заказ")
        out.append({"title": title, "text": body, "image": Path(get("image")).stem.lower() if get("image") else "",
                    "count": count, "color": color, "type": clean(get("type"), 24)})
    return out[:MAX_GAME_CARDS]


def game_face(row: dict, photo) -> Image.Image:
    W, H = CARD
    color = uno._rgb(row["color"].upper()) if row["color"].startswith("#") else (76, 94, 158)
    img = Image.new("RGB", CARD, color)
    d = ImageDraw.Draw(img)
    inner = (mm(3), mm(3), W - mm(3), H - mm(3))
    d.rounded_rectangle(inner, mm(2.6), fill=(252, 250, 246))
    title_h = mm(11)
    d.rounded_rectangle((inner[0], inner[1], inner[2], inner[1] + title_h), mm(2.6), fill=color)
    d.rectangle((inner[0], inner[1] + title_h - mm(3), inner[2], inner[1] + title_h), fill=color)
    if row["title"]:
        draw_text(img, (inner[0] + mm(3), inner[1], inner[2] - mm(3), inner[1] + title_h), row["title"],
                  lambda s: display(s, "Bold"), mm(4.6), mm(2.4), (255, 255, 255))
    y = inner[1] + title_h + mm(2)
    if photo is not None:
        size = (inner[2] - inner[0] - mm(4), mm(36))
        img.paste(photoai.fit(photo, size), (inner[0] + mm(2), y), cards._rounded_mask(size, mm(1.8)))
        y += size[1] + mm(2)
    bottom = inner[3] - (mm(7) if row["type"] else mm(3))
    if row["text"]:
        draw_text(img, (inner[0] + mm(3), y, inner[2] - mm(3), bottom), row["text"], serif, mm(4.4), mm(2.3),
                  (44, 40, 52), valign="center" if photo is None else "top")
    if row["type"]:
        d.text((W / 2, inner[3] - mm(3.5)), row["type"].upper(), font=display(mm(2.3), "Bold"), fill=color, anchor="mm")
    return img


def build_game(params, photos_by_name: dict, out_dir):
    faces = []
    for row in params["rows"]:
        face = game_face(row, photos_by_name.get(row["image"]))
        faces += [face] * row["count"]
    back = pattern_back(params["back"], CARD, params.get("title") or "")
    return save_sheets(faces, [back] * len(faces), CARD, 3, 3, out_dir, bleed=mm(1.2))


# ---------- общий вход ----------

def build(params: dict, photo_paths: list[Path], out_dir: Path, names: list[str] | None = None) -> list[Path]:
    """Листы для печати. У двусторонних — сначала все лицевые, затем все обороты."""
    p = params["product"]
    photos = [load_photo(x) for x in photo_paths]
    if p == "memory":
        return build_memory(params, photos, out_dir)
    if p in ("dates", "wishes"):
        return build_textcards(params, out_dir)
    if p == "stickers":
        return build_stickers(params, photos, out_dir)
    if p == "calendar":
        return build_calendar(params, photos, out_dir)
    if p == "postcards":
        return build_postcards(params, photos, out_dir)
    if p == "box":
        return build_box(params, photos, out_dir)
    if p == "game":
        by_name = {Path(n).stem.lower(): ph for n, ph in zip(names or [], photos)}
        return build_game(params, by_name, out_dir)
    raise ProductError("Неизвестное изделие")


def preview(params: dict, photos: list[Image.Image], names: list[str] | None = None) -> dict:
    """Образец для экрана заказа: лицо и оборот одной карточки (или страница целиком) + предупреждения."""
    p = params["product"]
    first = photos[0] if photos else None
    warnings = []
    if p == "memory":
        front, back = memory_face(first, params["frame"]), pattern_back(params["back"], MEMO)
    elif p == "dates":
        qs = _questions(params)
        s, q = qs[0] if qs else ("meet", "Ваш вопрос")
        front, back = question_face(q, s, 1, len(qs)), pattern_back(params["back"], CARD, params["title"])
    elif p == "wishes":
        text = params["wishes"][0] if params["wishes"] else ""
        front, back = wish_face(text), pattern_back(params["back"], CARD, params["title"])
    elif p == "stickers":
        st = sticker(first, params["shape"], STICKER_MM[params["size"]]) if first else None
        front = Image.new("RGB", (mm(90), mm(90)), (240, 241, 245))
        if st:
            k = min(1, (front.width - mm(8)) / max(st.size))
            st = st.resize((round(st.width * k), round(st.height * k)), Image.LANCZOS)
            front.paste(st, ((front.width - st.width) // 2, (front.height - st.height) // 2), st)
            if params["shape"] == "cut" and not photoai.can_cutout():
                warnings.append("Вырезание фона сейчас недоступно — сделаем скруглённые наклейки")
        back = None
    elif p == "calendar":
        front = calendar_month(photos[1] if len(photos) > 1 else first, _year(params), int(params["start"]),
                               ACCENTS[params["accent"]])
        back = calendar_cover(first, params["title"], _year(params), ACCENTS[params["accent"]])
    elif p == "postcards":
        front, back = postcard_face(first, params["greeting"]), postcard_back(params["message"])
    elif p == "box":
        front, back = box_page(first, params["title"], params["back"], params["deck"]), None
    elif p == "game":
        by_name = {Path(n).stem.lower(): ph for n, ph in zip(names or [], photos)}
        rows = params["rows"]
        missing = sorted({r["image"] for r in rows if r["image"] and r["image"] not in by_name})
        if missing:
            warnings.append("Нет картинок: " + ", ".join(missing[:6]) + (" и др." if len(missing) > 6 else "") +
                            " — эти карты будут без картинки")
        row = rows[0] if rows else {"title": "Название", "text": "Текст карты", "image": "", "count": 1,
                                    "color": "#4C5E9E", "type": ""}
        front, back = game_face(row, by_name.get(row["image"])), pattern_back(params["back"], CARD, params["title"])
    else:
        raise ProductError("Неизвестное изделие")
    if photos and p in ("memory", "postcards", "calendar", "box"):
        aspect = {"memory": 1, "postcards": POSTCARD[0] / POSTCARD[1], "calendar": (A4[0] - mm(20)) / mm(150),
                  "box": 66 / 91}[p]
        cut = sum(photoai.face_cut(ph.size, aspect, photoai.face_box(ph)) for ph in photos)
        if cut:
            warnings.append(f"На {cut} фото лица крупные и могут обрезаться — лучше снимки чуть издалека")
    return {"front": front, "back": back, "warnings": warnings}
