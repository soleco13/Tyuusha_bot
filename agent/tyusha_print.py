"""«Тюша Печать» — программа для компьютера, к которому подключён принтер.

Сервер с ботом и панелью стоит в интернете и до принтера не достаёт. Программа сама
обращается к серверу: забирает задания (листы + все настройки печати), печатает через
драйвер Windows в масштабе 1:1 и сообщает ход работы. Входящие подключения не нужны.

Оператору здесь делать нечего: печать запускается кнопкой в панели заказов.
Один раз при установке: ввести код из панели («Принтеры → Подключить компьютер»).

Работает без присмотра:
- профили печати и параметры работы приходят с сервера при каждом опросе;
- новая версия программы сама скачивается с GitHub Releases, проверяется и ставится,
  когда принтер свободен (только для собранного exe);
- надсмотрщик перезапускает программу после сбоя или зависания;
- компьютер не засыпает, пока программа открыта; есть автозапуск с Windows.

Режимы запуска exe: без параметров — надсмотрщик + окно; --child — само окно (запускает надсмотрщик);
--headless — без окна (проверки); --selftest — проверка сборки, результат в selftest.json.
Из исходников: run_agent.bat. Сборка: build_agent.bat. Без бумаги: TYUSHA_DRY_RUN=1.
"""
from __future__ import annotations

import ctypes
import hashlib
import http.client
import json
import logging
import logging.handlers
import os
import queue
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    BUNDLE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    BUNDLE = Path(__file__).resolve().parent
    sys.path.insert(0, str(BUNDLE.parent))   # printing.py лежит в папке бота
import printing  # noqa: E402

APP_NAME = "Тюша Печать"
VERSION = "1.1.0"
DEFAULT_SERVER = "https://213.21.241.28"
UPDATE_REPO = "soleco13/Tyuusha_bot"          # откуда брать новые версии (сервер может поменять)
UPDATE_API = os.getenv("TYUSHA_UPDATE_API")   # подмена адреса для проверок
DRY_RUN = os.getenv("TYUSHA_DRY_RUN") == "1"
INSTANCE = os.getenv("TYUSHA_INSTANCE", "")       # отдельная копия для проверок, не мешает рабочей
EXIT_RESTART, EXIT_UPGRADE = 75, 76           # коды выхода для надсмотрщика

HOME = Path(os.getenv("APPDATA") or Path.home()) / "TyushaPrint"
HOME.mkdir(parents=True, exist_ok=True)
CONFIG = HOME / "config.json"
JOURNAL = HOME / "journal.json"
CACHE = HOME / "cache"
UPDATES = HOME / "update"

_handler = logging.handlers.RotatingFileHandler(HOME / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(process)d %(levelname)s %(message)s",
                    handlers=[_handler] + ([] if FROZEN else [logging.StreamHandler()]))
log = logging.getLogger("tyusha")
threading.excepthook = lambda a: log.error("Сбой в потоке %s", a.thread.name if a.thread else "?",
                                           exc_info=(a.exc_type, a.exc_value, a.exc_traceback))

BLUE, INK, MUTED, BG, CARD, OK, BAD, WARN = "#2563EB", "#172033", "#6A7389", "#F5F7FB", "#FFFFFF", "#0E8F64", "#CF2F48", "#A86300"


# ---------- файлы ----------

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(path)


def version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


class Journal:
    """Какие задания уже ушли на принтер — чтобы при сбое связи не напечатать одно и то же дважды."""
    def __init__(self):
        self.data: dict[str, dict] = load_json(JOURNAL, {})
        self.lock = threading.Lock()

    def get(self, job_id: int) -> dict | None:
        with self.lock:
            return self.data.get(str(job_id))

    def put(self, job_id: int, **info) -> None:
        with self.lock:
            self.data[str(job_id)] = {**self.data.get(str(job_id), {}), **info, "at": time.time()}
            if len(self.data) > 300:
                for k in sorted(self.data, key=lambda k: self.data[k]["at"])[:100]:
                    del self.data[k]
            save_json(JOURNAL, self.data)


# ---------- связь с сервером ----------

class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class UntrustedCert(Exception):
    def __init__(self, fingerprint: str):
        super().__init__(fingerprint)
        self.fingerprint = fingerprint


def fingerprint_of(der: bytes) -> str:
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


class Api:
    """HTTPS с проверкой сертификата; для сервера с самоподписанным сертификатом — закрепление отпечатка."""
    def __init__(self, server: str, token: str | None = None, pin: str | None = None):
        u = urllib.parse.urlsplit(server.strip().rstrip("/"))
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ApiError(0, "Адрес сервера должен начинаться с https://")
        self.scheme, self.host, self.port = u.scheme, u.hostname, u.port
        self.base = u.path
        self.token, self.pin = token, pin

    def _conn(self, timeout: float):
        if self.scheme == "http":
            return http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        ctx = ssl.create_default_context()
        if self.pin:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=timeout, context=ctx)
        try:
            conn.connect()
        except ssl.SSLCertVerificationError:
            raise UntrustedCert(self.server_fingerprint()) from None
        if self.pin and fingerprint_of(conn.sock.getpeercert(binary_form=True)) != self.pin:
            conn.close()
            raise ApiError(0, "Сертификат сервера изменился. Если сервер переустанавливали — подключите компьютер заново")
        return conn

    def server_fingerprint(self) -> str:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((self.host, self.port or 443), timeout=10) as raw:
            with ctx.wrap_socket(raw, server_hostname=self.host) as s:
                return fingerprint_of(s.getpeercert(binary_form=True))

    def request(self, method: str, path: str, body: dict | None = None, raw: bool = False, timeout: float = 30):
        conn = self._conn(timeout)
        try:
            headers = {"Content-Type": "application/json", "User-Agent": f"TyushaPrint/{VERSION}"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            conn.request(method, self.base + path, body=json.dumps(body).encode() if body is not None else None,
                         headers=headers)
            r = conn.getresponse()
            data = r.read()
        finally:
            conn.close()
        if r.status >= 400:
            try:
                msg = json.loads(data).get("error") or f"Сервер ответил {r.status}"
            except Exception:
                msg = f"Сервер ответил {r.status}"
            raise ApiError(r.status, msg)
        return data if raw else json.loads(data or b"{}")


# ---------- компьютер ----------

def collect_printers() -> list[dict]:
    out = []
    for name in printing.list_printers():
        try:
            st = printing.printer_status(name)
            out.append({"name": name, "ok": st["ok"], "problems": st["problems"],
                        "jobs": [{k: j[k] for k in ("id", "document", "states", "problem")} for j in st["jobs"][:10]]})
        except Exception as e:  # noqa: BLE001
            out.append({"name": name, "ok": False, "problems": [f"не удалось опросить: {e}"], "jobs": []})
    return out


def launch_command() -> str:
    if FROZEN:
        return f'"{sys.executable}"'
    return f'"{Path(sys.executable).with_name("pythonw.exe")}" "{Path(__file__).resolve()}"'


def set_autostart(enabled: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                        winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, "TyushaPrint", 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, "TyushaPrint")
            except FileNotFoundError:
                pass


def autostart_value() -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            return winreg.QueryValueEx(key, "TyushaPrint")[0]
    except OSError:
        return None


def keep_awake() -> None:
    """Пока программа работает, компьютер не уходит в сон (экран гаснуть может)."""
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except Exception:
        pass


def tidy_up() -> None:
    """При старте: старые временные листы, старый exe после обновления, путь автозапуска."""
    shutil.rmtree(CACHE, ignore_errors=True)
    if FROZEN:
        old = Path(sys.executable).with_name(Path(sys.executable).stem + ".old.exe")
        for _ in range(10):
            if not old.exists():
                break
            try:
                old.unlink()
            except OSError:
                time.sleep(1)  # старая версия ещё закрывается
    if INSTANCE:  # проверочная копия не трогает автозапуск рабочей программы
        return
    try:
        current = autostart_value()
        registered = (current or "").strip().split('"')[1] if (current or "").startswith('"') else (current or "").split(" ")[0]
        if current and registered and not Path(registered).exists():  # программу переложили в другую папку
            set_autostart(True)
            log.info("Путь автозапуска указывал на удалённый файл — обновлён")
    except Exception as e:  # noqa: BLE001
        log.warning("Автозапуск: %s", e)


def fresh_env(**extra) -> dict:
    """Окружение для запуска своего же exe: новая копия распаковывается заново и не зависит от родителя
    (иначе PyInstaller отдаёт ей временную папку родителя, а та исчезает, когда родитель закрывается)."""
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1", **extra}
    for k in [k for k in env if k.startswith("_PYI_") or k == "_MEIPASS2"]:
        env.pop(k)
    return env


def single_instance(name: str, wait: float = 0) -> bool:
    """Именованный мьютекс; держим ссылку до конца процесса."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # код ошибки берём сразу после вызова
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    deadline = time.time() + wait
    while True:
        handle = kernel32.CreateMutexW(None, False, name)
        if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
            single_instance.handles.append(handle)
            return True
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        if time.time() >= deadline:
            log.info("Уже запущена другая копия (%s) — выходим", name)
            return False
        time.sleep(0.5)


single_instance.handles = []


# ---------- ядро: связь, печать, обновления, сторож ----------

class Core:
    def __init__(self):
        self.conf: dict = load_json(CONFIG, {})
        self.events: queue.Queue = queue.Queue()   # для окна
        self.server_conf: dict = {}                 # параметры работы с сервера
        self.exit_code: int | None = None
        self.worker = Worker(self)
        self.updater = Updater(self)

    def start(self) -> None:
        tidy_up()
        keep_awake()
        self.worker.start()
        self.updater.start()
        threading.Thread(target=self.watchdog, name="watchdog", daemon=True).start()

    def request_exit(self, code: int) -> None:
        if self.exit_code is None:
            self.exit_code = code
            log.info("Выход с кодом %s", code)
            self.worker.stop.set()
            self.events.put("exit")

    def watchdog(self) -> None:
        """Опрос сервера завис или поток упал — перезапускаемся целиком (это сделает надсмотрщик)."""
        while self.exit_code is None:
            time.sleep(30)
            stale = time.time() - self.worker.beat
            if not self.worker.is_alive() or stale > 600:
                log.error("Сторож: опрос %s (%.0f с без признаков жизни) — перезапуск",
                          "остановился" if not self.worker.is_alive() else "завис", stale)
                self.request_exit(EXIT_RESTART)


class Worker(threading.Thread):
    """Опрос сервера, печать, слежение за очередью Windows."""

    def __init__(self, core: Core):
        super().__init__(name="worker", daemon=True)
        self.core = core
        self.journal = Journal()
        self.stop = threading.Event()
        self.beat = time.time()
        self.connected: bool | None = None
        self.last_error = ""
        self.current: dict | None = None      # {"id", "label", "state", "win_job", "printer", "cancel"}
        self.history: deque = deque(maxlen=30)
        self.profiles: list[dict] = []
        self.printers: list[dict] = []
        self.name_on_server = ""

    def api(self) -> Api:
        c = self.core.conf
        return Api(c["server"], c.get("token"), c.get("pin"))

    def status(self) -> dict:
        self.printers = collect_printers()
        cur = self.current
        upd = self.core.updater
        return {"printers": self.printers, "default_printer": printing.default_printer(), "dry_run": DRY_RUN,
                "computer": socket.gethostname(), "update": upd.state_text(),
                "current": {"label": cur["label"], "state": cur["state"]} if cur else None}

    def run(self) -> None:
        backoff = 2
        while not self.stop.is_set():
            self.beat = time.time()
            if not self.core.conf.get("token"):
                self.stop.wait(1)
                continue
            busy = self.current is not None
            wait = int(self.core.server_conf.get("poll_wait", 15))
            try:
                resp = self.api().request("POST", "/agent/v1/poll", {
                    "status": self.status(), "version": VERSION, "wait": not busy,
                    "active_job": self.current["id"] if busy else None}, timeout=wait + 25)
                if self.connected is not True:
                    log.info("Связь с сервером есть")
                self.connected, self.last_error, backoff = True, "", 2
                self.name_on_server = resp.get("name", "")
                self.profiles = resp.get("profiles", [])
                self.core.server_conf = resp.get("config") or self.core.server_conf
                if resp.get("update_now"):
                    self.core.updater.check_now("по команде из панели")
                for c in resp.get("cancel", []):
                    self.cancel(c)
                if resp.get("job") and self.current is None:
                    job = resp["job"]
                    self.current = {"id": job["id"], "label": job["label"], "state": "Получено задание",
                                    "win_job": None, "printer": job["settings"]["printer"], "cancel": False}
                    threading.Thread(target=self.run_job, args=(job,), name=f"job-{job['id']}", daemon=True).start()
                self.core.events.put("refresh")
                if busy:
                    self.stop.wait(3)
            except ApiError as e:
                self.connected, self.last_error = False, str(e)
                log.warning("Сервер: %s", e)
                if e.status == 401:  # компьютер отключили в панели
                    self.core.conf.pop("token", None)
                    save_json(CONFIG, self.core.conf)
                    self.core.events.put("unpaired")
                self.core.events.put("refresh")
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 60)
            except Exception as e:  # noqa: BLE001
                if self.connected is not False:
                    log.warning("Нет связи с сервером: %s", e)
                self.connected, self.last_error = False, f"Нет связи с сервером: {e}"
                self.core.events.put("refresh")
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 60)

    def report(self, job_id: int, state: str, detail: str = "", problem: bool = False, win_job: int | None = None) -> None:
        body = {"state": state, "detail": detail, "problem": problem}
        if win_job is not None:
            body["win_job"] = win_job
        for attempt in range(10):  # сеть может моргнуть — повторяем несколько минут
            try:
                self.api().request("POST", f"/agent/v1/jobs/{job_id}/report", body)
                return
            except ApiError as e:
                if e.status in (401, 404):
                    return
            except Exception:
                pass
            time.sleep(min(2 ** attempt, 30))
        log.error("Не удалось сообщить серверу о задании %s (%s)", job_id, state)

    def finish(self, label: str, result: str) -> None:
        self.history.appendleft((time.strftime("%H:%M"), label, result))
        self.current = None
        self.core.events.put("refresh")

    def run_job(self, job: dict) -> None:
        cur = self.current
        s = job["settings"]
        if self.journal.get(job["id"]):  # уже отправляли на принтер — второй раз не печатаем
            self.report(job["id"], "done", "Уже было отправлено на принтер этим компьютером")
            return self.finish(job["label"], "уже было напечатано")
        tmp = CACHE / f"job_{job['id']}"
        try:
            tmp.mkdir(parents=True, exist_ok=True)
            pages = []
            for n in range(job["pages"]):
                cur["state"] = f"Загружаем листы: {n + 1} из {job['pages']}"
                self.core.events.put("refresh")
                path = tmp / f"page_{n + 1:02d}.png"
                for attempt in range(4):
                    try:
                        path.write_bytes(self.api().request("GET", f"/agent/v1/jobs/{job['id']}/pages/{n}",
                                                            raw=True, timeout=120))
                        break
                    except ApiError:
                        raise
                    except Exception:
                        if attempt == 3:
                            raise
                        time.sleep(3 * (attempt + 1))
                pages.append(path)
            if cur["cancel"]:
                self.report(job["id"], "cancelled", "Снято до печати")
                return self.finish(job["label"], "снято")
            cur["state"] = "Отправляем на принтер"
            self.core.events.put("refresh")
            result = printing.print_pages(pages, printer=s["printer"], job_name=job["label"], color=s["color"],
                                          quality=s.get("quality", "high"), devmode=s.get("devmode"),
                                          mode="file" if DRY_RUN else "printer", file_dir=HOME / "dry_run")
            self.journal.put(job["id"], state="spooled", win_job=result["job_id"])
            log.info("Задание %s «%s»: %s", job["id"], job["label"], result["message"])
            if result["job_id"] is None:  # пробный режим без бумаги
                self.journal.put(job["id"], state="done")
                self.report(job["id"], "done", "Листы сохранены в папку (пробный режим)")
                return self.finish(job["label"], "сохранено (пробный режим)")
            cur["win_job"] = result["job_id"]
            cur["state"] = "В очереди принтера"
            self.report(job["id"], "printing", "В очереди принтера", win_job=result["job_id"])
            self.watch(job, cur)
        except Exception as e:  # noqa: BLE001
            log.exception("Ошибка печати")
            self.report(job["id"], "error", f"Ошибка на компьютере: {e}")
            self.finish(job["label"], f"ошибка: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def watch(self, job: dict, cur: dict) -> None:
        """Следит за заданием в очереди Windows, пока принтер его не заберёт."""
        last, since, warned = None, time.time(), False
        stuck_after = int(self.core.server_conf.get("stuck_minutes", 20)) * 60
        while not self.stop.is_set():
            if cur["cancel"]:
                return
            try:
                st = printing.job_status(cur["printer"], cur["win_job"])
            except Exception as e:  # noqa: BLE001
                log.warning("Не удалось проверить очередь: %s", e)
                time.sleep(3)
                continue
            if st is None or st["printed"]:
                self.journal.put(job["id"], state="done")
                self.report(job["id"], "done", "Напечатано", win_job=cur["win_job"])
                log.info("Задание %s напечатано", job["id"])
                return self.finish(job["label"], "напечатано")
            text = ", ".join(st["states"])
            if (text, st["problem"]) != last:
                last, since, warned = (text, st["problem"]), time.time(), False
                cur["state"] = ("⚠ " if st["problem"] else "") + text
                self.report(job["id"], "printing", text, problem=st["problem"], win_job=cur["win_job"])
                self.core.events.put("refresh")
            elif not warned and time.time() - since > stuck_after:
                warned = True  # Windows молчит, а задание не двигается — пусть оператор посмотрит на принтер
                minutes = int((time.time() - since) // 60)
                self.report(job["id"], "printing", f"{text} — без изменений {minutes} мин, проверьте принтер",
                            problem=True, win_job=cur["win_job"])
            time.sleep(2)

    def cancel(self, c: dict) -> None:
        cur = self.current
        if not cur or cur["id"] != c["job_id"]:
            self.report(c["job_id"], "cancelled", "Задания уже нет на компьютере")
            return
        cur["cancel"] = True
        if cur.get("win_job"):
            try:
                printing.cancel_job(cur["printer"], cur["win_job"])
            except Exception as e:  # noqa: BLE001
                log.warning("Не удалось удалить задание из очереди: %s", e)
        self.journal.put(cur["id"], state="cancelled")
        self.report(cur["id"], "cancelled", "Снято с принтера по команде из панели")
        self.finish(cur["label"], "снято с принтера")


class Updater(threading.Thread):
    """Новые версии — из GitHub Releases (теги agent-vX.Y.Z, файл TyushaPrint.exe, строка SHA256 в описании).
    Скачиваем, сверяем контрольную сумму, запускаем самопроверку нового exe и ставим, когда принтер свободен."""

    def __init__(self, core: Core):
        super().__init__(name="updater", daemon=True)
        self.core = core
        self.now = threading.Event()
        self.reason = ""
        self.status = "проверим вскоре после запуска" if FROZEN else "из исходников обновляется через git pull"
        self.latest: str | None = None
        self.checked_at: float | None = None

    def state_text(self) -> str:
        return self.status

    def check_now(self, reason: str) -> None:
        self.reason = reason
        self.now.set()

    def run(self) -> None:
        if not FROZEN:
            return
        delay = 60 if not os.getenv("TYUSHA_UPDATE_NOW") else 1
        while self.core.exit_code is None:
            self.now.wait(delay)
            self.now.clear()
            try:
                self.cycle()
            except Exception as e:  # noqa: BLE001
                self.status = f"не удалось проверить обновления: {e}"
                log.warning("Обновление: %s", e)
            self.core.events.put("refresh")
            delay = float(self.core.server_conf.get("update_check_hours", 6)) * 3600

    def find_release(self) -> dict | None:
        repo = self.core.server_conf.get("update_repo") or UPDATE_REPO
        url = UPDATE_API or f"https://api.github.com/repos/{repo}/releases?per_page=20"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": f"TyushaPrint/{VERSION}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            releases = json.load(r)
        best = None
        for rel in releases:
            tag = rel.get("tag_name", "")
            if rel.get("draft") or rel.get("prerelease") or not tag.startswith("agent-v"):
                continue
            asset = next((a for a in rel.get("assets", []) if a.get("name") == "TyushaPrint.exe"), None)
            m = re.search(r"SHA256:\s*([0-9a-fA-F]{64})", rel.get("body") or "")
            digest = (asset or {}).get("digest") or ""
            sha = m.group(1) if m else (digest.split(":", 1)[1] if digest.startswith("sha256:") else None)
            if not asset or not sha:
                continue
            ver = tag[len("agent-v"):]
            if best is None or version_tuple(ver) > version_tuple(best["version"]):
                best = {"version": ver, "url": asset["browser_download_url"], "sha256": sha.lower(), "size": asset.get("size")}
        return best

    def cycle(self) -> None:
        self.status = "проверяем обновления…"
        rel = self.find_release()
        self.checked_at = time.time()
        if not rel or version_tuple(rel["version"]) <= version_tuple(VERSION):
            self.latest = rel["version"] if rel else None
            self.status = f"последняя версия, проверено в {time.strftime('%H:%M')}"
            return
        self.latest = rel["version"]
        log.info("Найдена версия %s (%s)", rel["version"], self.reason or "плановая проверка")
        new_exe = self.download(rel)
        self.selftest(new_exe, rel["version"])
        while self.core.worker.current is not None and self.core.exit_code is None:  # не мешаем печати
            self.status = f"версия {rel['version']} скачана — поставим, как только принтер освободится"
            self.core.events.put("refresh")
            time.sleep(5)
        self.install(new_exe, rel["version"])

    def download(self, rel: dict) -> Path:
        UPDATES.mkdir(parents=True, exist_ok=True)
        target = UPDATES / f"TyushaPrint-{rel['version']}.exe"
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == rel["sha256"]:
            return target
        part = target.with_suffix(".part")
        h = hashlib.sha256()
        req = urllib.request.Request(rel["url"], headers={"User-Agent": f"TyushaPrint/{VERSION}"})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
            total, got = int(r.headers.get("Content-Length") or rel.get("size") or 0), 0
            while chunk := r.read(256 * 1024):
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if total:
                    self.status = f"скачиваем версию {rel['version']}: {got * 100 // total}%"
        if h.hexdigest() != rel["sha256"]:
            part.unlink(missing_ok=True)
            raise RuntimeError("контрольная сумма скачанного файла не совпала — обновление отменено")
        part.replace(target)
        return target

    def selftest(self, exe: Path, version: str) -> None:
        """Новый exe должен запуститься и увидеть принтеры — иначе не ставим."""
        self.status = f"проверяем версию {version}…"
        home = UPDATES / "selftest"
        shutil.rmtree(home, ignore_errors=True)
        home.mkdir(parents=True)
        subprocess.run([str(exe), "--selftest"], env=fresh_env(APPDATA=str(home)), timeout=180,
                       creationflags=0x08000000)  # CREATE_NO_WINDOW
        res = load_json(home / "TyushaPrint" / "selftest.json", {})
        if not res.get("ok") or res.get("version") != version:
            raise RuntimeError(f"новая версия не прошла самопроверку: {res.get('error') or res}")

    def install(self, new_exe: Path, version: str) -> None:
        exe = Path(sys.executable)
        old = exe.with_name(exe.stem + ".old.exe")
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass
        exe.rename(old)                    # запущенный exe можно переименовать, но не перезаписать
        try:
            shutil.copy2(new_exe, exe)
        except Exception:
            old.rename(exe)                # вернуть как было
            raise
        log.info("Установлена версия %s, перезапуск", version)
        self.status = f"установлена версия {version}, перезапуск…"
        self.core.request_exit(EXIT_UPGRADE)


def selftest() -> None:
    """Проверка сборки без окна: модули грузятся, принтеры видны. Результат — в selftest.json."""
    result = {"version": VERSION, "frozen": FROZEN, "icon": (BUNDLE / "assets" / "icon.png").exists()}
    try:
        __import__("tkinter")  # окно должно собираться в exe
        result["default_printer"] = printing.default_printer()
        result["printers"] = [{"name": p["name"], "ok": p["ok"]} for p in collect_printers()]
        if result["default_printer"]:
            result["devmode_fields"] = len(printing.devmode_to_dict(printing._default_devmode(result["default_printer"])))
        result["ok"] = True
    except Exception as e:  # noqa: BLE001
        result.update(ok=False, error=repr(e))
    save_json(HOME / "selftest.json", result)


# ---------- окно программы ----------

def run_window(core: Core) -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    class App:
        def __init__(self):
            self.core = core
            self.root = tk.Tk()
            self.root.title(APP_NAME)
            self.root.geometry("560x680")
            self.root.minsize(480, 540)
            self.root.configure(bg=BG)
            self.root.report_callback_exception = lambda *a: log.error("Ошибка в окне", exc_info=a)
            icon = BUNDLE / "assets" / "icon.png"
            if icon.exists():
                self._icon = tk.PhotoImage(file=str(icon))
                self.root.iconphoto(True, self._icon)
            self.root.protocol("WM_DELETE_WINDOW", self.on_close)
            self.style()
            self.body = tk.Frame(self.root, bg=BG)
            self.body.pack(fill="both", expand=True, padx=18, pady=16)
            self._profiles_sig = None
            self.show_main() if core.conf.get("token") else self.show_pair()
            self.root.after(400, self.pump)

        def style(self) -> None:
            s = ttk.Style(self.root)
            s.theme_use("clam")
            s.configure(".", background=BG, foreground=INK, font=("Segoe UI", 10))
            s.configure("H.TLabel", font=("Segoe UI Semibold", 16), background=BG)
            s.configure("T.TLabel", font=("Segoe UI Semibold", 11), background=CARD)
            s.configure("C.TLabel", background=CARD)
            s.configure("M.TLabel", background=CARD, foreground=MUTED)
            s.configure("MB.TLabel", background=BG, foreground=MUTED)
            s.configure("Accent.TButton", background=BLUE, foreground="white", font=("Segoe UI Semibold", 10),
                        padding=(14, 8), borderwidth=0)
            s.map("Accent.TButton", background=[("active", "#1D4FC4"), ("disabled", "#9DB6F2")])
            s.configure("TButton", padding=(12, 6))
            s.configure("TCheckbutton", background=BG)

        def clear(self) -> None:
            for w in self.body.winfo_children():
                w.destroy()

        def card(self) -> tk.Frame:
            f = tk.Frame(self.body, bg=CARD, highlightthickness=1, highlightbackground="#E3E6EE", bd=0)
            f.pack(fill="x", pady=(0, 12))
            inner = tk.Frame(f, bg=CARD)
            inner.pack(fill="both", expand=True, padx=14, pady=12)
            return inner

        # --- подключение ---

        def show_pair(self, message: str = "") -> None:
            self.clear()
            ttk.Label(self.body, text="Подключение к Тюше", style="H.TLabel").pack(anchor="w")
            ttk.Label(self.body, style="MB.TLabel", wraplength=500, justify="left",
                      text="Откройте панель заказов → «Принтеры» → «Подключить компьютер» и введите код, который "
                           "там появится. Это нужно сделать один раз.").pack(anchor="w", pady=(4, 14))
            c = self.card()
            self.v_server = tk.StringVar(value=core.conf.get("server", DEFAULT_SERVER))
            self.v_code = tk.StringVar()
            self.v_name = tk.StringVar(value=core.conf.get("name") or socket.gethostname())
            self.v_auto = tk.BooleanVar(value=True)
            for label, var, width in (("Адрес сервера", self.v_server, 40), ("Код из панели (6 цифр)", self.v_code, 12),
                                      ("Название этого компьютера", self.v_name, 30)):
                ttk.Label(c, text=label, style="C.TLabel").pack(anchor="w", pady=(6, 2))
                e = ttk.Entry(c, textvariable=var, width=width, font=("Segoe UI", 12 if var is self.v_code else 10))
                e.pack(anchor="w", fill="x" if width > 20 else None)
                if var is self.v_code:
                    e.focus_set()
                    e.bind("<Return>", lambda _e: self.pair())
            ttk.Checkbutton(self.body, text="Запускать вместе с Windows (рекомендуем)", variable=self.v_auto).pack(anchor="w")
            self.pair_msg = tk.Label(self.body, text=message, fg=BAD, bg=BG, wraplength=500, justify="left")
            self.pair_msg.pack(anchor="w", pady=8)
            self.pair_btn = ttk.Button(self.body, text="Подключить", style="Accent.TButton", command=self.pair)
            self.pair_btn.pack(anchor="w")
            tk.Label(self.body, text=f"Версия {VERSION}", bg=BG, fg=MUTED).pack(side="bottom", anchor="w")

        def pair(self, pin: str | None = None) -> None:
            code = self.v_code.get().strip().replace(" ", "")
            if not (code.isdigit() and len(code) == 6):
                self.pair_msg.config(text="Введите 6 цифр кода из панели", fg=BAD)
                return
            server = self.v_server.get().strip().rstrip("/")
            self.pair_btn.state(["disabled"])
            self.pair_msg.config(text="Подключаемся…", fg=MUTED)

            def work():
                try:
                    resp = Api(server, pin=pin).request("POST", "/agent/v1/pair", {
                        "code": code, "name": self.v_name.get().strip(), "version": VERSION,
                        "status": {"printers": collect_printers(), "default_printer": printing.default_printer(),
                                   "computer": socket.gethostname(), "dry_run": DRY_RUN}})
                    core.events.put(("paired", server, pin, resp))
                except UntrustedCert as e:
                    core.events.put(("untrusted", e.fingerprint))
                except ApiError as e:
                    core.events.put(("pair_error", str(e)))
                except Exception as e:  # noqa: BLE001
                    core.events.put(("pair_error", f"Не удалось связаться с сервером: {e}"))
            threading.Thread(target=work, daemon=True).start()

        # --- главный экран ---

        def show_main(self) -> None:
            self.clear()
            head = tk.Frame(self.body, bg=BG)
            head.pack(fill="x")
            self.l_title = ttk.Label(head, text=core.conf.get("name", APP_NAME), style="H.TLabel")
            self.l_title.pack(side="left")
            self.l_conn = tk.Label(head, text="● подключаемся…", bg=BG, fg=MUTED, font=("Segoe UI Semibold", 10))
            self.l_conn.pack(side="right")
            ttk.Label(self.body, style="MB.TLabel", wraplength=520, justify="left",
                      text="Печать запускается из панели заказов. Здесь можно ничего не трогать — "
                           "не закрывайте программу и следите за бумагой в принтере.").pack(anchor="w", pady=(2, 12))
            c = self.card()
            ttk.Label(c, text="Сейчас", style="T.TLabel").pack(anchor="w")
            self.l_now = ttk.Label(c, text="Ждём задания", style="C.TLabel", wraplength=480, justify="left")
            self.l_now.pack(anchor="w", pady=(4, 0))
            c = self.card()
            ttk.Label(c, text="Профили печати", style="T.TLabel").pack(anchor="w")
            ttk.Label(c, style="M.TLabel", wraplength=480, justify="left",
                      text="Какой принтер и с какими настройками драйвера печатает каждый материал. «Настроить» откроет "
                           "окно драйвера: выберите тип бумаги и качество — дальше печать пойдёт с ними.").pack(anchor="w", pady=(2, 6))
            self.f_profiles = tk.Frame(c, bg=CARD)
            self.f_profiles.pack(fill="x")
            c = self.card()
            ttk.Label(c, text="Последние задания", style="T.TLabel").pack(anchor="w")
            self.l_hist = ttk.Label(c, text="Пока не было", style="M.TLabel", justify="left")
            self.l_hist.pack(anchor="w", pady=(4, 0))
            bottom = tk.Frame(self.body, bg=BG)
            bottom.pack(fill="x", side="bottom")
            self.v_auto = tk.BooleanVar(value=autostart_value() is not None)
            ttk.Checkbutton(bottom, text="Запускать вместе с Windows", variable=self.v_auto, command=self.toggle_auto).pack(side="left")
            ttk.Button(bottom, text="Выход", command=self.quit).pack(side="right")
            ttk.Button(bottom, text="Отключить компьютер", command=self.unpair).pack(side="right", padx=6)
            upd = tk.Frame(self.body, bg=BG)
            upd.pack(fill="x", side="bottom", pady=(0, 6))
            self.l_upd = tk.Label(upd, text="", bg=BG, fg=MUTED, justify="left", wraplength=380)
            self.l_upd.pack(side="left")
            if FROZEN:
                ttk.Button(upd, text="Проверить обновления",
                           command=lambda: core.updater.check_now("кнопка в программе")).pack(side="right")
            if DRY_RUN:
                tk.Label(self.body, text="Пробный режим: листы сохраняются в папку, бумага не тратится", fg=WARN, bg=BG).pack(side="bottom", anchor="w")
            self._profiles_sig = None
            self.refresh()

        def refresh(self) -> None:
            w = core.worker
            if not hasattr(self, "l_conn") or not self.l_conn.winfo_exists():
                return
            self.l_conn.config(text="● на связи" if w.connected else "● нет связи" if w.connected is False else "● подключаемся…",
                               fg=OK if w.connected else BAD if w.connected is False else MUTED)
            if w.name_on_server and w.name_on_server != core.conf.get("name"):
                core.conf["name"] = w.name_on_server
                save_json(CONFIG, core.conf)
                self.l_title.config(text=w.name_on_server)
            cur = w.current
            if cur:
                self.l_now.config(text=f"{cur['label']}\n{cur['state']} · принтер «{cur['printer']}»", foreground=INK)
            elif w.connected is False:
                self.l_now.config(text=f"Нет связи с сервером. Повторяем автоматически.\n{w.last_error}", foreground=BAD)
            else:
                self.l_now.config(text="Ждём задания из панели заказов", foreground=INK)
            if w.history:
                self.l_hist.config(text="\n".join(f"{t}  {label} — {res}" for t, label, res in list(w.history)[:8]))
            self.l_upd.config(text=f"Версия {VERSION} · {core.updater.state_text()}")
            sig = json.dumps([(p["key"], p["printer"], p["summary"]) for p in w.profiles] +
                             [(p["name"], p["ok"], p["problems"]) for p in w.printers], ensure_ascii=False)
            if sig == self._profiles_sig:
                return
            self._profiles_sig = sig
            for x in self.f_profiles.winfo_children():
                x.destroy()
            if not w.profiles:
                ttk.Label(self.f_profiles, style="M.TLabel", wraplength=480, justify="left",
                          text="Этому компьютеру пока не назначены профили. Назначьте их в панели: «Принтеры».").pack(anchor="w")
            for p in w.profiles:
                row = tk.Frame(self.f_profiles, bg=CARD)
                row.pack(fill="x", pady=4)
                info = next((x for x in w.printers if x["name"] == p["printer"]), None)
                state = "принтер не найден" if not info else ("готов" if info["ok"] else "; ".join(info["problems"]) or "есть проблемы")
                text = tk.Frame(row, bg=CARD)
                text.pack(side="left", fill="x", expand=True)
                tk.Label(text, text=p["title"], bg=CARD, fg=INK, font=("Segoe UI Semibold", 10)).pack(anchor="w")
                tk.Label(text, text=f"{p['printer']} — {state}", bg=CARD, fg=OK if info and info["ok"] else BAD).pack(anchor="w")
                tk.Label(text, text=p["summary"] or "настройки принтера по умолчанию", bg=CARD, fg=MUTED,
                         wraplength=330, justify="left").pack(anchor="w")
                ttk.Button(row, text="Настроить…", command=lambda prof=p: self.tune(prof)).pack(side="right")

        def tune(self, prof: dict) -> None:
            """Окно драйвера для профиля; результат сохраняем на сервер."""
            try:
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                d = printing.edit_devmode(prof["printer"], prof.get("devmode"), hwnd)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror(APP_NAME, f"Не удалось открыть настройки принтера: {e}")
                return
            if d is None:
                return
            summary = printing.devmode_summary(d)

            def send():
                try:
                    core.worker.api().request("POST", f"/agent/v1/profiles/{prof['key']}", {"devmode": d, "summary": summary})
                    prof["devmode"], prof["summary"] = d, summary
                    core.events.put(("info", f"Профиль «{prof['title']}» сохранён: {summary}"))
                except Exception as e:  # noqa: BLE001
                    core.events.put(("error", f"Не удалось сохранить профиль: {e}"))
            threading.Thread(target=send, daemon=True).start()

        def toggle_auto(self) -> None:
            try:
                set_autostart(self.v_auto.get())
            except Exception as e:  # noqa: BLE001
                messagebox.showerror(APP_NAME, f"Не удалось изменить автозапуск: {e}")

        def unpair(self) -> None:
            if not messagebox.askyesno(APP_NAME, "Отключить этот компьютер? Печать на нём остановится, "
                                                  "чтобы вернуть — понадобится новый код из панели."):
                return
            core.conf.pop("token", None)
            core.conf.pop("pin", None)
            save_json(CONFIG, core.conf)
            self.show_pair()

        def on_close(self) -> None:
            if messagebox.askyesno(APP_NAME, "Свернуть программу?\n\nЕсли её закрыть, заказы перестанут печататься. "
                                             "«Да» — свернуть, «Нет» — закрыть совсем."):
                self.root.iconify()
            else:
                self.quit()

        def quit(self) -> None:
            core.request_exit(0)

        def pump(self) -> None:
            try:
                while True:
                    ev = core.events.get_nowait()
                    if ev == "exit":
                        self.root.destroy()
                        return
                    if ev == "refresh":
                        self.refresh()
                    elif ev == "unpaired":
                        self.show_pair("Компьютер отключён в панели. Чтобы печатать снова, введите новый код.")
                    elif ev[0] == "paired":
                        _, server, pin, resp = ev
                        core.conf.update(server=server, pin=pin, token=resp["token"], name=resp["name"], agent_id=resp["agent_id"])
                        save_json(CONFIG, core.conf)
                        if self.v_auto.get():
                            try:
                                set_autostart(True)
                            except Exception as e:  # noqa: BLE001
                                log.warning("Автозапуск: %s", e)
                        log.info("Подключено к %s как «%s»", server, resp["name"])
                        self.show_main()
                    elif ev[0] == "untrusted":
                        self.pair_btn.state(["!disabled"])
                        if messagebox.askyesno(APP_NAME, "У сервера самоподписанный сертификат — так бывает, когда сервер "
                                                         "работает по IP-адресу.\n\nОтпечаток сертификата:\n" + ev[1] +
                                                         "\n\nДоверять этому серверу? Отпечаток запомнится, и при его смене "
                                                         "программа перестанет подключаться."):
                            self.pair(pin=ev[1])
                        else:
                            self.pair_msg.config(text="Подключение отменено", fg=BAD)
                    elif ev[0] == "pair_error":
                        self.pair_btn.state(["!disabled"])
                        self.pair_msg.config(text=ev[1], fg=BAD)
                    elif ev[0] == "info":
                        messagebox.showinfo(APP_NAME, ev[1])
                    elif ev[0] == "error":
                        messagebox.showerror(APP_NAME, ev[1])
            except queue.Empty:
                pass
            self.root.after(400, self.pump)

    app = App()
    app.root.mainloop()
    return core.exit_code if core.exit_code is not None else 0


def run_headless(core: Core) -> int:
    while core.exit_code is None:
        time.sleep(0.5)
    return core.exit_code


# ---------- надсмотрщик ----------

def supervise(argv: list[str]) -> int:
    """Держит программу запущенной: перезапускает после сбоя, после обновления запускает новый exe."""
    if not single_instance("TyushaPrintSupervisor" + INSTANCE, wait=20 if "--after-upgrade" in argv else 0):
        return 0
    root = logging.getLogger()  # свой журнал, чтобы не делить файл с окном при ротации
    root.removeHandler(_handler)
    _handler.close()
    root.addHandler(logging.handlers.RotatingFileHandler(HOME / "supervisor.log", maxBytes=300_000, backupCount=1,
                                                         encoding="utf-8"))
    log.info("Надсмотрщик %s запущен", VERSION)
    extra = [a for a in argv if a in ("--headless",)]
    crashes: deque = deque(maxlen=10)
    while True:
        started = time.time()
        code = subprocess.call([sys.executable, "--child", *extra], env=fresh_env())
        if code == 0:
            return 0
        if code == EXIT_UPGRADE:
            log.info("Надсмотрщик: запускаем обновлённую программу")
            subprocess.Popen([sys.executable, "--after-upgrade", *extra], close_fds=True, env=fresh_env())
            return 0
        if code == EXIT_RESTART:
            continue
        crashes.append(time.time())
        recent = [t for t in crashes if time.time() - t < 600]
        pause = min(300, 5 * 2 ** max(0, len(recent) - 1)) if time.time() - started < 60 else 5
        log.error("Программа завершилась с кодом %s — перезапуск через %s с", code, pause)
        time.sleep(pause)


def child_main(argv: list[str]) -> int:
    if not single_instance("TyushaPrintAgent" + INSTANCE, wait=15):
        if "--headless" not in argv:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo(APP_NAME, "Программа уже запущена — посмотрите на панели задач.")
        return 0
    log.info("%s %s запущена%s%s", APP_NAME, VERSION, " (пробный режим)" if DRY_RUN else "",
             " без окна" if "--headless" in argv else "")
    core = Core()
    core.start()
    return run_headless(core) if "--headless" in argv else run_window(core)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selftest" in args:
        selftest()
        sys.exit(0)
    if FROZEN and "--child" not in args:
        sys.exit(supervise(args))
    sys.exit(child_main(args))
