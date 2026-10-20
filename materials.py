"""Склад материалов и выбор бумаги.

Материалы считаются в листах A4 (чернила — в отпечатанных сторонах). Когда заказ оформлен, нужные
листы резервируются (списываются со склада); при отмене ещё не напечатанного заказа — возвращаются,
при перепечатке — списываются ещё раз. Если материала не хватает, заказ не оформится, а клиент
заранее увидит в приложении, что этот вариант бумаги временно недоступен.
"""
from __future__ import annotations

import db

# ключ: (название, единица, запас по умолчанию, порог «мало»)
MATERIALS = {
    "paper": ("Бумага офисная A4, 80 г/м²", "л.", 500, 100),
    "card": ("Картон A4, 300 г/м²", "л.", 100, 30),
    "photo": ("Фотобумага A4, глянец", "л.", 50, 15),
    "sticker": ("Самоклеящаяся бумага A4", "л.", 20, 5),
    "laminate": ("Плёнка для ламинирования A4", "л.", 50, 15),
    "ink": ("Чернила: запас отпечатков", "стор.", 1000, 150),
}

# Варианты бумаги для клиента: ключ: (название, подсказка, материалы на 1 лист, ключ надбавки, профиль печати)
PAPERS = {
    "plain": ("Обычная", "80 г/м², как в офисе", {"paper": 1}, None, "doc"),
    "thick": ("Плотная", "300 г/м², не просвечивает", {"card": 1}, "thick", "cards"),
    "photo": ("Фотобумага", "глянцевая, яркие цвета", {"photo": 1}, None, "photo"),
    "matte": ("Плотная матовая", "без бликов, как открытка", {"card": 1}, "matte", "cards"),
    "card": ("Картон", "300 г/м², как у магазинных карт", {"card": 1}, None, "cards"),
    "card_lam": ("Картон + ламинация", "не боится воды и царапин", {"card": 1, "laminate": 1}, "lam", "cards"),
    "sticker": ("Самоклейка", "клеится на телефон, ноутбук, кружку", {"sticker": 1}, None, "stickers"),
}

# Какие варианты бумаги есть у каждого вида заказа (первый — по умолчанию)
CHOICES = {
    "doc": ["plain", "thick"],
    "photo": ["photo", "matte"],
    "cards": ["card", "card_lam"],
    "craft": ["card", "card_lam"],
    "stickers": ["sticker"],
    "calendar": ["card", "photo"],
}

_ready = False


def _init() -> None:
    global _ready
    if _ready:
        return
    with db._lock:
        db._conn.executescript("""
        CREATE TABLE IF NOT EXISTS materials (key TEXT PRIMARY KEY, stock INTEGER NOT NULL, low INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS stock_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            key TEXT NOT NULL,
            delta INTEGER NOT NULL,             -- минус — расход, плюс — приход или возврат
            reason TEXT NOT NULL,               -- order | reprint | release | income | writeoff | set
            order_id INTEGER,
            note TEXT
        );
        CREATE INDEX IF NOT EXISTS stock_log_order ON stock_log(order_id);
        """)
        for key, (_, _, stock, low) in MATERIALS.items():
            db._conn.execute("INSERT OR IGNORE INTO materials (key, stock, low) VALUES (?, ?, ?)", (key, stock, low))
    _ready = True


class MaterialsError(Exception):
    """Не хватает материала — текст можно показать человеку."""


def choices_for(kind: str, product: str | None = None) -> list[str]:
    if kind == "craft":
        return CHOICES.get(product or "", CHOICES["craft"])
    return CHOICES.get(kind, ["plain"])


def default_paper(kind: str, product: str | None = None) -> str:
    return choices_for(kind, product)[0]


def profile_for(paper: str | None, kind: str) -> str:
    """Профиль печати (какой принтер и лоток) по бумаге заказа."""
    if paper in PAPERS:
        return PAPERS[paper][4]
    return {"cards": "cards", "doc": "doc"}.get(kind, "photo")


def needs(paper: str, sheets: int, sides: int) -> dict[str, int]:
    """Сколько материалов уйдёт: листы бумаги по варианту + чернила по числу сторон."""
    out: dict[str, int] = {}
    for key, per in PAPERS[paper][2].items():
        out[key] = out.get(key, 0) + per * sheets
    out["ink"] = sides
    return out


def stock() -> dict[str, dict]:
    _init()
    with db._lock:
        rows = db._conn.execute("SELECT key, stock, low FROM materials").fetchall()
    out = {}
    for key, value, low in rows:
        if key in MATERIALS:
            title, unit, _, _ = MATERIALS[key]
            out[key] = {"key": key, "title": title, "unit": unit, "stock": value, "low": low,
                        "state": "out" if value <= 0 else "low" if value <= low else "ok"}
    return out


def shortages(need: dict[str, int]) -> list[str]:
    s = stock()
    return [s[k]["title"] for k, n in need.items() if n > 0 and s.get(k, {"stock": 0})["stock"] < n]


def paper_state(paper: str) -> str:
    """ok | low | out — для подсказки в приложении (по бумаге; чернила не прячут вариант)."""
    s = stock()
    states = [s[k]["state"] for k in PAPERS[paper][2] if k in s]
    if "out" in states:
        return "out"
    return "low" if "low" in states else "ok"


def _apply(changes: dict[str, int], reason: str, order_id: int | None, note: str = "") -> list[str]:
    """Меняет запасы в одной транзакции и возвращает предупреждения о материалах, ставших «мало»."""
    _init()
    alerts = []
    with db._lock:
        before = {k: v["stock"] for k, v in stock().items()}
        db._conn.execute("BEGIN")
        try:
            for key, delta in changes.items():
                if not delta:
                    continue
                db._conn.execute("UPDATE materials SET stock = stock + ? WHERE key=?", (delta, key))
                db._conn.execute("INSERT INTO stock_log (at, key, delta, reason, order_id, note) VALUES (?, ?, ?, ?, ?, ?)",
                                 (db.now(), key, delta, reason, order_id, note or None))
            db._conn.execute("COMMIT")
        except Exception:
            db._conn.execute("ROLLBACK")
            raise
        after = stock()
    for key, info in after.items():
        if before.get(key, 0) > info["low"] >= info["stock"]:
            alerts.append(f"⚠️ Склад: «{info['title']}» осталось {max(info['stock'], 0)} {info['unit']} — пора пополнить")
    return alerts


def reserve(order_id: int | None, need: dict[str, int], reason: str = "order") -> list[str]:
    """Списывает материалы под заказ. Не хватает — MaterialsError и ничего не списывается."""
    with db._lock:
        missing = shortages(need)
        if missing:
            raise MaterialsError("Сейчас закончилось: " + ", ".join(missing).lower() +
                                 ". Мы уже пополняем запасы — попробуйте другой вариант бумаги или загляните позже")
        return _apply({k: -n for k, n in need.items()}, reason, order_id)


def release(order_id: int) -> list[str]:
    """Возвращает на склад всё, что было списано под заказ и ещё не возвращено."""
    _init()
    with db._lock:
        rows = db._conn.execute("SELECT key, SUM(delta) FROM stock_log WHERE order_id=? GROUP BY key", (order_id,)).fetchall()
        back = {k: -s for k, s in rows if s and s < 0}
        return _apply(back, "release", order_id) if back else []


def adjust(key: str, delta: int = 0, set_to: int | None = None, low: int | None = None, note: str = "") -> list[str]:
    """Действия склада из админки: приход (+), списание (−), точное значение, порог «мало»."""
    _init()
    if key not in MATERIALS:
        raise MaterialsError("Нет такого материала")
    alerts = []
    with db._lock:
        if low is not None:
            if not 0 <= low <= 100000:
                raise MaterialsError("Порог должен быть от 0 до 100 000")
            db._conn.execute("UPDATE materials SET low=? WHERE key=?", (low, key))
        if set_to is not None:
            if not 0 <= set_to <= 1_000_000:
                raise MaterialsError("Остаток должен быть от 0 до 1 000 000")
            delta = set_to - stock()[key]["stock"]
            reason = "set"
        else:
            reason = "income" if delta > 0 else "writeoff"
        if delta:
            alerts = _apply({key: delta}, reason, None, note)
    return alerts


def log(limit: int = 60) -> list[dict]:
    _init()
    with db._lock:
        rows = db._conn.execute("SELECT * FROM stock_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def used_since(day: str) -> dict[str, int]:
    """Сколько каждого материала ушло на заказы с начала дня day (с учётом возвратов)."""
    _init()
    with db._lock:
        rows = db._conn.execute("SELECT key, SUM(delta) FROM stock_log WHERE at >= ? AND reason IN "
                                "('order', 'reprint', 'release') GROUP BY key", (day,)).fetchall()
    return {k: -s for k, s in rows if s and s < 0}
