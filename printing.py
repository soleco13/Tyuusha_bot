"""Печать готовых листов A4 (PNG 300 DPI) на принтер Windows через GDI + слежение за очередью.

Лист рисуется в реальном масштабе 1:1, поэтому карты выходят ровно 63×88 мм.
Важно: в настройках печати не должно быть «Без полей»/«Масштабировать».
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from PIL import Image, ImageWin

log = logging.getLogger(__name__)

try:
    import win32con
    import win32gui
    import win32print
    import win32ui
except ImportError:  # не Windows или не установлен pywin32
    win32print = None

# GetDeviceCaps
LOGPIXELSX, LOGPIXELSY = 88, 90
PHYSICALOFFSETX, PHYSICALOFFSETY = 112, 113

QUALITY = {"draft": -1, "normal": -3, "high": -4}  # DMRES_DRAFT / MEDIUM / HIGH

# Флаги состояния принтера и задания (winspool.h) -> понятный текст
PRINTER_FLAGS = [
    (0x00000080, "принтер не в сети"), (0x00001000, "принтер недоступен"),
    (0x00000008, "замялась бумага"), (0x00000010, "закончилась бумага"),
    (0x00040000, "мало чернил"), (0x00100000, "требуется вмешательство"),
    (0x00400000, "открыта крышка"), (0x00000002, "ошибка принтера"), (0x00000001, "печать на паузе"),
]
JOB_FLAGS = [
    (0x00000040, "закончилась бумага"), (0x00000020, "принтер не в сети"),
    (0x00000400, "требуется вмешательство"), (0x00000200, "нет связи с принтером"),
    (0x00000002, "ошибка печати"), (0x00000001, "задание на паузе"),
    (0x00000004, "удаляется"), (0x00000010, "печатается"), (0x00000008, "передаётся на принтер"),
    (0x00000080, "напечатано"),
]
JOB_PROBLEM = 0x40 | 0x20 | 0x400 | 0x200 | 0x2 | 0x1
JOB_CONTROL_DELETE = 5


def list_printers() -> list[str]:
    if win32print is None:
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [p[2] for p in win32print.EnumPrinters(flags)]


def default_printer() -> str | None:
    if win32print is None:
        return None
    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        return None


def _flags_text(value: int, table) -> list[str]:
    return [text for bit, text in table if value & bit]


def printer_status(printer: str | None) -> dict:
    """Состояние принтера и его очередь — для админки."""
    printer = printer or default_printer()
    if win32print is None or not printer:
        return {"name": printer, "ok": False, "problems": ["принтер не найден"], "jobs": []}
    try:
        h = win32print.OpenPrinter(printer)
    except Exception as e:
        return {"name": printer, "ok": False, "problems": [f"нет доступа к принтеру: {e}"], "jobs": []}
    try:
        info = win32print.GetPrinter(h, 2)
        jobs = win32print.EnumJobs(h, 0, 50, 1)
    finally:
        win32print.ClosePrinter(h)
    problems = _flags_text(info["Status"], PRINTER_FLAGS)
    if info["Attributes"] & 0x400:  # PRINTER_ATTRIBUTE_WORK_OFFLINE
        problems.append("включён режим «работать автономно»")
    job_list = []
    for j in jobs:
        states = _flags_text(j["Status"], JOB_FLAGS)
        if j.get("pStatus"):
            states.insert(0, j["pStatus"])
        job_list.append({"id": j["JobId"], "document": j["pDocument"], "states": states or ["в очереди"],
                         "problem": bool(j["Status"] & JOB_PROBLEM), "pages": j.get("TotalPages", 0)})
    return {"name": printer, "ok": not problems and not any(j["problem"] for j in job_list),
            "problems": problems, "jobs": job_list}


def job_status(printer: str, job_id: int) -> dict | None:
    """None — задания больше нет в очереди (значит, принтер его забрал/напечатал)."""
    if win32print is None:
        return None
    h = win32print.OpenPrinter(printer)
    try:
        jobs = win32print.EnumJobs(h, 0, 100, 1)
    finally:
        win32print.ClosePrinter(h)
    for j in jobs:
        if j["JobId"] == job_id:
            states = _flags_text(j["Status"], JOB_FLAGS)
            if j.get("pStatus"):
                states.insert(0, j["pStatus"])
            return {"states": states or ["в очереди"], "problem": bool(j["Status"] & JOB_PROBLEM),
                    "printed": bool(j["Status"] & 0x80)}
    return None


def cancel_job(printer: str, job_id: int) -> None:
    h = win32print.OpenPrinter(printer, {"DesiredAccess": win32print.PRINTER_ALL_ACCESS})
    try:
        win32print.SetJob(h, job_id, 0, None, JOB_CONTROL_DELETE)
    finally:
        win32print.ClosePrinter(h)


def _make_dc(printer: str, color: bool, quality: str):
    handle = win32print.OpenPrinter(printer)
    try:
        devmode = win32print.GetPrinter(handle, 2)["pDevMode"]
    finally:
        win32print.ClosePrinter(handle)
    devmode.Color = win32con.DMCOLOR_COLOR if color else win32con.DMCOLOR_MONOCHROME
    devmode.PaperSize = win32con.DMPAPER_A4
    devmode.Orientation = win32con.DMORIENT_PORTRAIT
    devmode.Copies = 1
    devmode.PrintQuality = QUALITY.get(quality, QUALITY["normal"])
    devmode.Fields |= (win32con.DM_COLOR | win32con.DM_PAPERSIZE | win32con.DM_ORIENTATION
                       | win32con.DM_COPIES | win32con.DM_PRINTQUALITY)
    hdc = win32gui.CreateDC("WINSPOOL", printer, devmode)
    return win32ui.CreateDCFromHandle(hdc)


def print_pages(pages: list[Path], *, printer: str | None, job_name: str,
                color: bool = True, quality: str = "normal",
                mode: str = "printer", file_dir: Path | None = None) -> dict:
    """mode="printer" — отправить на принтер; mode="file" — только сложить листы
    в папку (для проверки без расхода бумаги).
    Возвращает {"printer", "job_id", "message"}; job_id нужен, чтобы следить за заданием."""
    if mode == "file":
        assert file_dir is not None
        target = file_dir / job_name
        target.mkdir(parents=True, exist_ok=True)
        for p in pages:
            shutil.copy(p, target / p.name)
        return {"printer": None, "job_id": None, "message": f"листы сохранены в папку {target.name}"}

    if win32print is None:
        raise RuntimeError("Печать доступна только на Windows с установленным pywin32")
    printer = printer or default_printer()
    if not printer:
        raise RuntimeError("Принтер не найден: укажите PRINTER_NAME в .env")

    dc = _make_dc(printer, color, quality)
    try:
        dpi_x, dpi_y = dc.GetDeviceCaps(LOGPIXELSX), dc.GetDeviceCaps(LOGPIXELSY)
        off_x, off_y = dc.GetDeviceCaps(PHYSICALOFFSETX), dc.GetDeviceCaps(PHYSICALOFFSETY)
        job_id = dc.StartDoc(job_name)
        for path in pages:
            img = Image.open(path).convert("RGB")
            src_dpi = img.info.get("dpi", (300, 300))[0] or 300
            # размер листа в точках принтера; сдвиг на непечатное поле, чтобы масштаб был 1:1
            w = round(img.width / src_dpi * dpi_x)
            h = round(img.height / src_dpi * dpi_y)
            dc.StartPage()
            ImageWin.Dib(img).draw(dc.GetHandleOutput(), (-off_x, -off_y, w - off_x, h - off_y))
            dc.EndPage()
        dc.EndDoc()
    finally:
        dc.DeleteDC()
    log.info("Отправлено на %s: %s (%d стр.), задание %s", printer, job_name, len(pages), job_id)
    return {"printer": printer, "job_id": job_id, "message": f"отправлено на «{printer}», листов: {len(pages)}"}
