"""API Telegram Mini App (/mapi/*). Личность клиента — по подписанным данным Telegram (initData)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import shutil
import time
import io
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl

from aiohttp import web
from PIL import Image, ImageOps

import cards
import config
import db
import docs
import materials
import photoai
import photos
import pricing
import products
import service

log = logging.getLogger("miniapi")

INIT_DATA_TTL = 24 * 3600
MAX_FILE = 20 * 1024 * 1024
MAX_PIXELS = 60_000_000
MAX_PHOTOS = {"deck36": 36, "deck54": 54, "uno": 76}
MAX_PHOTO_JOB = 54
MAX_COPIES_DOC = 20
MAX_OPEN_ORDERS = 5  # заказов «new» от одного клиента одновременно
_render_slot = asyncio.Semaphore(1)  # рендер колоды грузит процессор — по одному
_preview_slot = asyncio.Semaphore(2)  # превью и поиск лиц — лёгкие, но тоже не без меры
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
    elif o["kind"] == "craft":
        title = products.PRODUCTS[p["product"]]["title"]
        sub = f"{p['count']} шт. · {p['sheets']} л. A4"
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
            "product": p.get("product") or p.get("deck"),
            "events": [{"at": e["at"], "text": e["text"]} for e in events if e["actor"] != "admin" or e["kind"] != "info"][-10:]}


def _uno_config() -> dict:
    import uno
    return {"palettes": [{"key": k, "title": t, "colors": c} for k, (t, c) in uno.PALETTES.items()],
            "default_palette": uno.DEFAULT_PALETTE, "text_max": uno.TEXT_MAX, "caption_max": uno.CAPTION_MAX,
            "inks": {k: {"ink": ["#%02X%02X%02X" % c for c in s["ink"]], "center": s["center"]}
                     for k, s in uno.BACK_SPECS.items()}}


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
                              "backs": [{"key": k, "title": t} for k, (t, _) in cards.BACKS.items()],
                              "uno_backs": [{"key": k, "title": t} for k, (t, _) in cards.backs_for("uno").items()],
                              "uno_default_back": cards.default_back("uno"),
                              "uno": _uno_config(),
                              "styles": [{"key": k, "title": t} for k, t in cards.STYLES.items()],
                              "default_style": cards.DEFAULT_STYLE,
                              "crafts": products.schema(), "papers": _papers(),
                              "paper_choices": {k: materials.choices_for(k) for k in ("cards", "photo", "doc")},
                              "enhance": {"available": photoai.can_enhance(), "low_res": LOW_RES,
                                          "max": MAX_ENHANCE},
                              "cutout": photoai.can_cutout()})


def _papers() -> dict:
    p = pricing.get_prices()["paper"]
    return {k: {"title": t, "hint": h, "extra": p.get(extra, 0) if extra else 0, "state": materials.paper_state(k)}
            for k, (t, h, _, extra, _) in materials.PAPERS.items()}


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


LOW_RES = 1000          # короче этой стороны фото считаем слабым — его можно улучшить нейросетью
MAX_ENHANCE = 30        # больше фото за заказ не улучшаем: это долго
MAX_CRAFT_PHOTOS = 60
MAX_CSV = 512 * 1024


async def _read_upload(request: web.Request, session_dir, max_photos: int) -> dict:
    """Части формы заказа/превью: meta, фото (с исходными именами), документ, фото рубашки, CSV."""
    got = {"meta": None, "files": [], "names": [], "back_photo": None, "csv": None}
    reader = await request.multipart()
    while (part := await reader.next()) is not None:
        if part.name == "meta":
            got["meta"] = json.loads(await part.text())
        elif part.name == "back_photo":
            if got["back_photo"]:
                raise service.ServiceError("Фото для рубашки можно загрузить только одно")
            got["back_photo"] = session_dir / "back_photo"
            await _save_part(part, got["back_photo"], MAX_FILE, "Фото рубашки")
            _check_image(got["back_photo"])
        elif part.name == "csv":
            raw = await part.read(decode=False)
            if len(raw) > MAX_CSV:
                raise service.ServiceError("Таблица больше 512 КБ")
            for enc in ("utf-8-sig", "cp1251"):
                try:
                    got["csv"] = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise service.ServiceError("Не получилось прочитать таблицу: сохраните её как CSV в UTF-8")
        elif part.name == "document":
            if got["files"]:
                raise service.ServiceError("Документ можно загрузить только один")
            path = session_dir / "document"
            await _save_part(part, path, MAX_FILE, "Файл")
            got["files"].append(path)
        elif part.name == "photo":
            if len(got["files"]) >= max_photos:
                raise service.ServiceError(f"Не больше {max_photos} фото")
            path = session_dir / f"photo_{len(got['files']) + 1:02d}"
            await _save_part(part, path, MAX_FILE, "Фото")
            got["files"].append(path)
            got["names"].append(part.filename or path.name)
    if not isinstance(got["meta"], dict):
        raise service.ServiceError("Неверные данные заказа")
    return got


def _paper(meta: dict, kind: str, group: str | None = None) -> str:
    choices = materials.choices_for(kind, group)
    paper = meta.get("paper") or choices[0]
    if paper not in choices:
        raise service.ServiceError("Такой бумаги для этого заказа нет")
    return paper


def _enhance_files(files: list, limit: int = MAX_ENHANCE) -> int:
    """Улучшает слабые фото прямо в файлах заказа. Возвращает, сколько улучшено."""
    if not photoai.can_enhance():
        return 0
    done = 0
    for path in files:
        if done >= limit:
            break
        with Image.open(path) as im:
            small = min(im.size) < LOW_RES
        if not small:
            continue
        img = cards.load_photo(path)
        better = photoai.enhance(img)
        if better is not img:
            better.save(path, "JPEG", quality=93)
            done += 1
    return done


def _craft_group(product: str) -> str | None:
    g = products.PRODUCTS[product]["paper"]
    return None if g == "craft" else g


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
        session_dir.mkdir(parents=True)
        got = await _read_upload(request, session_dir, max(MAX_PHOTO_JOB, MAX_CRAFT_PHOTOS))
        meta, files, back_photo = got["meta"], got["files"], got["back_photo"]
        kind = meta.get("kind")
        if kind != "craft" and not files:
            raise service.ServiceError("Добавьте хотя бы одно фото")
        if kind != "doc":
            for path in files:
                _check_image(path)
        if kind == "cards":
            deck = meta.get("deck")
            if deck not in cards.DECKS:
                raise service.ServiceError("Неизвестная колода")
            if len(files) > MAX_PHOTOS[deck]:
                raise service.ServiceError(f"Для этой колоды — не больше {MAX_PHOTOS[deck]} фото")
            back = meta.get("back") or cards.default_back(deck)
            if back not in cards.backs_for(deck):
                raise service.ServiceError("Неизвестная рубашка")
            style = (meta.get("style") or cards.DEFAULT_STYLE) if deck != "uno" else cards.DEFAULT_STYLE
            if style not in cards.STYLES:
                raise service.ServiceError("Неизвестное оформление карт")
            params = {"deck": deck, "back": back, "style": style, "paper": _paper(meta, "cards")}
            if deck == "uno":
                import uno
                params.update(colors=uno.clean_colors(meta.get("colors")),
                              back_text=uno.clean_text(meta.get("back_text"), uno.TEXT_MAX).upper(),
                              back_caption=uno.clean_text(meta.get("back_caption"), uno.CAPTION_MAX),
                              back_photo=bool(back_photo))
        elif kind == "craft":
            product = meta.get("product")
            if product not in products.PRODUCTS:
                raise service.ServiceError("Неизвестное изделие")
            try:
                params = products.validate(product, meta, len(files), got["csv"])
            except products.ProductError as e:
                raise service.ServiceError(str(e)) from e
            params["paper"] = _paper(meta, "craft", _craft_group(product))
        elif kind == "photo":
            fmt, copies = meta.get("format"), int(meta.get("copies", 1))
            quality = meta.get("quality", "high")
            if fmt not in photos.FORMATS or quality not in service.QUALITY_TITLES or not 1 <= copies <= 20:
                raise service.ServiceError("Неверные параметры печати")
            params = {"format": fmt, "copies": copies, "color": bool(meta.get("color", True)), "quality": quality,
                      "paper": _paper(meta, "photo")}
        elif kind == "doc":
            copies = int(meta.get("copies", 1))
            if not 1 <= copies <= MAX_COPIES_DOC:
                raise service.ServiceError("Неверные параметры печати")
            params = {"copies": copies, "color": bool(meta.get("color", True)), "quality": "normal",
                      "paper": _paper(meta, "doc")}
            params["doc_pages"] = await asyncio.to_thread(docs.count_pages, files[0])
            if params["doc_pages"] * copies > docs.MAX_SHEETS:
                raise service.ServiceError(f"Не больше {docs.MAX_SHEETS} листов в заказе — уменьшите число копий")
        else:
            raise service.ServiceError("Неизвестный тип заказа")
        if materials.paper_state(params["paper"]) == "out":
            raise service.ServiceError(f"Сейчас закончилась бумага «{materials.PAPERS[params['paper']][0]}». "
                                       "Выберите другую или загляните позже")

        out = session_dir / "print"
        async with _render_slot:
            if meta.get("enhance") and kind in ("cards", "craft", "photo") and files:
                params["enhanced"] = await asyncio.to_thread(_enhance_files, files)
            if kind == "cards":
                uno_opts = None
                if params["deck"] == "uno":
                    uno_opts = {"colors": params["colors"], "back_text": params["back_text"],
                                "back_caption": params["back_caption"], "back_photo": back_photo}
                pages = await asyncio.to_thread(cards.build_deck, cards.DECKS[params["deck"]], files, out,
                                                back=params["back"], style=params["style"], uno_opts=uno_opts)
                params.update(sheets=len(pages) // 2, color=True, quality="high", sides=len(pages))
                previews = [pages[0], pages[len(pages) // 2]]
            elif kind == "craft":
                try:
                    pages = await asyncio.to_thread(products.build, params, files, out, got["names"])
                except products.ProductError as e:
                    raise service.ServiceError(str(e)) from e
                duplex = products.PRODUCTS[params["product"]]["duplex"]
                params.update(sheets=len(pages) // 2 if duplex else len(pages), color=True, quality="high",
                              sides=len(pages), duplex=duplex)
                previews = [pages[0], pages[len(pages) // 2]] if duplex else pages[:2]
            elif kind == "doc":
                once = await asyncio.to_thread(docs.build_doc_pages, files[0], not params["color"], out)
                pages = once * params["copies"]  # копии по порядку: весь документ, потом снова
                params["sheets"] = params["sides"] = len(pages)
                previews = once[:2]
            else:
                pages = await asyncio.to_thread(photos.build_photo_pages, files, params["format"],
                                                params["copies"], not params["color"], out)
                params["sheets"] = params["sides"] = len(pages)
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


def _data_url(img: Image.Image | None, max_side: int = 900) -> str | None:
    if img is None:
        return None
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=86)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def craft_preview(request: web.Request) -> web.Response:
    """Образец изделия по уменьшенным фото: лицо, оборот, число листов, цена и предупреждения."""
    user = _user(request)
    tmp = config.SESSIONS_DIR / f"p{user['id']}_{uuid.uuid4().hex[:8]}"
    try:
        tmp.mkdir(parents=True)
        got = await _read_upload(request, tmp, 8)
        meta = got["meta"]
        product = meta.get("product")
        if product not in products.PRODUCTS:
            raise service.ServiceError("Неизвестное изделие")
        n_photos = int(meta.get("n_photos") or len(got["files"]))
        names = meta.get("names") or got["names"]
        try:
            params = products.validate(product, meta, n_photos, got["csv"])
        except products.ProductError as e:
            return web.json_response({"ok": True, "invalid": str(e)})
        params["paper"] = _paper(meta, "craft", _craft_group(product))
        thumbs = []
        for path in got["files"]:
            _check_image(path)
            thumbs.append(cards.load_photo(path))
        # для таблицы карт сопоставляем картинки по именам всех выбранных файлов, а пришли только первые
        async with _preview_slot:
            pv = await asyncio.to_thread(products.preview, params, thumbs, names[:len(thumbs)])
        if product == "game":
            known = {Path(n).stem.lower() for n in names}
            pv["warnings"] = [w for w in pv["warnings"] if not w.startswith("Нет картинок")]
            missing = sorted({r["image"] for r in params["rows"] if r["image"] and r["image"] not in known})
            if missing:
                pv["warnings"].insert(0, "Нет картинок: " + ", ".join(missing[:6]) + (" и др." if len(missing) > 6 else "") +
                                      " — эти карты будут без картинки")
        amount, detail = pricing.quote("craft", params)
        return web.json_response({"ok": True, "front": _data_url(pv["front"]), "back": _data_url(pv["back"]),
                                  "count": params["count"], "sheets": params["sheets"], "amount": amount / 100,
                                  "detail": detail, "warnings": pv["warnings"],
                                  "rows": len(params.get("rows") or []) or None})
    except (json.JSONDecodeError, TypeError, ValueError):
        return _fail("Неверные данные")
    except service.ServiceError as e:
        return _fail(str(e))
    except Exception:
        log.exception("Превью изделия не получилось")
        return _fail("Не получилось показать образец. Попробуйте другое фото.", 500)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def detect_faces(request: web.Request) -> web.Response:
    """Где на фото лица — чтобы превью в приложении кадрировало так же, как печать."""
    _user(request)
    reader = await request.multipart()
    part = await reader.next()
    if part is None or part.name != "photo":
        return _fail("Фото не получено")
    raw = await part.read(decode=False)
    if len(raw) > 2 * 1024 * 1024:
        return _fail("Миниатюра больше 2 МБ")
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        return _fail("Не получилось прочитать фото")
    async with _preview_slot:
        box = await asyncio.to_thread(photoai.face_box, img)
    return web.json_response({"ok": True, "box": [round(float(v), 4) for v in box] if box else None})


def routes() -> list:
    return [web.get("/mapi/config", get_config), web.get("/mapi/orders", list_orders),
            web.post("/mapi/orders", create_order), web.post("/mapi/doc/inspect", inspect_doc),
            web.post("/mapi/preview", craft_preview), web.post("/mapi/faces", detect_faces),
            web.get(r"/mapi/orders/{id:\d+}/thumb", order_thumb),
            web.post(r"/mapi/orders/{id:\d+}/cancel", cancel_order)]
