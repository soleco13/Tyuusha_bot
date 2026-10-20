"""Цены (в рублях). Хранятся в БД, редактируются в админке."""
from __future__ import annotations

import copy

import db
import materials

DEFAULT_PRICES = {
    "cards": {"deck36": 990, "deck54": 1290, "uno": 1790},
    # цена за один отпечаток: формат -> {цвет/ЧБ}
    "photo": {"10x15": {"color": 30, "bw": 20},
              "a5": {"color": 60, "bw": 35},
              "a4": {"color": 100, "bw": 50}},
    # документы: цена за одну страницу A4
    "doc": {"color": 15, "bw": 8},
    # надбавка за качество, % к цене
    "quality_markup": {"draft": -20, "normal": 0, "high": 20},
    # надбавка за бумагу, ₽ за лист A4
    "paper": {"thick": 6, "matte": 8, "lam": 25},
    # изделия из конструктора (products.py) и улучшение фото, ₽
    "craft": {"memory_base": 290, "memory_pair": 25, "dates_sheet": 120, "wishes_sheet": 120,
              "stickers_sheet": 190, "calendar": 890, "postcard": 70, "box": 190, "game_sheet": 120,
              "enhance_photo": 10},
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
    for section in ("cards", "paper", "craft"):
        for key in clean[section]:
            clean[section][key] = _money(prices.get(section, {}).get(key, clean[section][key]))
    for fmt in clean["photo"]:
        for mode in ("color", "bw"):
            clean["photo"][fmt][mode] = _money(prices["photo"][fmt][mode])
    for mode in ("color", "bw"):
        if "doc" in prices:
            clean["doc"][mode] = _money(prices["doc"][mode])
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


def paper_extra(params: dict, p: dict) -> int:
    """Надбавка за бумагу в рублях: ₽ за лист × число листов."""
    paper = materials.PAPERS.get(params.get("paper") or "")
    key = paper[3] if paper else None
    return p["paper"].get(key, 0) * int(params.get("sheets", 0)) if key else 0


def quote(kind: str, params: dict) -> tuple[int, str]:
    """Возвращает (сумма в копейках, расшифровка для клиента)."""
    p = get_prices()
    extra = paper_extra(params, p) + p["craft"]["enhance_photo"] * int(params.get("enhanced", 0))
    tail = ""
    if paper_extra(params, p):
        tail += f" + бумага {paper_extra(params, p)} ₽"
    if params.get("enhanced"):
        tail += f" + улучшение {params['enhanced']} фото"
    if kind == "cards":
        rub = p["cards"][params["deck"]]
        return (rub + extra) * 100, f"Колода — {rub} ₽{tail}"
    if kind == "craft":
        import products
        rub, detail = products.price(params, p["craft"])
        return (rub + extra) * 100, detail + tail
    if kind == "doc":
        unit_k = p["doc"]["color" if params["color"] else "bw"] * 100
        count = params["doc_pages"] * params["copies"]
        return unit_k * count + extra * 100, f"{count} стр. × {format_rub(unit_k)}{tail}"
    unit = p["photo"][params["format"]]["color" if params["color"] else "bw"]
    markup = p["quality_markup"][params["quality"]]
    unit_k = round(unit * 100 * (100 + markup) / 100)
    count = params["photos"] * params["copies"]
    detail = f"{count} отп. × {format_rub(unit_k)}"
    if markup:
        detail += f" (качество {'+' if markup > 0 else '−'}{abs(markup)} %)"
    return unit_k * count + extra * 100, detail + tail


def format_rub(kop: int) -> str:
    rub, k = divmod(kop, 100)
    s = f"{rub:,}".replace(",", " ")
    return f"{s},{k:02d} ₽" if k else f"{s} ₽"
