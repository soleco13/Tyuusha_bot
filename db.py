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


def orders_since(day: str) -> list[dict]:
    """Все заказы, созданные начиная с дня day (YYYY-MM-DD) — для статистики."""
    with _lock:
        return [_row(r) for r in _conn.execute("SELECT * FROM orders WHERE created_at >= ? ORDER BY id", (day,))]


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



# ---------- печать через агента: компьютеры с принтерами, профили, задания ----------

# таблица print_jobs от прежней версии агента — другой формат, откладываем её в сторону
_old_cols = {r[1] for r in _conn.execute("PRAGMA table_info(print_jobs)")}
if _old_cols and "agent_id" not in _old_cols:
    _conn.execute("ALTER TABLE print_jobs RENAME TO print_jobs_v1")

_conn.executescript("""
CREATE TABLE IF NOT EXISTS agents (           -- компьютеры с принтером, подключённые кодом из панели
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,          -- sha256 токена; сам токен хранится только на компьютере
    version TEXT,
    status TEXT,                              -- JSON: принтеры и их состояние (присылает агент)
    last_seen REAL,
    revoked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pair_codes (code TEXT PRIMARY KEY, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS print_profiles (   -- как печатать материал: какой компьютер, принтер, настройки драйвера
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    agent_id INTEGER,
    printer TEXT,
    devmode TEXT,                             -- JSON: настройки драйвера, сохранённые на компьютере
    devmode_summary TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS print_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER,                         -- NULL — пробный лист
    agent_id INTEGER NOT NULL,
    profile TEXT NOT NULL,
    label TEXT NOT NULL,
    pages TEXT NOT NULL,                      -- JSON: пути к листам на сервере
    settings TEXT NOT NULL,                   -- JSON: всё, что нужно агенту для печати
    state TEXT NOT NULL,                      -- queued | sent | printing | done | error | cancelled
    detail TEXT,
    problem INTEGER NOT NULL DEFAULT 0,
    win_job INTEGER,
    cancel INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS print_jobs_state ON print_jobs(state);
""")

if "update_requested" not in {r[1] for r in _conn.execute("PRAGMA table_info(agents)")}:
    _conn.execute("ALTER TABLE agents ADD COLUMN update_requested INTEGER NOT NULL DEFAULT 0")

AGENT_JSON = ("status",)
PROFILE_JSON = ("devmode",)
JOB_JSON = ("pages", "settings")


def _plain(r: sqlite3.Row | None, json_fields: tuple[str, ...]) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for f in json_fields:
        if d.get(f):
            d[f] = json.loads(d[f])
    return d


def _update(table: str, key: str, key_value: Any, fields: dict) -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        _conn.execute(f"UPDATE {table} SET {sets} WHERE {key}=?", [_dump(v) for v in fields.values()] + [key_value])


# компьютеры

def add_agent(name: str, token_hash: str, version: str, status: dict) -> dict:
    with _lock:
        cur = _conn.execute("INSERT INTO agents (name, token_hash, version, status, last_seen, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)", (name, token_hash, version, _dump(status), time.time(), now()))
        return get_agent(cur.lastrowid)


def get_agent(agent_id: int) -> dict | None:
    with _lock:
        return _plain(_conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone(), AGENT_JSON)


def agent_by_token(token_hash: str) -> dict | None:
    with _lock:
        return _plain(_conn.execute("SELECT * FROM agents WHERE token_hash=? AND revoked=0", (token_hash,)).fetchone(),
                      AGENT_JSON)


def list_agents() -> list[dict]:
    with _lock:
        return [_plain(r, AGENT_JSON) for r in _conn.execute("SELECT * FROM agents WHERE revoked=0 ORDER BY id")]


def update_agent(agent_id: int, **fields) -> None:
    _update("agents", "id", agent_id, fields)


# коды подключения

def add_pair_code(code: str, expires: float) -> None:
    with _lock:
        _conn.execute("DELETE FROM pair_codes WHERE expires < ?", (time.time(),))
        _conn.execute("INSERT OR REPLACE INTO pair_codes (code, expires) VALUES (?, ?)", (code, expires))


def use_pair_code(code: str) -> bool:
    """Код одноразовый: проверяем и сразу удаляем."""
    with _lock:
        row = _conn.execute("SELECT expires FROM pair_codes WHERE code=?", (code,)).fetchone()
        _conn.execute("DELETE FROM pair_codes WHERE code=?", (code,))
    return bool(row) and row[0] >= time.time()


# профили печати

def ensure_profile(key: str, title: str) -> None:
    with _lock:
        _conn.execute("INSERT OR IGNORE INTO print_profiles (key, title) VALUES (?, ?)", (key, title))


def get_profile(key: str) -> dict | None:
    with _lock:
        return _plain(_conn.execute("SELECT * FROM print_profiles WHERE key=?", (key,)).fetchone(), PROFILE_JSON)


def list_profiles() -> list[dict]:
    with _lock:
        return [_plain(r, PROFILE_JSON) for r in _conn.execute("SELECT * FROM print_profiles ORDER BY rowid")]


def update_profile(key: str, **fields) -> None:
    fields["updated_at"] = now()
    _update("print_profiles", "key", key, fields)


# задания печати

def add_print_job(**fields) -> dict:
    fields.update(state="queued", created_at=now(), updated_at=now())
    cols = ", ".join(fields)
    with _lock:
        cur = _conn.execute(f"INSERT INTO print_jobs ({cols}) VALUES ({', '.join('?' for _ in fields)})",
                            [_dump(v) for v in fields.values()])
        return get_print_job(cur.lastrowid)


def get_print_job(job_id: int) -> dict | None:
    with _lock:
        return _plain(_conn.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone(), JOB_JSON)


def update_print_job(job_id: int, **fields) -> dict:
    fields["updated_at"] = now()
    _update("print_jobs", "id", job_id, fields)
    return get_print_job(job_id)


def print_jobs(where: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [_plain(r, JOB_JSON) for r in _conn.execute(f"SELECT * FROM print_jobs WHERE {where} ORDER BY id", args)]


def take_print_job(agent_id: int) -> dict | None:
    """Самое старое задание этого компьютера; отдаём один раз (queued → sent)."""
    with _lock:
        row = _conn.execute("SELECT id FROM print_jobs WHERE agent_id=? AND state='queued' AND cancel=0 "
                            "ORDER BY id LIMIT 1", (agent_id,)).fetchone()
        if not row:
            return None
        return update_print_job(row[0], state="sent", detail="Компьютер получил задание")
