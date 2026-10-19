"""Жизненный цикл заказа: печать, выдача, отмена.

Все изменения заказа идут через эти функции — их вызывают и бот, и веб-админка,
поэтому статусы везде одинаковые, а клиент получает уведомление о каждом шаге.

    new ─печать─▶ printing ─▶ printed ─выдача─▶ issued
     │               │ (карты)   ▲
     ▼               ▼           │
  cancelled    fronts_printed ─печать рубашек─┘

Оплаты пока нет: заказ сразу попадает оператору.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import logging
import shutil
from pathlib import Path

import agents
import cards
import config
import db
import photos
import printing
import tg
from pricing import format_rub

log = logging.getLogger("service")

STATUSES = {  # ключ: (для админа, эмодзи, для клиента)
    "new": ("Новый — ждёт печати", "🆕", "принят и стоит в очереди на печать"),
    "printing": ("Печатается", "🖨", "печатается прямо сейчас"),
    "fronts_printed": ("Ждёт печати рубашек", "🔄", "лицевые стороны готовы, скоро напечатаем рубашки"),
    "printed": ("Напечатан — ждёт выдачи", "📦", "напечатан и ждёт выдачи"),
    "issued": ("Выдан", "✅", "выдан"),
    "cancelled": ("Отменён", "✖️", "отменён"),
}
QUALITY_TITLES = {"draft": "Черновое", "normal": "Обычное", "high": "Высокое"}

ACTION_TITLES = {
    "printed_ok": "Напечатано", "print": "Печать", "print_backs": "Печать рубашек", "reprint": "Напечатать заново",
    "cancel_job": "Снять с принтера", "issue": "Выдан клиенту", "cancel": "Отменить заказ",
}


class ServiceError(Exception):
    """Ошибка, текст которой можно показать человеку."""


_locks: dict[int, asyncio.Lock] = {}


def _lock(order_id: int) -> asyncio.Lock:
    return _locks.setdefault(order_id, asyncio.Lock())


def get(order_id: int) -> dict:
    order = db.get_order(order_id)
    if not order:
        raise ServiceError(f"Заказ №{order_id} не найден")
    return order


# ---------- описание заказа ----------

def describe(kind: str, p: dict) -> str:
    if kind == "cards":
        deck = cards.DECKS[p["deck"]]
        return (f"🃏 {deck.title}\nФото: {p['photos']} шт.\nОформление: {cards.style_title(p.get('style'))}\nРубашка: {cards.back_title(p.get('back'))}\n"
                f"Листов A4: {p['sheets']} лицевых + {p['sheets']} рубашек\nПечать: цветная, высокое качество")
    if kind == "doc":
        return (f"📄 Документ: {p['doc_pages']} стр. × {p['copies']} коп.\n"
                f"Печать: {'цветная' if p['color'] else 'чёрно-белая'}\nЛистов A4: {p['sheets']}")
    return (f"🖼 Фото: {p['photos']} шт. × {p['copies']} коп.\n"
            f"Формат: {photos.FORMATS[p['format']][0]}\n"
            f"Цвет: {'цветная' if p['color'] else 'чёрно-белая'}, качество: {QUALITY_TITLES[p['quality']].lower()}\n"
            f"Листов A4: {p['sheets']}")


def short_title(order: dict) -> str:
    p = order["params"]
    if order["kind"] == "cards":
        return f"Карты, {len(cards.deck_cards(cards.DECKS[p['deck']]))} шт."
    if order["kind"] == "doc":
        return f"Документ, {p['doc_pages']} стр. × {p['copies']}"
    return f"Фото {photos.FORMATS[p['format']][0].split(' (')[0]}, {p['photos'] * p['copies']} отп."


def allowed_actions(order: dict) -> list[str]:
    return {
        "new": ["print", "cancel"],
        "printing": (["printed_ok"] if config.PRINT_MODE == "browser" else []) + ["cancel_job"],
        "fronts_printed": ["print_backs", "reprint", "cancel"],
        "printed": ["issue", "reprint", "cancel"],
        "issued": ["reprint"],
        "cancelled": [],
    }[order["status"]]


def client_status_line(order: dict) -> str:
    _, emoji, client = STATUSES[order["status"]]
    return f"{emoji} <b>№{order['id']}</b> · {short_title(order)} · {format_rub(order['amount'])}\n      {client}"


# ---------- создание ----------

async def create_order(session: dict, user) -> dict:
    """Из сессии бота (фото, листы, параметры, сумма) делает заказ и сообщает оператору."""
    order = db.create_order(
        kind=session["kind"], status="new", amount=session["amount"], params=session["params"],
        user_id=user.id, user_name=user.full_name, username=user.username,
        dir="", pages=[], previews=[], sources=[])
    order_dir = config.ORDERS_DIR / str(order["id"])
    if order_dir.exists():  # папка от старой версии бота
        legacy = config.DATA / "legacy_orders"
        legacy.mkdir(exist_ok=True)
        shutil.move(str(order_dir), legacy / f"{order['id']}_{int(dt.datetime.now().timestamp())}")
    shutil.move(str(session["dir"]), order_dir)
    rel = lambda p: str(order_dir / Path(p).relative_to(session["dir"]))  # noqa: E731
    order = db.update_order(order["id"], dir=str(order_dir), pages=[rel(p) for p in session["pages"]],
                            previews=[rel(p) for p in session["previews"]],
                            sources=[rel(p) for p in session["photos"]])
    db.add_event(order["id"], f"Заказ оформлен: {short_title(order)}, {format_rub(order['amount'])}", "client")
    await tg.notify_admins(
        f"🆕 Новый заказ №{order['id']} — {format_rub(order['amount'])}\n"
        f"{html.escape(order['user_name'] or '')}: {short_title(order)}\n\nПанель: {config.ADMIN_URL}/#order={order['id']}",
        tg.kb([("🖨 Печать", f"adm:print:{order['id']}")]))
    return order


# ---------- печать ----------

async def start_print(order_id: int, part: str, actor: str = "admin") -> dict:
    """part: front — лицевые/все листы, back — рубашки."""
    async with _lock(order_id):
        order = get(order_id)
        allowed = ("fronts_printed",) if part == "back" else ("new", "fronts_printed", "printed", "issued")
        if order["status"] not in allowed:
            raise ServiceError(f"Сейчас заказ «{STATUSES[order['status']][0]}» — эта печать недоступна")
        prev = order["status"]
        pages = [Path(p) for p in order["pages"]]
        if order["kind"] == "cards":
            half = len(pages) // 2
            pages = pages[half:] if part == "back" else pages[:half]
        what = "рубашек" if part == "back" else ("лицевых сторон" if order["kind"] == "cards" else "документа" if order["kind"] == "doc" else "фото")
        order = db.transition(order_id, (prev,), status="printing", print_state="Отправляем на принтер…",
                              print_job={"part": part, "prev": prev}, last_error=None)
        again = part == "front" and prev in ("printed", "issued", "fronts_printed")
        db.add_event(order_id, f"Печать {what}: {len(pages)} л." + (" (повторно)" if again else ""), actor)

    p = order["params"]
    if config.PRINT_MODE == "agent":  # печатает программа на компьютере с принтером
        try:
            job = agents.submit(order_id, order["kind"], f"Тюша №{order_id} {what}", pages,
                                p.get("color", True), p.get("quality", "high"))
        except agents.PrintError as e:
            db.update_order(order_id, status=prev, print_state=None, print_job=None)
            db.add_event(order_id, f"Печать не запущена: {e}", "system", "warning")
            raise ServiceError(str(e)) from e
        s = job["settings"]
        db.add_event(order_id, f"Задание №{job['id']} отправлено: принтер «{s['printer']}», профиль «{s['profile_title']}»",
                     "system")
        if prev == "new":
            await tg.safe_send(order["user_id"], f"🖨 Начали печатать заказ №{order_id}! Напишу, когда будет готово.")
        return db.update_order(order_id, print_state="Ждём, когда компьютер с принтером заберёт задание…",
                               print_job={"part": part, "prev": prev, "agent_job": job["id"]})
    if prev == "new":
        await tg.safe_send(order["user_id"], f"🖨 Начали печатать заказ №{order_id}! Напишу, когда будет готово.")
    if config.PRINT_MODE == "browser":  # листы печатает оператор из браузера и подтверждает результат
        return db.update_order(order_id, print_state="Печать в браузере: ждём подтверждения оператора",
                               print_job={"part": part, "prev": prev, "printer": "browser"})
    try:
        result = await asyncio.to_thread(
            printing.print_pages, pages, printer=config.PRINTER_NAME, job_name=f"Тюша №{order_id} {what}",
            color=p.get("color", True), quality=p.get("quality", "high"), mode=config.PRINT_MODE,
            file_dir=config.PRINTED_DIR)
    except Exception as e:
        log.exception("Ошибка печати")
        db.update_order(order_id, status=prev, print_state=None, print_job=None, last_error=f"Ошибка печати: {e}")
        db.add_event(order_id, f"Ошибка печати: {e}", "system", "error")
        raise ServiceError(f"Принтер не принял задание: {e}") from e

    db.add_event(order_id, result["message"][0].upper() + result["message"][1:], "system")
    if result["job_id"] is None:  # режим file — сразу готово
        return await _finish_print(order_id)
    return db.update_order(order_id, print_state="В очереди принтера",
                           print_job={"part": part, "prev": prev, "printer": result["printer"], "job_id": result["job_id"]})


async def _finish_print(order_id: int) -> dict:
    order = get(order_id)
    job = order["print_job"] or {}
    if order["kind"] == "cards" and job.get("part") == "front":
        order = db.update_order(order_id, status="fronts_printed", print_state=None, print_job=None)
        db.add_event(order_id, "Лицевые стороны напечатаны. Переверните стопку и запустите печать рубашек",
                     "system", "success")
        await tg.notify_admins(
            f"🔄 Заказ №{order_id}: лицевые стороны напечатаны.\nДайте чернилам высохнуть, переверните стопку "
            "(первый лист сверху) и запустите печать рубашек.",
            tg.kb([("🖨 Печать рубашек", f"adm:backs:{order_id}")]))
        return order
    first_time = job.get("prev") in ("new", "fronts_printed") and not order["printed_at"]
    status = "issued" if job.get("prev") == "issued" else "printed"
    order = db.update_order(order_id, status=status, print_state=None, print_job=None, printed_at=db.now())
    db.add_event(order_id, "Печать завершена", "system", "success")
    if first_time:
        await tg.send_anim(order["user_id"], "done",
                           f"🎉 <b>Ура! Заказ №{order_id} напечатан!</b>\n\nОн ждёт выдачи. Спасибо, что выбрали Тюшу 🐾",
                           tg.kb([("📦 Мои заказы", f"webapp:{config.ADMIN_URL}/miniapp/#orders")]))
    return order


async def finish_browser_print(order_id: int) -> dict:
    """Оператор подтвердил, что листы напечатаны из браузера."""
    async with _lock(order_id):
        order = get(order_id)
        if order["status"] != "printing":
            raise ServiceError("Заказ сейчас не на печати")
        return await _finish_print(order_id)


async def cancel_print_job(order_id: int, actor: str = "admin") -> dict:
    async with _lock(order_id):
        order = get(order_id)
        if order["status"] != "printing":
            raise ServiceError("Заказ сейчас не печатается")
        job = order["print_job"] or {}
        if job.get("agent_job"):
            agents.request_cancel(job["agent_job"])
        elif job.get("job_id"):
            try:
                await asyncio.to_thread(printing.cancel_job, job["printer"], job["job_id"])
            except Exception as e:
                log.warning("Не удалось удалить задание: %s", e)
        order = db.update_order(order_id, status=job.get("prev", "new"), print_state=None, print_job=None)
        db.add_event(order_id, "Задание печати снято с принтера", actor, "warning")
        return order


async def watch_print_jobs() -> None:
    """Смотрит в очередь Windows: что с заданием сейчас, и когда оно ушло — печать завершена."""
    for order in db.orders_in(("printing",)):
        job = order["print_job"] or {}
        if not job.get("job_id"):
            continue
        try:
            state = await asyncio.to_thread(printing.job_status, job["printer"], job["job_id"])
        except Exception as e:
            log.warning("Не удалось проверить задание: %s", e)
            continue
        if state is None or state["printed"]:
            await _finish_print(order["id"])
            continue
        text = ", ".join(state["states"])
        if state["problem"]:
            text = "⚠️ " + text
        if text != order["print_state"]:
            db.update_order(order["id"], print_state=text,
                            last_error=f"Принтер: {', '.join(state['states'])}" if state["problem"] else None)
            if state["problem"]:
                db.add_event(order["id"], f"Принтер сообщает: {', '.join(state['states'])}", "system", "error")
                await tg.notify_admins(f"⚠️ Заказ №{order['id']}: принтер сообщает — {', '.join(state['states'])}")


async def on_agent_job(job: dict) -> None:
    """Компьютер с принтером сообщил о ходе задания — двигаем заказ."""
    if not job["order_id"]:
        return  # пробный лист из раздела «Принтеры»
    order_id = job["order_id"]
    async with _lock(order_id):
        order = db.get_order(order_id)
        pj = (order or {}).get("print_job") or {}
        if not order or order["status"] != "printing" or pj.get("agent_job") != job["id"]:
            return  # задание уже снято или устарело
        state, detail = job["state"], job["detail"] or ""
        if state == "sent":
            db.update_order(order_id, print_state="Компьютер получил задание и готовит печать…")
            return
        if state == "printing":
            text = ("⚠️ " if job["problem"] else "") + (detail or "Печатается")
            if text != order["print_state"]:
                db.update_order(order_id, print_state=text, last_error=f"Принтер: {detail}" if job["problem"] else None)
                if job["problem"]:
                    db.add_event(order_id, f"Принтер сообщает: {detail}", "system", "error")
                    await tg.notify_admins(f"⚠️ Заказ №{order_id}: принтер сообщает — {detail}")
            return
        if state == "error":
            db.update_order(order_id, status=pj.get("prev", "new"), print_state=None, print_job=None,
                            last_error=f"Печать не удалась: {detail}")
            db.add_event(order_id, f"Печать не удалась: {detail}", "system", "error")
            await tg.notify_admins(f"⚠️ Заказ №{order_id}: печать не удалась — {detail}")
            return
        if state == "cancelled":
            db.update_order(order_id, status=pj.get("prev", "new"), print_state=None, print_job=None)
            return
    if state == "done":
        db.add_event(order_id, "Компьютер сообщил: листы напечатаны", "system")
        await _finish_print(order_id)


agents.on_job_update = on_agent_job


async def on_agent_state(agent: dict, online: bool) -> None:
    if online:
        await tg.notify_admins(f"✅ Компьютер с принтером «{agent['name']}» снова на связи — печать работает.")
    else:
        await tg.notify_admins(f"⚠️ Компьютер с принтером «{agent['name']}» не на связи больше {agents.OFFLINE_ALERT // 60} мин. "
                               "Заказы не напечатаются: проверьте, что компьютер включён и программа «Тюша Печать» открыта.")


agents.on_agent_state = on_agent_state


# ---------- выдача и отмена ----------

async def issue(order_id: int, actor: str = "admin", notify: bool = True) -> dict:
    async with _lock(order_id):
        order = db.transition(order_id, ("printed",), status="issued", issued_at=db.now())
        if not order:
            raise ServiceError("Отметить выданным можно только напечатанный заказ")
        db.add_event(order_id, "Заказ выдан клиенту", actor, "success")
    if notify:
        await tg.safe_send(order["user_id"], f"✅ Заказ №{order_id} выдан. Спасибо, что выбрали Тюшу! 🐾")
    return order


async def cancel(order_id: int, actor: str = "admin", reason: str = "", notify: bool = True) -> dict:
    async with _lock(order_id):
        order = get(order_id)
        if actor == "client" and order["status"] != "new":
            raise ServiceError("Заказ уже в работе — отменить его может только оператор")
        if order["status"] == "cancelled":
            raise ServiceError("Заказ уже отменён")
        if order["status"] == "printing":
            raise ServiceError("Заказ сейчас печатается — сначала снимите задание с принтера")
        if order["status"] == "issued":
            raise ServiceError("Заказ уже выдан")
        order = db.update_order(order_id, status="cancelled", cancelled_at=db.now(), cancel_reason=reason or None)
        who = "клиентом" if actor == "client" else "оператором"
        db.add_event(order_id, f"Заказ отменён {who}" + (f": {reason}" if reason else ""), actor, "warning")
    if actor == "client":
        await tg.notify_admins(f"✖️ Клиент отменил заказ №{order_id}")
    elif notify:
        text = f"Упс… заказ №{order_id} отменён." + (f"\nПричина: {html.escape(reason)}" if reason else "")
        await tg.send_anim(order["user_id"], "oops", text, tg.kb([("🐾 Открыть Тюшу", f"webapp:{config.ADMIN_URL}/miniapp/")]))
    return order


async def message_client(order_id: int, text: str, actor: str = "admin") -> None:
    order = get(order_id)
    sent = await tg.safe_send(order["user_id"], f"💬 <b>Сообщение по заказу №{order_id}:</b>\n\n{html.escape(text)}")
    if not sent:
        raise ServiceError("Не удалось отправить: возможно, клиент заблокировал бота")
    db.add_event(order_id, f"Сообщение клиенту: {text}", actor)


def set_note(order_id: int, note: str) -> dict:
    get(order_id)
    return db.update_order(order_id, admin_note=note.strip() or None)


async def background_loop() -> None:
    """Каждые 3 секунды: очередь принтера (локальная печать) или зависшие задания компьютеров (агент)."""
    while True:
        try:
            if config.PRINT_MODE == "agent":
                await agents.sweep()
            else:
                await watch_print_jobs()
        except Exception:
            log.exception("Ошибка фоновой задачи")
        await asyncio.sleep(3)
