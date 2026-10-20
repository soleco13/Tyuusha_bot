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
from PIL import Image, ImageOps

import agents
import cards
import config
import db
import materials
import pricing
import miniapi
import printing
import products
import service
import tg

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
    except (service.ServiceError, agents.PrintError) as e:
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
        "profile": materials.profile_for(o["params"].get("paper"), o["kind"]),
        "paper_title": (materials.PAPERS.get(o["params"].get("paper") or "") or ("",))[0],
        "duplex": service.is_duplex(o),
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
        "print_part": (o.get("print_job") or {}).get("part", "front"),
        "stages": {k: v[1] for k, v in service.STAGES.items()},
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
    profiles = {}
    if config.PRINT_MODE == "agent":
        printer = agents.printer_summary()
        profiles = {p["key"]: {"agent": p["agent_name"], "printer": p["printer"], "ready": p["ready"],
                               "tuned": p["has_devmode"]} for p in agents.overview()["profiles"]}
    elif config.PRINT_MODE == "browser":
        printer = {"name": "печать из браузера", "ok": True, "problems": [], "jobs": []}
    elif config.PRINT_MODE == "printer":
        printer = await asyncio.to_thread(printing.printer_status, config.PRINTER_NAME)
    else:
        printer = {"name": "сохранение в файлы", "ok": True, "problems": [], "jobs": []}
    return web.json_response({
        "ok": True,
        "groups": [{"key": k, "title": t, "count": sum(counts.get(s, 0) for s in st) if st else sum(counts.values())}
                   for k, (t, st) in GROUPS.items()],
        "counts": counts,
        "today": {"orders": today_count, "amount": pricing.format_rub(today_sum)},
        "printer": printer, "print_mode": config.PRINT_MODE, "profiles": profiles,
        "stock_low": [{"title": m["title"], "state": m["state"], "stock": m["stock"], "unit": m["unit"]}
                      for m in materials.stock().values() if m["state"] != "ok"],
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
    elif action == "printed_ok":
        await service.finish_browser_print(oid)
        message = "Печать подтверждена"
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
    if o["status"] == "printing" and config.PRINT_MODE == "agent":
        return "Задание отправлено на компьютер с принтером — статус обновится сам"
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
    if request.query.get("size") == "print" and kind == "pages":  # оригинал листа для печати, без сжатия
        return web.FileResponse(src, headers={"Cache-Control": "private, max-age=600"})
    size = 480 if request.query.get("size") == "thumb" else 1800
    cache = Path(order["dir"]) / "thumbs" / f"{kind}_{idx}_{size}.jpg"
    path = await asyncio.to_thread(_thumb, src, cache, size)
    return web.FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


PRINT_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Печать — {title}</title>
<style>
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font: 15px/1.4 system-ui, sans-serif; background: #e9ecf2; color: #172033; }}
.bar {{ position: sticky; top: 0; z-index: 5; background: #fff; border-bottom: 1px solid #d5dae5; padding: 12px 16px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
.bar b {{ font-size: 16px; }} .bar .hint {{ flex: 1 1 100%; color: #5b6479; font-size: 13px; }}
button {{ font: inherit; border: 0; border-radius: 10px; padding: 9px 16px; cursor: pointer; background: #e4ecfd; color: #1d4fc4; font-weight: 600; }}
button.ok {{ background: #2563eb; color: #fff; }} button.no {{ background: #fde4e4; color: #b3261e; }}
.sheet {{ width: 210mm; height: 297mm; margin: 14px auto; background: #fff; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,.18); }}
.sheet img {{ display: block; width: 210mm; height: 297mm; {filter} }}
#msg {{ font-size: 14px; }}
@media print {{
  .bar {{ display: none; }} body {{ background: #fff; }}
  .sheet {{ margin: 0; box-shadow: none; page-break-after: always; break-after: page; }}
  .sheet:last-child {{ page-break-after: auto; break-after: auto; }}
}}
</style></head><body>
<div class="bar">
  <b>{title}</b>
  <button onclick="window.print()">🖨 Печатать</button>
  {confirm_buttons}
  <span id="msg"></span>
  <div class="hint">В окне печати: принтер — Epson L3250, бумага A4, <b>масштаб 100%</b> (не «по размеру страницы»), поля — «нет», {color_hint}, качество — {quality}. Листов: {count}.</div>
</div>
{sheets}
<script>
const images = [...document.images];
Promise.all(images.map((i) => i.complete ? 0 : new Promise((r) => {{ i.onload = i.onerror = r; }}))).then(() => setTimeout(() => window.print(), 300));
async function act(a) {{
  const r = await fetch("/api/orders/{oid}/actions/" + a, {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: "{{}}" }});
  const d = await r.json();
  document.getElementById("msg").textContent = d.ok ? (a === "printed_ok" ? "Готово, заказ отмечен напечатанным. Окно можно закрыть." : "Печать отменена, заказ вернулся в прежний статус.") : (d.error || "Ошибка");
  if (d.ok) setTimeout(() => window.close(), 1200);
}}
</script></body></html>"""


async def print_page(request: web.Request) -> web.Response:
    """Страница для печати из браузера: листы A4 в реальный размер, диалог печати открывается сам."""
    if not _authorized(request):
        raise web.HTTPFound("/")
    if request.match_info["id"] == "test":
        from PIL import ImageDraw
        import cards
        path = config.DATA / "testprint.png"
        page = Image.new("RGB", cards.A4, "white")
        d = ImageDraw.Draw(page)
        x, y, side = cards.mm(80), cards.mm(40), cards.mm(50)
        d.rectangle((x, y, x + side, y + side), outline="black", width=4)
        d.text((cards.A4[0] // 2, cards.mm(25)), "Пробная печать", font=cards.rank_font(cards.mm(5)), fill="black", anchor="mm")
        d.text((cards.A4[0] // 2, y + side + cards.mm(10)), "Сторона квадрата должна быть ровно 50 мм",
               font=cards.rank_font(cards.mm(3.5)), fill="black", anchor="mm")
        page.save(path, dpi=(cards.DPI, cards.DPI))
        sheets = '<div class="sheet"><img src="/print/test/image"></div>'
        html_text = PRINT_PAGE.format(title="Пробный лист", confirm_buttons="", color_hint="цвет любой", quality="обычное",
                                      count=1, sheets=sheets, filter="", oid=0)
        return web.Response(text=html_text, content_type="text/html", headers={"Cache-Control": "no-store"})
    order = service.get(int(request.match_info["id"]))
    part = request.match_info["part"]
    pages = list(range(len(order["pages"])))
    if order["kind"] == "cards":
        half = len(pages) // 2
        pages = pages[half:] if part == "back" else pages[:half]
    p = order["params"]
    color = p.get("color", True)
    quality = service.QUALITY_TITLES.get(p.get("quality", "high"), "высокое").lower()
    title = f"Заказ №{order['id']}" + (" · рубашки" if part == "back" else "")
    confirm = ('<button class="ok" onclick="act(\'printed_ok\')">✅ Напечатано</button>'
               '<button class="no" onclick="act(\'cancel_job\')">✖ Не получилось</button>') if order["status"] == "printing" else ""
    sheets = "".join(f'<div class="sheet"><img src="/api/orders/{order["id"]}/files/pages/{i}?size=print"></div>' for i in pages)
    html_text = PRINT_PAGE.format(title=title, confirm_buttons=confirm, count=len(pages), sheets=sheets, oid=order["id"],
                                  color_hint="цветная печать" if color else "чёрно-белая печать", quality=quality,
                                  filter="" if color else "filter: grayscale(1);")
    return web.Response(text=html_text, content_type="text/html", headers={"Cache-Control": "no-store"})


async def print_test_image(request: web.Request) -> web.StreamResponse:
    if not _authorized(request):
        raise web.HTTPForbidden()
    return web.FileResponse(config.DATA / "testprint.png")


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


# ---------- склад ----------

async def stock_get(request: web.Request) -> web.Response:
    titles = {k: v[0] for k, v in materials.MATERIALS.items()}
    reasons = {"order": "заказ", "reprint": "перепечатка", "release": "возврат с отменённого заказа",
               "income": "приход", "writeoff": "списание", "set": "инвентаризация"}
    log_rows = [{**r, "title": titles.get(r["key"], r["key"]), "reason_title": reasons.get(r["reason"], r["reason"])}
                for r in materials.log(50)]
    papers = {k: {"title": t, "state": materials.paper_state(k)} for k, (t, *_rest) in materials.PAPERS.items()}
    return web.json_response({"ok": True, "materials": list(materials.stock().values()), "log": log_rows,
                              "papers": papers})


async def stock_update(request: web.Request) -> web.Response:
    key = request.match_info["key"]
    body = await request.json()
    try:
        alerts = materials.adjust(
            key, delta=int(body.get("delta") or 0),
            set_to=int(body["set"]) if body.get("set") not in (None, "") else None,
            low=int(body["low"]) if body.get("low") not in (None, "") else None,
            note=str(body.get("note", ""))[:200])
    except materials.MaterialsError as e:
        raise service.ServiceError(str(e)) from e
    for text in alerts:
        await tg.notify_admins(text)
    return web.json_response({"ok": True, "message": "Склад обновлён", "materials": list(materials.stock().values())})


# ---------- статистика ----------

def _product_label(o: dict) -> str:
    p = o["params"]
    if o["kind"] == "cards":
        return {"deck36": "Колода 36 карт", "deck54": "Колода 54 карты", "uno": "UNO"}.get(p.get("deck"), "Карты")
    if o["kind"] == "craft":
        return products.PRODUCTS.get(p.get("product"), {}).get("title", "Изделие")
    if o["kind"] == "doc":
        return "Документы"
    return "Фото " + {"10x15": "10×15", "a5": "A5", "a4": "A4"}.get(p.get("format"), "")


async def stats(request: web.Request) -> web.Response:
    import datetime as dt
    days = min(365, max(1, int(request.query.get("days", 30))))
    start = dt.date.today() - dt.timedelta(days=days - 1)
    since = start.isoformat()
    rows = db.orders_since(since)
    live = [o for o in rows if o["status"] != "cancelled"]
    by_day = {(start + dt.timedelta(days=i)).isoformat(): {"orders": 0, "revenue": 0} for i in range(days)}
    groups: dict[str, dict] = {}
    backs: dict[str, int] = {}
    papers: dict[str, int] = {}
    users: dict[int, int] = {}
    for o in live:
        day = o["created_at"][:10]
        if day in by_day:
            by_day[day]["orders"] += 1
            by_day[day]["revenue"] += o["amount"]
        g = groups.setdefault(_product_label(o), {"orders": 0, "revenue": 0})
        g["orders"] += 1
        g["revenue"] += o["amount"]
        back = o["params"].get("back")
        if back and (o["kind"] == "cards" or o["kind"] == "craft"):
            title = cards.back_title(back)
            backs[title] = backs.get(title, 0) + 1
        paper = materials.PAPERS.get(o["params"].get("paper") or "")
        if paper:
            papers[paper[0]] = papers.get(paper[0], 0) + o["params"].get("sheets", 0)
        users[o["user_id"]] = users.get(o["user_id"], 0) + 1
    revenue = sum(o["amount"] for o in live)
    used = materials.used_since(since)
    stock = materials.stock()
    return web.json_response({
        "ok": True, "days": days, "orders": len(live), "cancelled": len(rows) - len(live),
        "issued": sum(1 for o in live if o["status"] == "issued"),
        "revenue": pricing.format_rub(revenue), "avg": pricing.format_rub(revenue // len(live)) if live else "—",
        "clients": len(users), "repeat_clients": sum(1 for n in users.values() if n > 1),
        "by_day": [{"day": d, "orders": v["orders"], "revenue": v["revenue"] / 100} for d, v in by_day.items()],
        "products": sorted(({"title": k, "orders": v["orders"], "revenue": pricing.format_rub(v["revenue"]),
                             "kop": v["revenue"]} for k, v in groups.items()), key=lambda x: -x["kop"]),
        "backs": sorted(({"title": k, "count": v} for k, v in backs.items()), key=lambda x: -x["count"])[:10],
        "papers": sorted(({"title": k, "sheets": v} for k, v in papers.items()), key=lambda x: -x["sheets"]),
        "materials": [{"title": stock[k]["title"], "unit": stock[k]["unit"], "used": n}
                      for k, n in sorted(used.items(), key=lambda x: -x[1]) if k in stock],
    })


# ---------- этапы заказа с фото ----------

async def order_stage(request: web.Request) -> web.Response:
    oid = int(request.match_info["id"])
    order = service.get(oid)
    stage, text, photo = "", "", None
    reader = await request.multipart()
    while (part := await reader.next()) is not None:
        if part.name == "stage":
            stage = (await part.text()).strip()
        elif part.name == "text":
            text = (await part.text()).strip()[:800]
        elif part.name == "photo" and part.filename:
            raw = await part.read(decode=False)
            if len(raw) > 15 * 1024 * 1024:
                raise service.ServiceError("Фото больше 15 МБ")
            try:
                img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
            except Exception as e:
                raise service.ServiceError("Не получилось прочитать фото — нужен JPG или PNG") from e
            img.thumbnail((2560, 2560))
            photo = Path(order["dir"]) / f"stage_{int(time.time())}.jpg"
            photo.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(img.save, photo, "JPEG", quality=90)
    await service.send_stage(oid, stage, text, photo)
    return web.json_response({"ok": True, "message": "Клиент получил сообщение" + (" с фото" if photo else ""),
                              "order": _detail(service.get(oid))})


# ---------- принтеры: компьютеры с агентом и профили печати ----------

AGENT_EXE = config.BASE / "agent" / "dist" / "TyushaPrint.exe"


async def printers_overview(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "mode": config.PRINT_MODE, **agents.overview(), "download": True})


async def pair_code(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "code": agents.new_pair_code(), "expires_in": agents.PAIR_TTL})


async def agent_update(request: web.Request) -> web.Response:
    agent_id = int(request.match_info["id"])
    body = await request.json()
    if body.get("update"):
        agents.request_update(agent_id)
        return web.json_response({"ok": True, "message": "Команда отправлена: программа проверит обновление и поставит его, когда принтер свободен"})
    if body.get("revoke"):
        agents.revoke(agent_id)
        return web.json_response({"ok": True, "message": "Компьютер отключён — печатать на нём больше нельзя"})
    agents.rename(agent_id, str(body.get("name", "")))
    return web.json_response({"ok": True, "message": "Название сохранено"})


async def profile_update(request: web.Request) -> web.Response:
    body = await request.json()
    agent_id = int(body["agent_id"]) if body.get("agent_id") else None
    agents.bind_profile(request.match_info["key"], agent_id, body.get("printer") or None)
    return web.json_response({"ok": True, "message": "Профиль сохранён"})


async def profile_test(request: web.Request) -> web.Response:
    """Пробный лист через профиль: проверка связи, принтера и масштаба 1:1."""
    from PIL import ImageDraw
    import cards
    key = request.match_info["key"]
    path = config.DATA / "testprint.png"
    page = Image.new("RGB", cards.A4, "white")
    d = ImageDraw.Draw(page)
    x, y, side = cards.mm(80), cards.mm(40), cards.mm(50)
    d.rectangle((x, y, x + side, y + side), outline="black", width=4)
    d.text((cards.A4[0] // 2, cards.mm(25)), "Тюша · пробный лист", font=cards.rank_font(cards.mm(5)), fill="black", anchor="mm")
    d.text((cards.A4[0] // 2, y + side + cards.mm(10)), "Сторона квадрата должна быть ровно 50 мм",
           font=cards.rank_font(cards.mm(3.5)), fill="black", anchor="mm")
    d.text((cards.A4[0] // 2, y + side + cards.mm(18)), f"Профиль: {agents.PROFILES.get(key, key)}",
           font=cards.rank_font(cards.mm(3.5)), fill="black", anchor="mm")
    await asyncio.to_thread(page.save, path, dpi=(cards.DPI, cards.DPI))
    job = agents.submit(None, key, "Тюша: пробный лист", [path], True, "normal")
    return web.json_response({"ok": True, "job_id": job["id"],
                              "message": f"Пробный лист отправлен на «{job['settings']['printer']}»"})


async def print_job_state(request: web.Request) -> web.Response:
    job = db.get_print_job(int(request.match_info["id"]))
    if not job:
        raise web.HTTPNotFound()
    return web.json_response({"ok": True, "state": job["state"], "detail": job["detail"], "problem": bool(job["problem"])})


async def agent_download(request: web.Request) -> web.StreamResponse:
    if not AGENT_EXE.exists():  # обычный случай: берём последнюю версию с GitHub Releases
        raise web.HTTPFound(f"https://github.com/{config.AGENT_UPDATE_REPO}/releases/latest/download/TyushaPrint.exe")
    return web.FileResponse(AGENT_EXE, headers={"Content-Disposition": 'attachment; filename="TyushaPrint.exe"'})


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
        web.get("/api/stock", stock_get), web.post("/api/stock/{key}", stock_update),
        web.get("/api/stats", stats),
        web.post(r"/api/orders/{id:\d+}/stage", order_stage),
        web.post(r"/api/printer/jobs/{job:\d+}/cancel", printer_cancel_job),
        *miniapi.routes(),
        *agents.routes(),
        web.get("/api/printers", printers_overview), web.post("/api/printers/pair-code", pair_code),
        web.post(r"/api/printers/agents/{id:\d+}", agent_update),
        web.put("/api/printers/profiles/{key}", profile_update),
        web.post("/api/printers/profiles/{key}/test", profile_test),
        web.get(r"/api/printers/jobs/{id:\d+}", print_job_state),
        web.get("/agent/download", agent_download),
        web.get(r"/print/{id:\d+}/{part:front|back}", print_page), web.get("/print/{id:test}", print_page),
        web.get("/print/test/image", print_test_image),
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
