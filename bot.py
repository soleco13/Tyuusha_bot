"""Telegram-бот Тюша: конструктор игральных карт и печать фото + веб-админка заказов.

Запуск: python bot.py — поднимает бота, админку (ADMIN_URL) и фоновое слежение за принтером.
Заказ печатается только после того, как оператор нажмёт «Печать» в админке или в Telegram.
"""
from __future__ import annotations

import asyncio
import html
import logging
import shutil
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message

import admin_web
import cards
import config
import db
import photos
import pricing
import printing
import service
import tg
from tg import kb, send_anim

MAX_FILE = 20 * 1024 * 1024  # лимит скачивания файлов у Bot API
MAX_PHOTOS = 54
DOWNLOAD_RETRIES = 4

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("printbot")

dp = Dispatcher()

# user_id -> текущий незаконченный заказ (фото, параметры, листы)
sessions: dict[int, dict] = {}
_ack_tasks: dict[int, asyncio.Task] = {}
_busy: set[int] = set()  # пользователи, у которых сейчас идёт долгая операция

MAIN_MENU = kb([("🃏 Игральные карты из фото", "menu:cards")],
               [("🖼 Напечатать фото", "menu:photo")],
               [("📦 Мои заказы", "menu:orders"), ("🐾 Как это работает", "menu:help")])
DONE_KB = kb([("✅ Готово", "upload:done")], [("✖ Отмена", "cancel")])
STALE = "Эта кнопка уже не работает — начните заново: /start"

HELP_TEXT = (
    "🐾 <b>Как работает Тюша</b>\n\n"
    "1️⃣ Выбираете, что напечатать: колоду карт или фото.\n"
    "2️⃣ Присылаете снимки — лучше <b>файлом</b>, так качество выше.\n"
    "3️⃣ Тюша собирает макет и показывает превью со стоимостью.\n"
    "4️⃣ Оформляете заказ — оператор готовит принтер и бумагу.\n"
    "5️⃣ О каждом шаге приходит сообщение: начали печатать → напечатано → выдано 🎉\n\n"
    "Статус заказов — «📦 Мои заказы» или /orders. Отменить текущий шаг — /cancel"
)


# ---------- вспомогательное ----------

async def lock(cb: CallbackQuery, chosen: str) -> None:
    """Фиксирует выбор: под сообщением пишем, что выбрано, и убираем кнопки (повторно не нажать)."""
    msg = cb.message
    note = f"\n\n<b>✓ {html.escape(chosen)}</b>"
    try:
        if msg.text:
            await msg.edit_text(msg.html_text + note, reply_markup=None)
        elif msg.caption is not None:
            await msg.edit_caption(caption=(msg.html_text or "") + note, reply_markup=None)
        else:
            await msg.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


async def busy_guard(cb: CallbackQuery) -> bool:
    if cb.from_user.id in _busy:
        await cb.answer("⏳ Тюша ещё работает над прошлым шагом, секундочку…")
        return True
    return False


def new_session(user_id: int, kind: str) -> dict:
    drop_session(user_id)
    work = config.SESSIONS_DIR / f"{user_id}_{int(time.time() * 1000)}"
    (work / "src").mkdir(parents=True)
    sessions[user_id] = {"kind": kind, "stage": "choose", "dir": work, "photos": [], "params": {}}
    return sessions[user_id]


def drop_session(user_id: int) -> None:
    s = sessions.pop(user_id, None)
    if s and s["dir"].exists():
        shutil.rmtree(s["dir"], ignore_errors=True)


async def show_menu(chat_id: int, text: str = "Что сделаем? 🐾") -> None:
    await tg.safe_send(chat_id, text, MAIN_MENU)


# ---------- общие команды ----------

@dp.message(CommandStart())
async def start(message: Message) -> None:
    drop_session(message.from_user.id)
    name = html.escape(message.from_user.first_name or "")
    await send_anim(message.chat.id, "hello",
                    f"Привет{', ' + name if name else ''}! Я <b>Тюша</b> 🐾\n\n"
                    "Печатаю ваши фото и делаю настоящие игральные карты с вашими снимками — "
                    "на память, в подарок или для вечера с друзьями.\n\nЧто сделаем?", MAIN_MENU)


@dp.callback_query(F.data == "menu:home")
async def menu_home(cb: CallbackQuery) -> None:
    await cb.answer()
    drop_session(cb.from_user.id)
    await show_menu(cb.message.chat.id)


@dp.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=MAIN_MENU)


@dp.callback_query(F.data == "menu:help")
async def help_cb(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(HELP_TEXT, reply_markup=MAIN_MENU)


@dp.message(Command("myid"))
async def my_id(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@dp.message(Command("cancel"))
@dp.callback_query(F.data == "cancel")
async def cancel(event: Message | CallbackQuery) -> None:
    had = event.from_user.id in sessions
    drop_session(event.from_user.id)
    if isinstance(event, CallbackQuery):
        await event.answer("Отменено")
        await lock(event, "Отменено")
        message = event.message
    else:
        message = event
    text = "Хорошо, отменили 🐾 Что сделаем вместо этого?" if had else "Сейчас нечего отменять. Что сделаем?"
    await message.answer(text, reply_markup=MAIN_MENU)


# ---------- мои заказы ----------

def orders_view(user_id: int) -> tuple[str, object]:
    orders = db.list_orders(user_id=user_id, limit=6)
    if not orders:
        return "У вас пока нет заказов. Самое время сделать первый! 🐾", MAIN_MENU
    lines = [service.client_status_line(o) for o in orders]
    rows = [[(f"✖ Отменить №{o['id']}", f"ucancel:{o['id']}")] for o in orders if o["status"] == "new"]
    rows.append([("🔄 Обновить", "menu:orders_refresh"), ("🏠 Меню", "menu:home")])
    return ("📦 <b>Ваши заказы</b>\n\n" + "\n\n".join(lines) +
            f"\n\n<i>Обновлено в {time.strftime('%H:%M:%S')}</i>"), kb(*rows)


@dp.message(Command("orders"))
async def orders_cmd(message: Message) -> None:
    text, markup = orders_view(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@dp.callback_query(F.data == "menu:orders")
async def orders_cb(cb: CallbackQuery) -> None:
    await cb.answer()
    text, markup = orders_view(cb.from_user.id)
    await cb.message.answer(text, reply_markup=markup)


@dp.callback_query(F.data == "menu:orders_refresh")
async def orders_refresh(cb: CallbackQuery) -> None:
    text, markup = orders_view(cb.from_user.id)
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    await cb.answer("Обновлено")


@dp.callback_query(F.data.startswith("ucancel:"))
async def user_cancel_ask(cb: CallbackQuery) -> None:
    oid = int(cb.data.split(":")[1])
    order = db.get_order(oid)
    if not order or order["user_id"] != cb.from_user.id:
        return await cb.answer(STALE, show_alert=True)
    if order["status"] != "new":
        return await cb.answer(f"Заказ уже {service.STATUSES[order['status']][2]} — отменить нельзя", show_alert=True)
    await cb.answer()
    await cb.message.answer(f"Точно отменить заказ №{oid}?\n{service.short_title(order)}",
                            reply_markup=kb([("Да, отменить", f"ucancel_yes:{oid}"), ("Нет, оставить", f"ucancel_no:{oid}")]))


@dp.callback_query(F.data.startswith("ucancel_no:"))
async def user_cancel_no(cb: CallbackQuery) -> None:
    await cb.answer("Заказ остаётся в работе")
    await lock(cb, "Заказ остаётся в работе")


@dp.callback_query(F.data.startswith("ucancel_yes:"))
async def user_cancel_yes(cb: CallbackQuery) -> None:
    oid = int(cb.data.split(":")[1])
    order = db.get_order(oid)
    if not order or order["user_id"] != cb.from_user.id:
        return await cb.answer(STALE, show_alert=True)
    try:
        await service.cancel(oid, "client")
    except service.ServiceError as e:
        await cb.answer(str(e), show_alert=True)
        return await lock(cb, str(e))
    await cb.answer("Заказ отменён")
    await lock(cb, f"Заказ №{oid} отменён")
    await show_menu(cb.message.chat.id, "Заказ отменён. Что сделаем дальше? 🐾")


# ---------- выбор услуги ----------

@dp.callback_query(F.data == "menu:cards")
async def menu_cards(cb: CallbackQuery) -> None:
    if await busy_guard(cb):
        return
    await cb.answer()
    new_session(cb.from_user.id, "cards")
    prices = pricing.get_prices()["cards"]
    await cb.message.answer(
        "🃏 <b>Колода из ваших фото</b>\n\n"
        "Настоящий размер игральной карты 63×88 мм, ваши снимки на лицевой стороне, "
        "фирменная рубашка с Тюшей на обороте.\n\nВыберите колоду:",
        reply_markup=kb(*[[(f"{d.title} — {pricing.format_rub(prices[key] * 100)}", f"deck:{key}")]
                          for key, d in cards.DECKS.items()], [("✖ Отмена", "cancel")]))


@dp.callback_query(F.data.startswith("deck:"))
async def choose_deck(cb: CallbackQuery) -> None:
    s = sessions.get(cb.from_user.id)
    if not s or s["kind"] != "cards" or s["stage"] != "choose":
        return await cb.answer(STALE, show_alert=True)
    deck = cards.DECKS[cb.data.split(":", 1)[1]]
    s["params"]["deck"] = deck.key
    s["stage"] = "upload"
    await cb.answer()
    await lock(cb, deck.title)
    total = len(cards.deck_cards(deck))
    await cb.message.answer(
        f"📸 Пришлите от 1 до {total} фото. Тюша разложит их по картам по очереди: "
        f"одно фото будет на всех картах, {total} — на каждой карте своё.\n\n"
        "💡 Отправляйте фото <b>файлом</b> (📎 → Файл) — так Telegram их не сжимает.\n"
        "Когда всё пришлёте, нажмите «Готово».", reply_markup=DONE_KB)


@dp.callback_query(F.data == "menu:photo")
async def menu_photo(cb: CallbackQuery) -> None:
    if await busy_guard(cb):
        return
    await cb.answer()
    s = new_session(cb.from_user.id, "photo")
    s["stage"] = "upload"
    await cb.message.answer(
        "🖼 <b>Печать фото</b>\n\n"
        f"📸 Пришлите до {MAX_PHOTOS} снимков — потом выберем размер, количество и цвет.\n\n"
        "💡 Отправляйте фото <b>файлом</b> (📎 → Файл) — так Telegram их не сжимает.\n"
        "Когда всё пришлёте, нажмите «Готово».", reply_markup=DONE_KB)


# ---------- загрузка фото ----------

async def _ack_later(message: Message, user_id: int) -> None:
    # Ответ «принято N фото» один раз на пачку (альбом приходит десятком сообщений)
    await asyncio.sleep(1.5)
    s = sessions.get(user_id)
    if s and s["stage"] == "upload":
        n = len([p for p in s["photos"] if p])
        loading = s["photos"].count(None)
        extra = f" (ещё {loading} загружается…)" if loading else ""
        await message.answer(f"📥 Фото у Тюши: <b>{n}</b>{extra}. Можно прислать ещё или нажать «Готово».",
                             reply_markup=DONE_KB)


@dp.message(F.photo | F.document)
async def receive_photo(message: Message, bot: Bot) -> None:
    uid = message.from_user.id
    s = sessions.get(uid)
    if not s or s["stage"] != "upload":
        return await message.answer("Фото получено, но сначала выберите, что сделать 🐾", reply_markup=MAIN_MENU)

    if message.photo:
        file, ext = message.photo[-1], ".jpg"
    else:
        doc = message.document
        if not (doc.mime_type or "").startswith("image/"):
            return await message.reply("Это не изображение. Пришлите фото в JPG или PNG.")
        file, ext = doc, Path(doc.file_name or "").suffix.lower() or ".jpg"
    if file.file_size and file.file_size > MAX_FILE:
        return await message.reply("Файл больше 20 МБ — Telegram не даёт боту его скачать. "
                                   "Уменьшите фото и пришлите снова.")

    limit = len(cards.deck_cards(cards.DECKS[s["params"]["deck"]])) if s["kind"] == "cards" else MAX_PHOTOS
    if len([p for p in s["photos"] if p is not False]) >= limit:
        return await message.reply(f"Уже загружено максимум ({limit}). Нажмите «Готово».", reply_markup=DONE_KB)

    # Резервируем место сразу: фото из альбома скачиваются параллельно, порядок сохраняется.
    # None — ещё скачивается, False — не удалось скачать
    pos = len(s["photos"])
    s["photos"].append(None)
    dest = s["dir"] / "src" / f"{pos + 1:03d}{ext}"
    for attempt in range(DOWNLOAD_RETRIES):
        try:
            await bot.download(file, destination=dest)
            break
        except Exception as e:
            log.warning("Не скачалось фото (попытка %d): %s", attempt + 1, e)
            await asyncio.sleep(2 * (attempt + 1))
    else:
        s["photos"][pos] = False
        return await message.reply("⚠️ Это фото не загрузилось из-за сбоя связи. Пришлите его, пожалуйста, ещё раз.")
    try:
        cards.load_photo(dest)  # проверяем, что картинка открывается
    except Exception:
        s["photos"][pos] = False
        dest.unlink(missing_ok=True)
        return await message.reply("Не получилось открыть это изображение, пришлите другое.")
    s["photos"][pos] = dest

    if uid in _ack_tasks:
        _ack_tasks[uid].cancel()
    _ack_tasks[uid] = asyncio.create_task(_ack_later(message, uid))


@dp.callback_query(F.data == "upload:done")
async def upload_done(cb: CallbackQuery) -> None:
    s = sessions.get(cb.from_user.id)
    if not s or s["stage"] != "upload":
        return await cb.answer(STALE, show_alert=True)
    if await busy_guard(cb):
        return
    await cb.answer()
    if task := _ack_tasks.pop(cb.from_user.id, None):
        task.cancel()
    _busy.add(cb.from_user.id)
    try:
        # ждём фото, которые ещё скачиваются (например, «Готово» нажали сразу после альбома)
        if None in s["photos"]:
            wait = await cb.message.answer(f"⏳ Дожидаюсь загрузки фото ({s['photos'].count(None)} шт.)…")
            for _ in range(60):
                if None not in s["photos"]:
                    break
                await asyncio.sleep(1)
            try:
                await wait.delete()
            except Exception:
                pass
        ready = [p for p in s["photos"] if p]
        if not ready:
            return await cb.message.answer("Пока не загружено ни одного фото — пришлите хотя бы одно 📸",
                                           reply_markup=DONE_KB)
        failed = len(s["photos"]) - len(ready)
        s["photos"] = ready
        if failed:
            return await cb.message.answer(
                f"⚠️ {failed} фото не загрузилось. Пришлите его ещё раз и снова нажмите «Готово» — "
                f"или нажмите «Готово» сейчас, чтобы продолжить с {len(ready)} фото.", reply_markup=DONE_KB)
        await lock(cb, f"Фото загружены: {len(ready)}")
        if s["kind"] == "cards":
            await render_and_preview(cb.message, s)
        else:
            s["stage"] = "params"
            await cb.message.answer("📐 <b>Шаг 1 из 4.</b> Какой размер печатаем?", reply_markup=kb(
                *[[(title, f"fmt:{key}")] for key, (title, _, _) in photos.FORMATS.items()]))
    finally:
        _busy.discard(cb.from_user.id)


# ---------- параметры печати фото ----------

def _params_session(cb: CallbackQuery) -> dict | None:
    s = sessions.get(cb.from_user.id)
    return s if s and s["stage"] == "params" else None


@dp.callback_query(F.data.startswith("fmt:"))
async def choose_format(cb: CallbackQuery) -> None:
    s = _params_session(cb)
    if not s or "format" in s["params"]:
        return await cb.answer(STALE, show_alert=True)
    key = cb.data.split(":", 1)[1]
    s["params"]["format"] = key
    await cb.answer()
    await lock(cb, photos.FORMATS[key][0])
    await cb.message.answer("🔢 <b>Шаг 2 из 4.</b> Сколько копий каждого фото?", reply_markup=kb(
        [(str(n), f"copies:{n}") for n in (1, 2, 3, 5, 10)]))


@dp.callback_query(F.data.startswith("copies:"))
async def choose_copies(cb: CallbackQuery) -> None:
    s = _params_session(cb)
    if not s or "copies" in s["params"]:
        return await cb.answer(STALE, show_alert=True)
    s["params"]["copies"] = int(cb.data.split(":", 1)[1])
    await cb.answer()
    await lock(cb, f"Копий: {s['params']['copies']}")
    await cb.message.answer("🎨 <b>Шаг 3 из 4.</b> Цветная или чёрно-белая?", reply_markup=kb(
        [("🎨 Цветная", "color:1"), ("⚫ Чёрно-белая", "color:0")]))


@dp.callback_query(F.data.startswith("color:"))
async def choose_color(cb: CallbackQuery) -> None:
    s = _params_session(cb)
    if not s or "color" in s["params"]:
        return await cb.answer(STALE, show_alert=True)
    s["params"]["color"] = cb.data.endswith("1")
    await cb.answer()
    await lock(cb, "Цветная" if s["params"]["color"] else "Чёрно-белая")
    markup = pricing.get_prices()["quality_markup"]
    await cb.message.answer("✨ <b>Шаг 4 из 4.</b> Качество печати:", reply_markup=kb(
        [(title + (f" ({'+' if markup[key] > 0 else '−'}{abs(markup[key])} %)" if markup[key] else ""), f"q:{key}")
         for key, title in service.QUALITY_TITLES.items()]))


@dp.callback_query(F.data.startswith("q:"))
async def choose_quality(cb: CallbackQuery) -> None:
    s = _params_session(cb)
    if not s or "quality" in s["params"]:
        return await cb.answer(STALE, show_alert=True)
    if await busy_guard(cb):
        return
    key = cb.data.split(":", 1)[1]
    s["params"]["quality"] = key
    await cb.answer()
    await lock(cb, f"Качество: {service.QUALITY_TITLES[key].lower()}")
    _busy.add(cb.from_user.id)
    try:
        await render_and_preview(cb.message, s)
    finally:
        _busy.discard(cb.from_user.id)


# ---------- макет, превью и оформление ----------

async def render_and_preview(message: Message, s: dict) -> None:
    s["stage"] = "rendering"
    wait = await send_anim(message.chat.id, "thinking", "Тюша собирает макет… это займёт несколько секунд ⏳")
    out = s["dir"] / "print"
    shutil.rmtree(out, ignore_errors=True)
    p = s["params"]
    try:
        if s["kind"] == "cards":
            pages = await asyncio.to_thread(cards.build_deck, cards.DECKS[p["deck"]], s["photos"], out)
            p.update(sheets=len(pages) // 2, color=True, quality="high")
            previews = [pages[0], pages[len(pages) // 2]]  # первый лицевой лист и рубашка
        else:
            pages = await asyncio.to_thread(photos.build_photo_pages, s["photos"], p["format"],
                                            p["copies"], not p["color"], out)
            p["sheets"] = len(pages)
            previews = pages[:2]
        p["photos"] = len(s["photos"])
        s["pages"] = [str(x) for x in pages]
        preview_files = [await asyncio.to_thread(cards.make_preview, path, s["dir"] / f"preview_{i}.jpg")
                         for i, path in enumerate(previews)]
        s["previews"] = [str(x) for x in preview_files]
        s["amount"], detail = pricing.quote(s["kind"], p)
    except Exception:
        log.exception("Ошибка рендера")
        s["stage"] = "upload"
        await _delete_quietly(wait)
        await send_anim(message.chat.id, "oops", "Упс… макет не собрался. Пришлите другие фото и нажмите «Готово».",
                        DONE_KB)
        return
    await _delete_quietly(wait)
    await message.answer_media_group([InputMediaPhoto(media=FSInputFile(f)) for f in preview_files])
    s["stage"] = "review"
    await message.answer(
        "👀 <b>Вот как это будет выглядеть!</b>\n<i>Водяной знак только на превью, на печати его не будет.</i>\n\n"
        f"{service.describe(s['kind'], p)}\n\n💰 <b>Стоимость: {pricing.format_rub(s['amount'])}</b>"
        + (f"\n<i>{detail}</i>" if s["kind"] == "photo" else ""),
        reply_markup=kb([("✅ Оформить заказ", "order")],
                        [("🔁 Начать заново", f"menu:{s['kind']}"), ("✖ Отмена", "cancel")]))


@dp.callback_query(F.data == "order")
async def place_order(cb: CallbackQuery) -> None:
    s = sessions.get(cb.from_user.id)
    if not s or s["stage"] != "review":
        return await cb.answer(STALE, show_alert=True)
    if await busy_guard(cb):
        return
    s["stage"] = "ordering"
    _busy.add(cb.from_user.id)
    await cb.answer("Оформляю заказ…")
    await lock(cb, "Оформляем заказ…")
    try:
        order = await service.create_order(s, cb.from_user)
    except Exception:
        log.exception("Не удалось оформить заказ")
        s["stage"] = "review"
        await send_anim(cb.message.chat.id, "oops", "Упс… заказ не оформился. Попробуйте ещё раз через минуту.",
                        kb([("✅ Оформить заказ", "order")], [("✖ Отмена", "cancel")]))
        return
    finally:
        _busy.discard(cb.from_user.id)
    sessions.pop(cb.from_user.id, None)
    await send_anim(cb.message.chat.id, "printing",
                    f"✅ <b>Заказ №{order['id']} оформлен!</b>\n\n"
                    f"{service.describe(order['kind'], order['params'])}\n💰 {pricing.format_rub(order['amount'])}\n\n"
                    "Статус: 🆕 в очереди на печать.\n"
                    "Я напишу о каждом шаге: начали печатать → напечатано → выдано 🐾",
                    kb([("📦 Мои заказы", "menu:orders"), ("🏠 Меню", "menu:home")]))


# ---------- оператор в Telegram ----------

@dp.message(Command("admin"))
async def admin_link(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await message.answer(f"🧑‍💼 Панель заказов: {config.ADMIN_URL}\nПароль — ADMIN_PASSWORD в файле .env")


@dp.message(Command("printers"))
async def list_printers(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    names = printing.list_printers()
    status = await asyncio.to_thread(printing.printer_status, config.PRINTER_NAME)
    await message.answer(
        "Принтеры на компьютере:\n" + "\n".join(f"• {html.escape(n)}" for n in names)
        + f"\n\nСейчас используется: {html.escape(status['name'] or '—')}\nРежим: {config.PRINT_MODE}\n"
        + ("✅ Ошибок нет" if status["ok"] else "⚠️ " + html.escape("; ".join(status["problems"]) or "есть проблемные задания"))
        + f"\nВ очереди: {len(status['jobs'])}")


@dp.message(Command("testprint"))
async def test_print(message: Message) -> None:
    """Пробный лист: проверить связь с принтером и что масштаб 1:1 (квадрат ровно 50 мм)."""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    from PIL import Image, ImageDraw
    page = Image.new("RGB", cards.A4, "white")
    d = ImageDraw.Draw(page)
    x, y, side = cards.mm(80), cards.mm(40), cards.mm(50)
    d.rectangle((x, y, x + side, y + side), outline="black", width=4)
    d.text((cards.A4[0] // 2, cards.mm(25)), "Пробная печать", font=cards.rank_font(cards.mm(5)), fill="black", anchor="mm")
    d.text((cards.A4[0] // 2, y + side + cards.mm(10)), "Сторона квадрата должна быть ровно 50 мм",
           font=cards.rank_font(cards.mm(3.5)), fill="black", anchor="mm")
    path = config.DATA / "testprint.png"
    page.save(path, dpi=(cards.DPI, cards.DPI))
    status = await message.answer("🖨 Отправляю пробный лист…")
    try:
        result = await asyncio.to_thread(printing.print_pages, [path], printer=config.PRINTER_NAME,
                                         job_name="Тюша: пробный лист", mode=config.PRINT_MODE, file_dir=config.PRINTED_DIR)
        await status.edit_text(f"✅ Пробный лист {html.escape(result['message'])}. "
                               "Если он не вышел за минуту — посмотрите состояние принтера: /printers")
    except Exception as e:
        await status.edit_text(f"⚠️ Ошибка печати: {html.escape(str(e))}")


@dp.callback_query(F.data.startswith("adm:"))
async def admin_action(cb: CallbackQuery) -> None:
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("Нет доступа", show_alert=True)
    _, action, raw_id = cb.data.split(":")
    oid = int(raw_id)
    await cb.answer("Отправляю на принтер…")
    try:
        await service.start_print(oid, "back" if action == "backs" else "front", "admin")
    except service.ServiceError as e:
        await cb.message.answer(f"⚠️ Заказ №{oid}: {html.escape(str(e))}")
        return
    await lock(cb, "Отправлено на принтер")
    await cb.message.answer(f"🖨 Заказ №{oid} отправлен на принтер. Слежу за очередью — напишу, если что-то пойдёт не так.")


@dp.message()
async def fallback(message: Message) -> None:
    await message.answer("Мяу? 🐾 Тюша понимает кнопки — выберите, что сделать:", reply_markup=MAIN_MENU)


async def _delete_quietly(message: Message | None) -> None:
    if message:
        try:
            await message.delete()
        except Exception:
            pass


async def setup_profile(bot: Bot) -> None:
    """Команды в меню и описание бота (то, что видно до нажатия «Старт»)."""
    from aiogram.types import BotCommand, BotCommandScopeChat
    user_cmds = [BotCommand(command="start", description="Главное меню"),
                 BotCommand(command="orders", description="Мои заказы"),
                 BotCommand(command="help", description="Как это работает"),
                 BotCommand(command="cancel", description="Отменить текущий шаг")]
    admin_cmds = user_cmds + [BotCommand(command="admin", description="Ссылка на панель заказов"),
                              BotCommand(command="testprint", description="Пробный лист"),
                              BotCommand(command="printers", description="Состояние принтера")]
    try:
        await bot.set_my_commands(user_cmds)
        for admin in config.ADMIN_IDS:
            await bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=admin))
        await bot.set_my_short_description("Тюша 🐾 печатает ваши фото и делает игральные карты с вашими снимками")
        await bot.set_my_description(
            "Привет! Я Тюша 🐾\n\n"
            "🃏 Делаю игральные карты из ваших фото — 36 или 54 карты\n"
            "🖼 Печатаю фото 10×15, A5 и A4\n\n"
            "Присылаете снимки → смотрите превью → получаете готовую печать. Нажмите «Старт»!")
    except Exception as e:
        log.warning("Не удалось обновить профиль бота: %s", e)


async def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("Укажите BOT_TOKEN в файле .env (см. .env.example)")
    if not config.ADMIN_IDS:
        log.warning("ADMIN_IDS не задан: уведомления о заказах в Telegram приходить не будут")
    if not config.ADMIN_PASSWORD:
        log.warning("ADMIN_PASSWORD не задан: в веб-админку нельзя будет войти")
    log.info("Принтер: %s, режим: %s", config.PRINTER_NAME or printing.default_printer(), config.PRINT_MODE)
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    tg.bot = bot
    runner = await admin_web.start()
    background = asyncio.create_task(service.background_loop())
    await setup_profile(bot)
    try:
        await dp.start_polling(bot)
    finally:
        background.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
