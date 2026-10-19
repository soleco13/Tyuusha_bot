"""Агент печати: запускается на компьютере, к которому подключён принтер.

Сервер с ботом и админкой стоит в интернете и до принтера не достаёт. Агент сам
обращается к серверу: забирает задания на печать, печатает через драйвер Windows
(те же функции, что в printing.py) и сообщает ход работы. Входящие подключения
к компьютеру не нужны.

Настройки — в .env в папке бота: SERVER_URL, AGENT_TOKEN, PRINTER_NAME.
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
import printing  # noqa: E402

SERVER = os.getenv("SERVER_URL", "").rstrip("/")
TOKEN = os.getenv("AGENT_TOKEN", "")
PRINTER = os.getenv("PRINTER_NAME") or None
DRY_RUN = os.getenv("AGENT_DRY_RUN") == "1"   # без принтера: листы только сохраняются в папку (проверка связи)
POLL = 2.5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(ROOT / "agent.log", encoding="utf-8")])
log = logging.getLogger("agent")


def call(method: str, path: str, body: dict | None = None, raw: bool = False):
    req = urllib.request.Request(SERVER + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return data if raw else json.loads(data)


def status() -> dict:
    if DRY_RUN:
        return {"name": "пробный режим (без принтера)", "ok": True, "problems": [], "jobs": []}
    try:
        return printing.printer_status(PRINTER)
    except Exception as e:  # noqa: BLE001
        return {"name": PRINTER, "ok": False, "problems": [f"не удалось опросить принтер: {e}"], "jobs": []}


class Active:
    """Задание, которое сейчас в работе на этом компьютере."""
    def __init__(self, job_id: int):
        self.id = job_id
        self.win_job: int | None = None
        self.sending = True      # идёт отправка листов на принтер (в отдельном потоке)
        self.error: str | None = None
        self.last_text = ""


def report(job_id: int, state: str, detail: str = "", problem: bool = False, win_job: int | None = None) -> None:
    body = {"state": state, "detail": detail, "problem": problem}
    if win_job is not None:
        body["win_job"] = win_job
    for attempt in range(3):
        try:
            call("POST", f"/agent/jobs/{job_id}/report", body)
            return
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось сообщить серверу (%s), повтор", e)
            time.sleep(2 + attempt * 2)


def send_job(job: dict, act: Active) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="tyusha_"))
    try:
        pages = []
        for n in range(job["pages"]):
            path = tmp / f"page_{n + 1:02d}.png"
            path.write_bytes(call("GET", f"/agent/jobs/{job['id']}/pages/{n}", raw=True))
            pages.append(path)
        log.info("Задание %s «%s»: получено листов %d, печатаем", job["id"], job["label"], len(pages))
        result = printing.print_pages(pages, printer=PRINTER, job_name=job["label"], color=job["color"],
                                      quality=job["quality"], mode="file" if DRY_RUN else "printer",
                                      file_dir=ROOT / "data" / "agent_printed")
        act.win_job = result["job_id"]
        if act.win_job is None:  # пробный режим
            report(job["id"], "done", "Листы сохранены (пробный режим)")
            act.sending = False
            return
        report(job["id"], "printing", "Печатается", win_job=act.win_job)
    except Exception as e:  # noqa: BLE001
        log.exception("Ошибка печати")
        act.error = str(e)
        report(job["id"], "error", f"Ошибка печати на компьютере: {e}")
    finally:
        act.sending = False
        shutil.rmtree(tmp, ignore_errors=True)


def watch(act: Active) -> bool:
    """Следит за заданием в очереди Windows. True — задание закончено."""
    if act.sending:
        return False
    if act.error or act.win_job is None:
        return True
    try:
        st = printing.job_status(PRINTER or printing.default_printer(), act.win_job)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось проверить очередь принтера: %s", e)
        return False
    if st is None or st["printed"]:
        report(act.id, "done", "Напечатано", win_job=act.win_job)
        log.info("Задание %s напечатано", act.id)
        return True
    text = ", ".join(st["states"])
    if (text, st["problem"]) != (act.last_text, True) and text != act.last_text:
        act.last_text = text
        report(act.id, "printing", text, problem=st["problem"], win_job=act.win_job)
    return False


def main() -> None:
    if not SERVER or not TOKEN:
        raise SystemExit("Укажите SERVER_URL и AGENT_TOKEN в файле .env")
    log.info("Агент печати запущен. Сервер: %s, принтер: %s%s", SERVER, PRINTER or "по умолчанию",
             " (пробный режим)" if DRY_RUN else "")
    active: Active | None = None
    online = None
    while True:
        try:
            resp = call("POST", "/agent/poll", {"status": status(), "active_job": active.id if active else None})
            if online is not True:
                log.info("Связь с сервером есть")
                online = True
            for c in resp.get("cancel", []):
                if active and active.id == c["job_id"]:
                    try:
                        if c.get("win_job"):
                            printing.cancel_job(PRINTER or printing.default_printer(), c["win_job"])
                    except Exception as e:  # noqa: BLE001
                        log.warning("Не удалось удалить задание из очереди: %s", e)
                    report(active.id, "cancelled", "Снято с принтера")
                    active = None
            if active is None and resp.get("job"):
                active = Active(resp["job"]["id"])
                threading.Thread(target=send_job, args=(resp["job"], active), daemon=True).start()
            elif active and watch(active):
                active = None
        except urllib.error.HTTPError as e:
            if online is not False:
                log.error("Сервер отказал (%s). Проверьте AGENT_TOKEN", e.code)
            online = False
        except Exception as e:  # noqa: BLE001
            if online is not False:
                log.warning("Нет связи с сервером: %s", e)
            online = False
        time.sleep(POLL)


if __name__ == "__main__":
    main()
