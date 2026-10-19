// Тюша — Telegram Mini App (кликабельный прототип на демо-данных).
// Экраны S01–S14 из ТЗ; бизнес-правила (доступность материалов, цена, статусы)
// повторяют серверные, чтобы прототип вёл себя как настоящий.
import { icon } from "./icons.js";

const tg = window.Telegram?.WebApp;
const IMG = {
  waveBody: "img/tyusha-wave-body.png",
  wavePaw: "img/tyusha-wave-paw.png",
  printer: "img/tyusha-printer.png",
  face: "img/tyusha-face.png",
};

// ---------- справочники ----------

const MATERIALS = {
  paperA4: { name: "Бумага A4, 80 г/м²", left: 420, unit: "л." },
  photo10: { name: "Фотобумага 10×15", left: 0, unit: "л." },
  photoA4: { name: "Фотобумага A4", left: 64, unit: "л." },
  card300: { name: "Картон 300 г/м²", left: 96, unit: "л." },
  bag: { name: "Подарочные мешочки", left: 0, unit: "шт." },
  box: { name: "Коробочки для колод", left: 6, unit: "шт." },
};

const PRODUCTS = [
  { id: "deck36", cat: "cards", title: "Классическая колода", sub: "36 карт, от шестёрки до туза", price: 990, cards: 36,
    needs: { card300: 8, box: 1 }, days: "Завтра к 18:00", art: "classic",
    includes: [["cards", "36 карт 63×88 мм на картоне 300 г/м²"], ["paw", "Рубашка с медальоном Тюши"], ["box", "Коробочка для колоды"]],
    reqs: ["От 1 до 36 фото: фото распределятся по картам по очереди", "Лучше от 1000 px по короткой стороне", "JPG или PNG до 20 МБ"] },
  { id: "deck54", cat: "cards", title: "Полная колода", sub: "54 карты с двумя джокерами", price: 1290, cards: 54,
    needs: { card300: 12, box: 1 }, days: "Завтра к 18:00", art: "full",
    includes: [["cards", "54 карты 63×88 мм на картоне 300 г/м²"], ["stars", "Два джокера с вашими фото"], ["box", "Коробочка для колоды"]],
    reqs: ["От 1 до 54 фото", "Лучше от 1000 px по короткой стороне", "JPG или PNG до 20 МБ"] },
  { id: "dates", cat: "cards", title: "Карты для свиданий", sub: "40 карточек-вопросов и ваши фото", price: 890, cards: 40,
    needs: { card300: 6, bag: 1 }, days: "Через 2 дня", art: "dates",
    includes: [["heart", "40 вопросов для двоих"], ["gallery", "Ваши фото на обороте"], ["gift", "Подарочный мешочек"]],
    reqs: ["От 1 до 20 фото", "JPG или PNG до 20 МБ"] },
  { id: "memory", cat: "cards", title: "Мемори", sub: "24 пары карточек из ваших фото", price: 790, cards: 48,
    needs: { card300: 6, box: 1 }, days: "Завтра к 18:00", art: "memory",
    includes: [["layers", "48 квадратных карточек 60×60 мм"], ["magic", "Каждое фото печатаем дважды"], ["box", "Коробочка"]],
    reqs: ["Ровно 24 фото, по одному на пару", "JPG или PNG до 20 МБ"] },
  { id: "doc", cat: "docs", title: "Печать документов", sub: "PDF, JPG и PNG на A4 и A5", priceFrom: "от 10 ₽ за страницу",
    needs: { paperA4: 1 }, days: "Сегодня за 1 час", art: "doc" },
  { id: "photo", cat: "photo", title: "Печать фото", sub: "A5 и A4 на фотобумаге", priceFrom: "от 60 ₽ за фото",
    needs: { photoA4: 1 }, days: "Сегодня за 2 часа", art: "photo" },
];
const byId = (id) => PRODUCTS.find((p) => p.id === id);

const TARIFF = {
  prep: 30,
  doc: { A4: { bw: 10, color: 25 }, A5: { bw: 8, color: 18 } },
  photo: { "10x15": 30, a5: 60, a4: 100 },
};

const STATUS = {
  awaiting_payment: ["Ожидает оплаты", "hourglass", "warn"],
  payment_processing: ["Проверяем оплату", "refresh", ""],
  paid: ["Оплачен, ждёт оператора", "check", ""],
  preparing: ["Готовим принтер", "tune", ""],
  printing: ["Печатается", "printer", ""],
  quality_check: ["Проверка качества", "eye", ""],
  ready_for_pickup: ["Готов к выдаче", "box", "ok"],
  completed: ["Выдан", "check", "mute"],
  clarification_required: ["Нужно ваше решение", "chat", "warn"],
  paused: ["Приостановлен", "clock", "warn"],
  cancelled: ["Отменён", "close", "no"],
  refund_pending: ["Возвращаем деньги", "card", "warn"],
  refunded: ["Деньги возвращены", "card", "mute"],
};
const FLOW = [
  ["paid", "Оплачен", "check"], ["preparing", "Подготовка принтера", "tune"], ["printing", "Печать", "printer"],
  ["quality_check", "Проверка качества", "eye"], ["ready_for_pickup", "Готов к выдаче", "box"], ["completed", "Выдан", "paw"],
];
const NEXT_STEP = {
  paid: "Оператор проверит макет, подготовит бумагу и запустит печать. Напишем, когда начнём.",
  preparing: "Оператор загружает бумагу и проверяет принтер.",
  printing: "Печатаем прямо сейчас. Ориентировочно готово сегодня к 18:00.",
  quality_check: "Проверяем качество и комплектность.",
  ready_for_pickup: "Можно забирать. Назовите номер заказа в пункте выдачи.",
  completed: "Заказ выдан. Спасибо, что выбрали Тюшу!",
  refund_pending: "Отменили заказ. Деньги вернутся на карту за 1–7 дней, срок зависит от банка.",
  refunded: "Деньги вернули на карту.",
};

const SUITS = [["♠︎", ""], ["♥︎", "red"], ["♦︎", "red"], ["♣︎", ""]];
const RANKS36 = ["6", "7", "8", "9", "10", "В", "Д", "К", "Т"];
const RANKS54 = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "В", "Д", "К", "Т"];
const QUESTIONS = ["Что тебя рассмешило сегодня?", "Куда бы ты уехал завтра?", "Какая песня про нас?", "Самый смелый поступок?"];

// Примеры фото — Тюша на цветных фонах (в демо вместо снимков клиента)
const SAMPLE_PHOTOS = [
  { url: IMG.face, bg: "#DCE7FD", w: 1600, h: 1200, name: "Пример 1" },
  { url: IMG.printer, bg: "#F9D5DB", w: 1440, h: 1440, name: "Пример 2" },
  { url: IMG.waveBody, bg: "#FCEFC9", w: 1200, h: 1600, name: "Пример 3" },
  { url: IMG.face, bg: "#D9F2E7", w: 640, h: 480, name: "Пример 4" },
];

// ---------- состояние ----------

const tgUser = tg?.initDataUnsafe?.user;
const state = {
  tab: "home",
  stack: [],
  scroll: {},
  user: { name: tgUser?.first_name || "", username: tgUser?.username || "" },
  catCat: "all",
  q: "",
  ordersTab: "active",
  notify: { status: true, pickup: true, news: false },
  theme: "auto",
  draft: { pid: "deck54", title: "Колода «Выпускной»", photos: 14, updated: "вчера" },
  deck: null,          // конструктор карт
  swapFrom: null,
  doc: null,           // печать документа
  photoJob: null,      // печать фото
  review: null,        // что проверяем перед оплатой
  agreed: false,
  pay: { method: "sbp", phase: "idle", step: 0 },
  orders: [
    { id: 1042, pid: "deck36", title: "Колода «Наше лето»", sub: "36 карт · 12 фото", status: "printing", amount: 990,
      created: "Сегодня, 12:40", photos: [0, 1, 2],
      times: { paid: "Сегодня, 12:41", preparing: "12:55", printing: "13:20" },
      chat: [
        { me: false, who: "Оператор Аня", text: "Здравствуйте! Фото 7 получилось тёмным. Осветлить его перед печатью или оставить как есть?", at: "13:02" },
      ], unread: 1 },
    { id: 1038, pid: "doc", title: "Договор аренды.pdf", sub: "12 стр. · A4 · ч/б · 2 копии", status: "ready_for_pickup", amount: 270,
      created: "Вчера, 18:05", times: { paid: "Вчера, 18:06", preparing: "18:20", printing: "18:24", quality_check: "18:31", ready_for_pickup: "18:33" },
      chat: [], unread: 0 },
    { id: 1031, pid: "photo", title: "Фото A5", sub: "8 фото · цвет", status: "completed", amount: 480,
      created: "12 октября", times: { paid: "12 окт., 10:12", preparing: "10:30", printing: "10:41", quality_check: "10:52", ready_for_pickup: "10:55", completed: "13 окт., 17:40" },
      chat: [], unread: 0 },
    { id: 1027, pid: "photo", title: "Фото A4", sub: "3 фото · цвет", status: "refunded", amount: 300,
      created: "2 октября", reason: "Фото низкого разрешения (640×480): на A4 получилось бы нерезко. Деньги вернули.",
      times: { paid: "2 окт., 15:00" }, chat: [], unread: 0 },
  ],
};

// ---------- утилиты ----------

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rub = (n) => `${Math.round(n).toLocaleString("ru-RU")} ₽`;
const plural = (n, one, few, many) => {
  const a = n % 10, b = n % 100;
  return a === 1 && b !== 11 ? one : a >= 2 && a <= 4 && (b < 12 || b > 14) ? few : many;
};
function haptic(kind = "light") {
  try {
    if (!tg?.HapticFeedback) return;
    if (["success", "error", "warning"].includes(kind)) tg.HapticFeedback.notificationOccurred(kind);
    else if (kind === "select") tg.HapticFeedback.selectionChanged();
    else tg.HapticFeedback.impactOccurred(kind);
  } catch (e) { /* не в Telegram */ }
}
function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem("tyusha." + key);
    localStorage.setItem("tyusha." + key, value);
  } catch (e) { return null; }
  return null;
}

function availability(p, qty = 1) {
  for (const [m, need] of Object.entries(p.needs || {})) {
    const left = MATERIALS[m].left;
    if (left < need * qty) {
      const reason = left === 0 ? `Закончились: ${MATERIALS[m].name.toLowerCase()}` : `Не хватает: ${MATERIALS[m].name.toLowerCase()}`;
      return { ok: false, reason };
    }
  }
  const low = Object.entries(p.needs || {}).find(([m, need]) => MATERIALS[m].left < need * qty * 4);
  return { ok: true, low: !!low };
}
function availLine(p) {
  const a = availability(p);
  if (!a.ok) return `<span class="avail no">${icon("warn")}${esc(a.reason)}</span>`;
  if (a.low) return `<span class="avail low">${icon("clock")}Осталось немного · ${esc(p.days)}</span>`;
  return `<span class="avail ok">${icon("check")}В наличии · ${esc(p.days)}</span>`;
}

function photoStyle(ph) {
  if (!ph) return "background:var(--surface-2)";
  return `background:url('${ph.url}') center / ${ph.sample ? "contain" : "cover"} no-repeat, ${ph.bg || "#e8ecf4"}`;
}

// ---------- игральная карта ----------

function playingCard({ rank, suit, ph, cap = "", zoom = 1, x = 50, y = 50, cls = "", style = "" }) {
  const [glyph, color] = suit != null ? SUITS[suit] : ["", ""];
  const joker = rank === "JOKER";
  const bg = ph ? `background:url('${ph.url}') ${x}% ${y}% / ${ph.sample ? Math.round(zoom * 100) + "%" : zoom === 1 ? "cover" : Math.round(zoom * 120) + "%"} no-repeat, ${ph.bg || "#e8ecf4"}` : "background:var(--surface-2)";
  return `<div class="pc ${joker ? "" : color} ${cls}" style="${style}">
    <div class="win" style="${bg}"></div>
    <div class="ix">${joker ? "<span>J</span>" : `<span>${rank}</span><b>${glyph}</b>`}</div>
    <div class="ix r">${joker ? "<span>J</span>" : `<span>${rank}</span><b>${glyph}</b>`}</div>
    ${cap ? `<div class="cap">${esc(cap)}</div>` : ""}
    <div class="medal">${joker ? "★︎" : glyph}</div>
  </div>`;
}
const cardBack = (style = "") => `<div class="pc back" style="${style}"><div class="face" style="background-image:url('${IMG.face}')"></div></div>`;

function productArt(p, big = false) {
  const s = SAMPLE_PHOTOS;
  const sample = (i) => ({ ...s[i], sample: true });
  if (p.art === "classic") return `<div class="fan">${cardBack()}${playingCard({ rank: "Д", suit: 1, ph: sample(0) })}${playingCard({ rank: "Т", suit: 0, ph: sample(1) })}</div>`;
  if (p.art === "full") return `<div class="fan">${playingCard({ rank: "JOKER", ph: sample(2) })}${playingCard({ rank: "К", suit: 2, ph: sample(1) })}${cardBack()}</div>`;
  if (p.art === "dates") return `<div class="fan"><div class="pc q"><span>${esc(QUESTIONS[1])}</span></div><div class="pc q"><span>${esc(QUESTIONS[0])}</span></div><div class="pc q"><span>${esc(QUESTIONS[2])}</span></div></div>`;
  if (p.art === "memory") return `<div class="fan" style="aspect-ratio:1;width:44%">${[0, 0, 1].map((i) => `<div class="pc memo"><div class="win" style="${photoStyle(sample(i))};inset:8%"></div></div>`).join("")}</div>`;
  if (p.art === "doc") return `<div class="fan" style="aspect-ratio:210/297;width:44%"><div class="page"></div><div class="page"></div><div class="page"><b>1</b></div></div>`;
  return `<div class="fan" style="aspect-ratio:1;width:46%">${[2, 1, 0].map((i) => `<div class="pc memo" style="border-radius:6%"><div class="win" style="${photoStyle(sample(i))};inset:6%;outline:0;border-radius:3%"></div></div>`).join("")}</div>`;
}
const artBg = { classic: "#E4ECFD", full: "#EDE7F8", dates: "#FBE6EA", memory: "#E3F3EC", doc: "#EEF1F7", photo: "#FDF1DA" };

// ---------- расчёт цены ----------

function parseRange(text, total) {
  const pages = new Set();
  const parts = text.split(/[,;]+/).map((s) => s.trim()).filter(Boolean);
  if (!parts.length) return null;
  for (const part of parts) {
    const m = part.match(/^(\d+)\s*(?:[-–—]\s*(\d+))?$/);
    if (!m) return null;
    const a = +m[1], b = m[2] ? +m[2] : a;
    if (a < 1 || b > total || a > b) return null;
    for (let i = a; i <= b; i++) pages.add(i);
  }
  return pages;
}
function docSelected(d) {
  if (d.range === "all") return new Set(Array.from({ length: d.file.pages }, (_, i) => i + 1));
  return parseRange(d.rangeText, d.file.pages);
}
function quoteDoc(d) {
  const sel = docSelected(d);
  const n = sel ? sel.size : 0;
  const rate = TARIFF.doc[d.format][d.color ? "color" : "bw"];
  const lines = [["Подготовка файла", TARIFF.prep], [`${n} ${plural(n, "страница", "страницы", "страниц")} × ${d.copies} ${plural(d.copies, "копия", "копии", "копий")} × ${rate} ₽`, n * d.copies * rate]];
  return { total: lines.reduce((s, l) => s + l[1], 0), lines, sheets: (d.duplex ? Math.ceil(n / 2) : n) * d.copies, valid: n > 0 };
}
function quotePhoto(j) {
  const rate = TARIFF.photo[j.format];
  const n = j.photos.length * j.copies;
  return { total: n * rate, lines: [[`${n} ${plural(n, "отпечаток", "отпечатка", "отпечатков")} × ${rate} ₽`, n * rate]], valid: n > 0 };
}
function quoteDeck(dk) {
  const p = byId(dk.pid);
  return { total: p.price, lines: [[p.title, p.price]], valid: dk.photos.length > 0 };
}

// ---------- конструктор: раскладка колоды ----------

function deckLayout(dk) {
  const p = byId(dk.pid);
  const cards = [];
  if (p.id === "memory") {
    for (let i = 0; i < 48; i++) cards.push({ memo: true, i });
  } else {
    const ranks = p.id === "deck54" ? RANKS54 : RANKS36;
    SUITS.forEach((_, s) => ranks.forEach((r) => cards.push({ rank: r, suit: s })));
    if (p.id === "deck54") cards.push({ rank: "JOKER" }, { rank: "JOKER" });
  }
  return cards.map((c, i) => {
    const o = dk.edits[i] || {};
    const photoIndex = o.photo ?? (c.memo ? Math.floor(i / 2) : i) % Math.max(dk.photos.length, 1);
    return { ...c, i, o, ph: dk.photos[photoIndex], photoIndex };
  });
}
function lowRes(ph) { return ph && Math.min(ph.w, ph.h) < 800; }

// ---------- навигация ----------

const stage = () => document.getElementById("stage");
const current = () => state.stack.at(-1) || { name: state.tab };

function push(name, params = {}) {
  state.scroll[current().name] = window.scrollY;
  state.stack.push({ name, params });
  haptic("light");
  render("push");
  window.scrollTo(0, 0);
}
function back() {
  if (document.querySelector(".sheet-wrap")) return closeSheet();
  if (!state.stack.length) return;
  state.stack.pop();
  haptic("light");
  render("pop");
  window.scrollTo(0, state.scroll[current().name] || 0);
}
function goTab(tab) {
  if (state.tab === tab && !state.stack.length) return window.scrollTo({ top: 0, behavior: "smooth" });
  state.tab = tab;
  state.stack = [];
  haptic("select");
  render("tab");
  window.scrollTo(0, 0);
}

// ---------- общие куски ----------

function topbar(title, sub = "", right = "") {
  return `<header class="topbar">
    <button class="icon-btn" data-act="back" aria-label="Назад">${icon("back")}</button>
    <div><h1>${esc(title)}</h1>${sub ? `<small>${esc(sub)}</small>` : ""}</div>
    ${right || "<span></span>"}
  </header>`;
}
function steps(names, now) {
  return `<div class="steps" aria-label="Шаг ${now + 1} из ${names.length}">${names.map((n, i) =>
    `<div class="st ${i < now ? "done" : i === now ? "now" : ""}"><i></i>${esc(n)}</div>`).join("")}</div>`;
}
function seg(model, value, options) {
  const i = Math.max(0, options.findIndex((o) => o.v === value));
  return `<div class="seg" role="radiogroup">
    <span class="thumb" style="width:calc((100% - 8px - ${(options.length - 1) * 4}px) / ${options.length});transform:translateX(calc(${i} * (100% + 4px)))"></span>
    ${options.map((o) => `<button role="radio" aria-checked="${o.v === value}" class="${o.v === value ? "on" : ""}"
      data-act="set" data-model="${model}" data-value="${o.v}" ${o.off ? "disabled" : ""}>${esc(o.t)}${o.s ? `<small>${esc(o.s)}</small>` : ""}</button>`).join("")}
  </div>`;
}
function statusPill(status) {
  const [t, ic, tone] = STATUS[status];
  return `<span class="pill ${tone}">${icon(ic)}${esc(t)}</span>`;
}
function orderThumb(o) {
  const p = byId(o.pid);
  if (p.cat === "cards") return `<div class="othumb" style="background:${artBg[p.art]}">${playingCard({ rank: "Т", suit: 1, ph: { ...SAMPLE_PHOTOS[o.photos?.[0] ?? 0], sample: true } })}</div>`;
  if (p.cat === "docs") return `<div class="othumb">${icon("doc")}</div>`;
  return `<div class="othumb" style="background:${artBg.photo}">${icon("photo")}</div>`;
}
function dockBar(price, label, act, { disabled = false, sub = "Итого", go = "" } = {}) {
  return `<div class="dock"><div class="bar glass">
    ${price != null ? `<div class="price"><small>${esc(sub)}</small><b data-tween="price" data-value="${price}">${rub(price)}</b></div>` : ""}
    <button class="btn primary" ${go ? `data-go="${go}"` : `data-act="${act}"`} ${disabled ? "disabled" : ""}><span class="label">${esc(label)}</span></button>
  </div></div>`;
}

// ---------- экраны ----------

const SCREENS = {};

SCREENS.home = () => {
  const hour = new Date().getHours();
  const hello = hour < 5 ? "Доброй ночи" : hour < 12 ? "Доброе утро" : hour < 18 ? "Добрый день" : "Добрый вечер";
  const active = state.orders.find((o) => !["completed", "cancelled", "refunded"].includes(o.status));
  const draftP = byId(state.draft?.pid);
  const svc = [
    { t: "Документ", s: "от 10 ₽/стр.", ic: "doc", go: "doc", p: byId("doc") },
    { t: "Фото", s: "от 60 ₽", ic: "photo", go: "photo", p: byId("photo"), note: "10×15 пока нет" },
    { t: "Свои карты", s: "от 790 ₽", ic: "cards", go: "catalog-cards", p: null, tone: "pink" },
  ];
  return { html: `
    <div class="home-head">
      <div class="brandmark"><span class="dot">${icon("paw")}</span>Тюша</div>
      <button class="avatar" data-act="tab" data-tab="profile" aria-label="Профиль">${esc((state.user.name || "Т")[0])}</button>
    </div>
    <section class="hero">
      <div class="copy">
        <span class="eyebrow" style="color:var(--hero-muted)">${hello}${state.user.name ? ", " + esc(state.user.name) : ""}</span>
        <h1 class="display">Что напечатаем сегодня?</h1>
        <p>Документы, фото и колоды из ваших снимков. Заберёте в пункте выдачи.</p>
      </div>
      <span class="bubble">Привет!</span>
      <div class="mascot" aria-hidden="true"><img src="${IMG.waveBody}" alt=""><img class="paw" src="${IMG.wavePaw}" alt=""></div>
    </section>
    <div class="services">
      ${svc.map((x) => `<button class="service pressable" ${x.go === "catalog-cards" ? `data-act="cards-catalog"` : `data-go="${x.go}"`}>
        <span class="tile-icon ${x.tone || ""}">${icon(x.ic)}</span>
        <span class="t">${x.t}</span><span class="s">${x.s}</span>
        ${x.note ? `<span class="note">${icon("info")}${x.note}</span>` : ""}
      </button>`).join("")}
    </div>
    ${state.draft ? `<button class="card pressable" data-act="continue-draft" style="text-align:left">
      <div class="row"><span class="tile-icon pink">${icon("pen")}</span>
        <div class="grow"><div class="eyebrow">Продолжить</div><div style="font-weight:650">${esc(state.draft.title)}</div>
          <div class="small muted">${esc(draftP.title)} · сохранено ${esc(state.draft.updated)}</div></div>${icon("next")}</div>
      <div class="row small"><div class="grow progress"><i style="width:${Math.round(state.draft.photos / draftP.cards * 100)}%"></i></div>
        <span class="muted tabular">${state.draft.photos} из ${draftP.cards} фото</span></div>
    </button>` : ""}
    ${active ? `<button class="card pressable" data-go="order" data-id="${active.id}" style="text-align:left">
      <div class="row">${orderThumb(active)}<div class="grow"><div class="eyebrow">Заказ №${active.id}</div>
        <div style="font-weight:650">${esc(active.title)}</div></div>${statusPill(active.status)}</div>
      ${activeTrack(active)}
      <div class="small muted">${esc(NEXT_STEP[active.status] || "")}</div>
    </button>` : ""}
    <div class="h-section"><h2>Популярное</h2><a href="#" data-act="tab" data-tab="catalog">Весь каталог</a></div>
    <div class="hscroll">${PRODUCTS.filter((p) => p.cat === "cards").map(productCard).join("")}</div>
  ` };
};

function activeTrack(o) {
  const at = FLOW.findIndex((f) => f[0] === o.status);
  return `<div class="track" aria-hidden="true">${FLOW.map((_, i) => `<i class="${i < at ? "done" : i === at ? "now" : ""}"></i>`).join("")}</div>`;
}

function productCard(p) {
  const a = availability(p);
  return `<button class="product pressable ${a.ok ? "" : "off"}" data-go="product" data-id="${p.id}">
    <div class="art" style="background:${artBg[p.art]}">${productArt(p)}</div>
    <div class="meta"><span class="t">${esc(p.title)}</span><span class="s">${esc(p.sub)}</span>
      <span class="p tabular">${p.price ? rub(p.price) : esc(p.priceFrom)}</span>${availLine(p)}</div>
  </button>`;
}

SCREENS.catalog = () => {
  const cats = [["all", "Все"], ["cards", "Карты"], ["docs", "Документы"], ["photo", "Фото"]];
  const q = state.q.trim().toLowerCase();
  const list = PRODUCTS.filter((p) => (state.catCat === "all" || p.cat === state.catCat) &&
    (!q || (p.title + " " + p.sub).toLowerCase().includes(q)));
  return { html: `
    <div style="padding-top:12px" class="h-section"><h1 class="display" style="font-size:26px">Каталог</h1></div>
    <label class="search">${icon("search")}<input class="input" id="q" type="search" placeholder="Колода, мемори, документ…" value="${esc(state.q)}" data-model="q" autocomplete="off"></label>
    <div class="chips">${cats.map(([v, t]) => `<button class="chip ${state.catCat === v ? "on" : ""}" data-act="set" data-model="catCat" data-value="${v}">${t}</button>`).join("")}</div>
    ${list.length ? `<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px">${list.map(productCard).join("")}</div>`
      : `<div class="empty"><img src="${IMG.face}" alt=""><h3>Ничего не нашлось</h3><p>Попробуйте другое слово или откройте все услуги.</p>
        <button class="btn soft sm" data-act="clear-search">Показать всё</button></div>`}
  ` };
};

SCREENS.product = ({ id }) => {
  const p = byId(id);
  const a = availability(p);
  const isCards = p.cat === "cards";
  const cta = !a.ok ? null : isCards ? ["Собрать колоду", "start-deck"] : p.id === "doc" ? ["Загрузить файл", "go-doc"] : ["Выбрать фото", "go-photo"];
  return {
    html: `${topbar(p.title)}
    <div class="card" style="padding:0;overflow:hidden"><div class="product" style="box-shadow:none;border-radius:0">
      <div class="art pressable" style="background:${artBg[p.art]};aspect-ratio:5/4">${productArt(p, true)}</div></div>
      <div style="padding:2px 18px 18px;display:flex;flex-direction:column;gap:10px">
        <h1 class="display" style="font-size:24px">${esc(p.title)}</h1>
        <div class="muted">${esc(p.sub)}</div>
        <div class="row" style="justify-content:space-between"><b class="display tabular" style="font-size:22px">${p.price ? rub(p.price) : esc(p.priceFrom)}</b>${availLine(p)}</div>
      </div></div>
    ${!a.ok ? `<div class="notice no">${icon("warn")}<div><b>Сейчас недоступно</b><span>${esc(a.reason)}. Оформить заказ можно будет, как только оператор пополнит запас.</span></div></div>
      <div class="card flat"><div class="row"><div class="grow"><div style="font-weight:600">Сообщить, когда появится</div><div class="small muted">Пришлём сообщение в Telegram</div></div>
        <button class="switch" role="switch" aria-checked="${!!state.waitlist?.[p.id]}" data-act="waitlist" data-id="${p.id}" aria-label="Сообщить о поступлении"></button></div></div>` : ""}
    ${p.includes ? `<div class="card"><div class="eyebrow">Что входит</div><div class="list">${p.includes.map(([ic, t]) =>
      `<div class="list-item"><span class="tile-icon">${icon(ic)}</span><span class="t">${esc(t)}</span></div>`).join("")}</div></div>` : ""}
    ${p.reqs ? `<div class="card"><div class="eyebrow">Требования к фото</div><div class="list">${p.reqs.map((t) =>
      `<div class="list-item"><span style="color:var(--ok);--ic2:var(--ok)">${icon("check", "sm")}</span><span>${esc(t)}</span></div>`).join("")}</div></div>` : ""}
    <div class="card flat"><div class="row"><span class="tile-icon">${icon("clock")}</span><div class="grow"><div style="font-weight:600">${esc(p.days)}</div>
      <div class="small muted">Ориентировочный срок после оплаты. Забрать — в пункте выдачи.</div></div></div></div>`,
    dock: cta ? dockBar(p.price ?? null, cta[0], cta[1], { sub: "Стоимость" }) :
      `<div class="dock"><div class="bar glass solo"><button class="btn ghost block" disabled>Сейчас недоступно</button></div></div>`,
  };
};

// --- S04/S05: документ ---

function newDoc() {
  return { file: { name: "Договор аренды.pdf", pages: 12, size: 2.4, kind: "pdf", sample: true, ok: true },
    upload: null, error: null, format: "A4", color: false, duplex: true, range: "all", rangeText: "1-3, 5", copies: 1 };
}

SCREENS.doc = () => {
  const d = state.doc;
  const f = d.file;
  const up = d.upload;
  return {
    html: `${topbar("Печать документа")}
    ${steps(["Файл", "Настройки", "Проверка", "Оплата"], 0)}
    <label class="drop">
      <input type="file" id="doc-file" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" data-file="doc">
      <span class="tile-icon">${icon("file-add")}</span>
      <span class="grow"><b style="display:block">Выберите файл</b><span class="small muted">PDF, JPG или PNG · до 50 МБ · до 200 страниц</span></span>
    </label>
    ${up ? `<div class="card"><div class="row"><div class="file" style="box-shadow:none;padding:0;flex:1;min-width:0"><span class="doc-thumb"></span>
        <div class="grow" style="min-width:0"><div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(up.name)}</div>
        <div class="small muted tabular">${up.size.toFixed(1)} МБ</div></div></div></div>
      <div class="analysis">${[["Загружаем файл", 0], ["Проверяем формат", 1], ["Считаем страницы", 2]].map(([t, i]) =>
        `<div class="step ${up.step > i ? "done" : up.step === i ? "now" : ""}"><span class="dot">${up.step > i ? icon("check") : ""}</span>${t}${i === 0 && up.step === 0 ? ` · <span class="tabular">${up.pct}%</span>` : ""}</div>`).join("")}</div>
      <div class="progress"><i style="width:${Math.round((up.step + (up.step === 0 ? up.pct / 100 : 0)) / 3 * 100)}%"></i></div></div>` : ""}
    ${d.error ? `<div class="notice no">${icon("warn")}<div><b>${esc(d.error.title)}</b><span>${esc(d.error.text)}</span></div></div>` : ""}
    ${f && !up ? `<div class="file"><span class="doc-thumb" ${f.preview ? `style="background:url('${f.preview}') center/cover"` : ""}></span>
        <div class="grow" style="min-width:0"><div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(f.name)}</div>
        <div class="small muted tabular">${f.pages} ${plural(f.pages, "страница", "страницы", "страниц")} · ${f.size.toFixed(1)} МБ${f.sample ? " · пример" : ""}</div></div>
        <span class="pill ok">${icon("check")}Готов</span></div>` : ""}
    <div class="notice info">${icon("info")}<div><b>Принимаем PDF, JPG и PNG</b><span>Документ Word сохраните как PDF: так страницы точно напечатаются как на экране.</span></div></div>`,
    dock: dockBar(null, "Настроить печать", "", { go: "doc-settings", disabled: !f || !!up }),
  };
};

SCREENS["doc-settings"] = () => {
  const d = state.doc;
  const q = quoteDoc(d);
  const sel = docSelected(d) || new Set();
  const shown = Math.min(d.file.pages, 24);
  return {
    html: `${topbar("Настройки печати", d.file.name)}
    ${steps(["Файл", "Настройки", "Проверка", "Оплата"], 1)}
    <div class="pages" aria-label="Страницы документа">${Array.from({ length: shown }, (_, i) =>
      `<div class="page ${d.file.preview ? "img" : ""} ${sel.has(i + 1) ? "" : "skip"} ${d.color ? "" : "bw"}" ${d.file.preview ? `style="background-image:url('${d.file.preview}')"` : ""}><b>${i + 1}</b></div>`).join("")}
      ${d.file.pages > shown ? `<div class="page" style="display:grid;place-items:center;background-image:none"><b style="position:static">+${d.file.pages - shown}</b></div>` : ""}</div>
    <div class="field"><span class="lbl">Формат бумаги</span>${seg("doc.format", d.format, [{ v: "A4", t: "A4", s: "210×297 мм" }, { v: "A5", t: "A5", s: "148×210 мм" }])}</div>
    <div class="field"><span class="lbl">Цвет</span>${seg("doc.color", String(d.color), [{ v: "false", t: "Чёрно-белая", s: `${TARIFF.doc[d.format].bw} ₽ за стр.` }, { v: "true", t: "Цветная", s: `${TARIFF.doc[d.format].color} ₽ за стр.` }])}</div>
    <div class="field"><span class="lbl">Стороны листа</span>${seg("doc.duplex", String(d.duplex), [{ v: "false", t: "Одна" }, { v: "true", t: "Две" }])}
      <span class="hint">${d.duplex ? `Двусторонняя печать: ${q.sheets} ${plural(q.sheets, "лист", "листа", "листов")} вместо ${(sel.size || 0) * d.copies}. Цена за страницу та же.` : "Каждая страница на отдельном листе."}</span></div>
    <div class="field"><span class="lbl">Страницы</span>${seg("doc.range", d.range, [{ v: "all", t: `Все ${d.file.pages}` }, { v: "some", t: "Выбрать" }])}
      ${d.range === "some" ? `<input class="input ${docSelected(d) ? "" : "bad"}" id="range" inputmode="numeric" value="${esc(d.rangeText)}" data-model="doc.rangeText" placeholder="Например: 1-3, 5">
        <span class="hint" style="${docSelected(d) ? "" : "color:var(--danger)"}">${docSelected(d) ? `Выбрано ${sel.size} из ${d.file.pages}` : `Укажите страницы от 1 до ${d.file.pages}, например: 1-3, 5`}</span>` : ""}</div>
    <div class="field"><div class="row" style="justify-content:space-between"><div><span class="lbl">Копии</span><span class="hint">Каждая копия — полный комплект</span></div>
      <div class="stepper"><button data-act="step" data-model="doc.copies" data-d="-1" aria-label="Меньше">${icon("minus")}</button><output class="tabular">${d.copies}</output>
      <button data-act="step" data-model="doc.copies" data-d="1" aria-label="Больше">${icon("plus")}</button></div></div></div>`,
    dock: dockBar(q.total, "Проверить заказ", "review-doc", { disabled: !q.valid }),
  };
};

// --- фото ---

SCREENS.photo = () => {
  const j = state.photoJob;
  const q = quotePhoto(j);
  const bad = j.photos.filter(lowRes).length;
  return {
    html: `${topbar("Печать фото")}
    ${steps(["Фото", "Настройки", "Проверка", "Оплата"], j.photos.length ? 1 : 0)}
    <div class="photos">${j.photos.map((ph, i) => `<div class="photo" style="${photoStyle(ph)}"><span class="n">${i + 1}</span>${lowRes(ph) ? `<span class="bad" title="Низкое разрешение">${icon("warn")}</span>` : ""}</div>`).join("")}
      <label class="photo add" aria-label="Добавить фото"><input type="file" id="photo-files" accept="image/jpeg,image/png" multiple data-file="photo">${icon("upload", "lg")}</label></div>
    ${bad ? `<div class="notice warn">${icon("warn")}<div><b>${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением</b><span>На ${j.format === "a4" ? "A4" : "A5"} может получиться нерезко. Лучше заменить или выбрать формат меньше.</span></div></div>` : ""}
    <div class="field"><span class="lbl">Размер</span>${seg("photoJob.format", j.format, [
      { v: "10x15", t: "10×15", s: "нет бумаги", off: MATERIALS.photo10.left === 0 },
      { v: "a5", t: "A5", s: `${TARIFF.photo.a5} ₽` }, { v: "a4", t: "A4", s: `${TARIFF.photo.a4} ₽` }])}
      <span class="hint">10×15 вернётся, когда оператор пополнит фотобумагу.</span></div>
    <div class="field"><div class="row" style="justify-content:space-between"><div><span class="lbl">Копии каждого фото</span></div>
      <div class="stepper"><button data-act="step" data-model="photoJob.copies" data-d="-1" aria-label="Меньше">${icon("minus")}</button><output class="tabular">${j.copies}</output>
      <button data-act="step" data-model="photoJob.copies" data-d="1" aria-label="Больше">${icon("plus")}</button></div></div></div>`,
    dock: dockBar(q.total, "Проверить заказ", "review-photo", { disabled: !q.valid }),
  };
};

// --- S06: конструктор карт ---

SCREENS.deck = () => {
  const dk = state.deck;
  const p = byId(dk.pid);
  const layout = deckLayout(dk);
  const bad = dk.photos.filter(lowRes).length;
  const maxPhotos = p.id === "memory" ? 24 : p.cards;
  return {
    html: `${topbar(p.title, dk.saved ? "Черновик сохранён" : "")}
    ${steps(["Фото", "Макет", "Проверка", "Оплата"], 1)}
    <div class="h-section"><h2>Фото <span class="muted tabular" style="font-weight:500">${dk.photos.length} из ${maxPhotos}</span></h2>
      ${dk.photos.length > 1 ? `<a href="#" data-act="shuffle">Перемешать</a>` : ""}</div>
    <div class="photos">${dk.photos.map((ph, i) => `<button class="photo ${state.swapFrom === i ? "sel" : ""}" style="${photoStyle(ph)}" data-act="swap" data-i="${i}" aria-label="Фото ${i + 1}">
        <span class="n">${i + 1}</span>${lowRes(ph) ? `<span class="bad">${icon("warn")}</span>` : ""}</button>`).join("")}
      ${dk.photos.length < maxPhotos ? `<label class="photo add" aria-label="Добавить фото"><input type="file" id="deck-files" accept="image/jpeg,image/png" multiple data-file="deck">${icon("upload", "lg")}</label>` : ""}</div>
    <div class="small muted">${state.swapFrom != null ? "Теперь нажмите на фото, с которым поменять местами." : "Нажмите на два фото, чтобы поменять их местами. Нажмите на карту, чтобы поправить обрезку и подпись."}</div>
    ${bad ? `<div class="notice warn">${icon("warn")}<div><b>${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением</b><span>Отмечены значком. На карте 63×88 мм такое фото может выйти нерезким.</span></div></div>` : ""}
    <div class="h-section"><h2>Макет · ${layout.length} ${plural(layout.length, "карта", "карты", "карт")}</h2></div>
    <div class="deck" style="${p.id === "memory" ? "grid-template-columns:repeat(6,1fr)" : ""}">${layout.map((c) => c.memo
      ? `<button class="pc memo" data-act="edit-card" data-i="${c.i}" style="position:relative;animation-delay:${Math.min(c.i * 12, 400)}ms"><div class="win" style="${photoStyle(c.ph)};inset:8%"></div></button>`
      : `<button data-act="edit-card" data-i="${c.i}" style="display:block;animation:deal .5s var(--spring) both;animation-delay:${Math.min(c.i * 12, 400)}ms">${playingCard({ rank: c.rank, suit: c.suit, ph: c.ph, cap: c.o.cap, zoom: c.o.zoom || 1, x: c.o.x ?? 50, y: c.o.y ?? 50, style: "position:relative;aspect-ratio:63/88" })}</button>`).join("")}</div>`,
    dock: dockBar(quoteDeck(dk).total, "Проверить макет", "review-deck", { disabled: !dk.photos.length }),
  };
};

function editCardSheet(i) {
  const dk = state.deck;
  const c = deckLayout(dk)[i];
  const o = dk.edits[i] || {};
  const cardHtml = c.memo ? `<div class="pc memo editor-card" style="aspect-ratio:1"><div class="win" style="${photoStyle(c.ph)};inset:8%"></div></div>`
    : playingCard({ rank: c.rank, suit: c.suit, ph: c.ph, cap: o.cap, zoom: o.zoom || 1, x: o.x ?? 50, y: o.y ?? 50, cls: "editor-card" });
  return `<div class="grab"></div>
    <div class="row" style="justify-content:space-between"><h3>${c.memo ? `Карточка ${i + 1}` : c.rank === "JOKER" ? "Джокер" : `${c.rank} ${SUITS[c.suit][0]}`}</h3>
      <button class="icon-btn" data-act="close-sheet" aria-label="Закрыть">${icon("close")}</button></div>
    <div id="editor-preview" style="display:flex;justify-content:center">${cardHtml}</div>
    <div class="field"><span class="lbl">Фото на карте</span><div class="photos" style="grid-template-columns:repeat(6,1fr)">${dk.photos.map((ph, k) =>
      `<button class="photo ${k === c.photoIndex ? "sel" : ""}" style="${photoStyle(ph)}" data-act="card-photo" data-i="${i}" data-k="${k}" aria-label="Фото ${k + 1}"></button>`).join("")}</div></div>
    ${c.memo ? "" : `<div class="field"><label for="zoom">Масштаб <span class="muted tabular">${Math.round((o.zoom || 1) * 100)}%</span></label>
      <input type="range" id="zoom" min="1" max="2" step="0.05" value="${o.zoom || 1}" data-edit="zoom" data-i="${i}"></div>
    <div class="field"><label for="posx">Сдвиг по горизонтали</label><input type="range" id="posx" min="0" max="100" value="${o.x ?? 50}" data-edit="x" data-i="${i}"></div>
    <div class="field"><label for="posy">Сдвиг по вертикали</label><input type="range" id="posy" min="0" max="100" value="${o.y ?? 50}" data-edit="y" data-i="${i}"></div>
    <div class="field"><label for="cap">Подпись <span class="muted">до 18 символов</span></label>
      <input class="input" id="cap" maxlength="18" value="${esc(o.cap || "")}" placeholder="Например: Лето 2026" data-edit="cap" data-i="${i}"></div>`}
    <button class="btn primary block" data-act="close-sheet"><span class="label">Готово</span></button>`;
}

// --- S07/S08: проверка и подтверждение ---

function reviewData() {
  const r = state.review;
  if (r.kind === "deck") {
    const dk = state.deck, p = byId(dk.pid), q = quoteDeck(dk);
    const warns = [];
    const bad = dk.photos.filter(lowRes).length;
    if (bad) warns.push(["warn", `${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением`, "Может выйти нерезко. Вернитесь, чтобы заменить, или оставьте как есть."]);
    if (p.id === "memory" && dk.photos.length < 24) warns.push(["warn", `Фото: ${dk.photos.length} из 24`, "Недостающие пары заполнятся повтором ваших фото."]);
    return { p, q, title: p.title, flow: ["Фото", "Макет", "Проверка", "Оплата"],
      rows: [["Набор", p.title], ["Карт", String(p.cards)], ["Фото", String(dk.photos.length)], ["Бумага", "Картон 300 г/м²"], ["Срок", p.days]],
      warns, agree: "Макет проверен. После оплаты он фиксируется: изменения — только по согласованию с оператором.",
      art: `<div class="row" style="gap:8px;justify-content:center">${deckLayout(dk).slice(0, 3).map((c) => c.memo
        ? `<div class="pc memo" style="width:30%;position:relative"><div class="win" style="${photoStyle(c.ph)};inset:8%"></div></div>`
        : `<div style="width:28%">${playingCard({ rank: c.rank, suit: c.suit, ph: c.ph, cap: c.o.cap, zoom: c.o.zoom || 1, x: c.o.x ?? 50, y: c.o.y ?? 50, style: "position:relative;aspect-ratio:63/88" })}</div>`).join("")}</div>` };
  }
  if (r.kind === "doc") {
    const d = state.doc, p = byId("doc"), q = quoteDoc(d), sel = docSelected(d);
    return { p, q, title: d.file.name, flow: ["Файл", "Настройки", "Проверка", "Оплата"],
      rows: [["Файл", d.file.name], ["Страницы", d.range === "all" ? `все ${d.file.pages}` : `${sel.size} из ${d.file.pages}`], ["Формат", d.format],
        ["Цвет", d.color ? "цветная" : "чёрно-белая"], ["Стороны", d.duplex ? "две" : "одна"], ["Копии", String(d.copies)], ["Листов", String(q.sheets)], ["Срок", p.days]],
      warns: d.duplex && sel.size % 2 ? [["info", "Последняя страница без оборота", "Нечётное число страниц — оборот последнего листа останется чистым."]] : [],
      agree: "Параметры печати проверены." };
  }
  const j = state.photoJob, p = byId("photo"), q = quotePhoto(j);
  const bad = j.photos.filter(lowRes).length;
  return { p, q, title: `Фото ${j.format === "a4" ? "A4" : "A5"}`, flow: ["Фото", "Настройки", "Проверка", "Оплата"],
    rows: [["Фото", String(j.photos.length)], ["Размер", j.format === "a4" ? "A4" : "A5"], ["Копии", String(j.copies)], ["Бумага", "Фотобумага"], ["Срок", p.days]],
    warns: bad ? [["warn", `${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением`, "Может выйти нерезко."]] : [],
    agree: "Фото и параметры печати проверены." };
}

SCREENS.review = () => {
  const r = reviewData();
  const qty = r.p.cat === "docs" ? r.q.sheets : 1;
  const a = availability(r.p, qty);
  return {
    html: `${topbar("Проверка заказа")}
    ${steps(r.flow, 2)}
    ${r.art ? `<div class="card" style="background:${artBg[r.p.art]};box-shadow:none;padding:20px">${r.art}</div>` : ""}
    ${r.warns.map(([tone, t, s]) => `<div class="notice ${tone}">${icon(tone === "warn" ? "warn" : "info")}<div><b>${esc(t)}</b><span>${esc(s)}</span></div></div>`).join("")}
    ${a.ok ? `<div class="notice ok">${icon("check")}<div><b>Материалы в наличии</b><span>Зарезервируем их за вами сразу после оплаты.</span></div></div>`
      : `<div class="notice no">${icon("warn")}<div><b>Заказ сейчас нельзя оплатить</b><span>${esc(a.reason)}. Деньги не спишутся.</span></div></div>`}
    <div class="card"><div class="eyebrow">Заказ</div><dl class="kv">${r.rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>
    <div class="card"><div class="eyebrow">Стоимость</div><dl class="kv">${r.q.lines.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${rub(v)}</dd>`).join("")}
      <span class="sep"></span><dt class="total">Итого</dt><dd class="total">${rub(r.q.total)}</dd></dl></div>
    <button class="card flat pressable" data-go="pickup" style="text-align:left"><div class="row"><span class="tile-icon">${icon("pin")}</span>
      <div class="grow"><div style="font-weight:600">Самовывоз</div><div class="small muted">ул. Лесная, 5, офис 12 · пример адреса</div></div>${icon("next")}</div></button>
    <button class="check" role="checkbox" aria-checked="${state.agreed}" data-act="agree"><span class="box">${icon("check")}</span><span>${esc(r.agree)}</span></button>`,
    dock: dockBar(r.q.total, a.ok ? (state.agreed ? "Перейти к оплате" : "Отметьте проверку") : "Недоступно", "", { go: "pay", disabled: !a.ok || !state.agreed }),
  };
};

// --- S09: оплата ---

SCREENS.pay = () => {
  const r = reviewData();
  const pay = state.pay;
  if (pay.phase === "processing") {
    const stepsList = [["Платёж создан", "Сумма зафиксирована"], ["Ждём подтверждение банка", "Обычно до 30 секунд"], ["Передаём заказ оператору", "Резервируем материалы"]];
    return { html: `${topbar("Оплата", r.title)}
      <div class="card" style="align-items:center;text-align:center;padding:26px 18px">
        <img src="${IMG.face}" alt="" style="width:120px;animation:breathe 3s ease-in-out infinite">
        <h2 class="display" style="font-size:22px">Проверяем оплату</h2>
        <p class="muted" style="margin:0">Не закрывайте приложение. Если закроете — заказ не потеряется, статус придёт в Telegram.</p>
      </div>
      <div class="card"><div class="analysis">${stepsList.map(([t, s], i) =>
        `<div class="step ${pay.step > i ? "done" : pay.step === i ? "now" : ""}"><span class="dot">${pay.step > i ? icon("check") : ""}</span><div><div>${t}</div><div class="small muted">${s}</div></div></div>`).join("")}</div>
        <div class="progress"><i style="width:${Math.min(100, pay.step * 34 + 8)}%"></i></div></div>` };
  }
  return {
    html: `${topbar("Оплата", r.title)}
    ${steps(r.flow, 3)}
    <div class="card" style="align-items:center;text-align:center;gap:4px"><span class="eyebrow">К оплате</span>
      <b class="display tabular" style="font-size:34px">${rub(r.q.total)}</b><span class="small muted">Сумму рассчитал сервер по действующему тарифу</span></div>
    <div class="card"><div class="eyebrow">Способ оплаты</div><div class="list">
      ${[["sbp", "qr", "СБП", "Через приложение банка, без комиссии"], ["card", "card", "Банковская карта", "Visa, Mastercard, Мир"]].map(([v, ic, t, s]) =>
        `<button class="list-item" data-act="set" data-model="pay.method" data-value="${v}" role="radio" aria-checked="${pay.method === v}">
          <span class="tile-icon">${icon(ic)}</span><span class="grow"><span class="t" style="display:block">${t}</span><span class="s">${s}</span></span>
          <span class="check" style="padding:0;background:none;width:auto" aria-checked="${pay.method === v}"><span class="box" style="border-radius:50%">${icon("check")}</span></span></button>`).join("")}
    </div></div>
    <div class="notice info">${icon("shield")}<div><b>Демо-режим</b><span>Деньги не списываются. В рабочей версии откроется страница платёжной системы.</span></div></div>`,
    dock: dockBar(r.q.total, `Оплатить ${rub(r.q.total)}`, "pay-now", { sub: pay.method === "sbp" ? "СБП" : "Картой" }),
  };
};

SCREENS.success = ({ id }) => {
  const o = state.orders.find((x) => x.id === +id);
  return {
    html: `<div class="success">
      <div class="art"><img src="${IMG.printer}" alt=""></div>
      <span class="pill ok">${icon("check")}Оплачено</span>
      <h1 class="display">Заказ №${o.id} принят</h1>
      <p class="muted" style="margin:0;max-width:32ch">Он ждёт оператора: тот проверит макет, подготовит бумагу и запустит печать. О каждом шаге напишем в Telegram.</p>
      <div class="card" style="width:100%;text-align:left">${activeTrack(o)}<div class="row small"><span class="grow muted">Сейчас: ${esc(STATUS[o.status][0].toLowerCase())}</span><b>${rub(o.amount)}</b></div></div>
    </div>`,
    dock: `<div class="dock"><div class="bar glass solo" style="gap:8px"><button class="btn ghost" data-act="home" style="flex:.8">На главную</button>
      <button class="btn primary" data-act="open-order" data-id="${o.id}"><span class="label">Открыть заказ</span></button></div></div>`,
  };
};

// --- S11: мои заказы ---

const GROUPS = {
  active: (o) => !["completed", "cancelled", "refunded"].includes(o.status),
  done: (o) => o.status === "completed",
  cancelled: (o) => ["cancelled", "refunded", "refund_pending"].includes(o.status),
};
SCREENS.orders = () => {
  const list = state.orders.filter(GROUPS[state.ordersTab]);
  const counts = Object.fromEntries(Object.entries(GROUPS).map(([k, f]) => [k, state.orders.filter(f).length]));
  return { html: `
    <div style="padding-top:12px"><h1 class="display" style="font-size:26px">Заказы</h1></div>
    ${seg("ordersTab", state.ordersTab, [{ v: "active", t: `Активные · ${counts.active}` }, { v: "done", t: "Выданные" }, { v: "cancelled", t: "Отменённые" }])}
    ${list.length ? list.map((o) => `<button class="card pressable order-card" data-go="order" data-id="${o.id}">
        <div class="row">${orderThumb(o)}<div class="grow"><div style="font-weight:650">${esc(o.title)}</div>
          <div class="small muted">№${o.id} · ${esc(o.created)}</div></div><b class="tabular">${rub(o.amount)}</b></div>
        <div class="row" style="justify-content:space-between">${statusPill(o.status)}
          ${o.unread ? `<span class="pill">${icon("chat")}${o.unread} ${plural(o.unread, "новое", "новых", "новых")}</span>` : icon("next")}</div>
        ${GROUPS.active(o) && FLOW.some((f) => f[0] === o.status) ? activeTrack(o) : ""}
      </button>`).join("")
      : `<div class="empty"><img src="${IMG.face}" alt=""><h3>${state.ordersTab === "active" ? "Активных заказов нет" : state.ordersTab === "done" ? "Выданных заказов пока нет" : "Отменённых заказов нет"}</h3>
        <p>${state.ordersTab === "active" ? "Распечатайте документ, фото или соберите свою колоду." : "Здесь появятся заказы, когда они будут."}</p>
        ${state.ordersTab === "active" ? `<button class="btn primary sm" data-act="tab" data-tab="catalog"><span class="label">Сделать первый заказ</span></button>` : ""}</div>`}
  ` };
};

// --- S10: детали заказа ---

SCREENS.order = ({ id }) => {
  const o = state.orders.find((x) => x.id === +id);
  const p = byId(o.pid);
  const at = FLOW.findIndex((f) => f[0] === o.status);
  const inFlow = at >= 0;
  return {
    html: `${topbar(`Заказ №${o.id}`, o.created)}
    <div class="card">
      <div class="row">${orderThumb(o)}<div class="grow"><div style="font-weight:650">${esc(o.title)}</div><div class="small muted">${esc(o.sub)}</div></div></div>
      <div class="row" style="justify-content:space-between">${statusPill(o.status)}<b class="tabular">${rub(o.amount)}</b></div>
      <div class="small" style="color:var(--text);opacity:.85">${esc(o.reason || NEXT_STEP[o.status] || "")}</div>
    </div>
    ${o.status === "ready_for_pickup" ? `<button class="card pressable" data-go="pickup" style="text-align:left;background:var(--ok-soft);box-shadow:none">
      <div class="row"><span class="tile-icon" style="background:var(--surface);color:var(--ok);--ic2:var(--ok)">${icon("box")}</span>
      <div class="grow"><div style="font-weight:650">Можно забирать</div><div class="small muted">ул. Лесная, 5, офис 12 · сегодня до 20:00</div></div>${icon("next")}</div></button>` : ""}
    ${inFlow ? `<div class="card"><div class="eyebrow">Ход заказа</div><ol class="timeline">${FLOW.map(([k, t, ic], i) =>
      `<li class="${i < at || (i === at && k === "completed") ? "done" : i === at ? "now" : ""}"><span class="node"><i>${icon(ic)}</i></span>
        <div><div class="t">${t}</div><div class="s">${esc(o.times[k] || (i === at ? "сейчас" : ""))}</div></div></li>`).join("")}</ol></div>` : ""}
    <button class="card pressable" data-go="chat" data-id="${o.id}" style="text-align:left"><div class="row"><span class="tile-icon">${icon("chat")}</span>
      <div class="grow"><div style="font-weight:600">Переписка с оператором</div><div class="small muted">${o.chat.length ? esc(o.chat.at(-1).text).slice(0, 60) + "…" : "Вопрос по заказу? Напишите"}</div></div>
      ${o.unread ? `<span class="pill">${o.unread}</span>` : icon("next")}</div></button>
    <div class="card"><div class="eyebrow">Детали</div><dl class="kv">
      <dt>Услуга</dt><dd>${esc(p.title)}</dd><dt>Состав</dt><dd>${esc(o.sub)}</dd><dt>Оплачено</dt><dd>${rub(o.amount)}</dd>
      <dt>Макет</dt><dd>зафиксирован при оплате</dd></dl></div>
    ${o.status === "paid" ? `<button class="btn ghost block" data-act="ask-cancel" data-id="${o.id}" style="color:var(--danger)">Отменить и вернуть деньги</button>` : ""}`,
    dock: `<div class="dock"><div class="bar glass solo"><button class="btn primary block" data-act="repeat" data-id="${o.id}">${icon("repeat")}<span class="label">Повторить заказ</span></button></div></div>`,
  };
};

// --- S12: комментарии ---

SCREENS.chat = ({ id }) => {
  const o = state.orders.find((x) => x.id === +id);
  if (o.unread) o.unread = 0;
  const waiting = o.chat.length && !o.chat.at(-1).me && o.chat.at(-1).text.includes("Осветлить");
  return {
    html: `${topbar("Оператор", `Заказ №${o.id}`)}
    <div class="chat">
      <span class="day">${esc(o.created.split(",")[0])}</span>
      ${o.chat.length ? "" : `<div class="empty" style="padding:10px"><img src="${IMG.face}" alt="" style="width:96px"><p>Спросите что угодно о заказе — оператор ответит здесь, а уведомление придёт в Telegram.</p></div>`}
      ${o.chat.map((m) => `<div class="msg ${m.me ? "me" : "them"}">${m.me ? "" : `<div class="who">${esc(m.who)}</div>`}${esc(m.text)}<time>${esc(m.at)}</time></div>`).join("")}
      ${o.typing ? `<div class="msg them"><div class="who">Оператор Аня</div><span class="muted">печатает…</span></div>` : ""}
      ${waiting && !o.typing ? `<div class="quick">${["Осветлить", "Оставить как есть"].map((t) => `<button data-act="quick" data-id="${o.id}" data-text="${t}">${t}</button>`).join("")}</div>` : ""}
    </div>`,
    dock: `<div class="dock"><form class="bar glass" data-form="chat" data-id="${o.id}" style="padding:8px 8px 8px 16px">
      <input id="chat-input" class="input" style="background:transparent;min-height:40px;padding:0" placeholder="Сообщение оператору" autocomplete="off" maxlength="1000">
      <button class="btn primary" style="flex:none;min-height:44px;width:44px;padding:0;border-radius:14px" aria-label="Отправить">${icon("send")}</button></form></div>`,
  };
};

// --- S13: профиль ---

SCREENS.profile = () => {
  const u = state.user;
  return { html: `
    <div style="padding-top:12px"><h1 class="display" style="font-size:26px">Профиль</h1></div>
    <div class="card"><div class="row"><span class="avatar" style="width:56px;height:56px;font-size:22px">${esc((u.name || "Т")[0])}</span>
      <div class="grow"><div style="font-weight:650;font-size:17px">${esc(u.name || "Гость Тюши")}</div>
      <div class="small muted">${u.username ? "@" + esc(u.username) + " · " : ""}вход через Telegram</div></div>
      <span class="pill ok">${icon("shield")}Защищено</span></div></div>
    <div class="card"><div class="eyebrow">Уведомления в Telegram</div><div class="list">
      ${[["status", "Статус заказа", "Оплата, печать, готовность"], ["pickup", "Напоминание о выдаче", "Если заказ ждёт больше 3 дней"], ["news", "Новые шаблоны", "Не чаще раза в месяц"]].map(([k, t, s]) =>
        `<div class="list-item"><div class="grow"><div class="t">${t}</div><div class="s">${s}</div></div>
        <button class="switch" role="switch" aria-checked="${state.notify[k]}" data-act="notify" data-k="${k}" aria-label="${t}"></button></div>`).join("")}
    </div></div>
    <div class="card" style="padding:4px 16px"><div class="list">
      ${[["pickup", "pin", "Пункт выдачи", "Адрес, часы работы"], ["help", "info", "Как это работает", "Пять шагов от фото до печати"], ["privacy", "lock", "Файлы и конфиденциальность", "Сколько храним и кто видит"]].map(([k, ic, t, s]) =>
        `<button class="list-item" ${k === "pickup" ? `data-go="pickup"` : `data-act="sheet" data-sheet="${k}"`}><span class="tile-icon">${icon(ic)}</span>
        <span class="grow"><span class="t" style="display:block">${t}</span><span class="s">${s}</span></span>${icon("next")}</button>`).join("")}
    </div></div>
    <div class="field"><span class="lbl">Оформление</span>${seg("theme", state.theme, [{ v: "auto", t: "Как в Telegram" }, { v: "light", t: "Светлое" }, { v: "dark", t: "Тёмное" }])}</div>
    <p class="foot">Демо-версия: заказы и адрес — примеры.<br>Иконки — <a href="https://www.figma.com/community/file/1166831539721848736" target="_blank" rel="noopener">Solar by 480 Design</a>, CC BY 4.0.</p>
  ` };
};

// --- S14: получение ---

SCREENS.pickup = () => {
  const day = (new Date().getDay() + 6) % 7;
  const hours = [["Пн–Пт", "10:00–20:00", [0, 1, 2, 3, 4]], ["Суббота", "11:00–18:00", [5]], ["Воскресенье", "выходной", [6]]];
  return {
    html: `${topbar("Пункт выдачи")}
    <div class="card" style="padding:0;overflow:hidden">
      <div style="height:130px;position:relative;background:
        radial-gradient(circle at 60% 55%, var(--blue-soft) 0 22%, transparent 23%),
        repeating-linear-gradient(0deg, var(--surface-2) 0 1px, transparent 1px 26px), repeating-linear-gradient(90deg, var(--surface-2) 0 1px, transparent 1px 26px), var(--surface)">
        <span style="position:absolute;left:60%;top:55%;transform:translate(-50%,-80%);color:var(--blue);--ic2:var(--pink-ink)">${icon("pin", "lg")}</span></div>
      <div style="padding:16px;display:flex;flex-direction:column;gap:10px">
        <div class="row"><div class="grow"><div style="font-weight:650;font-size:17px">ул. Лесная, 5, офис 12</div><div class="small muted">Вход со двора, 2 этаж · пример адреса</div></div>
        <button class="btn soft sm" data-act="copy" data-text="ул. Лесная, 5, офис 12">${icon("copy", "sm")}<span class="label">Копировать</span></button></div></div></div>
    <div class="card"><div class="eyebrow">Часы работы</div><dl class="kv">${hours.map(([d, h, days]) =>
      `<dt style="${days.includes(day) ? "color:var(--text);font-weight:650" : ""}">${d}${days.includes(day) ? " · сегодня" : ""}</dt><dd>${h}</dd>`).join("")}</dl></div>
    <div class="card"><div class="eyebrow">Как забрать</div><ol class="timeline">
      ${[["chat", "Дождитесь сообщения «Готов к выдаче»", "Оно придёт от Тюши в Telegram"], ["tag", "Назовите номер заказа", "Например: №1038"], ["eye", "Проверьте заказ на месте", "Если что-то не так — сразу скажите оператору"]].map(([ic, t, s]) =>
        `<li class="done"><span class="node"><i>${icon(ic)}</i></span><div><div class="t">${t}</div><div class="s">${s}</div></div></li>`).join("")}</ol></div>
    <div class="notice info">${icon("clock")}<div><b>Храним заказ 14 дней</b><span>Через 3 дня пришлём напоминание. Без предупреждения заказ не утилизируем.</span></div></div>`,
  };
};

// ---------- листы ----------

const SHEETS = {
  help: () => `<div class="grab"></div><h3>Как работает Тюша</h3>
    <ol class="timeline">${[["upload", "Загрузите файл или фото", "PDF, JPG, PNG"], ["tune", "Настройте печать", "Цена видна сразу"], ["card", "Оплатите", "Материалы резервируются за вами"],
      ["printer", "Оператор печатает", "Только после проверки принтера"], ["box", "Заберите заказ", "Напишем, когда будет готово"]].map(([ic, t, s]) =>
      `<li class="done"><span class="node"><i>${icon(ic)}</i></span><div><div class="t">${t}</div><div class="s">${s}</div></div></li>`).join("")}</ol>
    <button class="btn primary block" data-act="close-sheet"><span class="label">Понятно</span></button>`,
  privacy: () => `<div class="grab"></div><h3>Файлы и конфиденциальность</h3>
    <div class="list">${[["lock", "Файлы видите только вы и оператор", "Доступ — по временной ссылке внутри заказа"], ["clock", "Храним 30 дней после выдачи", "Потом удаляем исходники и макеты"], ["shield", "Вход через Telegram", "Пароль не нужен, данные карты мы не видим"]].map(([ic, t, s]) =>
      `<div class="list-item"><span class="tile-icon">${icon(ic)}</span><span class="grow"><span class="t" style="display:block">${t}</span><span class="s">${s}</span></span></div>`).join("")}</div>
    <button class="btn primary block" data-act="close-sheet"><span class="label">Понятно</span></button>`,
  cancel: (id) => {
    const o = state.orders.find((x) => x.id === +id);
    return `<div class="grab"></div><h3>Отменить заказ №${o.id}?</h3>
      <p class="muted" style="margin:0">Печать ещё не началась. Вернём ${rub(o.amount)} на карту, обычно за 1–7 дней.</p>
      <div class="row"><button class="btn ghost" data-act="close-sheet" style="flex:1">Оставить</button>
      <button class="btn primary" data-act="do-cancel" data-id="${o.id}" style="flex:1;background:var(--danger);box-shadow:none"><span class="label">Отменить</span></button></div>`;
  },
};

function openSheet(html, onRender) {
  closeSheet(true);
  const wrap = document.createElement("div");
  wrap.className = "sheet-wrap";
  wrap.innerHTML = `<div class="sheet" role="dialog" aria-modal="true">${html}</div>`;
  wrap.addEventListener("click", (e) => { if (e.target === wrap) closeSheet(); });
  document.body.appendChild(wrap);
  wrap.sheetRender = onRender;
  haptic("light");
  updateBackButton();
}
function closeSheet(instant = false) {
  const wrap = document.querySelector(".sheet-wrap");
  if (!wrap) return;
  if (instant) { wrap.remove(); return; }
  wrap.classList.add("out");
  setTimeout(() => { wrap.remove(); updateBackButton(); }, 220);
  render();
}
function refreshSheet() {
  const wrap = document.querySelector(".sheet-wrap");
  if (wrap?.sheetRender) morph(wrap.querySelector(".sheet"), wrap.sheetRender());
}

function toast(text, tone = "ok") {
  document.querySelector(".toast")?.remove();
  const el = document.createElement("div");
  el.className = "toast glass";
  el.innerHTML = `<span style="color:var(--${tone === "ok" ? "ok" : "danger"});--ic2:currentColor">${icon(tone === "ok" ? "check" : "warn", "sm")}</span>${esc(text)}`;
  document.body.appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 260); }, 2400);
}

function confetti() {
  const box = document.createElement("div");
  box.className = "confetti";
  const colors = ["#2563EB", "#F9D5DB", "#172033", "#8FB3FF", "#F4A6B5"];
  box.innerHTML = Array.from({ length: 46 }, (_, i) => {
    const left = Math.random() * 100, dur = 1.8 + Math.random() * 1.4, delay = Math.random() * .4;
    return `<i style="left:${left}%;background:${colors[i % colors.length]};--dx:${(Math.random() - .5) * 120}px;--rot:${Math.random() * 720 - 360}deg;animation-duration:${dur}s;animation-delay:${delay}s"></i>`;
  }).join("");
  document.body.appendChild(box);
  setTimeout(() => box.remove(), 3600);
}

// ---------- рендер ----------

function morph(el, html) {
  if (window.Idiomorph) window.Idiomorph.morph(el, html, { morphStyle: "innerHTML" });
  else el.innerHTML = html;
}
const tweenFrom = {};

function render(mode = "morph") {
  const view = current();
  const out = SCREENS[view.name](view.params || {});
  const hasTop = out.html.trimStart().startsWith("<header");
  const html = `<section class="screen ${hasTop ? "has-top" : ""} ${mode !== "morph" ? "enter-" + mode : ""}" data-view="${view.name}">${out.html}</section>`;
  if (mode === "morph") morph(stage(), html); else stage().innerHTML = html;

  const chrome = document.getElementById("chrome");
  if (!state.stack.length) {
    const tabs = [["home", "home", "Главная"], ["catalog", "catalog", "Каталог"], ["orders", "orders", "Заказы"], ["profile", "profile", "Профиль"]];
    const idx = tabs.findIndex((t) => t[0] === state.tab);
    const unread = state.orders.reduce((s, o) => s + (o.unread || 0), 0);
    morph(chrome, `<div class="tabbar"><nav class="glass" aria-label="Разделы">
      <span class="glider" style="transform:translateX(${idx * 100}%)"></span>
      ${tabs.map(([k, ic, t]) => `<button class="${k === state.tab ? "on" : ""}" data-act="tab" data-tab="${k}" aria-current="${k === state.tab ? "page" : "false"}">
        ${icon(ic)}${t}${k === "orders" && unread ? `<span class="badge">${unread}</span>` : ""}</button>`).join("")}
    </nav></div>`);
  } else {
    morph(chrome, out.dock || "");
  }
  // плавная смена цены
  document.querySelectorAll("[data-tween]").forEach((el) => {
    const key = el.dataset.tween, to = +el.dataset.value, from = tweenFrom[key] ?? to;
    tweenFrom[key] = to;
    if (from === to || matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = rub(to); return; }
    const t0 = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - t0) / 420), e = 1 - Math.pow(1 - k, 3);
      el.textContent = rub(from + (to - from) * e);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
  updateBackButton();
}

function updateBackButton() {
  if (!tg?.BackButton) return;
  if (state.stack.length || document.querySelector(".sheet-wrap")) tg.BackButton.show(); else tg.BackButton.hide();
}

function applyTheme() {
  const root = document.documentElement;
  if (state.theme === "auto") {
    if (tg?.colorScheme) root.dataset.theme = tg.colorScheme; else delete root.dataset.theme;
  } else root.dataset.theme = state.theme;
}

// ---------- действия ----------

function setPath(path, value) {
  const keys = path.split(".");
  let obj = state;
  keys.slice(0, -1).forEach((k) => { obj = obj[k]; });
  const last = keys.at(-1), old = obj[last];
  obj[last] = typeof old === "boolean" ? value === "true" || value === true : typeof old === "number" ? +value : value;
}

const ACT = {
  back,
  home: () => { state.stack = []; state.tab = "home"; render("tab"); window.scrollTo(0, 0); },
  tab: (el) => goTab(el.dataset.tab),
  set: (el) => {
    setPath(el.dataset.model, el.dataset.value);
    if (el.dataset.model === "theme") { store("theme", state.theme); applyTheme(); }
    if (el.dataset.model === "photoJob.format" || el.dataset.model === "doc.format") state.agreed = false;
    haptic("select");
    render();
  },
  step: (el) => {
    const keys = el.dataset.model.split(".");
    const obj = state[keys[0]];
    obj[keys[1]] = Math.min(20, Math.max(1, obj[keys[1]] + +el.dataset.d));
    haptic("select");
    render();
  },
  "cards-catalog": () => { state.tab = "catalog"; state.catCat = "cards"; state.stack = []; render("tab"); window.scrollTo(0, 0); },
  "clear-search": () => { state.q = ""; state.catCat = "all"; render(); },
  "go-doc": () => { state.doc = state.doc || newDoc(); push("doc"); },
  "go-photo": () => { state.photoJob = state.photoJob || { photos: SAMPLE_PHOTOS.slice(0, 3).map((p) => ({ ...p, sample: true })), format: "a5", copies: 1 }; push("photo"); },
  "start-deck": () => { const id = current().params.id; startDeck(id); push("deck"); },
  "continue-draft": () => { startDeck(state.draft.pid, state.draft.photos); push("deck"); },
  waitlist: (el) => {
    state.waitlist = state.waitlist || {};
    state.waitlist[el.dataset.id] = !state.waitlist[el.dataset.id];
    render();
    toast(state.waitlist[el.dataset.id] ? "Напишем, когда появится" : "Не будем напоминать");
  },
  swap: (el) => {
    const i = +el.dataset.i;
    if (state.swapFrom == null) { state.swapFrom = i; haptic("select"); return render(); }
    if (state.swapFrom !== i) {
      const ph = state.deck.photos;
      [ph[state.swapFrom], ph[i]] = [ph[i], ph[state.swapFrom]];
      haptic("medium");
      saveDraft();
    }
    state.swapFrom = null;
    render();
  },
  shuffle: () => {
    const ph = state.deck.photos;
    for (let i = ph.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [ph[i], ph[j]] = [ph[j], ph[i]]; }
    haptic("medium");
    saveDraft();
    stage().innerHTML = ""; // перезапустить анимацию раздачи
    render();
  },
  "edit-card": (el) => {
    const i = +el.dataset.i;
    openSheet(editCardSheet(i), () => editCardSheet(i));
  },
  "card-photo": (el) => {
    const i = +el.dataset.i;
    state.deck.edits[i] = { ...(state.deck.edits[i] || {}), photo: +el.dataset.k };
    saveDraft();
    refreshSheet();
  },
  "close-sheet": () => closeSheet(),
  sheet: (el) => openSheet(SHEETS[el.dataset.sheet]()),
  "review-doc": () => { state.review = { kind: "doc" }; state.agreed = false; push("review"); },
  "review-photo": () => { state.review = { kind: "photo" }; state.agreed = false; push("review"); },
  "review-deck": () => { state.review = { kind: "deck" }; state.agreed = false; push("review"); },
  agree: () => { state.agreed = !state.agreed; haptic("select"); render(); },
  "pay-now": (el) => {
    el.classList.add("loading");
    state.pay.phase = "processing";
    state.pay.step = 0;
    render();
    const tick = (n, delay) => setTimeout(() => { state.pay.step = n; if (current().name === "pay") render(); }, delay);
    tick(1, 700);
    tick(2, 2300);
    setTimeout(() => {
      const o = createOrder();
      state.pay = { method: state.pay.method, phase: "idle", step: 0 };
      state.stack = [{ name: "success", params: { id: o.id } }];
      haptic("success");
      render("push");
      window.scrollTo(0, 0);
      confetti();
    }, 3300);
  },
  "open-order": (el) => { state.tab = "orders"; state.stack = [{ name: "order", params: { id: el.dataset.id } }]; render("push"); },
  "ask-cancel": (el) => openSheet(SHEETS.cancel(el.dataset.id)),
  "do-cancel": (el) => {
    const o = state.orders.find((x) => x.id === +el.dataset.id);
    o.status = "refund_pending";
    haptic("warning");
    closeSheet();
    toast(`Заказ №${o.id} отменён, деньги вернутся на карту`);
  },
  repeat: (el) => {
    const o = state.orders.find((x) => x.id === +el.dataset.id);
    const p = byId(o.pid);
    if (p.cat === "cards") { startDeck(p.id); push("deck"); }
    else if (p.cat === "docs") ACT["go-doc"]();
    else ACT["go-photo"]();
    toast("Параметры повторены — это будет новый заказ");
  },
  notify: (el) => { state.notify[el.dataset.k] = !state.notify[el.dataset.k]; haptic("select"); render(); },
  quick: (el) => sendChat(+el.dataset.id, el.dataset.text),
  copy: async (el) => {
    try { await navigator.clipboard.writeText(el.dataset.text); toast("Адрес скопирован"); }
    catch (e) { toast("Не удалось скопировать: выделите адрес вручную", "no"); }
  },
};

function startDeck(pid, photosCount) {
  if (!state.deck || state.deck.pid !== pid) {
    const n = Math.min(photosCount || 4, SAMPLE_PHOTOS.length);
    state.deck = { pid, photos: SAMPLE_PHOTOS.slice(0, n).map((p) => ({ ...p, sample: true })), edits: {}, saved: false };
  }
  state.swapFrom = null;
}
function saveDraft() {
  const dk = state.deck;
  state.draft = { pid: dk.pid, title: `Колода «${byId(dk.pid).title}»`, photos: dk.photos.length, updated: "только что" };
  dk.saved = true;
}

function createOrder() {
  const r = reviewData();
  const id = Math.max(...state.orders.map((o) => o.id)) + 1;
  const now = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  let sub;
  if (r.kind === "deck" || state.review.kind === "deck") {
    const dk = state.deck;
    sub = `${r.p.cards} ${plural(r.p.cards, "карта", "карты", "карт")} · ${dk.photos.length} фото`;
  } else if (state.review.kind === "doc") {
    const d = state.doc, n = docSelected(d).size;
    sub = `${n} стр. · ${d.format} · ${d.color ? "цвет" : "ч/б"} · ${d.copies} ${plural(d.copies, "копия", "копии", "копий")}`;
  } else {
    const j = state.photoJob;
    sub = `${j.photos.length} фото · ${j.format === "a4" ? "A4" : "A5"} · ${j.copies} ${plural(j.copies, "копия", "копии", "копий")}`;
  }
  const o = { id, pid: r.p.id, title: r.title, sub, status: "paid", amount: r.q.total, created: `Сегодня, ${now}`,
    times: { paid: `Сегодня, ${now}` }, chat: [], unread: 0, photos: [0] };
  state.orders.unshift(o);
  if (r.p.cat === "cards") { state.draft = null; state.deck = null; }
  state.agreed = false;
  return o;
}

function sendChat(id, text) {
  const o = state.orders.find((x) => x.id === id);
  const at = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  o.chat.push({ me: true, text, at });
  o.typing = true;
  haptic("light");
  render();
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  setTimeout(() => {
    o.typing = false;
    o.chat.push({ me: false, who: "Оператор Аня", text: text === "Осветлить" ? "Хорошо, осветлим фото 7 и продолжим печать." : "Принято! Если что-то понадобится — напишу здесь.", at });
    if (current().name === "chat") { render(); window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }); }
  }, 1400);
}

// ---------- файлы ----------

function readAsDataURL(file, onProgress) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
}
function imageSize(url) {
  return new Promise((resolve) => { const im = new Image(); im.onload = () => resolve([im.naturalWidth, im.naturalHeight]); im.onerror = () => resolve([0, 0]); im.src = url; });
}
async function countPdfPages(file) {
  const text = new TextDecoder("latin1").decode(await file.arrayBuffer());
  const pages = text.match(/\/Type\s*\/Page(?![a-zA-Z])/g);
  return pages ? pages.length : 0;
}

async function onDocFile(file) {
  const d = state.doc;
  d.error = null;
  const kind = /pdf$/i.test(file.type) || /\.pdf$/i.test(file.name) ? "pdf" : /image\/(jpeg|png)/.test(file.type) ? "img" : null;
  const size = file.size / 1048576;
  if (!kind) {
    d.error = { title: "Этот формат пока не принимаем", text: `«${file.name}» — сохраните документ как PDF и загрузите снова.` };
    return render();
  }
  if (size > 50) {
    d.error = { title: "Файл больше 50 МБ", text: "Сожмите PDF или разделите его на части." };
    return render();
  }
  d.upload = { name: file.name, size, step: 0, pct: 0 };
  render();
  let dataUrl;
  try {
    dataUrl = await readAsDataURL(file, (k) => { d.upload.pct = Math.round(k * 100); render(); });
  } catch (e) {
    d.upload = null;
    d.error = { title: "Файл не прочитался", text: "Попробуйте выбрать его ещё раз." };
    return render();
  }
  d.upload.step = 1; render();
  await new Promise((r) => setTimeout(r, 450));
  d.upload.step = 2; render();
  const pages = kind === "pdf" ? await countPdfPages(file) : 1;
  await new Promise((r) => setTimeout(r, 450));
  d.upload = null;
  if (!pages) {
    d.error = { title: "Не получилось прочитать страницы", text: "Файл может быть повреждён или защищён паролем. Сохраните его заново как PDF." };
    return render();
  }
  if (pages > 200) {
    d.error = { title: `В файле ${pages} страниц`, text: "Максимум — 200. Разделите документ на части." };
    return render();
  }
  d.file = { name: file.name, pages, size, kind, ok: true, preview: kind === "img" ? dataUrl : null };
  d.range = "all";
  haptic("success");
  render();
}

async function onPhotoFiles(files, target) {
  const list = [...files].filter((f) => /image\/(jpeg|png)/.test(f.type));
  if (list.length < files.length) toast("Часть файлов пропущена: принимаем JPG и PNG", "no");
  for (const f of list) {
    if (f.size > 20 * 1048576) { toast(`${f.name}: больше 20 МБ`, "no"); continue; }
    const url = await readAsDataURL(f);
    const [w, h] = await imageSize(url);
    const ph = { url, w, h, name: f.name };
    if (target === "deck") {
      const max = state.deck.pid === "memory" ? 24 : byId(state.deck.pid).cards;
      if (state.deck.photos.length >= max) break;
      state.deck.photos.push(ph);
      saveDraft();
    } else state.photoJob.photos.push(ph);
    render();
  }
  haptic("success");
}

// ---------- события ----------

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act],[data-go]");
  if (!el || el.disabled) return;
  if (el.tagName === "A") e.preventDefault();
  if (el.dataset.go) {
    const { go, act, ...params } = el.dataset;
    if (go === "doc") { state.doc = state.doc || newDoc(); }
    if (go === "photo") return ACT["go-photo"]();
    return push(go, params);
  }
  ACT[el.dataset.act]?.(el, e);
});

document.addEventListener("input", (e) => {
  const el = e.target;
  if (el.dataset.model) { setPath(el.dataset.model, el.value); render(); return; }
  if (el.dataset.edit) {
    const i = +el.dataset.i, dk = state.deck;
    const val = el.dataset.edit === "cap" ? el.value : +el.value;
    dk.edits[i] = { ...(dk.edits[i] || {}), [el.dataset.edit]: val };
    saveDraft();
    refreshSheet();
  }
});

document.addEventListener("change", (e) => {
  const el = e.target;
  if (!el.dataset.file || !el.files?.length) return;
  if (el.dataset.file === "doc") onDocFile(el.files[0]);
  else onPhotoFiles(el.files, el.dataset.file);
  el.value = "";
});

document.addEventListener("submit", (e) => {
  const form = e.target.closest("[data-form=chat]");
  if (!form) return;
  e.preventDefault();
  const input = form.querySelector("input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendChat(+form.dataset.id, text);
});

// перетаскивание файла на зону загрузки
document.addEventListener("dragover", (e) => { const d = e.target.closest(".drop"); if (d) { e.preventDefault(); d.classList.add("drag"); } });
document.addEventListener("dragleave", (e) => e.target.closest(".drop")?.classList.remove("drag"));
document.addEventListener("drop", (e) => {
  const d = e.target.closest(".drop");
  if (!d) return;
  e.preventDefault();
  d.classList.remove("drag");
  if (e.dataTransfer.files[0]) onDocFile(e.dataTransfer.files[0]);
});

// ---------- старт ----------

try {
  tg?.ready();
  tg?.expand();
  tg?.BackButton?.onClick(back);
  tg?.onEvent?.("themeChanged", applyTheme);
} catch (e) { /* открыт вне Telegram */ }
state.theme = store("theme") || "auto";
applyTheme();
const startHash = location.hash.slice(1);
if (["catalog", "orders", "profile"].includes(startHash)) state.tab = startHash;
render("tab");
