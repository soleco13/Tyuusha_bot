"""Веб-админка заказов: API на aiohttp + одностраничный интерфейс из папки admin/."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import logging
import secrets
import time
import zipfile
from pathlib import Path

from aiohttp import web
from PIL import Image

import config
import db
import pricing
import miniapi
import printing
import service

log = logging.getLogger("admin")

STATIC = config.BASE / "admin"
COOKIE = "tyusha_admin"
GROUPS = {
    "work": ("В работе", ["new", "printing", "fronts_printed"]),
    "ready": ("Ждут выдачи", ["printed"]),
    "done": ("Выданы", ["issued"]),
    "cancelled": ("Отменены", ["cancelled"]),
    "all": ("Все", []),
}

_secret_file = config.DATA / "admin_secret"
if not _secret_file.exists():
    _secret_file.write_text(secrets.token_hex(32))
_SECRET = _secret_file.read_text().strip()


def _token() -> str:
    return hmac.new(_SECRET.encode(), ("admin:" + config.ADMIN_PASSWORD).encode(), hashlib.sha256).hexdigest()


def _authorized(request: web.Request) -> bool:
    return bool(config.ADMIN_PASSWORD) and hmac.compare_digest(request.cookies.get(COOKIE, ""), _token())


@web.middleware
async def auth_middleware(request: web.Request, handler):
    path = request.path
    if path.startswith("/api/") and path not in ("/api/login", "/api/me") and not _authorized(request):
        return web.json_response({"ok": False, "error": "Нужно войти заново"}, status=401)
    try:
        return await handler(request)
    except service.ServiceError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    except (ValueError, KeyError) as e:
        return web.json_response({"ok": False, "error": f"Неверные данные: {e}"}, status=400)


# ---------- сериализация ----------

def _item(o: dict) -> dict:
    label, emoji, _ = service.STATUSES[o["status"]]
    return {
        "id": o["id"], "kind": o["kind"], "title": service.short_title(o),
        "status": o["status"], "status_label": label, "emoji": emoji,
        "amount": o["amount"], "amount_text": pricing.format_rub(o["amount"]),
        "user_name": o["user_name"], "username": o["username"], "user_id": o["user_id"],
        "created_at": o["created_at"], "updated_at": o["updated_at"],
        "print_state": o["print_state"], "last_error": o["last_error"],
        "actions": service.allowed_actions(o),
    }


def _detail(o: dict) -> dict:
    d = _item(o)
    d.update({
        "description": service.describe(o["kind"], o["params"]).split("\n"),
        "params": o["params"],
        "printed_at": o["printed_at"], "issued_at": o["issued_at"],
        "cancelled_at": o["cancelled_at"], "cancel_reason": o["cancel_reason"],
        "admin_note": o["admin_note"] or "",
        "pages": [{"name": Path(p).stem.replace("sheet_", "Лист ").replace("_face", " · лицо")
                   .replace("_back", " · рубашка").replace("page_", "Лист "),
                   "thumb": f"/api/orders/{o['id']}/files/pages/{i}?size=thumb",
                   "full": f"/api/orders/{o['id']}/files/pages/{i}?size=full"} for i, p in enumerate(o["pages"])],
        "sources": [{"name": f"Фото {i + 1}",
                     "thumb": f"/api/orders/{o['id']}/files/sources/{i}?size=thumb",
                     "full": f"/api/orders/{o['id']}/files/sources/{i}?size=full"} for i, _ in enumerate(o["sources"])],
        "events": db.events_for(o["id"]),
        "action_titles": service.ACTION_TITLES,
    })
    return d


# ---------- API ----------

async def index(request: web.Request) -> web.Response:
    # версии файлов в ссылках — после обновления браузер не возьмёт старые из кэша
    html_text = (STATIC / "index.html").read_text("utf-8")
    for name in ("app.css", "app.js"):
        html_text = html_text.replace(f"/static/{name}", f"/static/{name}?v={int((STATIC / name).stat().st_mtime)}")
    return web.Response(text=html_text, content_type="text/html", headers={"Cache-Control": "no-cache"})


async def login(request: web.Request) -> web.Response:
    body = await request.json()
    if not config.ADMIN_PASSWORD:
        return web.json_response({"ok": False, "error": "Пароль не задан: впишите ADMIN_PASSWORD в .env и перезапустите бота"},
                                 status=400)
    if not hmac.compare_digest(str(body.get("password", "")), config.ADMIN_PASSWORD):
        await asyncio.sleep(1)  # притормаживаем подбор пароля
        return web.json_response({"ok": False, "error": "Неверный пароль"}, status=401)
    resp = web.json_response({"ok": True})
    resp.set_cookie(COOKIE, _token(), max_age=30 * 24 * 3600, httponly=True, samesite="Strict",
                    secure=config.ADMIN_URL.startswith("https://"))
    return resp


async def logout(request: web.Request) -> web.Response:
    resp = web.json_response({"ok": True})
    resp.del_cookie(COOKIE)
    return resp


async def me(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "authorized": _authorized(request),
                              "password_set": bool(config.ADMIN_PASSWORD)})


async def summary(request: web.Request) -> web.Response:
    counts = db.count_by_status()
    today = time.strftime("%Y-%m-%d")
    today_count, today_sum = db.stats_since(today)
    printer = await asyncio.to_thread(printing.printer_status, config.PRINTER_NAME) \
        if config.PRINT_MODE == "printer" else {"name": "сохранение в файлы", "ok": True, "problems": [], "jobs": []}
    return web.json_response({
        "ok": True,
        "groups": [{"key": k, "title": t, "count": sum(counts.get(s, 0) for s in st) if st else sum(counts.values())}
                   for k, (t, st) in GROUPS.items()],
        "counts": counts,
        "today": {"orders": today_count, "amount": pricing.format_rub(today_sum)},
        "printer": printer, "print_mode": config.PRINT_MODE,
        "server_time": db.now(),
    })


async def orders(request: web.Request) -> web.Response:
    group = request.query.get("group", "work")
    statuses = GROUPS.get(group, GROUPS["all"])[1]
    items = db.list_orders(statuses or None, request.query.get("q", ""))
    return web.json_response({"ok": True, "orders": [_item(o) for o in items]})


async def order_detail(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "order": _detail(service.get(int(request.match_info["id"])))})


async def order_action(request: web.Request) -> web.Response:
    oid, action = int(request.match_info["id"]), request.match_info["action"]
    body = await request.json() if request.can_read_body else {}
    reason = str(body.get("reason", "")).strip()[:300]
    notify = bool(body.get("notify", True))
    message = "Готово"
    if action in ("print", "reprint"):
        o = await service.start_print(oid, "front", "admin")
        message = _print_message(o)
    elif action == "print_backs":
        message = _print_message(await service.start_print(oid, "back", "admin"))
    elif action == "cancel_job":
        await service.cancel_print_job(oid, "admin")
        message = "Задание снято с принтера"
    elif action == "issue":
        await service.issue(oid, "admin", notify)
        message = "Заказ отмечен выданным"
    elif action == "cancel":
        await service.cancel(oid, "admin", reason, notify)
        message = "Заказ отменён"
    elif action == "message":
        text = str(body.get("text", "")).strip()
        if not text:
            raise service.ServiceError("Напишите текст сообщения")
        await service.message_client(oid, text[:3000], "admin")
        message = "Сообщение отправлено клиенту"
    elif action == "note":
        service.set_note(oid, str(body.get("note", ""))[:2000])
        message = "Заметка сохранена"
    else:
        raise service.ServiceError("Неизвестное действие")
    return web.json_response({"ok": True, "message": message, "order": _detail(service.get(oid))})


def _print_message(o: dict) -> str:
    if o["status"] == "printing":
        return "Отправлено на принтер — слежу за очередью"
    done = {"fronts_printed": "Лицевые стороны готовы — теперь рубашки", "printed": "Напечатано",
            "issued": "Напечатано"}.get(o["status"], "Готово")
    return done + (" (режим «в файлы»: листы сохранены в data/printed)" if config.PRINT_MODE == "file" else "")


def _thumb(src: Path, cache: Path, max_side: int) -> Path:
    if not cache.exists() or cache.stat().st_mtime < src.stat().st_mtime:
        cache.parent.mkdir(exist_ok=True)
        img = Image.open(src).convert("RGB")
        img.thumbnail((max_side, max_side))
        img.save(cache, quality=85)
    return cache


async def order_file(request: web.Request) -> web.FileResponse:
    order = service.get(int(request.match_info["id"]))
    kind, idx = request.match_info["kind"], int(request.match_info["idx"])
    if kind not in ("pages", "sources"):
        raise web.HTTPNotFound()
    files = order[kind]
    if not 0 <= idx < len(files) or not Path(files[idx]).exists():
        raise web.HTTPNotFound()
    src = Path(files[idx])
    size = 480 if request.query.get("size") == "thumb" else 1800
    cache = Path(order["dir"]) / "thumbs" / f"{kind}_{idx}_{size}.jpg"
    path = await asyncio.to_thread(_thumb, src, cache, size)
    return web.FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


async def order_zip(request: web.Request) -> web.Response:
    order = service.get(int(request.match_info["id"]))

    def build() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            for p in order["pages"]:
                z.write(p, Path(p).name)
        return buf.getvalue()

    data = await asyncio.to_thread(build)
    return web.Response(body=data, content_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="tyusha_order_{order["id"]}.zip"'})


async def prices_get(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "prices": pricing.get_prices()})


async def prices_put(request: web.Request) -> web.Response:
    body = await request.json()
    return web.json_response({"ok": True, "prices": pricing.set_prices(body["prices"]),
                              "message": "Цены сохранены — новые заказы считаются по ним"})


async def printer_cancel_job(request: web.Request) -> web.Response:
    job_id = int(request.match_info["job"])
    printer = config.PRINTER_NAME or printing.default_printer()
    try:
        await asyncio.to_thread(printing.cancel_job, printer, job_id)
    except Exception as e:
        raise service.ServiceError(f"Не удалось удалить задание: {e}") from e
    return web.json_response({"ok": True, "message": "Задание удалено из очереди"})


async def miniapp_index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(config.BASE / "miniapp" / "index.html")


def make_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware], client_max_size=2 * 1024 * 1024)
    app.add_routes([
        web.get("/", index),
        web.post("/api/login", login), web.post("/api/logout", logout), web.get("/api/me", me),
        web.get("/api/summary", summary),
        web.get("/api/orders", orders),
        web.get(r"/api/orders/{id:\d+}", order_detail),
        web.post(r"/api/orders/{id:\d+}/actions/{action}", order_action),
        web.get(r"/api/orders/{id:\d+}/files/{kind}/{idx:\d+}", order_file),
        web.get(r"/api/orders/{id:\d+}/download", order_zip),
        web.get("/api/prices", prices_get), web.put("/api/prices", prices_put),
        web.post(r"/api/printer/jobs/{job:\d+}/cancel", printer_cancel_job),
        *miniapi.routes(),
        web.get("/miniapp", miniapp_index), web.get("/miniapp/", miniapp_index),
        web.static("/miniapp", config.BASE / "miniapp"),
        web.static("/static", STATIC),
    ])
    return app


async def start() -> web.AppRunner:
    runner = web.AppRunner(make_app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, config.ADMIN_HOST, config.ADMIN_PORT).start()
    log.info("Админка: %s", config.ADMIN_URL)
    return runner
