"""Связь с компьютером оператора, к которому подключён принтер (PRINT_MODE=agent).

Сервер печатать сам не может: он кладёт задания в очередь (таблица print_jobs),
а программа-агент на Windows-компьютере забирает их, печатает и сообщает о ходе работы.
"""
from __future__ import annotations

import hmac
import json
import logging
import time

from aiohttp import web

import config
import db

log = logging.getLogger("agent")

ONLINE_WINDOW = 25   # столько секунд после последнего опроса считаем компьютер на связи
STALE_JOB = 60       # задание «на компьютере» без вестей дольше — считаем потерянным

_seen_at = 0.0
_status: dict = {}


def online() -> bool:
    return time.time() - _seen_at < ONLINE_WINDOW


def printer_status() -> dict:
    """Состояние принтера в том же формате, что printing.printer_status (для админки)."""
    if not online():
        return {"name": "компьютер с принтером", "ok": False,
                "problems": ["компьютер с принтером не на связи: включите его и запустите агент"], "jobs": []}
    return {"name": _status.get("name") or "принтер", "ok": bool(_status.get("ok", True)),
            "problems": _status.get("problems", []), "jobs": _status.get("jobs", [])}


def submit(order_id: int | None, label: str, pages: list, color: bool, quality: str) -> dict:
    if not online():
        raise RuntimeError("компьютер с принтером не на связи. Включите его и запустите агент печати")
    job_id = db.add_print_job(order_id, label, color, quality, [str(p) for p in pages])
    return {"printer": "agent", "job_id": job_id, "message": "задание отправлено на компьютер с принтером"}


def request_cancel(job_id: int) -> None:
    job = db.get_print_job(job_id)
    if not job or job["state"] in ("done", "error", "cancelled"):
        return
    if job["state"] == "queued":
        db.update_print_job(job_id, state="cancelled", detail="Отменено до начала печати")
    else:
        db.update_print_job(job_id, cancel=1)


# ---------- HTTP для агента ----------

def _check(request: web.Request) -> None:
    got = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not config.AGENT_TOKEN or not hmac.compare_digest(got, config.AGENT_TOKEN):
        raise web.HTTPUnauthorized(text=json.dumps({"ok": False, "error": "bad token"}), content_type="application/json")


async def poll(request: web.Request) -> web.Response:
    global _seen_at, _status
    _check(request)
    body = await request.json()
    _seen_at, _status = time.time(), body.get("status") or {}
    active = body.get("active_job")
    # задание, которое сервер считает «на компьютере», а агент о нём не знает (перезапуск, сбой)
    for job in db.print_jobs_where("state IN ('taken','printing')"):
        if job["id"] != active and time.time() - time.mktime(time.strptime(job["updated_at"], "%Y-%m-%d %H:%M:%S")) > STALE_JOB:
            db.update_print_job(job["id"], state="error", detail="Программа печати на компьютере перезапустилась, задание потеряно")
    cancels = [{"job_id": j["id"], "win_job": j["win_job"]} for j in db.print_jobs_where("cancel=1 AND state IN ('taken','printing')")]
    job = None if active else db.take_print_job()
    out = None
    if job:
        out = {"id": job["id"], "label": job["label"], "color": bool(job["color"]), "quality": job["quality"],
               "pages": len(job["pages"])}
    return web.json_response({"ok": True, "job": out, "cancel": cancels})


async def page(request: web.Request) -> web.StreamResponse:
    _check(request)
    job = db.get_print_job(int(request.match_info["id"]))
    n = int(request.match_info["n"])
    if not job or not 0 <= n < len(job["pages"]):
        raise web.HTTPNotFound()
    return web.FileResponse(job["pages"][n])


async def report(request: web.Request) -> web.Response:
    _check(request)
    job_id = int(request.match_info["id"])
    body = await request.json()
    job = db.get_print_job(job_id)
    if not job:
        raise web.HTTPNotFound()
    state = body.get("state")
    if state not in ("printing", "done", "error", "cancelled"):
        return web.json_response({"ok": False, "error": "bad state"}, status=400)
    if job["state"] in ("done", "error", "cancelled"):
        return web.json_response({"ok": True})
    fields = {"state": state, "detail": str(body.get("detail") or "")[:300], "problem": int(bool(body.get("problem")))}
    if body.get("win_job") is not None:
        fields["win_job"] = int(body["win_job"])
    db.update_print_job(job_id, **fields)
    return web.json_response({"ok": True})


def routes() -> list:
    return [web.post("/agent/poll", poll), web.get(r"/agent/jobs/{id:\d+}/pages/{n:\d+}", page),
            web.post(r"/agent/jobs/{id:\d+}/report", report)]
