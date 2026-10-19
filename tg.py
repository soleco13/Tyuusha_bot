"""Отправка сообщений в Telegram из любого места (бот, админка, фоновые задачи)."""
from __future__ import annotations

import json
import logging

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

import config

log = logging.getLogger("tg")

bot: Bot | None = None  # выставляется при запуске

FILE_IDS = config.DATA / "file_ids.json"
_file_ids: dict[str, str] = json.loads(FILE_IDS.read_text("utf-8")) if FILE_IDS.exists() else {}


def kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Кнопки: ("текст", "callback"), ("текст", "url:https://...") или ("текст", "webapp:https://...")."""
    def button(t: str, d: str) -> InlineKeyboardButton:
        if d.startswith("url:"):
            return InlineKeyboardButton(text=t, url=d[4:])
        if d.startswith("webapp:"):
            return InlineKeyboardButton(text=t, web_app=WebAppInfo(url=d[7:]))
        return InlineKeyboardButton(text=t, callback_data=d)
    return InlineKeyboardMarkup(inline_keyboard=[[button(t, d) for t, d in row] for row in rows])


async def send_anim(chat_id: int, name: str, caption: str | None = None,
                    reply_markup: InlineKeyboardMarkup | None = None) -> Message | None:
    """GIF Тюши. После первой загрузки шлём по file_id; если анимация не ушла — отправляем текст."""
    path = config.ANIM_DIR / f"{name}.gif"
    sources = ([_file_ids[name]] if name in _file_ids else []) + ([FSInputFile(path)] if path.exists() else [])
    for source in sources:
        try:
            msg = await bot.send_animation(chat_id, source, caption=caption, reply_markup=reply_markup)
        except Exception as e:
            log.warning("Анимация %s не отправилась: %s", name, e)
            _file_ids.pop(name, None)
            continue
        if msg.animation and _file_ids.get(name) != msg.animation.file_id:
            _file_ids[name] = msg.animation.file_id
            FILE_IDS.write_text(json.dumps(_file_ids), "utf-8")
        return msg
    if caption:
        return await safe_send(chat_id, caption, reply_markup)
    return None


async def safe_send(chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> Message | None:
    """Сообщение, которое не роняет вызывающий код (клиент мог заблокировать бота)."""
    try:
        return await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception as e:
        log.warning("Не удалось написать %s: %s", chat_id, e)
        return None


async def safe_edit(chat_id: int, message_id: int | None, text: str,
                    reply_markup: InlineKeyboardMarkup | None = None) -> bool:
    if not message_id:
        return False
    try:
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup)
        return True
    except Exception as e:
        log.info("Не удалось изменить сообщение %s: %s", message_id, e)
        return False


async def notify_admins(text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    for admin in config.ADMIN_IDS:
        await safe_send(admin, text, reply_markup)
