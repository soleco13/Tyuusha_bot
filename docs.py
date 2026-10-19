"""Документы для печати: PDF и картинки превращаются в листы A4 (как фото и карты)."""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageOps

from cards import A4, DPI, mm

MAX_PAGES = 100
MAX_SHEETS = 300  # страниц × копий
MARGIN = mm(5)    # поля, которые принтер всё равно не пропечатает


class DocError(Exception):
    """Ошибка, текст которой можно показать клиенту."""


def sniff(path: Path) -> str:
    """Тип по содержимому, а не по имени: pdf | image."""
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG"):
        return "image"
    raise DocError("Принимаем PDF, JPG и PNG. Word и Excel сохраните как PDF")


def _open_pdf(path: Path) -> fitz.Document:
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise DocError("Не получилось открыть PDF — файл повреждён") from e
    if doc.needs_pass or doc.is_encrypted:
        doc.close()
        raise DocError("PDF защищён паролем. Снимите защиту и загрузите снова")
    return doc


def count_pages(path: Path) -> int:
    if sniff(path) == "image":
        return 1
    with _open_pdf(path) as doc:
        n = doc.page_count
    if n < 1:
        raise DocError("В файле нет страниц")
    if n > MAX_PAGES:
        raise DocError(f"В документе {n} стр. — принимаем не больше {MAX_PAGES}")
    return n


def _on_a4(img: Image.Image, grayscale: bool) -> Image.Image:
    """Вписывает страницу в A4 (альбомную поворачивает), поля белые."""
    img = img.convert("RGB")
    if img.width > img.height:
        img = img.rotate(90, expand=True)
    box = (A4[0] - 2 * MARGIN, A4[1] - 2 * MARGIN)
    img = ImageOps.contain(img, box, Image.LANCZOS)
    if grayscale:
        img = ImageOps.grayscale(img).convert("RGB")
    sheet = Image.new("RGB", A4, "white")
    sheet.paste(img, ((A4[0] - img.width) // 2, (A4[1] - img.height) // 2))
    return sheet


def build_doc_pages(src: Path, grayscale: bool, out_dir: Path) -> list[Path]:
    """По листу A4 (PNG, 300 dpi) на каждую страницу документа."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    if sniff(src) == "image":
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            sheets = [_on_a4(im, grayscale)]
    else:
        sheets = []
        with _open_pdf(src) as doc:
            if doc.page_count > MAX_PAGES:
                raise DocError(f"В документе {doc.page_count} стр. — принимаем не больше {MAX_PAGES}")
            for page in doc:
                r = page.rect
                k = min((A4[0] - 2 * MARGIN) / min(r.width, r.height), (A4[1] - 2 * MARGIN) / max(r.width, r.height))
                if r.width > r.height:  # альбомная: масштаб считаем по повёрнутому листу
                    k = min((A4[0] - 2 * MARGIN) / r.height, (A4[1] - 2 * MARGIN) / r.width)
                pix = page.get_pixmap(matrix=fitz.Matrix(k, k), colorspace=fitz.csRGB, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                sheets.append(_on_a4(img, grayscale))
    for i, sheet in enumerate(sheets, 1):
        p = out_dir / f"page_{i:03d}.png"
        sheet.save(p, dpi=(DPI, DPI))
        paths.append(p)
    return paths
