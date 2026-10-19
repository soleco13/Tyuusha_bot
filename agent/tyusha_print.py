"""«Тюша Печать» — программа для компьютера, к которому подключён принтер.

Сервер с ботом и панелью стоит в интернете и до принтера не достаёт. Программа сама
обращается к серверу: забирает задания (листы + все настройки печати), печатает через
драйвер Windows в масштабе 1:1 и сообщает ход работы. Входящие подключения не нужны.

Оператору здесь делать нечего: печать запускается кнопкой в панели заказов.
Один раз при установке: ввести код из панели («Принтеры → Подключить компьютер»)
и при желании настроить профили печати в окне драйвера.

Запуск из исходников: run_agent.bat; сборка в один exe: build_agent.bat.
Проверка без бумаги: переменная окружения TYUSHA_DRY_RUN=1 — листы сохраняются в папку.
"""
from __future__ import annotations

import ctypes
import hashlib
import http.client
import json
import logging
import os
import queue
import shutil
import socket
import ssl
import sys
import threading
import time
import tkinter as tk
import urllib.parse
from collections import deque
from pathlib import Path
from tkinter import messagebox, ttk

if getattr(sys, "frozen", False):          # собранный exe
    BUNDLE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    BUNDLE = Path(__file__).resolve().parent
    sys.path.insert(0, str(BUNDLE.parent))   # printing.py лежит в папке бота
import printing  # noqa: E402

APP_NAME = "Тюша Печать"
VERSION = "1.0.0"
DEFAULT_SERVER = "https://213.21.241.28"
POLL_WAIT = 15                        # сервер держит запрос до 15 с, пока не появится задание
DRY_RUN = os.getenv("TYUSHA_DRY_RUN") == "1"

HOME = Path(os.getenv("APPDATA") or Path.home()) / "TyushaPrint"
HOME.mkdir(parents=True, exist_ok=True)
CONFIG = HOME / "config.json"
JOURNAL = HOME / "journal.json"
CACHE = HOME / "cache"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(HOME / "agent.log", encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger("tyusha")

BLUE, INK, MUTED, BG, CARD, OK, BAD, WARN = "#2563EB", "#172033", "#6A7389", "#F5F7FB", "#FFFFFF", "#0E8F64", "#CF2F48", "#A86300"


# ---------- настройки и журнал ----------

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(path)


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
        if self.pin:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        else:
            ctx = ssl.create_default_context()
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


# ---------- состояние компьютера ----------

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


def set_autostart(enabled: bool) -> None:
    import winreg
    cmd = f'"{sys.executable}"' if getattr(sys, "frozen", False) else \
        f'"{Path(sys.executable).with_name("pythonw.exe")}" "{Path(__file__).resolve()}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                        winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, "TyushaPrint", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "TyushaPrint")
            except FileNotFoundError:
                pass


def autostart_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            winreg.QueryValueEx(key, "TyushaPrint")
            return True
    except OSError:
        return False


def keep_awake() -> None:
    """Пока программа работает, компьютер не уходит в сон (экран гаснуть может)."""
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except Exception:
        pass


# ---------- работа с заданиями ----------

class Worker(threading.Thread):
    """Фоновый поток: опрос сервера, печать, слежение за очередью Windows."""

    def __init__(self, app: "App"):
        super().__init__(daemon=True)
        self.app = app
        self.journal = Journal()
        self.stop = threading.Event()
        self.connected: bool | None = None
        self.last_error = ""
        self.current: dict | None = None      # {"id", "label", "state", "win_job", "printer", "cancel"}
        self.history: deque = deque(maxlen=30)
        self.profiles: list[dict] = []
        self.printers: list[dict] = []
        self.name = ""

    def api(self) -> Api:
        c = self.app.conf
        return Api(c["server"], c.get("token"), c.get("pin"))

    def status(self) -> dict:
        self.printers = collect_printers()
        cur = self.current
        return {"printers": self.printers, "default_printer": printing.default_printer(), "dry_run": DRY_RUN,
                "computer": socket.gethostname(),
                "current": {"label": cur["label"], "state": cur["state"]} if cur else None}

    def run(self) -> None:
        backoff = 2
        while not self.stop.is_set():
            if not self.app.conf.get("token"):
                time.sleep(1)
                continue
            busy = self.current is not None
            try:
                resp = self.api().request("POST", "/agent/v1/poll", {
                    "status": self.status(), "version": VERSION, "wait": not busy,
                    "active_job": self.current["id"] if busy else None}, timeout=POLL_WAIT + 20)
                if self.connected is not True:
                    log.info("Связь с сервером есть")
                self.connected, self.last_error, backoff = True, "", 2
                self.name = resp.get("name", "")
                self.profiles = resp.get("profiles", [])
                for c in resp.get("cancel", []):
                    self.cancel(c)
                if resp.get("job") and self.current is None:
                    job = resp["job"]
                    self.current = {"id": job["id"], "label": job["label"], "state": "Получено задание",
                                    "win_job": None, "printer": job["settings"]["printer"], "cancel": False}
                    threading.Thread(target=self.run_job, args=(job,), daemon=True).start()
                self.app.events.put("refresh")
                if busy:
                    self.stop.wait(3)
            except ApiError as e:
                self.connected, self.last_error = False, str(e)
                log.warning("Сервер: %s", e)
                if e.status == 401:  # компьютер отключили в панели
                    self.app.events.put("unpaired")
                    self.app.conf.pop("token", None)
                    save_json(CONFIG, self.app.conf)
                self.app.events.put("refresh")
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 30)
            except Exception as e:  # noqa: BLE001
                if self.connected is not False:
                    log.warning("Нет связи с сервером: %s", e)
                self.connected, self.last_error = False, f"Нет связи с сервером: {e}"
                self.app.events.put("refresh")
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 30)

    def report(self, job_id: int, state: str, detail: str = "", problem: bool = False, win_job: int | None = None) -> None:
        body = {"state": state, "detail": detail, "problem": problem}
        if win_job is not None:
            body["win_job"] = win_job
        for attempt in range(8):  # сеть может моргнуть — повторяем до ~2 минут
            try:
                self.api().request("POST", f"/agent/v1/jobs/{job_id}/report", body)
                return
            except ApiError as e:
                if e.status in (401, 404):
                    return
                time.sleep(min(2 ** attempt, 30))
            except Exception:
                time.sleep(min(2 ** attempt, 30))
        log.error("Не удалось сообщить серверу о задании %s (%s)", job_id, state)

    def finish(self, label: str, result: str) -> None:
        self.history.appendleft((time.strftime("%H:%M"), label, result))
        self.current = None
        self.app.events.put("refresh")

    def run_job(self, job: dict) -> None:
        cur = self.current
        s = job["settings"]
        seen = self.journal.get(job["id"])
        if seen:  # уже отправляли на принтер — второй раз не печатаем
            self.report(job["id"], "done", "Уже было отправлено на принтер этим компьютером")
            return self.finish(job["label"], "уже было напечатано")
        tmp = CACHE / f"job_{job['id']}"
        try:
            tmp.mkdir(parents=True, exist_ok=True)
            pages = []
            for n in range(job["pages"]):
                cur["state"] = f"Загружаем листы: {n + 1} из {job['pages']}"
                self.app.events.put("refresh")
                path = tmp / f"page_{n + 1:02d}.png"
                path.write_bytes(self.api().request("GET", f"/agent/v1/jobs/{job['id']}/pages/{n}", raw=True, timeout=120))
                pages.append(path)
            if cur["cancel"]:
                self.report(job["id"], "cancelled", "Снято до печати")
                return self.finish(job["label"], "снято")
            cur["state"] = "Отправляем на принтер"
            self.app.events.put("refresh")
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
        last = None
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
                last = (text, st["problem"])
                cur["state"] = ("⚠ " if st["problem"] else "") + text
                self.report(job["id"], "printing", text, problem=st["problem"], win_job=cur["win_job"])
                self.app.events.put("refresh")
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


# ---------- окно программы ----------

class App:
    def __init__(self):
        self.conf: dict = load_json(CONFIG, {})
        self.events: queue.Queue = queue.Queue()
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("560x640")
        self.root.minsize(480, 520)
        self.root.configure(bg=BG)
        icon = BUNDLE / "assets" / "icon.png"
        if icon.exists():
            self._icon = tk.PhotoImage(file=str(icon))
            self.root.iconphoto(True, self._icon)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.style()
        self.worker = Worker(self)
        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(fill="both", expand=True, padx=18, pady=16)
        self.show_main() if self.conf.get("token") else self.show_pair()
        self.worker.start()
        keep_awake()
        self.root.after(400, self.pump)

    def style(self) -> None:
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=INK, font=("Segoe UI", 10))
        s.configure("Card.TFrame", background=CARD)
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
        s.configure("TEntry", padding=6)

    def clear(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()

    def card(self, parent=None, **pack) -> tk.Frame:
        f = tk.Frame(parent or self.body, bg=CARD, highlightthickness=1, highlightbackground="#E3E6EE", bd=0)
        f.pack(fill="x", pady=(0, 12), **pack)
        inner = tk.Frame(f, bg=CARD)
        inner.pack(fill="both", expand=True, padx=14, pady=12)
        return inner

    # --- подключение ---

    def show_pair(self, message: str = "") -> None:
        self.clear()
        ttk.Label(self.body, text="Подключение к Тюше", style="H.TLabel").pack(anchor="w")
        ttk.Label(self.body, style="MB.TLabel", wraplength=500, justify="left",
                  text="Откройте панель заказов → «Принтеры» → «Подключить компьютер» и введите код, который там появится. "
                       "Это нужно сделать один раз.").pack(anchor="w", pady=(4, 14))
        c = self.card()
        self.v_server = tk.StringVar(value=self.conf.get("server", DEFAULT_SERVER))
        self.v_code = tk.StringVar()
        self.v_name = tk.StringVar(value=self.conf.get("name") or socket.gethostname())
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
                api = Api(server, pin=pin)
                resp = api.request("POST", "/agent/v1/pair", {
                    "code": code, "name": self.v_name.get().strip(), "version": VERSION,
                    "status": {"printers": collect_printers(), "default_printer": printing.default_printer(),
                               "computer": socket.gethostname(), "dry_run": DRY_RUN}})
                self.events.put(("paired", server, pin, resp))
            except UntrustedCert as e:
                self.events.put(("untrusted", e.fingerprint))
            except ApiError as e:
                self.events.put(("pair_error", str(e)))
            except Exception as e:  # noqa: BLE001
                self.events.put(("pair_error", f"Не удалось связаться с сервером: {e}"))
        threading.Thread(target=work, daemon=True).start()

    # --- главный экран ---

    def show_main(self) -> None:
        self.clear()
        head = tk.Frame(self.body, bg=BG)
        head.pack(fill="x")
        self.l_title = ttk.Label(head, text=self.conf.get("name", APP_NAME), style="H.TLabel")
        self.l_title.pack(side="left")
        self.l_conn = tk.Label(head, text="● подключаемся…", bg=BG, fg=MUTED, font=("Segoe UI Semibold", 10))
        self.l_conn.pack(side="right")
        ttk.Label(self.body, style="MB.TLabel", wraplength=520, justify="left",
                  text="Печать запускается из панели заказов. Здесь можно ничего не трогать — "
                       "просто не закрывайте программу и следите за бумагой в принтере.").pack(anchor="w", pady=(2, 12))

        c = self.card()
        ttk.Label(c, text="Сейчас", style="T.TLabel").pack(anchor="w")
        self.l_now = ttk.Label(c, text="Ждём задания", style="C.TLabel", wraplength=480, justify="left")
        self.l_now.pack(anchor="w", pady=(4, 0))

        c = self.card()
        top = tk.Frame(c, bg=CARD)
        top.pack(fill="x")
        ttk.Label(top, text="Профили печати", style="T.TLabel").pack(side="left")
        ttk.Label(c, style="M.TLabel", wraplength=480, justify="left",
                  text="Какой принтер и с какими настройками драйвера печатает каждый материал. "
                       "«Настроить» откроет окно драйвера: выберите тип бумаги и качество — дальше печать пойдёт с ними.").pack(anchor="w", pady=(2, 6))
        self.f_profiles = tk.Frame(c, bg=CARD)
        self.f_profiles.pack(fill="x")

        c = self.card()
        ttk.Label(c, text="Последние задания", style="T.TLabel").pack(anchor="w")
        self.l_hist = ttk.Label(c, text="Пока не было", style="M.TLabel", justify="left")
        self.l_hist.pack(anchor="w", pady=(4, 0))

        bottom = tk.Frame(self.body, bg=BG)
        bottom.pack(fill="x", side="bottom")
        self.v_auto = tk.BooleanVar(value=autostart_enabled())
        ttk.Checkbutton(bottom, text="Запускать вместе с Windows", variable=self.v_auto, command=self.toggle_auto).pack(side="left")
        ttk.Button(bottom, text="Выход", command=self.quit).pack(side="right")
        ttk.Button(bottom, text="Отключить компьютер", command=self.unpair).pack(side="right", padx=6)
        if DRY_RUN:
            tk.Label(self.body, text="Пробный режим: листы сохраняются в папку, бумага не тратится", fg=WARN, bg=BG).pack(side="bottom", anchor="w")
        self._profiles_sig = None
        self.refresh()

    def refresh(self) -> None:
        w = self.worker
        if not hasattr(self, "l_conn") or not self.l_conn.winfo_exists():
            return
        if w.connected:
            self.l_conn.config(text="● на связи", fg=OK)
        elif w.connected is False:
            self.l_conn.config(text="● нет связи", fg=BAD)
        if w.name and w.name != self.conf.get("name"):
            self.conf["name"] = w.name
            save_json(CONFIG, self.conf)
            self.l_title.config(text=w.name)
        cur = w.current
        if cur:
            self.l_now.config(text=f"{cur['label']}\n{cur['state']} · принтер «{cur['printer']}»", foreground=INK)
        elif w.connected is False:
            self.l_now.config(text=f"Нет связи с сервером. Повторяем автоматически.\n{w.last_error}", foreground=BAD)
        else:
            self.l_now.config(text="Ждём задания из панели заказов", foreground=INK)
        if w.history:
            self.l_hist.config(text="\n".join(f"{t}  {label} — {res}" for t, label, res in list(w.history)[:8]))
        sig = json.dumps([(p["key"], p["printer"], p["summary"]) for p in w.profiles] +
                         [(p["name"], p["ok"], p["problems"]) for p in w.printers], ensure_ascii=False)
        if sig != self._profiles_sig:
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
                color = BAD if not info or not info["ok"] else OK
                text = tk.Frame(row, bg=CARD)
                text.pack(side="left", fill="x", expand=True)
                tk.Label(text, text=p["title"], bg=CARD, fg=INK, font=("Segoe UI Semibold", 10)).pack(anchor="w")
                tk.Label(text, text=f"{p['printer']} — {state}", bg=CARD, fg=color).pack(anchor="w")
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
                self.worker.api().request("POST", f"/agent/v1/profiles/{prof['key']}", {"devmode": d, "summary": summary})
                prof["devmode"], prof["summary"] = d, summary
                self.events.put(("info", f"Профиль «{prof['title']}» сохранён: {summary}"))
            except Exception as e:  # noqa: BLE001
                self.events.put(("error", f"Не удалось сохранить профиль: {e}"))
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
        self.conf.pop("token", None)
        self.conf.pop("pin", None)
        save_json(CONFIG, self.conf)
        self.show_pair()

    def on_close(self) -> None:
        if messagebox.askyesno(APP_NAME, "Свернуть программу?\n\nЕсли её закрыть, заказы перестанут печататься. "
                                         "«Да» — свернуть, «Нет» — закрыть совсем."):
            self.root.iconify()
        else:
            self.quit()

    def quit(self) -> None:
        self.worker.stop.set()
        self.root.destroy()

    # --- события из фоновых потоков ---

    def pump(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                if ev == "refresh":
                    self.refresh()
                elif ev == "unpaired":
                    self.show_pair("Компьютер отключён в панели. Чтобы печатать снова, введите новый код.")
                elif ev[0] == "paired":
                    _, server, pin, resp = ev
                    self.conf.update(server=server, pin=pin, token=resp["token"], name=resp["name"], agent_id=resp["agent_id"])
                    save_json(CONFIG, self.conf)
                    if self.v_auto.get():
                        try:
                            set_autostart(True)
                        except Exception as e:  # noqa: BLE001
                            log.warning("Автозапуск: %s", e)
                    log.info("Подключено к %s как «%s»", server, resp["name"])
                    self.show_main()
                elif ev[0] == "untrusted":
                    fp = ev[1]
                    self.pair_btn.state(["!disabled"])
                    if messagebox.askyesno(APP_NAME, "У сервера самоподписанный сертификат — так бывает, когда сервер "
                                                     "работает по IP-адресу.\n\nОтпечаток сертификата:\n" + fp +
                                                     "\n\nДоверять этому серверу? Отпечаток запомнится, и при его смене "
                                                     "программа перестанет подключаться."):
                        self.pair(pin=fp)
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

    def run(self) -> None:
        self.root.mainloop()


def single_instance() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, "TyushaPrintAgent")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def selftest() -> None:
    """Проверка сборки без окна: модули грузятся, принтеры видны. Результат — в selftest.json."""
    result = {"version": VERSION, "frozen": bool(getattr(sys, "frozen", False)),
              "icon": (BUNDLE / "assets" / "icon.png").exists()}
    try:
        result["default_printer"] = printing.default_printer()
        result["printers"] = [{"name": p["name"], "ok": p["ok"]} for p in collect_printers()]
        if result["default_printer"]:
            result["devmode_fields"] = len(printing.devmode_to_dict(printing._default_devmode(result["default_printer"])))
        result["ok"] = True
    except Exception as e:  # noqa: BLE001
        result.update(ok=False, error=repr(e))
    save_json(HOME / "selftest.json", result)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if not single_instance():
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo(APP_NAME, "Программа уже запущена — посмотрите на панели задач.")
        sys.exit(0)
    log.info("%s %s запущена%s", APP_NAME, VERSION, " (пробный режим)" if DRY_RUN else "")
    App().run()
