"""Telegram-бот Тюша. Клиенты работают только в Mini App (миниприложение), чат — для кнопки «Открыть»
и уведомлений о статусе заказа. Оператор получает заказы с кнопкой «Печать» и командами /admin, /printers, /testprint.

Запуск: python bot.py — поднимает бота, админку и Mini App (ADMIN_URL), слежение за принтером.
"""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, BotCommandScopeChat, CallbackQuery, MenuButtonWebApp, Message,
                           WebAppInfo)

import admin_web
import config
import printing
import service
import tg
from tg import kb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("printbot")

dp = Dispatcher()

APP_URL = f"{config.ADMIN_URL}/miniapp/"
OPEN_APP = kb([("🐾 Открыть Тюшу", f"webapp:{APP_URL}")])


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


# ---------- клиент: всё в Mini App ----------

@dp.message(CommandStart())
async def start(message: Message) -> None:
    name = html.escape(message.from_user.first_name or "")
    await message.answer(
        f"Привет{', ' + name if name else ''}! Я <b>Тюша</b> 🐾\n\n"
        "Печатаю ваши фото и делаю настоящие игральные карты с вашими снимками. "
        "Всё делается в приложении — нажмите кнопку ниже или «Тюша» слева от поля ввода.", reply_markup=OPEN_APP)


@dp.message(Command("myid"))
async def my_id(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


# ---------- оператор в Telegram ----------

@dp.message(Command("admin"))
async def admin_link(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await message.answer(f"🧑‍💼 Панель заказов: {config.ADMIN_URL}\nПароль — ADMIN_PASSWORD в файле .env")


@dp.message(Command("testprint"))
async def test_print(message: Message) -> None:
    """Пробный лист из браузера: проверить связь с принтером и что масштаб 1:1 (квадрат ровно 50 мм)."""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    if config.PRINT_MODE == "agent":
        await message.answer(f"🖨 Пробный лист: панель → «Принтеры» → «Пробный лист» у нужного профиля — "
                             f"{config.ADMIN_URL}/#printers. Квадрат на листе должен быть ровно 50 мм.")
        return
    await message.answer(f"🖨 Пробный лист: откройте {config.ADMIN_URL}/print/test в браузере на компьютере с принтером "
                         "(сначала войдите в админку). Квадрат на листе должен быть ровно 50 мм.")


@dp.callback_query(F.data.startswith("adm:"))
async def admin_action(cb: CallbackQuery) -> None:
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("Нет доступа", show_alert=True)
    _, action, raw_id = cb.data.split(":")
    oid = int(raw_id)
    await cb.answer("Готовлю печать…")
    try:
        await service.start_print(oid, "back" if action == "backs" else "front", "admin")
    except service.ServiceError as e:
        await cb.message.answer(f"⚠️ Заказ №{oid}: {html.escape(str(e))}")
        return
    await lock(cb, "Печать запущена")
    if config.PRINT_MODE == "agent":
        await cb.message.answer(f"🖨 Заказ №{oid}: задание отправлено на компьютер с принтером. Напишу, если что-то пойдёт не так.")
    elif config.PRINT_MODE == "browser":
        part = "back" if action == "backs" else "front"
        await cb.message.answer(f"🖨 Заказ №{oid}: откройте окно печати в админке — {config.ADMIN_URL}/print/{oid}/{part}\n"
                                "Напечатайте листы и нажмите там «Напечатано».")
    else:
        await cb.message.answer(f"🖨 Заказ №{oid} отправлен на принтер. Слежу за очередью — напишу, если что-то пойдёт не так.")


@dp.message()
async def fallback(message: Message) -> None:
    await message.answer("Заказы принимаем в приложении 🐾 Нажмите кнопку ниже.", reply_markup=OPEN_APP)


async def setup_profile(bot: Bot) -> None:
    """Меню, команды и описание бота; кнопка «Тюша» в меню открывает Mini App."""
    admin_cmds = [BotCommand(command="start", description="Открыть Тюшу"),
                  BotCommand(command="admin", description="Ссылка на панель заказов"),
                  BotCommand(command="testprint", description="Пробный лист")]
    try:
        await bot.set_my_commands([BotCommand(command="start", description="Открыть Тюшу")])
        for admin in config.ADMIN_IDS:
            await bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=admin))
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Тюша", web_app=WebAppInfo(url=APP_URL)))
        await bot.set_my_short_description("Тюша 🐾 печатает ваши фото и делает игральные карты с вашими снимками")
        await bot.set_my_description(
            "Привет! Я Тюша 🐾\n\n"
            "🃏 Делаю игральные карты из ваших фото — 36 или 54 карты\n"
            "🖼 Печатаю фото 10×15, A5 и A4\n\n"
            "Нажмите «Старт» и откройте приложение.")
    except Exception as e:
        log.warning("Не удалось обновить профиль бота: %s", e)


async def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("Укажите BOT_TOKEN в файле .env (см. .env.example)")
    if not config.ADMIN_IDS:
        log.warning("ADMIN_IDS не задан: уведомления о заказах в Telegram приходить не будут")
    if not config.ADMIN_PASSWORD:
        log.warning("ADMIN_PASSWORD не задан: в веб-админку нельзя будет войти")
    log.info("Принтер: %s, режим: %s", config.PRINTER_NAME or (printing.default_printer() if config.PRINT_MODE == "printer" else None), config.PRINT_MODE)
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
