"use strict";
/* Админка Тюши: список заказов, карточка заказа, действия, цены, состояние принтера. */

const POLL_MS = 4000;
const $app = document.getElementById("app");

const state = {
  view: "orders",          // orders | prices
  group: "work",
  q: "",
  summary: null,
  orders: [],
  openId: null,
  detail: null,
  lastSync: 0,
  online: true,
  knownIds: new Set(),
  firstLoad: true,
  printerOpen: false,
  sound: localStore("sound") === "1",
};

// ---------- утилиты ----------

function localStore(key, value) {
  try {
    if (value === undefined) return localStorage.getItem("tyusha." + key);
    localStorage.setItem("tyusha." + key, value);
  } catch (e) { return null; }
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

function parseTime(s) { return s ? new Date(s.replace(" ", "T")) : null; }

function ago(s) {
  const d = parseTime(s);
  if (!d) return "";
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 45) return "только что";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} мин назад`;
  const h = Math.round(min / 60);
  if (h < 24 && d.getDate() === new Date().getDate()) return `${h} ч назад`;
  return d.toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function fullTime(s) {
  const d = parseTime(s);
  return d ? d.toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) : "—";
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch (e) {
    throw new Error("Нет связи с ботом. Проверьте, что он запущен.");
  }
  if (res.status === 401 && path !== "/api/login") {
    renderLogin();
    throw new Error("Нужно войти заново");
  }
  let data = {};
  try { data = await res.json(); } catch (e) { /* пустой ответ */ }
  if (!res.ok || data.ok === false) throw new Error(data.error || `Ошибка сервера (${res.status})`);
  return data;
}

function toast(text, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = text;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "error" ? 7000 : 3500);
}

/** Кнопка в состоянии «работаю»: блокируется, крутится спиннер, текст меняется. */
async function withLoading(btn, text, fn) {
  const old = btn ? btn.innerHTML : "";
  if (btn) { btn.classList.add("loading"); btn.disabled = true; if (text) btn.textContent = text; }
  try { return await fn(); }
  finally { if (btn && btn.isConnected) { btn.classList.remove("loading"); btn.disabled = false; btn.innerHTML = old; } }
}

function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    o.frequency.value = 880; g.gain.value = 0.08;
    o.start(); o.frequency.setValueAtTime(1175, ctx.currentTime + 0.12);
    o.stop(ctx.currentTime + 0.25);
  } catch (e) { /* звук недоступен */ }
}

// ---------- вход ----------

function renderLogin(message = "") {
  stopPolling();
  $app.innerHTML = `
    <div class="login">
      <form id="login-form">
        <img src="/static/tyusha.png" alt="">
        <h1>Тюша · Заказы</h1>
        <div class="muted">Панель оператора</div>
        <input class="input" id="password" type="password" placeholder="Пароль" autocomplete="current-password" autofocus>
        <button class="btn primary" type="submit">Войти</button>
        <div class="error" id="login-error">${esc(message)}</div>
      </form>
    </div>`;
  document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button");
    const err = document.getElementById("login-error");
    err.textContent = "";
    await withLoading(btn, "Проверяем…", async () => {
      try {
        await api("/api/login", { method: "POST", body: { password: document.getElementById("password").value } });
        renderShell();
      } catch (ex) { err.textContent = ex.message; }
    });
  });
}

// ---------- каркас ----------

function renderShell() {
  $app.innerHTML = `
    <div id="offline" class="offline hidden">Нет связи с ботом — данные могут быть устаревшими. Пробуем переподключиться…</div>
    <header class="topbar">
      <div class="brand"><img src="/static/tyusha.png" alt="">Тюша</div>
      <nav class="nav">
        <button data-view="orders">Заказы</button>
        <button data-view="prices">Цены</button>
        <button data-view="stock">Склад<span class="nav-badge hidden" id="stock-badge"></span></button>
        <button data-view="stats">Статистика</button>
        <button data-view="printers">Принтеры</button>
      </nav>
      <div class="spacer"></div>
      <button class="chip" id="printer-chip" title="Состояние принтера и очередь"><span class="dot"></span><span>Принтер…</span></button>
      <button class="chip" id="sound-chip" title="Звук при новом заказе"></button>
      <button class="btn ghost sm" id="logout">Выйти</button>
    </header>
    <div id="printer-pop" class="popover hidden"></div>
    <main class="page" id="page"></main>`;
  $app.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));
  document.getElementById("logout").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST" }).catch(() => {});
    renderLogin();
  });
  document.getElementById("printer-chip").addEventListener("click", () => {
    state.printerOpen = !state.printerOpen;
    renderPrinter();
  });
  document.getElementById("sound-chip").addEventListener("click", () => {
    state.sound = !state.sound;
    localStore("sound", state.sound ? "1" : "0");
    renderSoundChip();
    if (state.sound) beep();
  });
  renderSoundChip();
  applyHash();
  startPolling();
}

function renderSoundChip() {
  const el = document.getElementById("sound-chip");
  if (el) el.innerHTML = state.sound ? '🔔<span class="label"> Звук вкл.</span>' : '🔕<span class="label"> Звук выкл.</span>';
}

function go(view) {
  state.view = view;
  location.hash = view !== "orders" ? view : (state.openId ? `order=${state.openId}` : "");
  renderPage();
}

const VIEWS = ["prices", "printers", "stock", "stats"];

function applyHash() {
  const h = location.hash.slice(1);
  const m = h.match(/order=(\d+)/);
  state.view = VIEWS.includes(h) ? h : "orders";
  renderPage();
  if (m) openOrder(Number(m[1]));
}
window.addEventListener("hashchange", () => {
  const view = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "orders";
  if (view !== state.view && document.getElementById("page")) { state.view = view; renderPage(); }
  const m = location.hash.match(/order=(\d+)/);
  if (m && Number(m[1]) !== state.openId) openOrder(Number(m[1]));
});

function renderPage() {
  $app.querySelectorAll("[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === state.view));
  stopPrintersTimer();
  if (state.view === "prices") return renderPrices();
  if (state.view === "printers") return renderPrinters();
  if (state.view === "stock") return renderStock();
  if (state.view === "stats") return renderStats();
  const page = document.getElementById("page");
  page.innerHTML = `
    <section id="stock-warn"></section>
    <section class="stats" id="stats"></section>
    <div class="toolbar">
      <div class="tabs" id="tabs"></div>
      <input class="search" id="search" type="search" placeholder="Поиск: №, имя или @ник" value="${esc(state.q)}">
      <div class="sync" id="sync"></div>
    </div>
    <section class="list" id="list"><div class="empty">Загружаем заказы…</div></section>`;
  let t;
  document.getElementById("search").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => { state.q = e.target.value; refresh(); }, 250);
  });
  renderSummary();
  renderList();
  refresh();
}

// ---------- обновление данных ----------

let pollTimer = null;
setInterval(renderSync, 1000);
function startPolling() { stopPolling(); pollTimer = setInterval(refresh, POLL_MS); }
function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null; }

let refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const [summary, list] = await Promise.all([
      api("/api/summary"),
      state.view === "orders" ? api(`/api/orders?group=${state.group}&q=${encodeURIComponent(state.q)}`) : null,
    ]);
    state.summary = summary;
    if (list) {
      detectNew(list.orders);
      state.orders = list.orders;
    }
    if (state.openId && !document.querySelector(".modal-wrap")) {
      const d = await api(`/api/orders/${state.openId}`).catch(() => null);
      if (d && state.openId === d.order.id) { state.detail = d.order; renderDrawer(false); }
    }
    state.online = true;
    state.lastSync = Date.now();
  } catch (e) {
    state.online = false;
  } finally {
    refreshing = false;
  }
  document.getElementById("offline")?.classList.toggle("hidden", state.online);
  renderStockWarn();
  renderSummary();
  renderList();
  renderPrinter();
  renderSync();
}

function detectNew(orders) {
  const fresh = orders.filter((o) => o.status === "new" && !state.knownIds.has(o.id));
  orders.forEach((o) => state.knownIds.add(o.id));
  if (state.firstLoad) { state.firstLoad = false; return; }
  fresh.forEach((o) => { o._fresh = true; toast(`🆕 Новый заказ №${o.id} — ${o.amount_text}`, "ok"); });
  if (fresh.length && state.sound) beep();
}

function renderSync() {
  const el = document.getElementById("sync");
  if (!el) return;
  if (!state.online) { el.innerHTML = `<span class="dot bad"></span> нет связи`; return; }
  if (!state.lastSync) { el.textContent = "загрузка…"; return; }
  const s = Math.round((Date.now() - state.lastSync) / 1000);
  el.innerHTML = `<span class="dot ok"></span> обновлено ${s < 2 ? "только что" : s + " с назад"}`;
  const work = state.summary?.counts?.new || 0;
  document.title = (work ? `(${work}) ` : "") + "Тюша · Заказы";
}

function renderStockWarn() {
  const low = state.summary?.stock_low || [];
  const badge = document.getElementById("stock-badge");
  if (badge) { badge.textContent = low.length; badge.classList.toggle("hidden", !low.length); }
  const el = document.getElementById("stock-warn");
  if (!el) return;
  const out = low.filter((m) => m.state === "out");
  el.innerHTML = low.length ? `<a class="banner ${out.length ? "error" : "warn"}" href="#stock" style="margin-bottom:14px;text-decoration:none">⚠️
    <div>${out.length ? "Закончилось: " + out.map((m) => esc(m.title)).join(", ") : "Заканчивается: " + low.map((m) => `${esc(m.title)} (${m.stock} ${esc(m.unit)})`).join(", ")}
    <div class="small">${out.length ? "Клиенты не смогут заказать бумагу на этом материале." : "Пора пополнить склад."} Открыть склад →</div></div></a>` : "";
}

function renderSummary() {
  const el = document.getElementById("stats");
  const s = state.summary;
  if (!el || !s) return;
  const c = s.counts || {};
  const tiles = [
    ["work", c.new || 0, "Новых — ждут печати"],
    ["work", (c.printing || 0) + (c.fronts_printed || 0), "Печатаются / ждут рубашек"],
    ["ready", c.printed || 0, "Напечатаны — ждут выдачи"],
  ];
  el.innerHTML = tiles.map(([g, n, label]) =>
    `<button class="stat" data-group="${g}" title="Показать эти заказы"><div class="num">${n}</div><div class="lbl">${label}</div></button>`
  ).join("") + `<div class="stat static"><div class="num">${esc(s.today.amount)}</div><div class="lbl">Сегодня: ${s.today.orders} ${plural(s.today.orders, "заказ", "заказа", "заказов")}</div></div>`;
  el.querySelectorAll("[data-group]").forEach((b) => b.addEventListener("click", () => setGroup(b.dataset.group)));

  const tabs = document.getElementById("tabs");
  tabs.innerHTML = s.groups.map((g) =>
    `<button data-group="${g.key}" class="${state.group === g.key ? "active" : ""}">${esc(g.title)}<span class="count">${g.count}</span></button>`
  ).join("");
  tabs.querySelectorAll("[data-group]").forEach((b) => b.addEventListener("click", () => setGroup(b.dataset.group)));
}

function setGroup(g) {
  if (state.group === g) return;
  state.group = g;
  state.orders = [];
  document.getElementById("list").innerHTML = `<div class="empty">Загружаем…</div>`;
  renderSummary();
  refresh();
}

// ---------- список ----------

const QUICK = { new: "print", fronts_printed: "print_backs", printed: "issue" };

function badge(o) {
  if (o.last_error && o.status !== "cancelled") return `<span class="badge error" title="${esc(o.last_error)}">⚠️ ${esc(o.status_label)}</span>`;
  return `<span class="badge ${o.status}">${esc(o.status_label)}</span>`;
}

function renderList() {
  const el = document.getElementById("list");
  if (!el || state.view !== "orders") return;
  if (!state.lastSync && !state.orders.length) return;
  if (!state.orders.length) {
    const msg = state.q ? "Ничего не нашлось — попробуйте другой запрос" :
      ({ work: "Новых заказов нет — Тюша отдыхает 🐾", ready: "Нет заказов, ждущих выдачи", done: "Выданных заказов пока нет", cancelled: "Отменённых заказов нет" }[state.group] || "Заказов пока нет");
    el.innerHTML = `<div class="empty"><img src="/static/tyusha.png" alt=""><p>${msg}</p></div>`;
    return;
  }
  el.innerHTML = `
    <div class="row head"><div>№</div><div>Клиент</div><div>Заказ</div><div>Сумма</div><div>Статус</div><div>Создан</div><div></div></div>
    ${state.orders.map((o) => {
      const q = QUICK[o.status];
      return `<div class="row ${o.id === state.openId ? "selected" : ""} ${o._fresh ? "fresh" : ""}" data-id="${o.id}">
        <div class="id">№${o.id}</div>
        <div class="client"><b>${esc(o.user_name || "Без имени")}</b><span>${o.username ? "@" + esc(o.username) : "id " + o.user_id}</span></div>
        <div class="what">${esc(o.title)}</div>
        <div class="amount">${esc(o.amount_text)}</div>
        <div class="status">${badge(o)}</div>
        <div class="when" title="${esc(fullTime(o.created_at))}">${ago(o.created_at)}</div>
        <div class="quick">${q ? `<button class="btn sm ${q === "issue" ? "" : "primary"}" data-quick="${q}" data-id="${o.id}">${esc(ACTIONS[q].label)}</button>` : ""}</div>
      </div>`;
    }).join("")}`;
  el.querySelectorAll(".row[data-id]").forEach((r) => r.addEventListener("click", (e) => {
    if (e.target.closest("[data-quick]")) return;
    openOrder(Number(r.dataset.id));
  }));
  el.querySelectorAll("[data-quick]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    const o = state.orders.find((x) => x.id === Number(b.dataset.id));
    doAction(o, b.dataset.quick, b);
  }));
}

// ---------- действия ----------

/** Куда уйдёт задание при печати через компьютер с принтером. */
function routeNote(o) {
  if (state.summary?.print_mode !== "agent") return "";
  const prof = state.summary.profiles?.[o.profile || (["cards", "doc"].includes(o.kind) ? o.kind : "photo")];
  if (!prof?.agent || !prof?.printer) {
    return `<div class="banner error" style="margin-bottom:10px">⚠️ <div>Для этого материала не выбран принтер<div class="small">Откройте «Принтеры» и настройте профиль.</div></div></div>`;
  }
  if (!prof.ready) {
    return `<div class="banner warn" style="margin-bottom:10px">⚠️ <div>Компьютер «${esc(prof.agent)}» или принтер сейчас не готов<div class="small">Проверьте, что программа «Тюша Печать» запущена, а принтер включён. Иначе печать не начнётся.</div></div></div>`;
  }
  return `<div class="banner ok" style="margin-bottom:10px">🖨 <div>Печатает «${esc(prof.agent)}» → ${esc(prof.printer)}
    <div class="small">${prof.tuned ? "С настройками драйвера из профиля." : "Настройки драйвера по умолчанию — их можно задать в программе на компьютере."} Всё остальное выставится само.</div></div></div>`;
}

const CANCEL_PRESETS = ["Плохое качество фото", "Клиент попросил отменить", "Закончились материалы", "Принтер не работает"];

const ACTIONS = {
  print: {
    label: "🖨 Печать", style: "primary",
    confirm: (o) => {
      const p = o.params || {}, cardsDeck = o.duplex ?? o.kind === "cards";
      const sheets = p.sheets ?? "?";
      const paper = o.paper_title ? `«${esc(o.paper_title.toLowerCase())}»` : cardsDeck ? "плотной фотобумаги (200–300 г/м²)" : o.kind === "doc" ? "обычной офисной бумаги" : "бумаги для фото";
      return {
        title: `Печать заказа №${o.id}`,
        html: `${routeNote(o)}<p>Перед печатью подготовьте принтер:</p><ol>
          <li>Положите в лоток <b>${sheets} л. A4</b>: ${paper}.</li>
          <li>Проверьте, что принтер включён и чернил достаточно.</li>
          ${cardsDeck ? `<li>Сначала печатаются лицевые стороны, затем — ${o.kind === "craft" ? "обороты" : "рубашки"}.</li>` : ""}</ol>`,
        ok: "Принтер готов — печатать",
      };
    },
  },
  print_backs: {
    label: "🖨 Печать рубашек", style: "primary",
    confirm: (o) => ({
      title: `Рубашки для заказа №${o.id}`,
      html: `${routeNote(o)}<ol><li>Дайте чернилам высохнуть 1–2 минуты.</li>
        <li>Переверните стопку чистой стороной для печати, <b>первый лист сверху</b>, порядок не меняйте.</li>
        <li>Положите обратно в лоток.</li></ol>
        <p class="small">Совет: если печатаете впервые — проверьте ориентацию на одном листе.</p>`,
      ok: "Стопка перевёрнута — печатать",
    }),
  },
  reprint: {
    label: "↻ Напечатать заново", style: "",
    confirm: (o) => ({
      title: `Напечатать заказ №${o.id} заново?`,
      html: `<p>Будет израсходовано ещё ${o.params?.sheets ?? "несколько"} л. бумаги. Клиент уведомление не получит.</p>`,
      ok: "Напечатать заново",
    }),
  },
  printed_ok: { label: "✅ Напечатано", style: "primary" },
  cancel_job: {
    label: "⏹ Снять с принтера", style: "danger",
    confirm: (o) => ({
      title: "Снять задание с принтера?",
      html: "<p>Заказ вернётся в предыдущий статус. Уже напечатанные листы останутся.</p>",
      ok: "Снять задание", danger: true,
    }),
  },
  issue: {
    label: "✅ Выдан клиенту", style: "",
    confirm: (o) => ({
      title: `Заказ №${o.id} выдан?`,
      html: `<label class="check"><input type="checkbox" name="notify" checked> Написать клиенту «Заказ выдан, спасибо»</label>`,
      ok: "Да, выдан",
    }),
  },
  cancel: {
    label: "✖ Отменить заказ", style: "danger",
    confirm: (o) => ({
      title: `Отменить заказ №${o.id}?`,
      html: `<p>Клиент увидит причину в Telegram.</p>
        <div class="presets">${CANCEL_PRESETS.map((p) => `<button type="button" data-preset="${esc(p)}">${esc(p)}</button>`).join("")}</div>
        <textarea name="reason" rows="3" placeholder="Причина отмены (необязательно)"></textarea>
        <label class="check"><input type="checkbox" name="notify" checked> Уведомить клиента</label>`,
      ok: "Отменить заказ", danger: true, cancelText: "Не отменять",
    }),
  },
};

function confirmModal(cfg) {
  return new Promise((resolve) => {
    const wrap = document.createElement("div");
    wrap.className = "modal-wrap";
    wrap.innerHTML = `<form class="modal" role="dialog" aria-modal="true">
      <h3>${esc(cfg.title)}</h3>${cfg.html || ""}
      <div class="buttons">
        <button type="button" class="btn" data-close>${esc(cfg.cancelText || "Отмена")}</button>
        <button type="submit" class="btn ${cfg.danger ? "danger solid" : "primary"}">${esc(cfg.ok)}</button>
      </div></form>`;
    document.body.appendChild(wrap);
    const form = wrap.querySelector("form");
    const close = (val) => { wrap.remove(); document.removeEventListener("keydown", onKey); resolve(val); };
    const onKey = (e) => { if (e.key === "Escape") close(null); };
    document.addEventListener("keydown", onKey);
    wrap.addEventListener("click", (e) => { if (e.target === wrap) close(null); });
    wrap.querySelector("[data-close]").addEventListener("click", () => close(null));
    wrap.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => {
      form.reason.value = b.dataset.preset; form.reason.focus();
    }));
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const data = {};
      if (form.reason) data.reason = form.reason.value;
      if (form.notify) data.notify = form.notify.checked;
      close(data);
    });
    form.querySelector("button[type=submit]").focus();
  });
}

const PROGRESS = {
  print: "Отправляем…", print_backs: "Отправляем…", reprint: "Отправляем…",
  cancel_job: "Снимаем…", printed_ok: "Сохраняем…", issue: "Сохраняем…", cancel: "Отменяем…",
};

async function doAction(order, action, btn) {
  const def = ACTIONS[action];
  let body = {};
  if (def.confirm) {
    // для подтверждения нужны полные данные (листы и т. п.)
    const full = order.params ? order : (await api(`/api/orders/${order.id}`).catch(() => ({ order })) ).order;
    const res = await confirmModal(def.confirm(full));
    if (!res) return;
    body = res;
  }
  // Окно печати открываем сразу по клику (иначе браузер блокирует всплывающее окно), адрес — после ответа сервера
  const printAction = ["print", "print_backs", "reprint"].includes(action) && state.summary?.print_mode === "browser";
  const printWin = printAction ? window.open("about:blank", "_blank") : null;
  await withLoading(btn, PROGRESS[action], async () => {
    try {
      const r = await api(`/api/orders/${order.id}/actions/${action}`, { method: "POST", body });
      toast(r.message, "ok");
      if (printAction) {
        const url = `/print/${order.id}/${action === "print_backs" ? "back" : "front"}`;
        if (printWin) printWin.location = url;
        else {
          toast("Браузер заблокировал окно печати — откройте его кнопкой в карточке заказа", "warn");
          location.hash = `order=${order.id}`;
        }
      }
      if (state.openId === order.id) { state.detail = r.order; renderDrawer(false); }
    } catch (e) {
      printWin?.close();
      toast(e.message, "error");
    }
  });
  refresh();
}

// ---------- карточка заказа ----------

async function openOrder(id) {
  state.openId = id;
  if (state.view === "orders") history.replaceState(null, "", `#order=${id}`);
  state.detail = null;
  renderDrawer(true);
  try {
    state.detail = (await api(`/api/orders/${id}`)).order;
  } catch (e) {
    toast(e.message, "error");
    closeOrder();
    return;
  }
  renderDrawer(true);
  renderList();
}

function closeOrder() {
  state.openId = null;
  state.detail = null;
  document.querySelector(".drawer")?.remove();
  document.querySelector(".scrim")?.remove();
  history.replaceState(null, "", location.pathname);
  renderList();
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.querySelector(".modal-wrap") && !document.querySelector(".lightbox") && state.openId) closeOrder();
});

function statusBanner(o) {
  if (o.status === "printing" && state.summary?.print_mode === "browser") {
    return `<div class="banner info"><div>Печать из браузера<div class="small">Откройте окно печати, напечатайте листы и нажмите «Напечатано».</div>
      <div style="margin-top:8px"><a class="btn primary sm" href="/print/${o.id}/${o.print_part || "front"}" target="_blank" rel="noopener">🖨 Открыть окно печати</a></div></div></div>`;
  }
  if (o.status === "printing") {
    const problem = (o.print_state || "").startsWith("⚠️");
    return `<div class="banner ${problem ? "error" : "info"}">${problem ? "" : '<span class="spinner"></span>'}
      <div>${problem ? "Принтер сообщает о проблеме" : "Идёт печать"}<div class="small">${esc(o.print_state || "")}</div>
      ${problem ? '<div class="small">Устраните проблему — печать продолжится сама. Или снимите задание с принтера.</div>' : ""}</div></div>`;
  }
  if (o.last_error) return `<div class="banner error">⚠️ <div>${esc(o.last_error)}<div class="small">Исправьте причину и повторите действие.</div></div></div>`;
  const hints = {
    new: ["info", "Заказ ждёт печати. Подготовьте бумагу и нажмите «Печать»."],
    fronts_printed: ["warn", "Лицевые стороны готовы. Переверните стопку и напечатайте рубашки."],
    printed: ["ok", "Напечатан. Когда клиент заберёт заказ — отметьте «Выдан клиенту»."],
    issued: ["ok", "Заказ выдан клиенту."],
    cancelled: ["warn", "Заказ отменён" + (o.cancel_reason ? `: ${o.cancel_reason}` : ".")],
  }[o.status];
  return hints ? `<div class="banner ${hints[0]}">${esc(hints[1])}</div>` : "";
}

function renderDrawer(full) {
  let drawer = document.querySelector(".drawer");
  if (!state.openId) return;
  if (!drawer) {
    const scrim = document.createElement("div");
    scrim.className = "scrim";
    scrim.addEventListener("click", closeOrder);
    drawer = document.createElement("aside");
    drawer.className = "drawer";
    document.body.append(scrim, drawer);
    full = true;
  }
  const o = state.detail;
  if (!o) {
    drawer.innerHTML = `<header><h2>Заказ №${state.openId}</h2><div class="spacer" style="flex:1"></div>
      <button class="btn ghost" data-close aria-label="Закрыть">✕</button></header><div class="body"><div class="empty">Загружаем заказ…</div></div>`;
    drawer.querySelector("[data-close]").addEventListener("click", closeOrder);
    return;
  }
  if (full || !drawer.querySelector("[data-live]")) {
    drawer.innerHTML = `
      <header>
        <h2>Заказ №${o.id}</h2><span data-badge></span>
        <div style="flex:1"></div>
        <a class="btn sm" href="/api/orders/${o.id}/download" title="Скачать листы для печати">⬇ ZIP</a>
        <button class="btn ghost" data-close aria-label="Закрыть">✕</button>
      </header>
      <div class="body">
        <div data-live></div>
        <section class="card">
          <h3>Клиент</h3>
          <dl class="kv">
            <dt>Имя</dt><dd>${esc(o.user_name || "—")}</dd>
            <dt>Telegram</dt><dd>${o.username ? `<a href="https://t.me/${esc(o.username)}" target="_blank" rel="noopener">@${esc(o.username)}</a>` : "ника нет"} <span class="muted small">· id ${o.user_id}</span></dd>
          </dl>
          <div style="margin-top:12px">
            <textarea id="msg" rows="2" placeholder="Написать клиенту от имени бота…"></textarea>
            <div class="row-end"><span class="hint">Сообщение придёт в чат с ботом</span><button class="btn sm" id="send-msg">Отправить</button></div>
          </div>
        </section>
        <section class="card" id="stage-box">
          <h3>Этап заказа для клиента</h3>
          <div class="stage-row">
            <select class="input" name="stage">${Object.entries(o.stages || {}).map(([k, t]) => `<option value="${k}">${esc(t)}</option>`).join("")}</select>
            <label class="btn sm" style="position:relative;overflow:hidden">📷 Фото<input type="file" name="stage_photo" accept="image/*" style="position:absolute;inset:0;opacity:0"></label>
            <span class="hint" data-file-name>Фото не выбрано</span>
          </div>
          <textarea name="stage_text" rows="2" placeholder="Пара слов клиенту (необязательно): «Всё готово, забирайте после 18:00»"></textarea>
          <div class="row-end"><span class="hint">Клиент получит сообщение с фото готового заказа</span><button class="btn sm primary" id="send-stage">Отправить этап</button></div>
        </section>
        <section class="card">
          <h3>Состав заказа</h3>
          <dl class="kv" data-content></dl>
        </section>
        <section class="card">
          <h3>Листы для печати</h3>
          <div class="thumbs">${o.pages.map((p, i) => `<button class="thumb" data-img="pages" data-i="${i}"><img loading="lazy" src="${p.thumb}" alt=""><span>${esc(p.name)}</span></button>`).join("")}</div>
        </section>
        <section class="card">
          <h3>Фото клиента · ${o.sources.length}</h3>
          <div class="thumbs">${o.sources.map((p, i) => `<button class="thumb square" data-img="sources" data-i="${i}"><img loading="lazy" src="${p.thumb}" alt=""><span>${esc(p.name)}</span></button>`).join("")}</div>
        </section>
        <section class="card">
          <h3>Заметка оператора</h3>
          <textarea id="note" rows="2" placeholder="Видна только в панели">${esc(o.admin_note)}</textarea>
          <div class="row-end"><span id="note-state" class="hint">Сохраняется автоматически</span></div>
        </section>
        <section class="card"><h3>История</h3><ul class="timeline" data-events></ul></section>
      </div>`;
    drawer.querySelector("[data-close]").addEventListener("click", closeOrder);
    drawer.querySelectorAll("[data-img]").forEach((b) => b.addEventListener("click", () =>
      openLightbox(state.detail[b.dataset.img], Number(b.dataset.i))));
    const send = drawer.querySelector("#send-msg");
    send.addEventListener("click", () => sendMessage(send));
    const stageBtn = drawer.querySelector("#send-stage");
    stageBtn.addEventListener("click", () => sendStage(stageBtn));
    const stageFile = drawer.querySelector("[name=stage_photo]");
    stageFile.addEventListener("change", () => {
      drawer.querySelector("[data-file-name]").textContent = stageFile.files[0]?.name || "Фото не выбрано";
    });
    bindNote(drawer.querySelector("#note"));
  }
  // живые части — обновляются при каждом опросе, не трогая поля ввода
  drawer.querySelector("[data-badge]").innerHTML = badge(o);
  drawer.querySelector("[data-live]").innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px">
      ${statusBanner(o)}
      <div class="actions">${o.actions.length ? o.actions.map((a) =>
        `<button class="btn ${ACTIONS[a]?.style || ""}" data-action="${a}">${esc(a === "print_backs" && o.kind === "craft" ? "🖨 Печать оборотов" : ACTIONS[a]?.label || o.action_titles[a])}</button>`).join("")
        : '<span class="hint">Действий нет — заказ завершён.</span>'}</div>
    </div>`;
  drawer.querySelectorAll("[data-action]").forEach((b) => b.addEventListener("click", () => doAction(state.detail, b.dataset.action, b)));
  drawer.querySelector("[data-content]").innerHTML = `
    ${o.description.map((line) => { const [k, ...v] = line.replace(/^[🃏🖼]\s*/u, "").split(": "); return v.length ? `<dt>${esc(k)}</dt><dd>${esc(v.join(": "))}</dd>` : `<dt>Что</dt><dd>${esc(k)}</dd>`; }).join("")}
    <dt>Стоимость</dt><dd><b>${esc(o.amount_text)}</b> <span class="muted small">· оплата пока не подключена</span></dd>
    <dt>Создан</dt><dd>${esc(fullTime(o.created_at))}</dd>
    ${o.printed_at ? `<dt>Напечатан</dt><dd>${esc(fullTime(o.printed_at))}</dd>` : ""}
    ${o.issued_at ? `<dt>Выдан</dt><dd>${esc(fullTime(o.issued_at))}</dd>` : ""}
    ${o.cancelled_at ? `<dt>Отменён</dt><dd>${esc(fullTime(o.cancelled_at))}${o.cancel_reason ? " · " + esc(o.cancel_reason) : ""}</dd>` : ""}`;
  const actor = { client: "👤 клиент", admin: "🧑‍💼 оператор", system: "🤖 система" };
  drawer.querySelector("[data-events]").innerHTML = o.events.slice().reverse().map((ev) =>
    `<li class="${ev.kind === "stage" ? "success" : ev.kind}">${ev.kind === "stage" ? "📣 " : ""}${esc(ev.text)}<time>${esc(fullTime(ev.at))} · ${actor[ev.actor] || esc(ev.actor)}</time></li>`).join("");
}

async function sendMessage(btn) {
  const area = document.getElementById("msg");
  const text = area.value.trim();
  if (!text) { toast("Напишите текст сообщения", "error"); area.focus(); return; }
  await withLoading(btn, "Отправляем…", async () => {
    try {
      const r = await api(`/api/orders/${state.openId}/actions/message`, { method: "POST", body: { text } });
      area.value = "";
      toast(r.message, "ok");
      state.detail = r.order;
      renderDrawer(false);
    } catch (e) { toast(e.message, "error"); }
  });
}

function bindNote(area) {
  let timer, last = area.value;
  const label = document.getElementById("note-state");
  const save = async () => {
    if (area.value === last) return;
    const value = area.value;
    label.className = "hint"; label.textContent = "Сохраняем…";
    try {
      await api(`/api/orders/${state.openId}/actions/note`, { method: "POST", body: { note: value } });
      last = value;
      label.className = "saved"; label.textContent = "✓ Сохранено";
    } catch (e) {
      label.className = "hint"; label.textContent = "Не сохранилось: " + e.message;
    }
  };
  area.addEventListener("input", () => { label.className = "hint"; label.textContent = "Есть несохранённые изменения…"; clearTimeout(timer); timer = setTimeout(save, 800); });
  area.addEventListener("blur", save);
}

// ---------- просмотр изображений ----------

function openLightbox(items, index) {
  const box = document.createElement("div");
  box.className = "lightbox";
  const show = () => {
    const it = items[index];
    box.innerHTML = `<div class="bar"><b>${esc(it.name)}</b><span class="muted">${index + 1} из ${items.length}</span>
      <div style="flex:1"></div>
      <button class="btn sm" data-prev ${index === 0 ? "disabled" : ""}>←</button>
      <button class="btn sm" data-next ${index === items.length - 1 ? "disabled" : ""}>→</button>
      <a class="btn sm" href="${it.full}" target="_blank" rel="noopener">Открыть</a>
      <button class="btn sm" data-close>✕</button></div>
      <div class="stage"><img src="${it.full}" alt=""></div>`;
    box.querySelector("[data-close]").addEventListener("click", close);
    box.querySelector("[data-prev]").addEventListener("click", () => { index--; show(); });
    box.querySelector("[data-next]").addEventListener("click", () => { index++; show(); });
  };
  const onKey = (e) => {
    if (e.key === "Escape") close();
    if (e.key === "ArrowLeft" && index > 0) { index--; show(); }
    if (e.key === "ArrowRight" && index < items.length - 1) { index++; show(); }
  };
  const close = () => { box.remove(); document.removeEventListener("keydown", onKey); };
  box.addEventListener("click", (e) => { if (e.target.classList.contains("stage")) close(); });
  document.addEventListener("keydown", onKey);
  document.body.appendChild(box);
  show();
}

// ---------- принтер ----------

function renderPrinter() {
  const chip = document.getElementById("printer-chip");
  const pop = document.getElementById("printer-pop");
  const s = state.summary;
  if (!chip || !s) return;
  const p = s.printer;
  const problems = [...p.problems, ...p.jobs.filter((j) => j.problem).map((j) => j.states.join(", "))];
  const label = s.print_mode === "file" ? "Режим: в файлы" : s.print_mode === "browser" ? "Печать из браузера" :
    s.print_mode === "agent" && problems.length ? problems[0] :
    problems.length ? `Принтер: ${problems[0]}` : (p.jobs.length ? `Принтер: в очереди ${p.jobs.length}` : "Принтер готов");
  chip.innerHTML = `<span class="dot ${problems.length ? "bad" : (p.jobs.length ? "warn" : "ok")}"></span><span>${esc(label)}</span>`;
  pop.classList.toggle("hidden", !state.printerOpen);
  if (!state.printerOpen) return;
  pop.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
      <b>${esc(p.name || "Принтер")}</b><button class="btn ghost sm" data-close>✕</button></div>
    ${problems.length ? `<div class="banner error" style="margin-top:10px">⚠️ ${esc(problems.join("; "))}</div>` :
      `<div class="banner ok" style="margin-top:10px">Ошибок нет</div>`}
    <p class="hint">Windows знает не обо всех проблемах: если задание висит долго — проверьте сам принтер.</p>
    ${s.print_mode === "agent" ? '<p><a class="btn sm" href="#printers">Компьютеры и профили печати</a></p>' : ""}
    <div style="margin-top:6px"><b>Очередь печати</b></div>
    ${p.jobs.length ? p.jobs.map((j) => `<div class="job"><div>${esc(j.document)}<div class="small ${j.problem ? "" : "muted"}" style="${j.problem ? "color:var(--danger)" : ""}">${esc(j.states.join(", "))}</div></div>
      ${s.print_mode === "agent" ? "" : `<button class="btn sm danger" data-job="${j.id}">Удалить</button>`}</div>`).join("") : '<div class="hint" style="padding:8px 0">Очередь пуста</div>'}`;
  pop.querySelector("[data-close]").addEventListener("click", () => { state.printerOpen = false; renderPrinter(); });
  pop.querySelectorAll("[data-job]").forEach((b) => b.addEventListener("click", async () => {
    const ok = await confirmModal({ title: "Удалить задание из очереди?", html: "<p>Если это заказ, он вернётся в предыдущий статус при следующей проверке — лучше снимать задание из карточки заказа.</p>", ok: "Удалить", danger: true });
    if (!ok) return;
    await withLoading(b, "…", async () => {
      try { toast((await api(`/api/printer/jobs/${b.dataset.job}/cancel`, { method: "POST", body: {} })).message, "ok"); refresh(); }
      catch (e) { toast(e.message, "error"); }
    });
  }));
}

// ---------- цены ----------

async function renderPrices() {
  const page = document.getElementById("page");
  page.innerHTML = `<div class="empty">Загружаем цены…</div>`;
  let prices;
  try { prices = (await api("/api/prices")).prices; }
  catch (e) { page.innerHTML = `<div class="empty">Не удалось загрузить цены: ${esc(e.message)}</div>`; return; }
  const money = (path, v) => `<span class="money"><input class="input" type="number" min="0" step="1" data-path="${path}" value="${v}"> ₽</span>`;
  const fmt = { "10x15": "10×15 см", a5: "A5", a4: "A4" };
  page.innerHTML = `
    <h2 style="margin:0 0 4px">Цены</h2>
    <p class="muted" style="margin:0 0 18px">Новые заказы считаются по этим ценам. Уже оформленные заказы не меняются.</p>
    <div class="prices">
      <section class="card"><h3>Игральные карты</h3>
        <div class="price-row"><span>Колода 36 карт</span>${money("cards.deck36", prices.cards.deck36)}</div>
        <div class="price-row"><span>Колода 54 карты</span>${money("cards.deck54", prices.cards.deck54)}</div>
        <div class="price-row"><span>Колода UNO, 108 карт</span>${money("cards.uno", prices.cards.uno)}</div>
      </section>
      <section class="card"><h3>Фото — за один отпечаток</h3>
        ${Object.keys(prices.photo).map((f) => `
          <div class="price-row"><span>${fmt[f] || f}, цветное</span>${money(`photo.${f}.color`, prices.photo[f].color)}</div>
          <div class="price-row"><span>${fmt[f] || f}, ч/б</span>${money(`photo.${f}.bw`, prices.photo[f].bw)}</div>`).join("")}
      </section>
      <section class="card"><h3>Документы — за одну страницу A4</h3>
        <div class="price-row"><span>Цветная печать</span>${money("doc.color", prices.doc.color)}</div>
        <div class="price-row"><span>Чёрно-белая печать</span>${money("doc.bw", prices.doc.bw)}</div>
      </section>
      <section class="card"><h3>Изделия</h3>
        ${[["memory_base", "Мемори — основа"], ["memory_pair", "Мемори — за каждую пару"], ["dates_sheet", "Карты для свиданий — за лист (9 карт)"],
          ["wishes_sheet", "Карты желаний — за лист (9 карт)"], ["game_sheet", "Карты для игры — за лист (9 карт)"],
          ["stickers_sheet", "Наклейки — за лист A4"], ["calendar", "Фотокалендарь"], ["postcard", "Открытка — за штуку"],
          ["box", "Коробка для колоды"], ["enhance_photo", "Улучшение одного фото нейросетью"]].map(([k, t]) =>
          `<div class="price-row"><span>${t}</span>${money(`craft.${k}`, prices.craft[k])}</div>`).join("")}
      </section>
      <section class="card"><h3>Надбавка за бумагу — за лист A4</h3>
        <div class="price-row"><span>Плотная (документы)</span>${money("paper.thick", prices.paper.thick)}</div>
        <div class="price-row"><span>Плотная матовая (фото)</span>${money("paper.matte", prices.paper.matte)}</div>
        <div class="price-row"><span>Ламинация (карты и изделия)</span>${money("paper.lam", prices.paper.lam)}</div>
        <p class="hint">Добавляется к цене заказа за каждый лист A4.</p>
      </section>
      <section class="card"><h3>Надбавка за качество фото</h3>
        ${[["draft", "Черновое"], ["normal", "Обычное"], ["high", "Высокое"]].map(([k, t]) =>
          `<div class="price-row"><span>${t}</span><span class="money"><input class="input" type="number" min="-90" max="500" step="1" data-path="quality_markup.${k}" value="${prices.quality_markup[k]}"> %</span></div>`).join("")}
        <p class="hint">Например, +20 % — высокое качество на 20 % дороже базовой цены.</p>
      </section>
    </div>
    <div class="row-end" style="margin-top:16px"><span id="prices-state" class="hint"></span><button class="btn primary" id="save-prices">Сохранить цены</button></div>`;
  const label = document.getElementById("prices-state");
  page.querySelectorAll("input").forEach((i) => i.addEventListener("input", () => { label.className = "hint"; label.textContent = "Есть несохранённые изменения"; }));
  document.getElementById("save-prices").addEventListener("click", async (e) => {
    const next = JSON.parse(JSON.stringify(prices));
    for (const input of page.querySelectorAll("[data-path]")) {
      if (input.value === "" || Number.isNaN(Number(input.value))) { toast("Заполните все цены числами", "error"); input.focus(); return; }
      const keys = input.dataset.path.split(".");
      let obj = next;
      keys.slice(0, -1).forEach((k) => { obj = obj[k]; });
      obj[keys.at(-1)] = Number(input.value);
    }
    await withLoading(e.currentTarget, "Сохраняем…", async () => {
      try {
        const r = await api("/api/prices", { method: "PUT", body: { prices: next } });
        prices = r.prices;
        label.className = "saved"; label.textContent = "✓ " + r.message;
        toast("Цены сохранены", "ok");
      } catch (ex) { label.className = "hint"; toast(ex.message, "error"); }
    });
  });
}

// ---------- принтеры: компьютеры с программой «Тюша Печать» и профили ----------

let printersTimer = null;
function stopPrintersTimer() { if (printersTimer) clearInterval(printersTimer); printersTimer = null; }

function seenText(sec) {
  if (sec < 60) return "только что";
  const m = Math.round(sec / 60);
  return m < 60 ? `${m} мин назад` : `${Math.round(m / 60)} ч назад`;
}

function printerLine(pr) {
  const tone = pr.ok ? "ok" : "bad";
  const text = pr.ok ? (pr.jobs?.length ? `в очереди ${pr.jobs.length}` : "готов") : (pr.problems.join("; ") || "есть проблемы");
  return `<div class="pr-line"><span class="dot ${tone}"></span><span class="pr-name">${esc(pr.name)}</span><span class="${pr.ok ? "muted" : "pr-bad"}">${esc(text)}</span></div>`;
}

function verLess(a, b) {
  const pa = String(a || "").split(".").map(Number), pb = String(b || "").split(".").map(Number);
  for (let i = 0; i < 3; i++) { if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) < (pb[i] || 0); }
  return false;
}

function agentCard(a) {
  const used = new Set((state.printers?.profiles || []).filter((p) => p.agent_id === a.id).map((p) => p.printer));
  const main = a.printers.filter((p) => used.has(p.name));
  const other = a.printers.filter((p) => !used.has(p.name));
  return `<section class="card agent-card">
    <div class="agent-head">
      <div><b class="agent-name">${esc(a.name)}</b>
        <div class="small ${a.online ? "" : "pr-bad"}"><span class="dot ${a.online ? "ok" : "bad"}"></span>
          ${a.online ? "на связи" : `не на связи · ${seenText(a.seen_ago)}`}${a.version ? ` · программа ${esc(a.version)}` : ""}${a.dry_run ? " · пробный режим" : ""}</div></div>
      <div class="agent-actions">
        <button class="btn sm" data-rename="${a.id}">Переименовать</button>
        <button class="btn sm danger" data-revoke="${a.id}">Отключить</button>
      </div>
    </div>
    ${a.version && a.latest_version && verLess(a.version, a.latest_version) ? `<div class="banner warn"><div>Доступна версия ${esc(a.latest_version)}
      <div class="small">${a.update_requested ? "Команда отправлена — программа обновится, когда принтер освободится." :
        "Программа обновится сама в течение нескольких часов. Можно не ждать:"}</div></div>
      ${a.update_requested ? "" : `<button class="btn sm" data-update="${a.id}">Обновить сейчас</button>`}</div>` : ""}
    ${a.update ? `<div class="hint">Обновления: ${esc(a.update)}</div>` : ""}
    ${a.current ? `<div class="banner info"><span class="spinner"></span><div>${esc(a.current.label)}<div class="small">${esc(a.current.state)}</div></div></div>` : ""}
    ${main.length ? `<div class="pr-list">${main.map(printerLine).join("")}</div>` : '<div class="hint">Принтеры этого компьютера пока не выбраны ни в одном профиле.</div>'}
    ${other.length ? `<details class="pr-more"><summary>Другие принтеры на компьютере · ${other.length}</summary><div class="pr-list">${other.map(printerLine).join("")}</div></details>` : ""}
  </section>`;
}

function profileCard(p, agents) {
  const agent = agents.find((a) => a.id === p.agent_id);
  const printers = agent ? agent.printers : [];
  const status = !p.agent_id || !p.printer ? ["bad", "Не выбран компьютер или принтер"] :
    !agent?.online ? ["bad", `«${p.agent_name}» не на связи`] :
    !p.printer_info ? ["bad", "Принтер не найден на компьютере"] :
    p.printer_info.problems?.length ? ["warn", p.printer_info.problems.join("; ")] : ["ok", "Готов к печати"];
  return `<section class="card profile-card" data-profile="${p.key}">
    <div class="agent-head"><b>${esc(p.title)}</b><span class="badge ${status[0] === "ok" ? "printed" : status[0] === "warn" ? "fronts_printed" : "error"}">${esc(status[1])}</span></div>
    <div class="profile-grid">
      <label>Компьютер<select class="input" data-field="agent">
        <option value="">— не выбран —</option>
        ${agents.map((a) => `<option value="${a.id}" ${a.id === p.agent_id ? "selected" : ""}>${esc(a.name)}${a.online ? "" : " (не на связи)"}</option>`).join("")}
      </select></label>
      <label>Принтер<select class="input" data-field="printer">
        <option value="">— не выбран —</option>
        ${printers.map((pr) => `<option ${pr.name === p.printer ? "selected" : ""}>${esc(pr.name)}</option>`).join("")}
      </select></label>
    </div>
    <div class="hint">${p.has_devmode ? `Настройки драйвера: ${esc(p.devmode_summary || "заданы")}` :
      "Настройки драйвера не заданы — печать пойдёт с настройками принтера по умолчанию. Чтобы выбрать тип бумаги и качество, на компьютере в программе «Тюша Печать» нажмите «Настроить…» у этого профиля."}</div>
    <div class="row-end"><span class="hint" data-state></span>
      <button class="btn sm" data-test="${p.key}" ${status[0] === "bad" ? "disabled" : ""}>Пробный лист</button>
      <button class="btn sm primary" data-save="${p.key}" hidden>Сохранить</button></div>
  </section>`;
}

async function renderPrinters(soft = false) {
  const page = document.getElementById("page");
  if (!soft) page.innerHTML = `<div class="empty">Загружаем принтеры…</div>`;
  let data;
  try { data = await api("/api/printers"); }
  catch (e) { if (!soft) page.innerHTML = `<div class="empty">Не удалось загрузить: ${esc(e.message)}</div>`; return; }
  if (state.view !== "printers") return;
  state.printers = data;
  const agentsHtml = data.agents.length ? data.agents.map(agentCard).join("") :
    `<div class="card empty-agents"><img src="/static/tyusha.png" alt=""><div><b>Компьютер с принтером ещё не подключён</b>
      <p class="hint">Нажмите «Подключить компьютер» — появится код. На компьютере с принтером запустите программу «Тюша Печать» и введите его.</p></div></div>`;
  if (soft && document.getElementById("agents-list")) {
    // обновляем только состояние компьютеров — выпадающие списки профилей не трогаем, их могут сейчас менять
    document.getElementById("agents-list").innerHTML = agentsHtml;
    bindAgentButtons();
    return;
  }
  page.innerHTML = `
    <div class="page-head"><div><h2 style="margin:0">Принтеры</h2>
      <p class="muted" style="margin:4px 0 0">Печатает программа «Тюша Печать» на компьютере, к которому подключён принтер. Оператор только нажимает «Печать» в заказе.</p></div>
      <div class="page-head-actions">
        ${data.download ? '<a class="btn" href="/agent/download">Скачать программу</a>' : ""}
        <button class="btn primary" id="pair-btn">Подключить компьютер</button></div></div>
    ${data.mode !== "agent" ? `<div class="banner warn">⚠️ <div>Сейчас на сервере режим печати «${esc(data.mode)}»
      <div class="small">Чтобы печатать через компьютер с принтером, в файле .env на сервере укажите <b>PRINT_MODE=agent</b> и перезапустите бота.</div></div></div>` : ""}
    <h3 class="section-title">Компьютеры с принтером</h3>
    <div id="agents-list">${agentsHtml}</div>
    <h3 class="section-title">Профили печати</h3>
    <p class="hint" style="margin:-4px 0 10px">Профиль — это материал: на каком компьютере и принтере его печатать и с какими настройками драйвера. Заказ сам выбирает профиль.</p>
    <div class="profiles">${data.profiles.map((p) => profileCard(p, data.agents)).join("")}</div>`;
  document.getElementById("pair-btn").addEventListener("click", pairModal);
  bindAgentButtons();
  page.querySelectorAll(".profile-card").forEach(bindProfileCard);
  stopPrintersTimer();
  printersTimer = setInterval(() => renderPrinters(true), 5000);
}

function bindAgentButtons() {
  document.querySelectorAll("[data-update]").forEach((b) => b.addEventListener("click", () => withLoading(b, "Отправляем…", async () => {
    try { toast((await api(`/api/printers/agents/${b.dataset.update}`, { method: "POST", body: { update: true } })).message, "ok"); renderPrinters(true); }
    catch (e) { toast(e.message, "error"); }
  })));
  document.querySelectorAll("[data-rename]").forEach((b) => b.addEventListener("click", async () => {
    const a = state.printers.agents.find((x) => x.id === Number(b.dataset.rename));
    const res = await confirmModal({ title: "Название компьютера", ok: "Сохранить",
      html: `<p>Его видят операторы в окне печати.</p><textarea name="reason" rows="1" maxlength="60">${esc(a.name)}</textarea>` });
    if (!res) return;
    try { toast((await api(`/api/printers/agents/${a.id}`, { method: "POST", body: { name: res.reason } })).message, "ok"); renderPrinters(); }
    catch (e) { toast(e.message, "error"); }
  }));
  document.querySelectorAll("[data-revoke]").forEach((b) => b.addEventListener("click", async () => {
    const a = state.printers.agents.find((x) => x.id === Number(b.dataset.revoke));
    const res = await confirmModal({ title: `Отключить «${a.name}»?`, danger: true, ok: "Отключить",
      html: "<p>Программа на этом компьютере перестанет получать задания, профили с ним освободятся. Чтобы вернуть — подключите компьютер заново кодом.</p>" });
    if (!res) return;
    try { toast((await api(`/api/printers/agents/${a.id}`, { method: "POST", body: { revoke: true } })).message, "ok"); renderPrinters(); }
    catch (e) { toast(e.message, "error"); }
  }));
}

function bindProfileCard(card) {
  const key = card.dataset.profile;
  const agentSel = card.querySelector('[data-field="agent"]');
  const printerSel = card.querySelector('[data-field="printer"]');
  const save = card.querySelector("[data-save]");
  const test = card.querySelector("[data-test]");
  const label = card.querySelector("[data-state]");
  const changed = () => { save.hidden = false; test.disabled = true; label.className = "hint"; label.textContent = "Есть несохранённые изменения"; };
  agentSel.addEventListener("change", () => {
    const a = state.printers.agents.find((x) => x.id === Number(agentSel.value));
    printerSel.innerHTML = '<option value="">— не выбран —</option>' + (a ? a.printers.map((pr) => `<option>${esc(pr.name)}</option>`).join("") : "");
    changed();
  });
  printerSel.addEventListener("change", changed);
  save.addEventListener("click", () => withLoading(save, "Сохраняем…", async () => {
    try {
      const r = await api(`/api/printers/profiles/${key}`, { method: "PUT", body: { agent_id: agentSel.value || null, printer: printerSel.value || null } });
      toast(r.message, "ok");
      renderPrinters();
    } catch (e) { toast(e.message, "error"); }
  }));
  test.addEventListener("click", () => withLoading(test, "Отправляем…", async () => {
    try {
      const r = await api(`/api/printers/profiles/${key}/test`, { method: "POST", body: {} });
      toast(r.message, "ok");
      const names = { queued: "ждёт компьютер", sent: "компьютер получил", printing: "печатается", done: "напечатан ✓", error: "ошибка", cancelled: "снят" };
      for (let i = 0; i < 90; i++) {  // следим за пробным листом до 3 минут
        await new Promise((res) => setTimeout(res, 2000));
        const j = await api(`/api/printers/jobs/${r.job_id}`).catch(() => null);
        if (!j || !label.isConnected) return;
        label.textContent = `Пробный лист: ${names[j.state] || j.state}${j.detail ? " — " + j.detail : ""}`;
        label.className = j.state === "done" ? "saved" : (j.state === "error" || j.problem) ? "hint pr-bad" : "hint";
        if (["done", "error", "cancelled"].includes(j.state)) return;
      }
    } catch (e) { toast(e.message, "error"); }
  }));
}

async function pairModal() {
  let code;
  try { code = await api("/api/printers/pair-code", { method: "POST", body: {} }); }
  catch (e) { toast(e.message, "error"); return; }
  const before = new Set((state.printers?.agents || []).map((a) => a.id));
  const wrap = document.createElement("div");
  wrap.className = "modal-wrap";
  const deadline = Date.now() + code.expires_in * 1000;
  wrap.innerHTML = `<div class="modal" role="dialog" aria-modal="true">
    <h3>Подключить компьютер с принтером</h3>
    <ol class="pair-steps">
      <li>На компьютере с принтером <a href="/agent/download">скачайте программу «Тюша Печать»</a> и запустите её. Дальше она обновляется сама.</li>
      <li>Адрес сервера: <code>${esc(location.origin)}</code></li>
      <li>Введите код:</li></ol>
    <div class="pair-code" aria-label="Код подключения">${code.code.slice(0, 3)} ${code.code.slice(3)}</div>
    <p class="hint" id="pair-state">Код действует <span id="pair-left"></span>. Ждём компьютер…</p>
    <div class="buttons"><button class="btn" data-close>Закрыть</button></div></div>`;
  document.body.appendChild(wrap);
  let timer = null;
  const close = () => { clearInterval(timer); wrap.remove(); renderPrinters(); };
  wrap.querySelector("[data-close]").addEventListener("click", close);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  let tick = 0;
  const step = async () => {
    const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    const el = document.getElementById("pair-left");
    if (el) el.textContent = left ? `ещё ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : "— истёк, закройте окно и получите новый";
    if (tick++ % 2) return;
    const d = await api("/api/printers").catch(() => null);
    const fresh = d?.agents.find((a) => !before.has(a.id));
    if (fresh) {
      clearInterval(timer);
      document.getElementById("pair-state").innerHTML = `<span class="saved">✓ Подключён «${esc(fresh.name)}». Профили можно настроить на странице «Принтеры».</span>`;
      wrap.querySelector(".pair-code").classList.add("done");
    }
  };
  step();
  timer = setInterval(step, 1000);
}

// ---------- старт ----------

(async function boot() {
  try {
    const me = await api("/api/me");
    if (me.authorized) renderShell();
    else renderLogin(me.password_set ? "" : "Пароль не задан: впишите ADMIN_PASSWORD в .env и перезапустите бота");
  } catch (e) {
    $app.innerHTML = `<div class="boot">Не удалось связаться с ботом: ${esc(e.message)}</div>`;
  }
})();

// ---------- склад ----------

async function renderStock() {
  const page = document.getElementById("page");
  if (!page.querySelector("[data-stock]")) page.innerHTML = `<div class="empty" data-stock>Загружаем склад…</div>`;
  let data;
  try { data = await api("/api/stock"); }
  catch (e) { page.innerHTML = `<div class="empty">Не удалось загрузить склад: ${esc(e.message)}</div>`; return; }
  const stateText = { ok: ["ok", "в наличии"], low: ["warn", "мало"], out: ["error", "закончилось"] };
  page.innerHTML = `
    <h2 style="margin:0 0 4px">Склад</h2>
    <p class="muted" style="margin:0 0 18px">Материалы списываются, когда клиент оформляет заказ, и возвращаются, если заказ отменён до печати.
      Когда материал закончился, клиенты не смогут выбрать бумагу на нём — заказ не оформится.</p>
    <div class="stock-grid">${data.materials.map((m) => {
      const [tone, label] = stateText[m.state];
      return `<section class="card stock-card" data-key="${m.key}">
        <div class="row-between"><h3>${esc(m.title)}</h3><span class="pill ${tone}">${label}</span></div>
        <div class="stock-num"><b>${m.stock}</b> ${esc(m.unit)}</div>
        <div class="stock-bar"><i class="${tone}" style="width:${Math.min(100, Math.round(m.stock / Math.max(1, m.low * 4) * 100))}%"></i></div>
        <div class="stock-actions">
          <input class="input" type="number" min="1" step="1" placeholder="Сколько" data-amount>
          <button class="btn sm primary" data-op="income">+ Приход</button>
          <button class="btn sm" data-op="writeoff">− Списать</button>
        </div>
        <details><summary class="hint">Точный остаток и порог «мало»</summary>
          <div class="stock-actions" style="margin-top:8px">
            <label class="hint">Остаток <input class="input" type="number" min="0" value="${m.stock}" data-set></label>
            <label class="hint">Порог <input class="input" type="number" min="0" value="${m.low}" data-low></label>
            <button class="btn sm" data-op="save">Сохранить</button>
          </div></details>
      </section>`; }).join("")}</div>
    <section class="card" style="margin-top:16px"><h3>Движение по складу</h3>
      ${data.log.length ? `<table class="table"><thead><tr><th>Когда</th><th>Материал</th><th>Изменение</th><th>Причина</th></tr></thead><tbody>
        ${data.log.map((r) => `<tr><td>${esc(fullTime(r.at))}</td><td>${esc(r.title)}</td>
          <td class="${r.delta < 0 ? "neg" : "pos"}">${r.delta > 0 ? "+" : ""}${r.delta}</td>
          <td>${esc(r.reason_title)}${r.order_id ? ` · <a href="#order=${r.order_id}">№${r.order_id}</a>` : ""}${r.note ? ` · ${esc(r.note)}` : ""}</td></tr>`).join("")}
        </tbody></table>` : `<p class="hint">Движений пока нет.</p>`}
    </section>`;
  page.querySelectorAll(".stock-card").forEach((card) => card.querySelectorAll("[data-op]").forEach((b) => b.addEventListener("click", async () => {
    const op = b.dataset.op, key = card.dataset.key;
    let body;
    if (op === "save") body = { set: card.querySelector("[data-set]").value, low: card.querySelector("[data-low]").value };
    else {
      const n = Number(card.querySelector("[data-amount]").value);
      if (!n || n < 0) { toast("Укажите, сколько листов", "error"); card.querySelector("[data-amount]").focus(); return; }
      body = { delta: op === "income" ? n : -n };
    }
    await withLoading(b, "…", async () => {
      try { const r = await api(`/api/stock/${key}`, { method: "POST", body }); toast(r.message, "ok"); renderStock(); refresh(); }
      catch (e) { toast(e.message, "error"); }
    });
  })));
}

// ---------- статистика ----------

let statsDays = 30;
async function renderStats() {
  const page = document.getElementById("page");
  page.innerHTML = `<div class="empty">Считаем…</div>`;
  let s;
  try { s = await api(`/api/stats?days=${statsDays}`); }
  catch (e) { page.innerHTML = `<div class="empty">Не удалось посчитать: ${esc(e.message)}</div>`; return; }
  const maxRev = Math.max(1, ...s.by_day.map((d) => d.revenue));
  const bars = (items, valueKey, labelFn) => {
    const max = Math.max(1, ...items.map((x) => x[valueKey]));
    return items.length ? items.map((x) => `<div class="hbar"><span class="t">${esc(x.title)}</span>
      <span class="track"><i style="width:${Math.round(x[valueKey] / max * 100)}%"></i></span><b>${esc(labelFn(x))}</b></div>`).join("")
      : `<p class="hint">Пока нет данных.</p>`;
  };
  page.innerHTML = `
    <div class="row-between" style="margin-bottom:14px"><h2 style="margin:0">Статистика</h2>
      <div class="tabs">${[[7, "7 дней"], [30, "30 дней"], [90, "90 дней"], [365, "Год"]].map(([d, t]) =>
        `<button data-days="${d}" class="${d === statsDays ? "active" : ""}">${t}</button>`).join("")}</div></div>
    <section class="stats">
      <div class="stat static"><div class="num">${esc(s.revenue)}</div><div class="lbl">Выручка</div></div>
      <div class="stat static"><div class="num">${s.orders}</div><div class="lbl">Заказов · средний чек ${esc(s.avg)}</div></div>
      <div class="stat static"><div class="num">${s.clients}</div><div class="lbl">Клиентов · вернулись ${s.repeat_clients}</div></div>
      <div class="stat static"><div class="num">${s.cancelled}</div><div class="lbl">Отменено · выдано ${s.issued}</div></div>
    </section>
    <section class="card"><h3>Выручка по дням</h3>
      <div class="chart" style="--n:${s.by_day.length}">${s.by_day.map((d) => `<div class="col" title="${esc(d.day)}: ${d.orders} зак., ${Math.round(d.revenue)} ₽">
        <i style="height:${Math.round(d.revenue / maxRev * 100)}%"></i></div>`).join("")}</div>
      <div class="row-between hint"><span>${esc(s.by_day[0]?.day || "")}</span><span>${esc(s.by_day.at(-1)?.day || "")}</span></div></section>
    <div class="prices" style="margin-top:16px">
      <section class="card"><h3>Что заказывают</h3>${bars(s.products, "kop", (x) => `${x.revenue} · ${x.orders}`)}</section>
      <section class="card"><h3>Популярные рубашки</h3>${bars(s.backs, "count", (x) => String(x.count))}</section>
      <section class="card"><h3>Ушло материалов</h3>${bars(s.materials, "used", (x) => `${x.used} ${x.unit}`)}</section>
      <section class="card"><h3>Бумага в заказах, листов</h3>${bars(s.papers, "sheets", (x) => String(x.sheets))}</section>
    </div>`;
  page.querySelectorAll("[data-days]").forEach((b) => b.addEventListener("click", () => { statsDays = Number(b.dataset.days); renderStats(); }));
}

// ---------- этап заказа с фото ----------

async function sendStage(btn) {
  const box = document.getElementById("stage-box");
  const form = new FormData();
  form.append("stage", box.querySelector("[name=stage]").value);
  form.append("text", box.querySelector("[name=stage_text]").value.trim());
  const file = box.querySelector("[name=stage_photo]").files[0];
  if (file) form.append("photo", file, file.name);
  await withLoading(btn, "Отправляем…", async () => {
    try {
      const res = await fetch(`/api/orders/${state.openId}/stage`, { method: "POST", body: form });
      const r = await res.json().catch(() => ({}));
      if (!res.ok || r.ok === false) throw new Error(r.error || `Ошибка сервера (${res.status})`);
      toast(r.message, "ok");
      box.querySelector("[name=stage_text]").value = "";
      box.querySelector("[name=stage_photo]").value = "";
      box.querySelector("[data-file-name]").textContent = "Фото не выбрано";
      state.detail = r.order;
      renderDrawer(false);
    } catch (e) { toast(e.message, "error"); }
  });
}
