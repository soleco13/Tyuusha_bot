"""Рассылка поста всем клиентам бота.

Пост — папка: caption.html (подпись, HTML Telegram), картинки *.jpg/*.png (альбом, по имени),
button.txt (необязательно — две строки: текст сообщения и надпись кнопки, открывающей Mini App;
уходит отдельным сообщением под альбомом).

    python broadcast.py assets/posts/2026-11-backs          # только админам — посмотреть, как выглядит
    python broadcast.py assets/posts/2026-11-backs --all    # всем, кто не заблокировал бота

Работает рядом с запущенным ботом: только отправляет сообщения, обновления не читает.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import FSInputFile, InputMediaPhoto

import config
import db
import tg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("broadcast")
LOG = config.DATA / "broadcasts.log"


async def send_post(bot: Bot, chat_id: int, post: Path, file_ids: list[str]) -> None:
    caption = (post / "caption.html").read_text("utf-8").strip()
    images = sorted(p for p in post.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    sources = file_ids or [FSInputFile(p) for p in images]
    if len(sources) == 1:
        msgs = [await bot.send_photo(chat_id, sources[0], caption=caption)]
    else:
        media = [InputMediaPhoto(media=s, caption=caption if i == 0 else None) for i, s in enumerate(sources)]
        msgs = await bot.send_media_group(chat_id, media)
    if not file_ids:  # дальше шлём по file_id — без повторной загрузки
        file_ids.extend(m.photo[-1].file_id for m in msgs)
    button = post / "button.txt"
    if button.exists():
        text, label = button.read_text("utf-8").strip().split("\n", 1)
        await bot.send_message(chat_id, text, reply_markup=tg.kb([(label.strip(), f"webapp:{config.ADMIN_URL}/miniapp/")]))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("post", type=Path)
    ap.add_argument("--all", action="store_true", help="всем клиентам (без флага — только админам)")
    args = ap.parse_args()

    targets = db.broadcast_users() if args.all else sorted(config.ADMIN_IDS)
    log.info("Пост %s → %d получателей", args.post, len(targets))
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    file_ids: list[str] = []
    ok = blocked = failed = 0
    try:
        for uid in targets:
            for attempt in range(3):
                try:
                    await send_post(bot, uid, args.post, file_ids)
                    ok += 1
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramForbiddenError:
                    db.set_user_blocked(uid)
                    blocked += 1
                    break
                except Exception as e:
                    log.warning("%s: %s", uid, e)
                    failed += 1
                    break
            await asyncio.sleep(0.1)  # с запасом от лимита Telegram ~30 сообщений/с
    finally:
        await bot.session.close()
    summary = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {args.post.name} {'all' if args.all else 'admins'}: " \
              f"доставлено {ok}, заблокировали бота {blocked}, ошибок {failed}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(summary + "\n")
    log.info(summary)


if __name__ == "__main__":
    asyncio.run(main())
