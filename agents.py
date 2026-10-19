"""Связь сервера с компьютерами, к которым подключены принтеры (PRINT_MODE=agent).

Сервер стоит в интернете и до принтера не достаёт. На компьютере с принтером работает
программа «Тюша Печать» (папка agent/): она сама обращается к серверу, забирает задания
со всеми настройками, печатает и сообщает ход работы. Входящие подключения не нужны.

Подключение: в панели «Принтеры → Подключить компьютер» — одноразовый код на 10 минут;
программа обменивает его на собственный токен (на сервере хранится только его хэш).

Профиль печати = материал (карты, фото) → компьютер + принтер + настройки драйвера,
которые один раз настраиваются в окне драйвера на самом компьютере.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from pathlib import Path

from aiohttp import web

import db

log = logging.getLogger("agents")

PROFILES = {
    "cards": "Игральные карты (картон 300 г/м²)",
    "photo": "Фото (фотобумага)",
}
for _key, _title in PROFILES.items():
    db.ensure_profile(_key, _title)

POLL_WAIT = 15        # долгий опрос: сервер держит запрос, пока не появится задание
ONLINE_WINDOW = 40    # столько секунд после последнего опроса компьютер считается на связи
PAIR_TTL = 600        # код подключения живёт 10 минут
QUEUED_TIMEOUT = 60   # задание не забрали за это время, а компьютер не на связи — ошибка
LOST_AFTER = 120      # во время печати пропала связь дольше этого — ошибка

_wake: dict[int, asyncio.Event] = {}
_pair_attempts: dict[str, list[float]] = {}
on_job_update = None  # async callback(job) — выставляет service.py


class PrintError(Exception):
    """Печать сейчас невозможна; текст показываем оператору."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _ts(s: str) -> float:
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))


def is_online(agent: dict | None) -> bool:
    return bool(agent and agent.get("last_seen") and time.time() - agent["last_seen"] < ONLINE_WINDOW)


def wake(agent_id: int) -> None:
    ev = _wake.get(agent_id)
    if ev:
        ev.set()


def profile_key(kind: str) -> str:
    return "cards" if kind == "cards" else "photo"


def _printer_info(agent: dict, printer: str) -> dict | None:
    for p in (agent.get("status") or {}).get("printers", []):
        if p.get("name") == printer:
            return p
    return None


async def _notify(job: dict | None) -> None:
    if job and on_job_update:
        try:
            await on_job_update(job)
        except Exception:
            log.exception("Ошибка обработки статуса задания %s", job.get("id"))


# ---------- для сервиса и панели ----------

def new_pair_code() -> str:
    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.add_pair_code(code, time.time() + PAIR_TTL)
    return code


def submit(order_id: int | None, kind_or_profile: str, label: str, pages: list, color: bool, quality: str) -> dict:
    key = kind_or_profile if kind_or_profile in PROFILES else profile_key(kind_or_profile)
    prof = db.get_profile(key)
    if not prof or not prof["agent_id"] or not prof["printer"]:
        raise PrintError(f"Профиль «{PROFILES[key]}» не настроен: откройте «Принтеры» и выберите компьютер и принтер")
    agent = db.get_agent(prof["agent_id"])
    if not agent or agent["revoked"]:
        raise PrintError("Компьютер для этого профиля отключён: выберите другой в разделе «Принтеры»")
    if not is_online(agent):
        raise PrintError(f"Компьютер «{agent['name']}» не на связи. Включите его и запустите программу «Тюша Печать»")
    info = _printer_info(agent, prof["printer"])
    if not info:
        raise PrintError(f"На компьютере «{agent['name']}» не найден принтер «{prof['printer']}»")
    offline = [p for p in info.get("problems", []) if "не в сети" in p or "недоступен" in p]
    if offline:
        raise PrintError(f"Принтер «{prof['printer']}»: {offline[0]}. Проверьте, что он включён")
    settings = {"printer": prof["printer"], "color": bool(color), "quality": quality,
                "devmode": prof["devmode"], "profile": key, "profile_title": prof["title"]}
    job = db.add_print_job(order_id=order_id, agent_id=agent["id"], profile=key, label=label,
                           pages=[str(p) for p in pages], settings=settings)
    wake(agent["id"])
    return job


def request_cancel(job_id: int) -> None:
    job = db.get_print_job(job_id)
    if not job or job["state"] in ("done", "error", "cancelled"):
        return
    if job["state"] == "queued":
        db.update_print_job(job_id, state="cancelled", detail="Отменено до начала печати")
    else:
        db.update_print_job(job_id, cancel=1, detail="Снимаем с принтера…")
        wake(job["agent_id"])


async def sweep() -> None:
    """Задания, которые застряли из-за пропавшей связи, — в ошибку, чтобы оператор видел и решал."""
    now = time.time()
    for job in db.print_jobs("state IN ('queued', 'sent', 'printing')"):
        agent = db.get_agent(job["agent_id"])
        if is_online(agent):
            continue
        last = (agent or {}).get("last_seen") or 0
        if job["state"] == "queued" and now - _ts(job["created_at"]) > QUEUED_TIMEOUT:
            job = db.update_print_job(job["id"], state="error",
                                      detail="Компьютер с принтером не на связи — задание не отправлено")
        elif job["state"] != "queued" and now - last > LOST_AFTER:
            job = db.update_print_job(job["id"], state="error",
                                      detail="Пропала связь с компьютером во время печати. Проверьте, что напечаталось")
        else:
            continue
        await _notify(job)


def overview() -> dict:
    """Компьютеры и профили — для страницы «Принтеры» и шапки панели."""
    agents = []
    for a in db.list_agents():
        st = a.get("status") or {}
        agents.append({"id": a["id"], "name": a["name"], "online": is_online(a), "version": a.get("version"),
                       "last_seen": a.get("last_seen"), "seen_ago": int(time.time() - (a.get("last_seen") or 0)),
                       "printers": st.get("printers", []), "default_printer": st.get("default_printer"),
                       "current": st.get("current"), "dry_run": st.get("dry_run", False)})
    by_id = {a["id"]: a for a in agents}
    profiles = []
    for p in db.list_profiles():
        a = by_id.get(p["agent_id"])
        info = next((x for x in (a or {}).get("printers", []) if x.get("name") == p["printer"]), None) if a else None
        profiles.append({"key": p["key"], "title": p["title"], "agent_id": p["agent_id"],
                         "agent_name": a["name"] if a else None, "printer": p["printer"],
                         "has_devmode": bool(p["devmode"]), "devmode_summary": p["devmode_summary"],
                         "ready": bool(a and a["online"] and info and not info.get("problems")),
                         "printer_info": info})
    return {"agents": agents, "profiles": profiles}


def printer_summary() -> dict:
    """Состояние для значка в шапке панели — в формате printing.printer_status."""
    ov = overview()
    used = {p["agent_id"] for p in ov["profiles"] if p["agent_id"]}
    agents = [a for a in ov["agents"] if a["id"] in used] or ov["agents"]
    if not agents:
        return {"name": "компьютер с принтером", "ok": False, "jobs": [],
                "problems": ["компьютер с принтером не подключён — откройте «Принтеры»"]}
    problems, jobs = [], []
    for a in agents:
        if not a["online"]:
            problems.append(f"«{a['name']}» не на связи")
            continue
        names = {p["printer"] for p in ov["profiles"] if p["agent_id"] == a["id"]}
        for pr in a["printers"]:
            if pr.get("name") in names:
                problems += pr.get("problems", [])
                jobs += pr.get("jobs", [])
    return {"name": ", ".join(a["name"] for a in agents), "ok": not problems, "problems": problems, "jobs": jobs}


def bind_profile(key: str, agent_id: int | None, printer: str | None) -> None:
    prof = db.get_profile(key)
    if not prof:
        raise PrintError("Нет такого профиля")
    if agent_id:
        agent = db.get_agent(agent_id)
        if not agent or agent["revoked"]:
            raise PrintError("Компьютер не найден")
        if printer and not _printer_info(agent, printer):
            raise PrintError(f"На компьютере «{agent['name']}» нет принтера «{printer}»")
    changed = (prof["agent_id"], prof["printer"]) != (agent_id, printer)
    fields = {"agent_id": agent_id, "printer": printer}
    if changed:  # настройки драйвера относятся к конкретному принтеру
        fields.update(devmode=None, devmode_summary=None)
    db.update_profile(key, **fields)


def revoke(agent_id: int) -> None:
    db.update_agent(agent_id, revoked=1)
    for p in db.list_profiles():
        if p["agent_id"] == agent_id:
            db.update_profile(p["key"], agent_id=None, printer=None, devmode=None, devmode_summary=None)
    wake(agent_id)


def rename(agent_id: int, name: str) -> None:
    name = name.strip()[:60]
    if not name:
        raise PrintError("Название не может быть пустым")
    db.update_agent(agent_id, name=name)


# ---------- HTTP для программы на компьютере ----------

def _json_error(status: int, text: str) -> web.HTTPException:
    cls = {401: web.HTTPUnauthorized, 403: web.HTTPForbidden, 404: web.HTTPNotFound,
           429: web.HTTPTooManyRequests}.get(status, web.HTTPBadRequest)
    return cls(text=json.dumps({"ok": False, "error": text}, ensure_ascii=False), content_type="application/json")


def _auth(request: web.Request) -> dict:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    agent = db.agent_by_token(_hash(token)) if token else None
    if not agent:
        raise _json_error(401, "Компьютер не подключён или отключён в панели. Подключите его заново кодом")
    return agent


def _job_payload(job: dict) -> dict:
    return {"id": job["id"], "label": job["label"], "pages": len(job["pages"]), "settings": job["settings"]}


def _agent_profiles(agent_id: int) -> list[dict]:
    return [{"key": p["key"], "title": p["title"], "printer": p["printer"], "devmode": p["devmode"],
             "summary": p["devmode_summary"]} for p in db.list_profiles() if p["agent_id"] == agent_id]


async def pair(request: web.Request) -> web.Response:
    ip = request.remote or "?"
    recent = [t for t in _pair_attempts.get(ip, []) if time.time() - t < 600]
    if len(recent) >= 10:
        raise _json_error(429, "Слишком много попыток. Подождите 10 минут")
    _pair_attempts[ip] = recent + [time.time()]
    body = await request.json()
    code = str(body.get("code", "")).strip().replace(" ", "")
    if not db.use_pair_code(code):
        raise _json_error(403, "Код неверный или устарел. Получите новый в панели: «Принтеры → Подключить компьютер»")
    token = secrets.token_urlsafe(32)
    name = str(body.get("name") or "Компьютер с принтером").strip()[:60]
    agent = db.add_agent(name, _hash(token), str(body.get("version", ""))[:20], body.get("status") or {})
    # если профили ещё никуда не привязаны — привязываем к этому компьютеру и его принтеру по умолчанию
    default = (body.get("status") or {}).get("default_printer")
    if default:
        for p in db.list_profiles():
            if not p["agent_id"]:
                db.update_profile(p["key"], agent_id=agent["id"], printer=default)
    log.info("Подключён компьютер «%s» (id %s)", name, agent["id"])
    return web.json_response({"ok": True, "token": token, "agent_id": agent["id"], "name": agent["name"]})


async def poll(request: web.Request) -> web.Response:
    agent = _auth(request)
    body = await request.json()
    db.update_agent(agent["id"], last_seen=time.time(), status=body.get("status") or {},
                    version=str(body.get("version", ""))[:20])
    active = body.get("active_job")

    # задание, которое сервер считает «на компьютере», а программа о нём не знает (перезапуск, сбой)
    for job in db.print_jobs("agent_id=? AND state IN ('sent', 'printing')", (agent["id"],)):
        if job["id"] != active and time.time() - _ts(job["updated_at"]) > 30:
            await _notify(db.update_print_job(job["id"], state="error",
                                              detail="Программа печати на компьютере перезапустилась — проверьте, что напечаталось"))

    def collect():
        cancels = [{"job_id": j["id"], "win_job": j["win_job"], "printer": j["settings"]["printer"]}
                   for j in db.print_jobs("agent_id=? AND cancel=1 AND state IN ('sent', 'printing')", (agent["id"],))]
        job = None if active else db.take_print_job(agent["id"])
        return job, cancels

    job, cancels = collect()
    if not job and not cancels and body.get("wait"):
        ev = _wake.setdefault(agent["id"], asyncio.Event())
        ev.clear()
        try:
            await asyncio.wait_for(ev.wait(), POLL_WAIT)
        except asyncio.TimeoutError:
            pass
        if db.get_agent(agent["id"])["revoked"]:
            raise _json_error(401, "Компьютер отключён в панели")
        db.update_agent(agent["id"], last_seen=time.time())
        job, cancels = collect()
    if job:
        await _notify(job)
    return web.json_response({"ok": True, "name": db.get_agent(agent["id"])["name"],
                              "job": _job_payload(job) if job else None, "cancel": cancels,
                              "profiles": _agent_profiles(agent["id"])})


async def page(request: web.Request) -> web.StreamResponse:
    agent = _auth(request)
    job = db.get_print_job(int(request.match_info["id"]))
    n = int(request.match_info["n"])
    if not job or job["agent_id"] != agent["id"] or not 0 <= n < len(job["pages"]):
        raise _json_error(404, "Лист не найден")
    path = Path(job["pages"][n])
    if not path.exists():
        raise _json_error(404, "Файл листа пропал с сервера")
    return web.FileResponse(path)


async def report(request: web.Request) -> web.Response:
    agent = _auth(request)
    job = db.get_print_job(int(request.match_info["id"]))
    if not job or job["agent_id"] != agent["id"]:
        raise _json_error(404, "Задание не найдено")
    body = await request.json()
    state = body.get("state")
    if state not in ("printing", "done", "error", "cancelled"):
        raise _json_error(400, "Неверный статус")
    if job["state"] in ("done", "error", "cancelled"):
        return web.json_response({"ok": True})  # повторное сообщение — уже учтено
    fields = {"state": state, "detail": str(body.get("detail") or "")[:300], "problem": int(bool(body.get("problem")))}
    if body.get("win_job") is not None:
        fields["win_job"] = int(body["win_job"])
    db.update_agent(agent["id"], last_seen=time.time())
    await _notify(db.update_print_job(job["id"], **fields))
    return web.json_response({"ok": True})


async def save_profile(request: web.Request) -> web.Response:
    """Программа на компьютере сохраняет настройки драйвера для профиля."""
    agent = _auth(request)
    prof = db.get_profile(request.match_info["key"])
    if not prof or prof["agent_id"] != agent["id"]:
        raise _json_error(403, "Этот профиль печатает другой компьютер")
    body = await request.json()
    devmode = body.get("devmode")
    if devmode is not None and not isinstance(devmode, dict):
        raise _json_error(400, "Неверные настройки")
    db.update_profile(prof["key"], devmode=devmode, devmode_summary=str(body.get("summary") or "")[:200] or None)
    return web.json_response({"ok": True})


def routes() -> list:
    return [
        web.post("/agent/v1/pair", pair),
        web.post("/agent/v1/poll", poll),
        web.get(r"/agent/v1/jobs/{id:\d+}/pages/{n:\d+}", page),
        web.post(r"/agent/v1/jobs/{id:\d+}/report", report),
        web.post("/agent/v1/profiles/{key}", save_profile),
    ]
