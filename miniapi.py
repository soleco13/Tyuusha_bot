"""API Telegram Mini App (/mapi/*). Личность клиента — по подписанным данным Telegram (initData)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import shutil
import time
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qsl

from aiohttp import web
from PIL import Image

import cards
import config
import db
import docs
import photos
import pricing
import service

log = logging.getLogger("miniapi")

INIT_DATA_TTL = 24 * 3600
MAX_FILE = 20 * 1024 * 1024
MAX_PIXELS = 60_000_000
MAX_PHOTOS = {"deck36": 36, "deck54": 54}
MAX_PHOTO_JOB = 54
MAX_COPIES_DOC = 20
MAX_OPEN_ORDERS = 5  # заказов «new» от одного клиента одновременно
_render_slot = asyncio.Semaphore(1)  # рендер колоды грузит процессор — по одному
_placing: set[int] = set()


def _verify_init_data(raw: str) -> dict | None:
    try:
        pairs = dict(parse_qsl(raw, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    got = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), got):
        return None
    if time.time() - int(pairs.get("auth_date", "0")) > INIT_DATA_TTL:
        return None
    try:
        user = json.loads(pairs["user"])
        user["id"] = int(user["id"])
    except (KeyError, ValueError, TypeError):
        return None
    return user


def _user(request: web.Request) -> dict:
    user = _verify_init_data(request.headers.get("X-Init-Data", ""))
    if not user:
        raise web.HTTPUnauthorized(text=json.dumps({"ok": False, "error": "Откройте приложение из Telegram заново"}),
                                   content_type="application/json")
    return user


def _fail(text: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": text}, status=status)


def _public(o: dict) -> dict:
    p = o["params"]
    events = db.events_for(o["id"])
    times = {"new": o["created_at"], "printed": o.get("printed_at"), "issued": o.get("issued_at")}
    if o["kind"] == "cards":
        deck = cards.DECKS[p["deck"]]
        title, n = deck.title.split(" (")[0], len(cards.deck_cards(deck))
        sub = f"{n} карт · {p['photos']} фото"
    elif o["kind"] == "doc":
        title = "Документ"
        sub = f"{p['doc_pages']} стр. · {p['copies']} коп. · {'цвет' if p['color'] else 'ч/б'}"
    else:
        title = f"Фото {photos.FORMATS[p['format']][0].split(' (')[0].split(' —')[0]}"
        sub = (f"{p['photos']} фото · {p['copies']} коп. · {'цвет' if p['color'] else 'ч/б'} · "
               f"{service.QUALITY_TITLES[p['quality']].lower()}")
    return {"id": o["id"], "kind": o["kind"], "status": o["status"], "amount": o["amount"] / 100,
            "title": title, "sub": sub, "created": o["created_at"], "times": times,
            "reason": o.get("cancel_reason"), "thumb": bool(o.get("previews")),
            "events": [{"at": e["at"], "text": e["text"]} for e in events if e["actor"] != "admin" or e["kind"] != "info"][-10:]}


def _own_order(request: web.Request, user: dict) -> dict:
    try:
        order = service.get(int(request.match_info["id"]))
    except ValueError:
        raise service.ServiceError("Неверный номер заказа")
    if order["user_id"] != user["id"]:
        raise service.ServiceError("Заказ не найден")
    return order


async def get_config(request: web.Request) -> web.Response:
    _user(request)
    return web.json_response({"ok": True, "prices": pricing.get_prices(), "max_photos": MAX_PHOTOS,
                              "max_photo_job": MAX_PHOTO_JOB, "default_back": cards.DEFAULT_BACK,
                              "backs": [{"key": k, "title": t} for k, (t, _) in cards.BACKS.items()]})


async def list_orders(request: web.Request) -> web.Response:
    user = _user(request)
    return web.json_response({"ok": True, "orders": [_public(o) for o in db.list_orders(user_id=user["id"], limit=100)]})


async def order_thumb(request: web.Request) -> web.StreamResponse:
    user = _user(request)
    order = _own_order(request, user)
    if not order.get("previews"):
        raise web.HTTPNotFound()
    return web.FileResponse(order["previews"][0], headers={"Cache-Control": "private, max-age=3600"})


async def cancel_order(request: web.Request) -> web.Response:
    user = _user(request)
    order = _own_order(request, user)
    await service.cancel(order["id"], actor="client", reason="отменён клиентом в приложении")
    return web.json_response({"ok": True, "order": _public(service.get(order["id"]))})


async def _save_part(part, path, limit: int, what: str) -> None:
    size = 0
    with open(path, "wb") as f:
        while chunk := await part.read_chunk(256 * 1024):
            size += len(chunk)
            if size > limit:
                raise service.ServiceError(f"{what} больше {limit // 1048576} МБ")
            f.write(chunk)


async def inspect_doc(request: web.Request) -> web.Response:
    """Считает страницы документа, чтобы показать цену до оформления. Файл не сохраняется."""
    user = _user(request)
    if user["id"] in _placing:
        return _fail("Подождите, предыдущий заказ ещё оформляется", 429)
    tmp = config.SESSIONS_DIR / f"i{user['id']}_{uuid.uuid4().hex[:8]}"
    try:
        tmp.mkdir(parents=True)
        reader = await request.multipart()
        part = await reader.next()
        if part is None or part.name != "document":
            raise service.ServiceError("Файл не получен")
        await _save_part(part, tmp / "doc", MAX_FILE, "Файл")
        pages = await asyncio.to_thread(docs.count_pages, tmp / "doc")
        return web.json_response({"ok": True, "pages": pages})
    except docs.DocError as e:
        return _fail(str(e))
    except service.ServiceError as e:
        return _fail(str(e))
    except Exception:
        log.exception("Не удалось проверить документ")
        return _fail("Не получилось прочитать файл. Попробуйте сохранить его как PDF", 500)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _check_image(path) -> None:
    with Image.open(path) as im:
        if im.format not in ("JPEG", "PNG"):
            raise service.ServiceError("Принимаем только JPG и PNG")
        if im.width * im.height > MAX_PIXELS:
            raise service.ServiceError("Фото слишком большое по разрешению")
        im.verify()


async def create_order(request: web.Request) -> web.Response:
    user = _user(request)
    uid = user["id"]
    if uid in _placing:
        return _fail("Предыдущий заказ ещё оформляется — подождите немного", 429)
    if sum(1 for o in db.list_orders(["new"], user_id=uid) if o) >= MAX_OPEN_ORDERS:
        return _fail("У вас уже несколько заказов ждут печати. Дождитесь их или отмените лишние.", 429)
    _placing.add(uid)
    session_dir = config.SESSIONS_DIR / f"m{uid}_{uuid.uuid4().hex[:8]}"
    try:
        meta, files = None, []
        session_dir.mkdir(parents=True)
        reader = await request.multipart()
        while (part := await reader.next()) is not None:
            if part.name == "meta":
                meta = json.loads(await part.text())
            elif part.name == "document":
                if files:
                    raise service.ServiceError("Документ можно загрузить только один")
                path = session_dir / "document"
                await _save_part(part, path, MAX_FILE, "Файл")
                files.append(path)
            elif part.name == "photo":
                if len(files) >= MAX_PHOTO_JOB:
                    raise service.ServiceError(f"Не больше {MAX_PHOTO_JOB} фото")
                path = session_dir / f"photo_{len(files) + 1:02d}"
                size = 0
                with open(path, "wb") as f:
                    while chunk := await part.read_chunk(256 * 1024):
                        size += len(chunk)
                        if size > MAX_FILE:
                            raise service.ServiceError("Фото больше 20 МБ")
                        f.write(chunk)
                files.append(path)
        if not isinstance(meta, dict) or not files:
            raise service.ServiceError("Добавьте хотя бы одно фото")
        kind = meta.get("kind")
        if kind != "doc":
            for path in files:
                _check_image(path)
        if kind == "cards":
            deck = meta.get("deck")
            if deck not in cards.DECKS:
                raise service.ServiceError("Неизвестная колода")
            if len(files) > MAX_PHOTOS[deck]:
                raise service.ServiceError(f"Для этой колоды — не больше {MAX_PHOTOS[deck]} фото")
            back = meta.get("back") or cards.DEFAULT_BACK
            if back not in cards.BACKS:
                raise service.ServiceError("Неизвестная рубашка")
            params = {"deck": deck, "back": back}
        elif kind == "photo":
            fmt, copies = meta.get("format"), int(meta.get("copies", 1))
            quality = meta.get("quality", "high")
            if fmt not in photos.FORMATS or quality not in service.QUALITY_TITLES or not 1 <= copies <= 20:
                raise service.ServiceError("Неверные параметры печати")
            params = {"format": fmt, "copies": copies, "color": bool(meta.get("color", True)), "quality": quality}
        elif kind == "doc":
            copies = int(meta.get("copies", 1))
            if not 1 <= copies <= MAX_COPIES_DOC:
                raise service.ServiceError("Неверные параметры печати")
            params = {"copies": copies, "color": bool(meta.get("color", True)), "quality": "normal"}
            params["doc_pages"] = await asyncio.to_thread(docs.count_pages, files[0])
            if params["doc_pages"] * copies > docs.MAX_SHEETS:
                raise service.ServiceError(f"Не больше {docs.MAX_SHEETS} листов в заказе — уменьшите число копий")
        else:
            raise service.ServiceError("Неизвестный тип заказа")

        out = session_dir / "print"
        async with _render_slot:
            if kind == "cards":
                pages = await asyncio.to_thread(cards.build_deck, cards.DECKS[params["deck"]], files, out,
                                                back=params["back"])
                params.update(sheets=len(pages) // 2, color=True, quality="high")
                previews = [pages[0], pages[len(pages) // 2]]
            elif kind == "doc":
                once = await asyncio.to_thread(docs.build_doc_pages, files[0], not params["color"], out)
                pages = once * params["copies"]  # копии по порядку: весь документ, потом снова
                params["sheets"] = len(pages)
                previews = once[:2]
            else:
                pages = await asyncio.to_thread(photos.build_photo_pages, files, params["format"],
                                                params["copies"], not params["color"], out)
                params["sheets"] = len(pages)
                previews = pages[:2]
            params["photos"] = len(files) if kind != "doc" else 0
            preview_files = [await asyncio.to_thread(cards.make_preview, p, session_dir / f"preview_{i}.jpg")
                             for i, p in enumerate(previews)]
        amount, _ = pricing.quote(kind, params)
        session = {"kind": kind, "params": params, "amount": amount, "dir": session_dir, "photos": files,
                   "pages": pages, "previews": preview_files}
        tg_user = SimpleNamespace(id=uid, username=user.get("username"),
                                  full_name=" ".join(x for x in (user.get("first_name"), user.get("last_name")) if x) or str(uid))
        order = await service.create_order(session, tg_user)
        return web.json_response({"ok": True, "order": _public(order)})
    except (json.JSONDecodeError, TypeError, ValueError):
        return _fail("Неверные данные заказа")
    except (service.ServiceError, docs.DocError) as e:
        return _fail(str(e))
    except Exception:
        log.exception("Заказ из Mini App не оформился")
        return _fail("Не получилось собрать макет. Попробуйте другие фото или файл.", 500)
    finally:
        _placing.discard(uid)
        shutil.rmtree(session_dir, ignore_errors=True)


def routes() -> list:
    return [web.get("/mapi/config", get_config), web.get("/mapi/orders", list_orders),
            web.post("/mapi/orders", create_order), web.post("/mapi/doc/inspect", inspect_doc),
            web.get(r"/mapi/orders/{id:\d+}/thumb", order_thumb),
            web.post(r"/mapi/orders/{id:\d+}/cancel", cancel_order)]
