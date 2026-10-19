"""Хранилище заказов (SQLite): заказы, журнал событий, настройки (цены)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from config import DB_PATH

_lock = threading.RLock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL")

_conn.executescript("""
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                 -- cards | photo
    status TEXT NOT NULL,               -- см. service.STATUSES
    amount INTEGER NOT NULL,            -- стоимость, копейки
    params TEXT NOT NULL,               -- JSON: параметры печати
    user_id INTEGER NOT NULL,
    user_name TEXT,
    username TEXT,
    dir TEXT NOT NULL,                  -- папка заказа с файлами
    pages TEXT NOT NULL,                -- JSON: листы для печати
    previews TEXT NOT NULL,             -- JSON: превью с водяным знаком
    sources TEXT NOT NULL,              -- JSON: исходные фото
    print_state TEXT,                   -- что сейчас говорит принтер
    print_job TEXT,                     -- JSON: {printer, job_id, part, prev}
    last_error TEXT,
    cancel_reason TEXT,
    admin_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    printed_at TEXT,
    issued_at TEXT,
    cancelled_at TEXT
);
CREATE INDEX IF NOT EXISTS orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS orders_user ON orders(user_id);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,                -- client | admin | system
    kind TEXT NOT NULL,                 -- info | success | warning | error
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_order ON events(order_id);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
""")

JSON_FIELDS = ("params", "pages", "previews", "sources", "print_job")


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for f in JSON_FIELDS:
        if d.get(f):
            d[f] = json.loads(d[f])
    return d


def _dump(value: Any) -> Any:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value


def create_order(**fields) -> dict:
    fields.setdefault("created_at", now())
    fields["updated_at"] = fields["created_at"]
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with _lock:
        cur = _conn.execute(f"INSERT INTO orders ({cols}) VALUES ({marks})", [_dump(v) for v in fields.values()])
        return get_order(cur.lastrowid)


def get_order(order_id: int) -> dict | None:
    with _lock:
        return _row(_conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())


def update_order(order_id: int, **fields) -> dict:
    fields["updated_at"] = now()
    sets = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        _conn.execute(f"UPDATE orders SET {sets} WHERE id=?", [_dump(v) for v in fields.values()] + [order_id])
        return get_order(order_id)


def transition(order_id: int, from_statuses: tuple[str, ...], **fields) -> dict | None:
    """Атомарно меняет поля, только если заказ сейчас в одном из from_statuses.
    Защищает от двойных нажатий: второй клик получит None."""
    fields["updated_at"] = now()
    sets = ", ".join(f"{k}=?" for k in fields)
    marks = ", ".join("?" for _ in from_statuses)
    with _lock:
        cur = _conn.execute(f"UPDATE orders SET {sets} WHERE id=? AND status IN ({marks})",
                            [_dump(v) for v in fields.values()] + [order_id, *from_statuses])
        return get_order(order_id) if cur.rowcount else None


def list_orders(statuses: list[str] | None = None, q: str = "", user_id: int | None = None,
                limit: int = 200) -> list[dict]:
    where, args = [], []
    if statuses:
        where.append(f"status IN ({', '.join('?' for _ in statuses)})")
        args += statuses
    if user_id is not None:
        where.append("user_id=?")
        args.append(user_id)
    q = q.strip().lstrip("№#@")
    if q:
        if q.isdigit():
            where.append("(id=? OR user_id=?)")
            args += [int(q), int(q)]
        else:
            where.append("(user_name LIKE ? OR username LIKE ?)")
            args += [f"%{q}%", f"%{q}%"]
    sql = "SELECT * FROM orders" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY id DESC LIMIT ?"
    with _lock:
        return [_row(r) for r in _conn.execute(sql, args + [limit]).fetchall()]


def count_by_status() -> dict[str, int]:
    with _lock:
        return {r[0]: r[1] for r in _conn.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")}


def stats_since(day: str) -> tuple[int, int]:
    """(число заказов, сумма в копейках) с начала дня day, без отменённых."""
    with _lock:
        row = _conn.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM orders "
                            "WHERE created_at >= ? AND status != 'cancelled'", (day,)).fetchone()
    return row[0], row[1]


def orders_in(statuses: tuple[str, ...]) -> list[dict]:
    with _lock:
        marks = ", ".join("?" for _ in statuses)
        return [_row(r) for r in _conn.execute(f"SELECT * FROM orders WHERE status IN ({marks})", statuses)]


def add_event(order_id: int, text: str, actor: str = "system", kind: str = "info") -> None:
    with _lock:
        _conn.execute("INSERT INTO events (order_id, at, actor, kind, text) VALUES (?, ?, ?, ?, ?)",
                      (order_id, now(), actor, kind, text))


def events_for(order_id: int) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute("SELECT * FROM events WHERE order_id=? ORDER BY id", (order_id,))]


def get_setting(key: str, default: Any = None) -> Any:
    with _lock:
        row = _conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_setting(key: str, value: Any) -> None:
    with _lock:
        _conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
