"""Цены (в рублях). Хранятся в БД, редактируются в админке."""
from __future__ import annotations

import copy

import db

DEFAULT_PRICES = {
    "cards": {"deck36": 990, "deck54": 1290},
    # цена за один отпечаток: формат -> {цвет/ЧБ}
    "photo": {"10x15": {"color": 30, "bw": 20},
              "a5": {"color": 60, "bw": 35},
              "a4": {"color": 100, "bw": 50}},
    # надбавка за качество, % к цене
    "quality_markup": {"draft": -20, "normal": 0, "high": 20},
}


def get_prices() -> dict:
    saved = db.get_setting("prices") or {}
    prices = copy.deepcopy(DEFAULT_PRICES)
    for section, values in saved.items():
        if section in prices and isinstance(values, dict):
            for k, v in values.items():
                if isinstance(prices[section].get(k), dict) and isinstance(v, dict):
                    prices[section][k].update(v)
                elif k in prices[section]:
                    prices[section][k] = v
    return prices


def set_prices(prices: dict) -> dict:
    clean = copy.deepcopy(DEFAULT_PRICES)
    for deck in clean["cards"]:
        clean["cards"][deck] = _money(prices["cards"][deck])
    for fmt in clean["photo"]:
        for mode in ("color", "bw"):
            clean["photo"][fmt][mode] = _money(prices["photo"][fmt][mode])
    for q in clean["quality_markup"]:
        v = int(prices["quality_markup"][q])
        if not -90 <= v <= 500:
            raise ValueError("Надбавка за качество должна быть от −90 до 500 %")
        clean["quality_markup"][q] = v
    db.set_setting("prices", clean)
    return clean


def _money(v) -> int:
    v = int(v)
    if not 0 <= v <= 1_000_000:
        raise ValueError("Цена должна быть от 0 до 1 000 000 ₽")
    return v


def quote(kind: str, params: dict) -> tuple[int, str]:
    """Возвращает (сумма в копейках, расшифровка для клиента)."""
    p = get_prices()
    if kind == "cards":
        rub = p["cards"][params["deck"]]
        return rub * 100, f"Колода — {rub} ₽"
    unit = p["photo"][params["format"]]["color" if params["color"] else "bw"]
    markup = p["quality_markup"][params["quality"]]
    unit_k = round(unit * 100 * (100 + markup) / 100)
    count = params["photos"] * params["copies"]
    detail = f"{count} отп. × {format_rub(unit_k)}"
    if markup:
        detail += f" (качество {'+' if markup > 0 else '−'}{abs(markup)} %)"
    return unit_k * count, detail


def format_rub(kop: int) -> str:
    rub, k = divmod(kop, 100)
    s = f"{rub:,}".replace(",", " ")
    return f"{s},{k:02d} ₽" if k else f"{s} ₽"
