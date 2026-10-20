"""Раскладка фото для печати на листах A4."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

import photoai
from cards import A4, DPI, load_photo, mm

# формат -> (ширина, высота слота в мм, слотов на лист A4)
FORMATS = {
    "10x15": ("10×15 см (2 шт. на листе A4)", (150, 100), 2),
    "a5": ("A5 — 14,8×21 см", (148, 210), 1),
    "a4": ("A4 — на весь лист", (200, 287), 1),
}


def _cut_marks(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    g, l = mm(1), mm(4)
    for x in (x1, x2):
        d.line((x, y1 - g - l, x, y1 - g), fill="black", width=2)
        d.line((x, y2 + g, x, y2 + g + l), fill="black", width=2)
    for y in (y1, y2):
        d.line((x1 - g - l, y, x1 - g, y), fill="black", width=2)
        d.line((x2 + g, y, x2 + g + l, y), fill="black", width=2)


def _fit_into(photo: Image.Image, size: tuple[int, int]) -> Image.Image:
    # поворачиваем фото под ориентацию слота, чтобы обрезать как можно меньше
    if (photo.width > photo.height) != (size[0] > size[1]):
        photo = photo.rotate(90, expand=True)
        photo.info.pop("face_box", None)  # после поворота лица ищем заново
    return photoai.fit(photo, size, (0.5, 0.5))


def build_photo_pages(photo_paths: list[Path], fmt: str, copies: int, grayscale: bool,
                      out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    _, (w_mm, h_mm), per_page = FORMATS[fmt]
    slot = (mm(w_mm), mm(h_mm))

    items: list[Image.Image] = []
    for p in photo_paths:
        img = _fit_into(load_photo(p), slot)
        if grayscale:
            img = ImageOps.grayscale(img).convert("RGB")
        items += [img] * copies

    # слоты на листе: столбиком по центру
    gap = mm(8) if per_page > 1 else 0
    total_h = per_page * slot[1] + (per_page - 1) * gap
    x0, y0 = (A4[0] - slot[0]) // 2, (A4[1] - total_h) // 2

    paths: list[Path] = []
    for start in range(0, len(items), per_page):
        page = Image.new("RGB", A4, "white")
        d = ImageDraw.Draw(page)
        for i, img in enumerate(items[start:start + per_page]):
            y = y0 + i * (slot[1] + gap)
            page.paste(img, (x0, y))
            if fmt != "a4":
                _cut_marks(d, (x0, y, x0 + slot[0], y + slot[1]))
        path = out_dir / f"page_{start // per_page + 1:02d}.png"
        page.save(path, dpi=(DPI, DPI))
        paths.append(path)
    return paths
