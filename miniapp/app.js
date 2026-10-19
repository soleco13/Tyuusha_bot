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

const PRODUCTS = [
  { id: "deck36", cat: "cards", title: "Классическая колода", sub: "36 карт, от шестёрки до туза", price: 990, cards: 36, art: "classic",
    includes: [["cards", "36 карт 63×88 мм"], ["heart", "Рубашка на выбор: 5 вариантов"], ["stars", "Ваши фото на каждой карте"]],
    reqs: ["От 1 до 36 фото: фото распределятся по картам по очереди", "Лучше от 1000 px по короткой стороне", "JPG или PNG до 20 МБ"] },
  { id: "deck54", cat: "cards", title: "Полная колода", sub: "54 карты с двумя джокерами", price: 1290, cards: 54, art: "full",
    includes: [["cards", "54 карты 63×88 мм"], ["stars", "Два джокера с вашими фото"], ["heart", "Рубашка на выбор: 5 вариантов"]],
    reqs: ["От 1 до 54 фото", "Лучше от 1000 px по короткой стороне", "JPG или PNG до 20 МБ"] },
  { id: "photo", cat: "photo", title: "Печать фото", sub: "10×15, A5 и A4", priceFrom: "от 20 ₽ за фото", art: "photo" },
];
const byId = (id) => PRODUCTS.find((p) => p.id === id);

let PRICES = {
  cards: { deck36: 990, deck54: 1290 },
  photo: { "10x15": { color: 30, bw: 20 }, a5: { color: 60, bw: 35 }, a4: { color: 100, bw: 50 } },
  quality_markup: { draft: -20, normal: 0, high: 20 },
};

// Рубашки карт: картинки — img/backs/<key>.png, список и выбор по умолчанию уточняются с сервера
let BACKS = [{ key: "hearts", title: "Сердечки" }, { key: "plaid", title: "Шотландка" }, { key: "night", title: "Звёздная ночь" },
  { key: "dots", title: "Мятный горошек" }, { key: "flowers", title: "Ромашки" }];
let DEFAULT_BACK = "hearts";
const backTitle = (key) => (BACKS.find((b) => b.key === key) || BACKS[0]).title;

const STATUS = {
  new: ["Принят, ждёт печати", "check", ""],
  printing: ["Печатается", "printer", ""],
  printed: ["Готов к выдаче", "box", "ok"],
  issued: ["Выдан", "check", "mute"],
  cancelled: ["Отменён", "close", "no"],
};
const FLOW = [
  ["new", "Принят", "check"], ["printing", "Печать", "printer"], ["printed", "Готов к выдаче", "box"], ["issued", "Выдан", "paw"],
];
const NEXT_STEP = {
  new: "Оператор проверит заказ и запустит печать. Напишем в Telegram, когда начнём.",
  printing: "Печатаем прямо сейчас. Напишем, когда будет готово.",
  printed: "Заказ готов. Оператор скажет в Telegram, как его забрать.",
  issued: "Заказ выдан. Спасибо, что выбрали Тюшу!",
};

const FORMAT_NAMES = { "10x15": "10×15", a5: "A5", a4: "A4" };
const QUALITY_NAMES = { draft: "черновое", normal: "обычное", high: "высокое" };
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
    theme: "auto",
  draft: null,
  deck: null,          // конструктор карт
  swapFrom: null,
  photoJob: null,      // печать фото
  uploadPct: 0,
  review: null,        // что проверяем перед оформлением
  agreed: false,
  orders: [],
  ordersLoaded: false,
  placing: false,
};

// ---------- утилиты ----------

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rub = (n) => `${(Math.round(n * 100) / 100).toLocaleString("ru-RU")} ₽`;
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

function availability() { return { ok: true, low: false }; }
function availLine() { return `<span class="avail ok">${icon("check")}Печатаем после заказа</span>`; }

function photoStyle(ph) {
  if (!ph) return "background:var(--surface-2)";
  return `background:url('${ph.url}') center / ${ph.sample ? "contain" : "cover"} no-repeat, ${ph.bg || "#e8ecf4"}`;
}

// ---------- игральная карта ----------

// Карта как в печати: крупный засечный ранг, рядом большая масть, под рангом маленькая; фото с мягкими краями
function playingCard({ rank, suit, ph, zoom = 1, x = 50, y = 50, cls = "", style = "" }) {
  const joker = rank === "JOKER";
  const [glyph, color] = joker ? ["★\uFE0E", "joker"] : SUITS[suit];
  const r = joker ? "J" : rank;
  const bg = ph ? `background:url('${ph.url}') ${x}% ${y}% / ${ph.sample ? Math.round(zoom * 100) + "%" : zoom === 1 ? "cover" : Math.round(zoom * 120) + "%"} no-repeat, ${ph.bg || "#e8ecf4"}` : "background:var(--surface-2)";
  const ix = (side) => `<div class="ix ${side} ${r.length > 1 ? "two" : ""}"><span class="rk">${r}</span><b class="big">${glyph}</b><b class="sm">${glyph}</b></div>`;
  return `<div class="pc ${color} ${cls}" style="${style}"><div class="win" style="${bg}"></div>${ix("")}${ix("r")}</div>`;
}
const cardBack = (key = DEFAULT_BACK, style = "") => `<div class="pc back" style="background-image:url('img/backs/${key}.png');${style}"></div>`;

function productArt(p, big = false) {
  const s = SAMPLE_PHOTOS;
  const sample = (i) => ({ ...s[i], sample: true });
  if (p.art === "classic") return `<div class="fan">${cardBack("hearts")}${playingCard({ rank: "Д", suit: 1, ph: sample(0) })}${playingCard({ rank: "Т", suit: 0, ph: sample(1) })}</div>`;
  if (p.art === "full") return `<div class="fan">${playingCard({ rank: "JOKER", ph: sample(2) })}${playingCard({ rank: "К", suit: 2, ph: sample(1) })}${cardBack("night")}</div>`;
  if (p.art === "dates") return `<div class="fan"><div class="pc q"><span>${esc(QUESTIONS[1])}</span></div><div class="pc q"><span>${esc(QUESTIONS[0])}</span></div><div class="pc q"><span>${esc(QUESTIONS[2])}</span></div></div>`;
  if (p.art === "memory") return `<div class="fan" style="aspect-ratio:1;width:44%">${[0, 0, 1].map((i) => `<div class="pc memo"><div class="win" style="${photoStyle(sample(i))};inset:8%"></div></div>`).join("")}</div>`;
  if (p.art === "doc") return `<div class="fan" style="aspect-ratio:210/297;width:44%"><div class="page"></div><div class="page"></div><div class="page"><b>1</b></div></div>`;
  return `<div class="fan" style="aspect-ratio:1;width:46%">${[2, 1, 0].map((i) => `<div class="pc memo" style="border-radius:6%"><div class="win" style="${photoStyle(sample(i))};inset:6%;outline:0;border-radius:3%"></div></div>`).join("")}</div>`;
}
const artBg = { classic: "#E4ECFD", full: "#EDE7F8", dates: "#FBE6EA", memory: "#E3F3EC", doc: "#EEF1F7", photo: "#FDF1DA" };

// ---------- расчёт цены ----------

function photoUnit(j) {
  const base = PRICES.photo[j.format][j.color ? "color" : "bw"];
  return Math.round(base * 100 * (100 + PRICES.quality_markup[j.quality]) / 100) / 100;
}
function quotePhoto(j) {
  const rate = photoUnit(j);
  const n = j.photos.length * j.copies;
  return { total: Math.round(n * rate * 100) / 100, lines: [[`${n} ${plural(n, "отпечаток", "отпечатка", "отпечатков")} × ${rub(rate)}`, n * rate]], valid: n > 0 };
}
function quoteDeck(dk) {
  const p = byId(dk.pid);
  return { total: p.price, lines: [[p.title, p.price]], valid: dk.photos.length > 0 };
}

// ---------- конструктор: раскладка колоды ----------

function deckLayout(dk) {
  const p = byId(dk.pid);
  const cards = [];
  const ranks = p.id === "deck54" ? RANKS54 : RANKS36;
  SUITS.forEach((_, s) => ranks.forEach((r) => cards.push({ rank: r, suit: s })));
  if (p.id === "deck54") cards.push({ rank: "JOKER" }, { rank: "JOKER" });
  return cards.map((c, i) => {
    const o = dk.edits[i] || {};
    const photoIndex = i % Math.max(dk.photos.length, 1);
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
  if (o.thumbUrl) return `<div class="othumb" style="background:url('${o.thumbUrl}') center / cover"></div>`;
  return o.kind === "cards" ? `<div class="othumb" style="background:${artBg.classic}">${icon("cards")}</div>` : `<div class="othumb" style="background:${artBg.photo}">${icon("photo")}</div>`;
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
  const active = state.orders.find((o) => !["issued", "cancelled"].includes(o.status));
  const draftP = byId(state.draft?.pid);
  const svc = [
    { t: "Фото", s: "от 20 ₽", ic: "photo", go: "photo", p: byId("photo") },
    { t: "Свои карты", s: "от 990 ₽", ic: "cards", go: "catalog-cards", p: null, tone: "pink" },
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
        <p>Фото и колоды игральных карт из ваших снимков.</p>
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
  const cats = [["all", "Все"], ["cards", "Карты"], ["photo", "Фото"]];
  const q = state.q.trim().toLowerCase();
  const list = PRODUCTS.filter((p) => (state.catCat === "all" || p.cat === state.catCat) &&
    (!q || (p.title + " " + p.sub).toLowerCase().includes(q)));
  return { html: `
    <div style="padding-top:12px" class="h-section"><h1 class="display" style="font-size:26px">Каталог</h1></div>
    <label class="search">${icon("search")}<input class="input" id="q" type="search" placeholder="Колода, фото…" value="${esc(state.q)}" data-model="q" autocomplete="off"></label>
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
  const cta = isCards ? ["Собрать колоду", "start-deck"] : ["Выбрать фото", "go-photo"];
  return {
    html: `${topbar(p.title)}
    <div class="card" style="padding:0;overflow:hidden"><div class="product" style="box-shadow:none;border-radius:0">
      <div class="art pressable" style="background:${artBg[p.art]};aspect-ratio:5/4">${productArt(p, true)}</div></div>
      <div style="padding:2px 18px 18px;display:flex;flex-direction:column;gap:10px">
        <h1 class="display" style="font-size:24px">${esc(p.title)}</h1>
        <div class="muted">${esc(p.sub)}</div>
        <div class="row" style="justify-content:space-between"><b class="display tabular" style="font-size:22px">${p.price ? rub(p.price) : esc(p.priceFrom)}</b>${availLine(p)}</div>
      </div></div>
    ${p.includes ? `<div class="card"><div class="eyebrow">Что входит</div><div class="list">${p.includes.map(([ic, t]) =>
      `<div class="list-item"><span class="tile-icon">${icon(ic)}</span><span class="t">${esc(t)}</span></div>`).join("")}</div></div>` : ""}
    ${p.reqs ? `<div class="card"><div class="eyebrow">Требования к фото</div><div class="list">${p.reqs.map((t) =>
      `<div class="list-item"><span style="color:var(--ok);--ic2:var(--ok)">${icon("check", "sm")}</span><span>${esc(t)}</span></div>`).join("")}</div></div>` : ""}
    <div class="card flat"><div class="row"><span class="tile-icon">${icon("clock")}</span><div class="grow"><div style="font-weight:600">Печатаем после заказа</div>
      <div class="small muted">Напишем в Telegram, когда заказ будет готов.</div></div></div></div>`,
    dock: dockBar(p.price ?? null, cta[0], cta[1], { sub: "Стоимость" }),
  };
};

SCREENS.photo = () => {
  const j = state.photoJob;
  const q = quotePhoto(j);
  const bad = j.photos.filter(lowRes).length;
  return {
    html: `${topbar("Печать фото")}
    ${steps(["Фото", "Настройки", "Проверка", "Заказ"], j.photos.length ? 1 : 0)}
    <div class="photos">${j.photos.map((ph, i) => `<div class="photo" style="${photoStyle(ph)}"><span class="n">${i + 1}</span>${lowRes(ph) ? `<span class="bad" title="Низкое разрешение">${icon("warn")}</span>` : ""}</div>`).join("")}
      <label class="photo add" aria-label="Добавить фото"><input type="file" id="photo-files" accept="image/jpeg,image/png" multiple data-file="photo">${icon("upload", "lg")}</label></div>
    ${bad ? `<div class="notice warn">${icon("warn")}<div><b>${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением</b><span>На большом формате может получиться нерезко. Лучше заменить фото или выбрать формат меньше.</span></div></div>` : ""}
    <div class="field"><span class="lbl">Размер</span>${seg("photoJob.format", j.format, [
      { v: "10x15", t: "10×15", s: rub(PRICES.photo["10x15"][j.color ? "color" : "bw"]) },
      { v: "a5", t: "A5", s: rub(PRICES.photo.a5[j.color ? "color" : "bw"]) }, { v: "a4", t: "A4", s: rub(PRICES.photo.a4[j.color ? "color" : "bw"]) }])}</div>
    <div class="field"><span class="lbl">Цвет</span>${seg("photoJob.color", String(j.color), [{ v: "true", t: "Цветная" }, { v: "false", t: "Чёрно-белая" }])}</div>
    <div class="field"><span class="lbl">Качество</span>${seg("photoJob.quality", j.quality, [{ v: "draft", t: "Черновое" }, { v: "normal", t: "Обычное" }, { v: "high", t: "Высокое" }])}</div>
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
  const maxPhotos = p.cards;
  return {
    html: `${topbar(p.title, dk.saved ? "Черновик сохранён" : "")}
    ${steps(["Фото", "Макет", "Проверка", "Заказ"], dk.photos.length ? 1 : 0)}
    <div class="h-section"><h2>Фото <span class="muted tabular" style="font-weight:500">${dk.photos.length} из ${maxPhotos}</span></h2>
      ${dk.photos.length > 1 ? `<a href="#" data-act="shuffle">Перемешать</a>` : ""}</div>
    <div class="photos">${dk.photos.map((ph, i) => `<button class="photo ${state.swapFrom === i ? "sel" : ""}" style="${photoStyle(ph)}" data-act="swap" data-i="${i}" aria-label="Фото ${i + 1}">
        <span class="n">${i + 1}</span>${lowRes(ph) ? `<span class="bad">${icon("warn")}</span>` : ""}</button>`).join("")}
      ${dk.photos.length < maxPhotos ? `<label class="photo add" aria-label="Добавить фото"><input type="file" id="deck-files" accept="image/jpeg,image/png" multiple data-file="deck">${icon("upload", "lg")}</label>` : ""}</div>
    <div class="small muted">${state.swapFrom != null ? "Теперь нажмите на фото, с которым поменять местами." : "Нажмите на два фото, чтобы поменять их местами. Фото ложатся на карты по очереди."}</div>
    ${bad ? `<div class="notice warn">${icon("warn")}<div><b>${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением</b><span>Отмечены значком. На карте 63×88 мм такое фото может выйти нерезким.</span></div></div>` : ""}
    <div class="h-section"><h2>Рубашка <span class="muted" style="font-weight:500">· ${esc(backTitle(dk.back))}</span></h2></div>
    <div class="backs" role="radiogroup" aria-label="Рубашка карт">${BACKS.map((b) => `<button class="back-opt ${b.key === dk.back ? "on" : ""}" role="radio"
      aria-checked="${b.key === dk.back}" data-act="set" data-model="deck.back" data-value="${b.key}">${cardBack(b.key)}<span>${esc(b.title)}</span></button>`).join("")}</div>
    <div class="h-section"><h2>Макет · ${layout.length} ${plural(layout.length, "карта", "карты", "карт")}</h2></div>
    <div class="deck">${layout.map((c) =>
      `<div style="display:block;animation:deal .5s var(--spring) both;animation-delay:${Math.min(c.i * 12, 400)}ms">${playingCard({ rank: c.rank, suit: c.suit, ph: c.ph, style: "position:relative;aspect-ratio:63/88" })}</div>`).join("")}</div>`,
    dock: dockBar(quoteDeck(dk).total, "Проверить макет", "review-deck", { disabled: !dk.photos.length }),
  };
};

// --- S07/S08: проверка и подтверждение ---

function reviewData() {
  const r = state.review;
  if (r.kind === "deck") {
    const dk = state.deck, p = byId(dk.pid), q = quoteDeck(dk);
    const warns = [];
    const bad = dk.photos.filter(lowRes).length;
    if (bad) warns.push(["warn", `${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением`, "Может выйти нерезко. Вернитесь, чтобы заменить, или оставьте как есть."]);
    if (dk.photos.length < p.cards) warns.push(["info", `Фото: ${dk.photos.length} из ${p.cards}`, "Если фото меньше, чем карт, они повторятся по кругу."]);
    return { p, q, title: p.title, flow: ["Фото", "Макет", "Проверка", "Заказ"],
      rows: [["Набор", p.title], ["Карт", String(p.cards)], ["Фото", String(dk.photos.length)], ["Рубашка", backTitle(dk.back)]],
      warns, agree: "Макет проверен. После оформления заказ уйдёт оператору.",
      art: `<div class="row" style="gap:8px;justify-content:center"><div style="width:28%">${cardBack(dk.back, "position:relative;aspect-ratio:63/88")}</div>${deckLayout(dk).slice(0, 2).map((c) => c.memo
        ? `<div class="pc memo" style="width:30%;position:relative"><div class="win" style="${photoStyle(c.ph)};inset:8%"></div></div>`
        : `<div style="width:28%">${playingCard({ rank: c.rank, suit: c.suit, ph: c.ph, zoom: c.o.zoom || 1, x: c.o.x ?? 50, y: c.o.y ?? 50, style: "position:relative;aspect-ratio:63/88" })}</div>`).join("")}</div>` };
  }
  const j = state.photoJob, p = byId("photo"), q = quotePhoto(j);
  const bad = j.photos.filter(lowRes).length;
  return { p, q, title: `Фото ${FORMAT_NAMES[j.format]}`, flow: ["Фото", "Настройки", "Проверка", "Заказ"],
    rows: [["Фото", String(j.photos.length)], ["Размер", FORMAT_NAMES[j.format]], ["Копии", String(j.copies)], ["Цвет", j.color ? "цветная" : "чёрно-белая"], ["Качество", QUALITY_NAMES[j.quality]]],
    warns: bad ? [["warn", `${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением`, "Может выйти нерезко."]] : [],
    agree: "Фото и параметры печати проверены." };
}

SCREENS.review = () => {
  const r = reviewData();
  return {
    html: `${topbar("Проверка заказа")}
    ${steps(r.flow, 2)}
    ${r.art ? `<div class="card" style="background:${artBg[r.p.art]};box-shadow:none;padding:20px">${r.art}</div>` : ""}
    ${r.warns.map(([tone, t, s]) => `<div class="notice ${tone}">${icon(tone === "warn" ? "warn" : "info")}<div><b>${esc(t)}</b><span>${esc(s)}</span></div></div>`).join("")}
    <div class="notice info">${icon("info")}<div><b>Оплаты в приложении пока нет</b><span>Заказ уйдёт оператору, о стоимости и получении он напишет в Telegram.</span></div></div>
    <div class="card"><div class="eyebrow">Заказ</div><dl class="kv">${r.rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>
    <div class="card"><div class="eyebrow">Стоимость</div><dl class="kv">${r.q.lines.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${rub(v)}</dd>`).join("")}
      <span class="sep"></span><dt class="total">Итого</dt><dd class="total">${rub(r.q.total)}</dd></dl></div>
    <button class="check" role="checkbox" aria-checked="${state.agreed}" data-act="agree"><span class="box">${icon("check")}</span><span>${esc(r.agree)}</span></button>`,
    dock: dockBar(r.q.total, state.agreed ? "Оформить заказ" : "Отметьте проверку", "place-order", { disabled: !state.agreed }),
  };
};

// --- оформление заказа ---

SCREENS.placing = () => ({
  html: `<div class="card" style="align-items:center;text-align:center;padding:30px 18px;margin-top:40px">
    <img src="${IMG.printer}" alt="" style="width:140px;animation:breathe 3s ease-in-out infinite">
    <h2 class="display" style="font-size:22px">Тюша собирает макет</h2>
    <p class="muted" style="margin:0">Загружаем фото и готовим листы для печати. Это займёт до минуты, не закрывайте приложение.</p>
    <div class="progress" style="width:100%"><i style="width:${state.uploadPct}%"></i></div>
  </div>`,
});

SCREENS.success = ({ id }) => {
  const o = state.orders.find((x) => x.id === +id) || { id, status: "new", amount: 0 };
  return {
    html: `<div class="success">
      <div class="art"><img src="${IMG.printer}" alt=""></div>
      <span class="pill ok">${icon("check")}Принято</span>
      <h1 class="display">Заказ №${o.id} принят</h1>
      <p class="muted" style="margin:0;max-width:32ch">Он ждёт оператора: тот проверит заказ и запустит печать. О каждом шаге напишем в Telegram.</p>
      <div class="card" style="width:100%;text-align:left">${activeTrack(o)}<div class="row small"><span class="grow muted">Сейчас: ${esc(STATUS[o.status][0].toLowerCase())}</span><b>${rub(o.amount)}</b></div></div>
    </div>`,
    dock: `<div class="dock"><div class="bar glass solo" style="gap:8px"><button class="btn ghost" data-act="home" style="flex:.8">На главную</button>
      <button class="btn primary" data-act="open-order" data-id="${o.id}"><span class="label">Открыть заказ</span></button></div></div>`,
  };
};

// --- S11: мои заказы ---

const GROUPS = {
  active: (o) => !["issued", "cancelled"].includes(o.status),
  done: (o) => o.status === "issued",
  cancelled: (o) => o.status === "cancelled",
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
          ${icon("next")}</div>
        ${GROUPS.active(o) && FLOW.some((f) => f[0] === o.status) ? activeTrack(o) : ""}
      </button>`).join("")
      : `<div class="empty"><img src="${IMG.face}" alt=""><h3>${state.ordersTab === "active" ? "Активных заказов нет" : state.ordersTab === "done" ? "Выданных заказов пока нет" : "Отменённых заказов нет"}</h3>
        <p>${state.ordersTab === "active" ? "Распечатайте фото или соберите свою колоду." : "Здесь появятся заказы, когда они будут."}</p>
        ${state.ordersTab === "active" ? `<button class="btn primary sm" data-act="tab" data-tab="catalog"><span class="label">Сделать первый заказ</span></button>` : ""}</div>`}
  ` };
};

// --- S10: детали заказа ---

SCREENS.order = ({ id }) => {
  const o = state.orders.find((x) => x.id === +id);
  if (!o) return { html: `${topbar("Заказ")}<div class="empty"><img src="${IMG.face}" alt=""><h3>Заказ не найден</h3></div>` };
  const at = FLOW.findIndex((f) => f[0] === o.status);
  const inFlow = at >= 0;
  return {
    html: `${topbar(`Заказ №${o.id}`, o.created)}
    <div class="card">
      <div class="row">${orderThumb(o)}<div class="grow"><div style="font-weight:650">${esc(o.title)}</div><div class="small muted">${esc(o.sub)}</div></div></div>
      <div class="row" style="justify-content:space-between">${statusPill(o.status)}<b class="tabular">${rub(o.amount)}</b></div>
      <div class="small" style="color:var(--text);opacity:.85">${esc(o.reason || NEXT_STEP[o.status] || "")}</div>
    </div>
    ${inFlow ? `<div class="card"><div class="eyebrow">Ход заказа</div><ol class="timeline">${FLOW.map(([k, t, ic], i) =>
      `<li class="${i < at || (i === at && k === "issued") ? "done" : i === at ? "now" : ""}"><span class="node"><i>${icon(ic)}</i></span>
        <div><div class="t">${t}</div><div class="s">${esc(o.times[k] || (i === at ? "сейчас" : ""))}</div></div></li>`).join("")}</ol></div>` : ""}
    ${o.status === "new" ? `<button class="btn ghost block" data-act="ask-cancel" data-id="${o.id}" style="color:var(--danger)">Отменить заказ</button>` : ""}`,
    dock: `<div class="dock"><div class="bar glass solo"><button class="btn primary block" data-act="repeat" data-id="${o.id}">${icon("repeat")}<span class="label">Повторить заказ</span></button></div></div>`,
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
    <div class="card" style="padding:4px 16px"><div class="list">
      ${[["help", "info", "Как это работает", "Четыре шага от фото до печати"]].map(([k, ic, t, s]) =>
        `<button class="list-item" data-act="sheet" data-sheet="${k}"><span class="tile-icon">${icon(ic)}</span>
        <span class="grow"><span class="t" style="display:block">${t}</span><span class="s">${s}</span></span>${icon("next")}</button>`).join("")}
    </div></div>
    <div class="field"><span class="lbl">Оформление</span>${seg("theme", state.theme, [{ v: "auto", t: "Как в Telegram" }, { v: "light", t: "Светлое" }, { v: "dark", t: "Тёмное" }])}</div>
    <p class="foot">Иконки — <a href="https://www.figma.com/community/file/1166831539721848736" target="_blank" rel="noopener">Solar by 480 Design</a>, CC BY 4.0.</p>
  ` };
};

// ---------- листы ----------

const SHEETS = {
  help: () => `<div class="grab"></div><h3>Как работает Тюша</h3>
    <ol class="timeline">${[["upload", "Загрузите фото", "JPG или PNG"], ["tune", "Настройте печать", "Цена видна сразу"],
      ["printer", "Оператор печатает", "Напишем, когда начнёт"], ["box", "Заберите заказ", "Напишем, когда будет готово"]].map(([ic, t, s]) =>
      `<li class="done"><span class="node"><i>${icon(ic)}</i></span><div><div class="t">${t}</div><div class="s">${s}</div></div></li>`).join("")}</ol>
    <button class="btn primary block" data-act="close-sheet"><span class="label">Понятно</span></button>`,
  cancel: (id) => {
    const o = state.orders.find((x) => x.id === +id);
    return `<div class="grab"></div><h3>Отменить заказ №${o.id}?</h3>
      <p class="muted" style="margin:0">Печать ещё не началась, заказ можно отменить.</p>
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
    if (el.dataset.model.startsWith("photoJob.")) state.agreed = false;
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
  "go-photo": () => { state.photoJob = state.photoJob || { photos: [], format: "10x15", copies: 1, color: true, quality: "high" }; push("photo"); },
  "start-deck": () => { const id = current().params.id; startDeck(id); push("deck"); },
  "continue-draft": () => { startDeck(state.draft.pid, state.draft.photos); push("deck"); },
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
  "close-sheet": () => closeSheet(),
  sheet: (el) => openSheet(SHEETS[el.dataset.sheet]()),
  "review-photo": () => { state.review = { kind: "photo" }; state.agreed = false; push("review"); },
  "review-deck": () => { state.review = { kind: "deck" }; state.agreed = false; push("review"); },
  agree: () => { state.agreed = !state.agreed; haptic("select"); render(); },
  "place-order": () => placeOrder(),
  "open-order": (el) => { state.tab = "orders"; state.stack = [{ name: "order", params: { id: el.dataset.id } }]; render("push"); },
  "ask-cancel": (el) => openSheet(SHEETS.cancel(el.dataset.id)),
  "do-cancel": async (el) => {
    closeSheet();
    try {
      const r = await api(`/mapi/orders/${el.dataset.id}/cancel`, { method: "POST" });
      Object.assign(state.orders.find((x) => x.id === +el.dataset.id), r.order, { status: r.order.status });
      haptic("warning");
      toast(`Заказ №${el.dataset.id} отменён`);
    } catch (e) { toast(e.message, "no"); }
    render();
  },
  repeat: (el) => {
    const o = state.orders.find((x) => x.id === +el.dataset.id);
    if (o.kind === "cards") { startDeck(o.title.includes("36") || o.sub.startsWith("36") ? "deck36" : "deck54"); push("deck"); }
    else ACT["go-photo"]();
    toast("Добавьте фото — это будет новый заказ");
  },
  copy: async (el) => {
    try { await navigator.clipboard.writeText(el.dataset.text); toast("Адрес скопирован"); }
    catch (e) { toast("Не удалось скопировать: выделите адрес вручную", "no"); }
  },
};

function startDeck(pid, photosCount) {
  if (!state.deck || state.deck.pid !== pid) {
    state.deck = { pid, photos: [], edits: {}, saved: false, back: DEFAULT_BACK };
  }
  state.swapFrom = null;
}
function saveDraft() {
  const dk = state.deck;
  state.draft = dk.photos.length ? { pid: dk.pid, title: byId(dk.pid).title, photos: dk.photos.length, updated: "только что" } : null;
  dk.saved = true;
}

// ---------- сервер ----------

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "X-Init-Data": tg?.initData || "", ...(opts.headers || {}) } });
  let data = null;
  try { data = await res.json(); } catch (e) { /* не JSON */ }
  if (!res.ok || !data?.ok) {
    if (res.status === 401) throw new Error("Откройте приложение из Telegram: кнопка «Тюша» у бота.");
    throw new Error(data?.error || "Нет связи с сервером. Попробуйте ещё раз.");
  }
  return data;
}

function mapOrder(o) {
  const fmt = (t) => {
    if (!t) return "";
    const d = new Date(t.replace(" ", "T"));
    return isNaN(d) ? t : d.toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
  };
  return { ...o, status: o.status === "fronts_printed" ? "printing" : o.status, created: fmt(o.created),
    times: Object.fromEntries(Object.entries(o.times || {}).map(([k, v]) => [k, fmt(v)])) };
}

async function loadThumb(o) {
  try {
    const res = await fetch(`/mapi/orders/${o.id}/thumb`, { headers: { "X-Init-Data": tg?.initData || "" } });
    if (res.ok) { o.thumbUrl = URL.createObjectURL(await res.blob()); return true; }
  } catch (e) { /* без миниатюры */ }
  return false;
}

let ordersSig = "";
async function refreshOrders() {
  try {
    const { orders } = await api("/mapi/orders");
    const old = new Map(state.orders.map((o) => [o.id, o]));
    const next = orders.map(mapOrder);
    next.forEach((o) => { o.thumbUrl = old.get(o.id)?.thumbUrl; });
    const sig = JSON.stringify(next.map((o) => [o.id, o.status, o.reason]));
    const changed = sig !== ordersSig || !state.ordersLoaded;
    ordersSig = sig;
    state.orders = next;
    state.ordersLoaded = true;
    await Promise.all(next.filter((o) => o.thumb && !o.thumbUrl).map(loadThumb));
    if (changed && ["home", "orders", "order", "success"].includes(current().name)) render();
  } catch (e) { /* повторим при следующем опросе */ }
}

async function loadConfig() {
  try {
    const c = await api("/mapi/config");
    PRICES = c.prices;
    if (Array.isArray(c.backs) && c.backs.length) { BACKS = c.backs; DEFAULT_BACK = c.default_back || BACKS[0].key; }
    PRODUCTS.forEach((p) => { if (PRICES.cards[p.id]) p.price = PRICES.cards[p.id]; });
    const min = Math.min(...Object.values(PRICES.photo).flatMap((f) => Object.values(f)));
    byId("photo").priceFrom = `от ${min} ₽ за фото`;
    render();
  } catch (e) { /* остаются цены по умолчанию */ }
}

// Фото перед отправкой уменьшаем: телефонные снимки по 8–12 МБ × десятки штук по мобильной сети не уйдут.
async function prepareUpload(ph, maxSide) {
  const file = ph.file;
  try {
    const bmp = await createImageBitmap(file);
    const k = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    if (k === 1 && file.size < 3 * 1048576 && /jpeg|png/.test(file.type)) { bmp.close?.(); return file; }
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    bmp.close?.();
    return await new Promise((resolve) => c.toBlob((b) => resolve(b || file), "image/jpeg", 0.92));
  } catch (e) { return file; }
}

async function placeOrder() {
  if (state.placing) return;
  const r = state.review;
  const isDeck = r.kind === "deck";
  const list = isDeck ? state.deck.photos : state.photoJob.photos;
  const meta = isDeck ? { kind: "cards", deck: state.deck.pid, back: state.deck.back || DEFAULT_BACK }
    : { kind: "photo", format: state.photoJob.format, copies: state.photoJob.copies, color: state.photoJob.color, quality: state.photoJob.quality };
  state.placing = true;
  state.uploadPct = 5;
  state.stack.push({ name: "placing", params: {} });
  render("push");
  try {
    const form = new FormData();
    form.append("meta", JSON.stringify(meta));
    const maxSide = isDeck ? 2200 : 3600;
    for (let i = 0; i < list.length; i++) {
      form.append("photo", await prepareUpload(list[i], maxSide), `photo_${i + 1}.jpg`);
      state.uploadPct = 5 + Math.round((i + 1) / list.length * 60);
      if (current().name === "placing") render();
    }
    state.uploadPct = 70;
    render();
    const { order } = await api("/mapi/orders", { method: "POST", body: form });
    const o = mapOrder(order);
    state.orders.unshift(o);
    loadThumb(o).then(() => render());
    if (isDeck) { state.draft = null; state.deck = null; } else state.photoJob = null;
    state.agreed = false;
    state.stack = [{ name: "success", params: { id: o.id } }];
    haptic("success");
    render("push");
    window.scrollTo(0, 0);
    confetti();
  } catch (e) {
    state.stack.pop();
    haptic("error");
    render("pop");
    toast(e.message, "no");
  } finally {
    state.placing = false;
  }
}

// ---------- файлы ----------

function imageSize(url) {
  return new Promise((resolve) => { const im = new Image(); im.onload = () => resolve([im.naturalWidth, im.naturalHeight]); im.onerror = () => resolve([0, 0]); im.src = url; });
}
async function onPhotoFiles(files, target) {
  const list = [...files].filter((f) => /image\/(jpeg|png)/.test(f.type));
  if (list.length < files.length) toast("Часть файлов пропущена: принимаем JPG и PNG", "no");
  for (const f of list) {
    if (f.size > 20 * 1048576) { toast(`${f.name}: больше 20 МБ`, "no"); continue; }
    const url = URL.createObjectURL(f);
    const [w, h] = await imageSize(url);
    const ph = { url, w, h, name: f.name, file: f };
    if (target === "deck") {
      const max = byId(state.deck.pid).cards;
      if (state.deck.photos.length >= max) break;
      state.deck.photos.push(ph);
      saveDraft();
    } else if (state.photoJob.photos.length < 54) state.photoJob.photos.push(ph);
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
  onPhotoFiles(el.files, el.dataset.file);
  el.value = "";
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
loadConfig();
refreshOrders();
setInterval(() => { if (!document.hidden && !state.placing) refreshOrders(); }, 15000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshOrders(); });
