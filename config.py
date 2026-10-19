"""Настройки из .env — в одном месте для бота, админки и сервиса заказов."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
PRINTER_NAME = os.getenv("PRINTER_NAME") or None
PRINT_MODE = os.getenv("PRINT_MODE", "printer")  # printer | file

# Веб-админка
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_HOST = os.getenv("ADMIN_HOST", "127.0.0.1")
ADMIN_PORT = int(os.getenv("ADMIN_PORT", "8080"))
ADMIN_URL = os.getenv("ADMIN_URL") or f"http://{'127.0.0.1' if ADMIN_HOST == '0.0.0.0' else ADMIN_HOST}:{ADMIN_PORT}"

DATA = Path(os.getenv("PRINTBOT_DATA") or BASE / "data")
SESSIONS_DIR = DATA / "sessions"
ORDERS_DIR = DATA / "orders"
PRINTED_DIR = DATA / "printed"
DB_PATH = DATA / "orders.sqlite3"
ANIM_DIR = BASE / "assets" / "anim"

for _d in (SESSIONS_DIR, ORDERS_DIR, PRINTED_DIR):
    _d.mkdir(parents=True, exist_ok=True)
