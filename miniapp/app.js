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
    includes: [["cards", "36 карт 63×88 мм"], ["heart", "Рубашка на выбор: 20 вариантов"], ["stars", "Ваши фото на каждой карте"]],
    reqs: ["От 1 до 36 фото: фото распределятся по картам по очереди", "Лучше от 1000 px по короткой стороне", "JPG или PNG до 20 МБ"] },
  { id: "deck54", cat: "cards", title: "Полная колода", sub: "54 карты с двумя джокерами", price: 1290, cards: 54, art: "full",
    includes: [["cards", "54 карты 63×88 мм"], ["stars", "Два джокера с вашими фото"], ["heart", "Рубашка на выбор: 20 вариантов"]],
    reqs: ["От 1 до 54 фото", "Лучше от 1000 px по короткой стороне", "JPG или PNG до 20 МБ"] },
  { id: "uno", cat: "cards", title: "UNO с вашими фото", sub: "108 карт, фото в овале карт с цифрами", price: 1790, cards: 108, maxPhotos: 76, art: "uno",
    includes: [["cards", "108 карт 63×88 мм, полный набор для игры"], ["stars", "Ваши фото на 76 картах с цифрами"], ["heart", "6 рубашек на выбор"]],
    reqs: ["От 1 до 76 фото: распределятся по картам с цифрами по очереди", "Лучше от 1000 px по короткой стороне", "JPG или PNG до 20 МБ"] },
  { id: "doc", cat: "doc", title: "Печать документов", sub: "PDF, JPG и PNG на листах A4", priceFrom: "от 8 ₽ за страницу", art: "doc",
    includes: [["doc", "Каждая страница на отдельном листе A4"], ["tune", "Цветная или чёрно-белая печать"], ["copy", "Нужное число копий"]],
    reqs: ["PDF, JPG или PNG до 20 МБ, не больше 100 страниц", "Word и Excel сохраните как PDF", "PDF без пароля"] },
  { id: "photo", cat: "photo", title: "Печать фото", sub: "10×15, A5 и A4", priceFrom: "от 20 ₽ за фото", art: "photo" },
];
const byId = (id) => PRODUCTS.find((p) => p.id === id);

let PRICES = {
  cards: { deck36: 990, deck54: 1290, uno: 1790 },
  doc: { color: 15, bw: 8 },
  photo: { "10x15": { color: 30, bw: 20 }, a5: { color: 60, bw: 35 }, a4: { color: 100, bw: 50 } },
  quality_markup: { draft: -20, normal: 0, high: 20 },
  paper: { thick: 6, matte: 8, lam: 25 },
  craft: { memory_base: 290, memory_pair: 25, dates_sheet: 120, wishes_sheet: 120, stickers_sheet: 190, calendar: 890,
    postcard: 70, box: 190, game_sheet: 120, enhance_photo: 10 },
};

// Рубашки карт: картинки — img/backs/<key>.png, список и выбор по умолчанию уточняются с сервера
let BACKS = [{ key: "hearts", title: "Сердечки" }, { key: "plaid", title: "Шотландка" }, { key: "night", title: "Звёздная ночь" },
  { key: "dots", title: "Мятный горошек" }, { key: "flowers", title: "Ромашки" }];
let DEFAULT_BACK = "hearts";
const backTitle = (key) => ([...BACKS, ...UNO_BACKS].find((b) => b.key === key) || BACKS[0]).title;

// Оформление лицевой стороны: классическое или фото на всю карту с маленьким ч/б индексом
let STYLES = [{ key: "classic", title: "Классическая" }, { key: "full", title: "Фото на всю карту" }, { key: "vintage", title: "Старинная" }];
// «Старинная»: у В, Д, К — фигуры из открытой колоды (img/vintage), у остальных карт — фото в рамке
const COURT = { "В": "J", "Д": "Q", "К": "K" };
const SUIT_KEYS = ["spades", "hearts", "diamonds", "clubs"];
const isCourt = (c) => c.rank in COURT && c.suit != null;
let DEFAULT_STYLE = "classic";
const styleTitle = (key) => (STYLES.find((s) => s.key === key) || STYLES[0]).title;

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
  docJob: null,        // печать документа
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

function productPapers(p) {
  if (p.craft) return p.craft.papers;
  return PAPER_CHOICES[p.cat === "cards" ? "cards" : p.cat] || [];
}
function availability(p) {
  const states = productPapers(p || {}).map((k) => PAPERS[k]?.state || "ok");
  const ok = !states.length || states.some((x) => x !== "out");
  return { ok, low: ok && states.length > 0 && states.every((x) => x !== "ok") };
}
function availLine(p) {
  const a = availability(p);
  if (!a.ok) return `<span class="avail no">${icon("warn")}Временно нет: закончилась бумага</span>`;
  if (a.low) return `<span class="avail warn">${icon("clock")}Материалов осталось мало</span>`;
  return `<span class="avail ok">${icon("check")}Печатаем после заказа</span>`;
}

function photoStyle(ph, aspect = 1, dflt = [0.5, 0.5]) {
  if (!ph) return "background:var(--surface-2)";
  return `background:url('${ph.url}') ${ph.sample ? "center" : facePos(ph, aspect, dflt)} / ${ph.sample ? "contain" : "cover"} no-repeat, ${ph.bg || "#e8ecf4"}`;
}

// ---------- игральная карта ----------

// Карта как в печати: крупный засечный ранг, рядом большая масть, под рангом маленькая; фото с мягкими краями
function playingCard({ rank, suit, ph, zoom = 1, x = null, y = null, cls = "", style = "", full = false, ink = "black", vintage = false }) {
  const joker = rank === "JOKER";
  if (vintage) {
    const [glyph, color] = joker ? ["★\uFE0E", "joker"] : SUITS[suit];
    const r = joker ? "J" : rank;
    const art = !joker && rank in COURT ? `background:url('img/vintage/${SUIT_KEYS[suit]}_${COURT[rank]}.jpg') center / cover no-repeat`
      : ph ? `background:url('${ph.url}') ${facePos(ph, .62)} / cover no-repeat, ${ph.bg || "#e8ecf4"}` : "background:var(--surface-2)";
    const ix = (side) => `<div class="vix ${side} ${r.length > 1 ? "two" : ""}"><span>${r}</span><b>${glyph}</b></div>`;
    return `<div class="pc vin ${color} ${cls}" style="${style}"><div class="vf" style="${art}"></div>${ix("")}${ix("r")}</div>`;
  }
  if (full) {
    const glyph = joker ? "★\uFE0E" : SUITS[suit][0];
    const bg = ph ? `background:url('${ph.url}') ${facePos(ph, 63 / 88, [0.5, 0.45])} / cover no-repeat, ${ph.bg || "#e8ecf4"}` : "background:var(--surface-2)";
    return `<div class="pc full ink-${ink} ${cls}" style="${style}"><div class="bg" style="${bg}"></div>
      <div class="fix ${(joker ? "J" : rank).length > 1 ? "two" : ""}"><span>${joker ? "J" : rank}</span><b>${glyph}</b></div></div>`;
  }
  const [glyph, color] = joker ? ["★\uFE0E", "joker"] : SUITS[suit];
  const r = joker ? "J" : rank;
  const pos = x != null ? `${x}% ${y ?? 50}%` : ph?.sample ? "50% 50%" : facePos(ph, 42 / 61);
  const bg = ph ? `background:url('${ph.url}') ${pos} / ${ph.sample ? Math.round(zoom * 100) + "%" : zoom === 1 ? "cover" : Math.round(zoom * 120) + "%"} no-repeat, ${ph.bg || "#e8ecf4"}` : "background:var(--surface-2)";
  const ix = (side) => `<div class="ix ${side} ${r.length > 1 ? "two" : ""}"><span class="rk">${r}</span><b class="big">${glyph}</b><b class="sm">${glyph}</b></div>`;
  return `<div class="pc ${color} ${cls}" style="${style}"><div class="win" style="${bg}"></div>${ix("")}${ix("r")}</div>`;
}
// ---------- конструктор UNO (рисунок как в печати, uno.py) ----------

// Палитры, лимиты надписи и цвета надписей рубашек приходят с сервера; здесь — те же значения по умолчанию
let UNO = {
  palettes: [{ key: "pastel", title: "Пастель", colors: ["#4CBED4", "#9CCE4A", "#F69EBE", "#B89CE8"] },
    { key: "classic", title: "Классика", colors: ["#E8413A", "#F6C431", "#3DAA4B", "#2F7BD9"] },
    { key: "candy", title: "Конфетная", colors: ["#FF8FAB", "#FFC46B", "#7ED6C1", "#A79BFF"] },
    { key: "berry", title: "Ягодная", colors: ["#D64570", "#F2A541", "#3FA796", "#6C5CE7"] }],
  default_palette: "pastel", text_max: 12, caption_max: 22,
  inks: { uwu_blush: { ink: ["#968C8E", "#3C3638", "#181416"], center: "text", ring: "#F7F0EA" },
    uwu_sky: { ink: ["#C4E4F6", "#283C50", "#141822"], center: "text", ring: "#282834" },
    uwu_hot: { ink: ["#FCCC1C", "#E27814", "#6E2814"], center: "text", ring: "#6E1446" },
    reverse_lilac: { ink: ["#FFFFFF", "#6040A0", "#14121A"], center: "reverse", ring: "#FAF8FE" },
    reverse_hearts: { ink: ["#FFFFFF", "#D06074", "#28181E"], center: "reverse", ring: "#FFFCFA" },
    reverse_noir: { ink: ["#ECF0EC", "#606460", "#08080A"], center: "reverse", ring: "#DEE4DE" } },
};
let UNO_BACKS = [{ key: "uwu_blush", title: "Пудровая UWU" }, { key: "uwu_sky", title: "Небесная UWU" },
  { key: "uwu_hot", title: "Малиновая UWU" }, { key: "reverse_lilac", title: "Сиреневый разворот" },
  { key: "reverse_hearts", title: "Разворот с сердечками" }, { key: "reverse_noir", title: "Чёрный разворот" }];
let UNO_DEFAULT_BACK = "reverse_lilac";
const UNO_WILD = { base: "#2C2836", dark: "#100E16" };
const isUno = (pid) => pid === "uno";
const backsFor = (pid) => (isUno(pid) ? UNO_BACKS : BACKS);
const defaultBackFor = (pid) => (isUno(pid) ? UNO_DEFAULT_BACK : DEFAULT_BACK);
const unoPaletteColors = (key) => (UNO.palettes.find((p) => p.key === key) || UNO.palettes[0]).colors.slice();

// Как palette() на сервере: тёмный контур и светлый ободок считаются от основного цвета
function unoPalette(colors) {
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const mix = (a, b, t) => a.map((x, i) => Math.round(x + (b[i] - x) * t));
  const css = (c) => `rgb(${c.join(",")})`;
  return colors.map((h) => {
    const base = hex(h), lum = (0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2]) / 255;
    return { base: css(base), dark: css(mix(base, [12, 10, 20], 0.5 + 0.18 * lum)), light: css(mix(base, [255, 255, 255], 0.82)) };
  });
}

// Та же чистка надписи, что на сервере: только буквы, цифры и простые знаки
const unoClean = (v, max) => (v || "").replace(/[^0-9A-Za-zА-Яа-яЁё !?.,&+\-'’♥]/g, "").replace(/\s+/g, " ").trim().slice(0, max).trim();

function unoDeck() {
  const out = [];
  for (let color = 0; color < 4; color++) {
    out.push({ rank: "0", color });
    for (const r of ["1", "2", "3", "4", "5", "6", "7", "8", "9", "skip", "reverse", "draw2"]) out.push({ rank: r, color }, { rank: r, color });
  }
  for (let k = 0; k < 4; k++) out.push({ rank: "wild", color: null });
  for (let k = 0; k < 4; k++) out.push({ rank: "wild4", color: null });
  return out;
}

function arrowPts(cx, cy, L, w, ang) {
  const a = ang * Math.PI / 180, ux = Math.sin(a), uy = -Math.cos(a), vx = -uy, vy = ux, head = L * .46;
  const t = [cx - ux * L / 2, cy - uy * L / 2], n = [cx + ux * (L / 2 - head), cy + uy * (L / 2 - head)], tip = [cx + ux * L / 2, cy + uy * L / 2];
  return [[t[0] + vx * w / 2, t[1] + vy * w / 2], [n[0] + vx * w / 2, n[1] + vy * w / 2], [n[0] + vx * w * 1.3, n[1] + vy * w * 1.3], tip,
    [n[0] - vx * w * 1.3, n[1] - vy * w * 1.3], [n[0] - vx * w / 2, n[1] - vy * w / 2], [t[0] - vx * w / 2, t[1] - vy * w / 2]]
    .map((p) => p.map((v) => v.toFixed(1)).join(",")).join(" ");
}

// Значок действия (SVG 100×100): один общий контур, как на печати. cols — 4 цвета палитры для «смены цвета» и «+4»
function unoSym(kind, fill, dark, ow = 7, cols = []) {
  const o = `stroke="${dark}" stroke-width="${ow * 2}" stroke-linejoin="round"`;
  let body = "";
  if (kind === "skip") {
    const ring = (s, w) => `<circle cx="50" cy="50" r="30" fill="none" stroke="${s}" stroke-width="${w}"/>`;
    const bar = (s, w) => `<line x1="31" y1="69" x2="69" y2="31" stroke="${s}" stroke-width="${w}"/>`;
    body = ring(dark, 12 + ow * 2) + bar(dark, 12 + ow * 2) + ring(fill, 12) + bar(fill, 12);
  } else if (kind === "reverse") {
    const up = arrowPts(50 - 10.6 + 4.9, 50 - 10.6 - 4.9, 56, 12, 45), down = arrowPts(50 + 10.6 - 4.9, 50 + 10.6 + 4.9, 56, 12, 225);
    body = `<polygon points="${up}" fill="${dark}" ${o}/><polygon points="${down}" fill="${dark}" ${o}/>
      <polygon points="${up}" fill="${fill}"/><polygon points="${down}" fill="${fill}"/>`;
  } else if (kind === "draw2" || kind === "wild4") {
    const n = kind === "draw2" ? 2 : 4, cw = n === 2 ? 34 : 25, ch = n === 2 ? 48 : 36;
    const offs = n === 2 ? [[-9, 7], [9, -7]] : [[-21, 15], [-7, 5], [7, -5], [21, -15]];
    const fills = n === 2 ? [fill, fill] : cols;
    body = `<g transform="rotate(12 50 50)">${offs.map(([dx, dy], i) => `<rect x="${50 + dx - cw / 2}" y="${50 + dy - ch / 2}" width="${cw}" height="${ch}" rx="4"
      fill="${fills[i]}" stroke="${dark}" stroke-width="${ow}" paint-order="stroke"/>`).join("")}</g>`;
  } else if (kind === "wild") {
    const R = 42, pie = (i) => { const a0 = (-90 + i * 90) * Math.PI / 180, a1 = (i * 90) * Math.PI / 180;
      return `<path d="M50 50 L${50 + R * Math.cos(a0)} ${50 + R * Math.sin(a0)} A${R} ${R} 0 0 1 ${50 + R * Math.cos(a1)} ${50 + R * Math.sin(a1)}Z" fill="${cols[i]}"/>`; };
    body = `<g transform="rotate(28 50 50)"><circle cx="50" cy="50" r="${R + ow}" fill="${dark}"/>${[0, 1, 2, 3].map(pie).join("")}</g>`;
  }
  return `<svg viewBox="0 0 100 100" aria-hidden="true">${body}</svg>`;
}

function unoCard({ rank, color, ph, colors, cls = "", style = "" }) {
  const pal = unoPalette(colors || unoPaletteColors(UNO.default_palette));
  const cols = pal.map((p) => p.base);
  const { base, dark } = color == null ? UNO_WILD : pal[color];
  const digit = /^\d$/.test(rank);
  const plus = rank === "draw2" || rank === "wild4";
  const corner = digit || plus ? `<span>${rank === "draw2" ? "+2" : rank === "wild4" ? "+4" : rank}</span>` : unoSym(rank, "#fff", dark, 9, cols);
  let mid;
  if (digit && ph) mid = `<div class="ovi"><div class="ovp" style="${photoStyle(ph, .7, [0.5, 0.42])}"></div></div>`;
  else if (digit) mid = `<b class="big">${rank}</b>`;
  else mid = `<div class="sym s-${rank}">${unoSym(rank, base, dark, 7, cols)}</div>`;
  return `<div class="uc u-${color == null ? "wild" : color} ${cls}" style="--b:${base};--d:${dark};${style}"><i class="fr"></i><div class="ov">${mid}</div>
    <div class="ci ${plus ? "plus" : ""}">${corner}</div><div class="ci r ${plus ? "plus" : ""}">${corner}</div></div>`;
}

// Рубашка UNO: без своих надписи и фото — готовая картинка; иначе «пустая» рубашка, а сверху фото и надпись.
// Размер надписи подбирается так же, как на сервере: чтобы с наклоном влезла в ширину карты.
function unoBack(dk, style = "") {
  const text = unoClean(dk.backText, UNO.text_max).toUpperCase(), caption = unoClean(dk.backCaption, UNO.caption_max);
  if (!text && !caption && !dk.backPhoto) return cardBack(dk.back, style);
  const spec = UNO.inks[dk.back] || UNO.inks[UNO_DEFAULT_BACK];
  const [fill, shade, outline] = spec.ink;
  const cos = Math.cos(24 * Math.PI / 180), sin = Math.sin(24 * Math.PI / 180);
  const fsMax = text.length <= 4 ? 27 : 23.8;
  let fs = text ? Math.min(fsMax, 88.9 / (1.02 * text.length * cos + 1.25 * sin)) : 0;
  let cap = caption ? Math.max(5.1, fs * .3) : 0;
  if (caption) { // подпись тоже должна влезть
    const capW = .74 * caption.length * cap * cos;
    if (capW > 88.9) { const k = 88.9 / capW; cap *= k; fs *= k; }
  }
  const depth = fs * .13, steps = 7;
  const shadow = text ? Array.from({ length: steps }, (_, i) => { const k = depth * (i + 1) / steps;
    return `${(k * .6).toFixed(2)}cqw ${k.toFixed(2)}cqw 0 ${shade}`; }).join(",") : "none";
  const photo = dk.backPhoto ? `<div class="ubp" style="box-shadow:0 0 0 .56cqw ${spec.ring}"><div class="ovp" style="${photoStyle(dk.backPhoto)}"></div></div>` : "";
  const word = text ? `<b style="font-size:${fs.toFixed(2)}cqw;color:${fill};-webkit-text-stroke:${(fs / 8).toFixed(2)}cqw ${outline};text-shadow:${shadow}">${esc(text)}</b>` : "";
  const sub = caption ? `<small style="font-size:${cap.toFixed(2)}cqw;-webkit-text-stroke:${(cap / 4.5).toFixed(2)}cqw ${outline}">${esc(caption)}</small>` : "";
  return `<div class="pc back ub" style="background-image:url('img/backs/${dk.back}_blank.png');${style}">${photo}
    ${word || sub ? `<div class="ubt">${word}${sub}</div>` : ""}</div>`;
}

// Экран UNO в конструкторе: цвета, рубашка, надпись и фото на рубашке
function unoDesigner(dk) {
  const pal = unoPalette(dk.colors);
  return `<div class="h-section"><h2>Цвета карт <span class="muted" style="font-weight:500">· ${esc(dk.palette === "custom" ? "свои" : (UNO.palettes.find((p) => p.key === dk.palette) || {}).title || "")}</span></h2></div>
    <div class="palettes" role="radiogroup" aria-label="Палитра карт">${UNO.palettes.map((p) => `<button class="pal-opt ${p.key === dk.palette ? "on" : ""}" role="radio"
      aria-checked="${p.key === dk.palette}" data-act="uno-palette" data-value="${p.key}"><span class="dots">${p.colors.map((c) => `<i style="background:${c}"></i>`).join("")}</span>${esc(p.title)}</button>`).join("")}</div>
    <div class="swatches">${dk.colors.map((c, i) => `<label class="swatch" style="--c:${c};--d:${pal[i].dark}" aria-label="Цвет ${i + 1}">
      <input type="color" value="${c}" data-model="deck.colors.${i}"><span>${i + 1}</span></label>`).join("")}
      <span class="small muted">Нажмите на кружок, чтобы выбрать свой цвет. Контуры и оттенки Тюша подберёт сама.</span></div>
    <div class="uno-preview">${[["7", 0], ["skip", 1], ["draw2", 2], ["reverse", 3]].map(([r, c], k) => unoCard({ rank: r, color: c, ph: k === 0 ? dk.photos[0] : null, colors: dk.colors })).join("")}</div>`;
}

function unoBackEditor(dk) {
  const tmax = UNO.text_max, cmax = UNO.caption_max;
  const tlen = (dk.backText || "").length, clen = (dk.backCaption || "").length;
  return `<div class="h-section"><h2>Надпись и фото на рубашке</h2></div>
    <div class="ub-edit">
      <div class="ub-prev">${unoBack(dk, "position:relative;aspect-ratio:63/88")}</div>
      <div class="ub-fields">
        <label class="field"><span class="lbl">Надпись <span class="muted tabular">${tlen}/${tmax}</span></span>
          <input class="input" type="text" maxlength="${tmax}" placeholder="${(UNO.inks[dk.back] || {}).center === "text" ? "UWU" : "Например, СЕМЬЯ"}" value="${esc(dk.backText || "")}" data-model="deck.backText" autocomplete="off"></label>
        <label class="field"><span class="lbl">Подпись под ней <span class="muted tabular">${clen}/${cmax}</span></span>
          <input class="input" type="text" maxlength="${cmax}" placeholder="Например, Новый год 2026" value="${esc(dk.backCaption || "")}" data-model="deck.backCaption" autocomplete="off"></label>
        <div class="row" style="gap:8px;flex-wrap:wrap">
          <label class="btn soft sm" style="position:relative;overflow:hidden">${icon("photo")}${dk.backPhoto ? "Заменить фото" : "Фото на рубашку"}
            <input type="file" data-file="unoback" accept="image/jpeg,image/png" style="position:absolute;inset:0;opacity:0"></label>
          ${dk.backPhoto ? `<button class="btn ghost sm" data-act="uno-back-photo-off">Убрать фото</button>` : ""}
        </div>
      </div>
    </div>
    <div class="small muted">Надпись можно не писать. Буквы, цифры и простые знаки; размер подстроится сам, чтобы всё влезло. Фото встанет в овал рубашки.</div>`;
}

const cardBack = (key = DEFAULT_BACK, style = "") => `<div class="pc back" style="background-image:url('img/backs/${key}.png');${style}"></div>`;

function productArt(p, big = false) {
  const s = SAMPLE_PHOTOS;
  const sample = (i) => ({ ...s[i], sample: true });
  if (p.art === "classic") return `<div class="fan">${cardBack("hearts")}${playingCard({ rank: "Д", suit: 1, ph: sample(0) })}${playingCard({ rank: "Т", suit: 0, ph: sample(1) })}</div>`;
  if (p.art === "full") return `<div class="fan">${playingCard({ rank: "JOKER", ph: sample(2) })}${playingCard({ rank: "К", suit: 2, ph: sample(1) })}${cardBack("night")}</div>`;
  if (p.art === "dates") return `<div class="fan"><div class="pc q"><span>${esc(QUESTIONS[1])}</span></div><div class="pc q"><span>${esc(QUESTIONS[0])}</span></div><div class="pc q"><span>${esc(QUESTIONS[2])}</span></div></div>`;
  if (p.art === "memory") return `<div class="fan" style="aspect-ratio:1;width:44%">${[0, 0, 1].map((i) => `<div class="pc memo"><div class="win" style="${photoStyle(sample(i))};inset:8%"></div></div>`).join("")}</div>`;
  if (p.art === "uno") return `<div class="fan">${cardBack("reverse_lilac")}${unoCard({ rank: "7", color: 2, ph: sample(0) })}${unoCard({ rank: "reverse", color: 0 })}</div>`;
  const ca = p.cat === "gifts" ? craftArt(p.art, sample) : "";
  if (ca) return ca;
  if (p.art === "doc") return `<div class="fan" style="aspect-ratio:210/297;width:44%"><div class="page"></div><div class="page"></div><div class="page"><b>1</b></div></div>`;
  return `<div class="fan" style="aspect-ratio:1;width:46%">${[2, 1, 0].map((i) => `<div class="pc memo" style="border-radius:6%"><div class="win" style="${photoStyle(sample(i))};inset:6%;outline:0;border-radius:3%"></div></div>`).join("")}</div>`;
}
const artBg = { wishes: "#FBEDEA", stickers: "#EAF0FB", calendar: "#F4EEE4", postcards: "#EAF3EC", box: "#EFE9F8", game: "#E8EEF8",
  classic: "#E4ECFD", full: "#EDE7F8", uno: "#FCE8F0", dates: "#FBE6EA", memory: "#E3F3EC", doc: "#EEF1F7", photo: "#FDF1DA" };

// ---------- расчёт цены ----------

function photoUnit(j) {
  const base = PRICES.photo[j.format][j.color ? "color" : "bw"];
  return Math.round(base * 100 * (100 + PRICES.quality_markup[j.quality]) / 100) / 100;
}
// Надбавки: бумага (₽ за лист A4) и улучшение слабых фото — так же считает сервер (pricing.quote)
function addExtras(q, paper, sheets, photosList, enhance) {
  const ex = paperExtra(paper) * sheets;
  if (ex) { q.lines.push([`${PAPERS[paper].title}: ${sheets} л. × ${rub(paperExtra(paper))}`, ex]); q.total += ex; }
  const n = enhance ? weakPhotos(photosList || []) : 0;
  if (n) { const e = n * (PRICES.craft?.enhance_photo ?? 10); q.lines.push([`Улучшение ${n} фото`, e]); q.total += e; }
  q.total = Math.round(q.total * 100) / 100;
  return q;
}
const photoSheets = (j) => Math.ceil(j.photos.length * j.copies / (j.format === "10x15" ? 2 : 1));
const deckCount = (dk) => (isUno(dk.pid) ? 108 : dk.pid === "deck54" ? 54 : 36);
const deckSheets = (dk) => Math.ceil(deckCount(dk) / 9);
function quotePhoto(j) {
  const rate = photoUnit(j);
  const n = j.photos.length * j.copies;
  return addExtras({ total: Math.round(n * rate * 100) / 100, lines: [[`${n} ${plural(n, "отпечаток", "отпечатка", "отпечатков")} × ${rub(rate)}`, n * rate]], valid: n > 0 },
    j.paper, photoSheets(j), j.photos, j.enhance);
}
function quoteDoc(j) {
  const rate = PRICES.doc[j.color ? "color" : "bw"];
  const n = j.pages * j.copies;
  return addExtras({ total: n * rate, lines: [[`${n} ${plural(n, "страница", "страницы", "страниц")} × ${rub(rate)}`, n * rate]], valid: j.pages > 0 && !j.checking },
    j.paper, n, [], false);
}
function quoteDeck(dk) {
  const p = byId(dk.pid);
  return addExtras({ total: p.price, lines: [[p.title, p.price]], valid: dk.photos.length > 0 }, dk.paper, deckSheets(dk), dk.photos, dk.enhance);
}

// ---------- конструктор: раскладка колоды ----------

function deckLayout(dk) {
  const p = byId(dk.pid);
  if (isUno(p.id)) {  // фото только на картах с цифрами, по очереди
    let k = 0;
    return unoDeck().map((c, i) => {
      const photoIndex = /^\d$/.test(c.rank) && dk.photos.length ? k++ % dk.photos.length : null;
      return { ...c, i, o: {}, uno: true, colors: dk.colors, ph: photoIndex == null ? null : dk.photos[photoIndex], photoIndex };
    });
  }
  const cards = [];
  const ranks = p.id === "deck54" ? RANKS54 : RANKS36;
  SUITS.forEach((_, s) => ranks.forEach((r) => cards.push({ rank: r, suit: s })));
  if (p.id === "deck54") cards.push({ rank: "JOKER" }, { rank: "JOKER" });
  if (dk.style === "vintage") {  // как на сервере: фигуры со своим рисунком, фото по очереди на остальных
    let k = 0;
    return cards.map((c, i) => {
      const photoIndex = isCourt(c) || !dk.photos.length ? null : k++ % dk.photos.length;
      return { ...c, i, o: {}, vintage: true, ph: photoIndex == null ? null : dk.photos[photoIndex], photoIndex };
    });
  }
  if (dk.style === "full" && dk.photos.length) {
    const lums = dk.photos.map((ph) => ph.lum ?? 0.5);
    const order = assignByLight(cards, lums);
    return cards.map((c, i) => {
      const ink = inkFor(c) || (lums[order[i]] >= 0.5 ? "black" : "white");
      return { ...c, i, o: {}, ph: dk.photos[order[i]], photoIndex: order[i], ink, full: true };
    });
  }
  return cards.map((c, i) => {
    const o = dk.edits[i] || {};
    const photoIndex = i % Math.max(dk.photos.length, 1);
    return { ...c, i, o, ph: dk.photos[photoIndex], photoIndex };
  });
}

// Та же раскладка, что на сервере (cards.assign_by_light): чёрные масти — на светлые фото, белые — на тёмные
function inkFor(c) {
  if (c.rank === "JOKER") return null;
  return c.suit === 0 || c.suit === 3 ? "black" : "white";
}
function assignByLight(deck, lums) {
  const n = deck.length, p = lums.length;
  const base = Math.floor(n / p), extra = n % p;
  const decisive = new Set([...lums.keys()].sort((a, b) => Math.abs(lums[b] - 0.5) - Math.abs(lums[a] - 0.5)).slice(0, extra));
  const slots = [];
  lums.forEach((_, i) => { for (let k = 0; k < base + (decisive.has(i) ? 1 : 0); k++) slots.push(i); });
  slots.sort((a, b) => lums[b] - lums[a]);
  const idx = (pred) => deck.map((c, k) => (pred(inkFor(c)) ? k : -1)).filter((k) => k >= 0);
  const black = idx((x) => x === "black"), white = idx((x) => x === "white"), other = idx((x) => x === null);
  const groups = [[black, slots.slice(0, black.length)], [other, slots.slice(black.length, black.length + other.length)],
    [white, slots.slice(black.length + other.length)]];
  const result = new Array(n).fill(0);
  for (const [cardsIdx, groupSlots] of groups) {
    const seen = new Map();
    const keyed = groupSlots.map((i) => { const k = seen.get(i) || 0; seen.set(i, k + 1); return [k, -lums[i], i]; });
    keyed.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
    cardsIdx.forEach((k, j) => { result[k] = keyed[j][2]; });
  }
  return result;
}

// Яркость угла под индексом (как на сервере: фото вписано в карту 63×88, угол 17×23 мм)
function cornerLuminance(url) {
  return new Promise((resolve) => {
    const im = new Image();
    im.onload = () => {
      try {
        const W = 126, H = 176, c = document.createElement("canvas");
        c.width = W; c.height = H;
        const k = Math.max(W / im.naturalWidth, H / im.naturalHeight);
        const w = im.naturalWidth * k, h = im.naturalHeight * k;
        const ctx = c.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(im, (W - w) * 0.5, (H - h) * 0.45, w, h);
        const d = ctx.getImageData(0, 0, Math.round(W * 17 / 63), Math.round(H * 23 / 88)).data;
        let sum = 0;
        for (let i = 0; i < d.length; i += 4) sum += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
        resolve(sum / (d.length / 4) / 255);
      } catch (e) { resolve(0.5); }
    };
    im.onerror = () => resolve(0.5);
    im.src = url;
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
  if (o.kind === "doc") return `<div class="othumb" style="background:${artBg.doc}">${icon("doc")}</div>`;
  if (o.kind === "craft") return `<div class="othumb" style="background:${artBg[o.product] || artBg.memory}">${icon(CRAFT_ICON[o.product] || "gift")}</div>`;
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

// ---------- бумага, улучшение фото, кадр по лицу ----------

// Варианты бумаги, надбавки и наличие на складе приходят с сервера (materials.py)
let PAPERS = {
  plain: { title: "Обычная", hint: "80 г/м², как в офисе", extra: 0, state: "ok" },
  thick: { title: "Плотная", hint: "300 г/м², не просвечивает", extra: 6, state: "ok" },
  photo: { title: "Фотобумага", hint: "глянцевая, яркие цвета", extra: 0, state: "ok" },
  matte: { title: "Плотная матовая", hint: "без бликов, как открытка", extra: 8, state: "ok" },
  card: { title: "Картон", hint: "300 г/м², как у магазинных карт", extra: 0, state: "ok" },
  card_lam: { title: "Картон + ламинация", hint: "не боится воды и царапин", extra: 25, state: "ok" },
  sticker: { title: "Самоклейка", hint: "клеится на телефон, ноутбук, кружку", extra: 0, state: "ok" },
};
let PAPER_CHOICES = { cards: ["card", "card_lam"], photo: ["photo", "matte"], doc: ["plain", "thick"] };
let ENH = { available: false, low_res: 1000, max: 30 };

const pickPaper = (choices) => choices.find((k) => PAPERS[k]?.state !== "out") || choices[0];
const paperExtra = (k) => PAPERS[k]?.extra || 0;

function paperPicker(model, choices, value, sheets) {
  if (!choices || choices.length < 2) {
    const k = choices?.[0];
    return k ? `<div class="card flat"><div class="row"><span class="tile-icon">${icon("layers")}</span><div class="grow">
      <div style="font-weight:600">${esc(PAPERS[k]?.title || "")}</div><div class="small muted">${esc(PAPERS[k]?.hint || "")}</div></div></div></div>` : "";
  }
  return `<div class="h-section"><h2>Бумага</h2></div><div class="papers" role="radiogroup" aria-label="Бумага">${choices.map((k) => {
    const p = PAPERS[k] || { title: k, hint: "", extra: 0, state: "ok" };
    const off = p.state === "out";
    const extra = p.extra ? `+${rub(p.extra * sheets)}` : "без доплаты";
    return `<button class="paper-opt ${k === value ? "on" : ""}" role="radio" aria-checked="${k === value}" ${off ? "disabled" : ""}
      data-act="set" data-model="${model}" data-value="${k}"><span class="t">${esc(p.title)}</span><span class="s">${esc(p.hint)}</span>
      <span class="x ${off ? "no" : p.state === "low" ? "warn" : ""}">${off ? "закончилась" : p.state === "low" ? `осталось мало · ${extra}` : extra}</span></button>`;
  }).join("")}</div>`;
}

const weakPhotos = (list) => (ENH.available ? Math.min(ENH.max, list.filter((ph) => ph && Math.min(ph.w, ph.h) < ENH.low_res).length) : 0);
function enhanceBlock(model, list, on) {
  const n = weakPhotos(list);
  if (!n) return "";
  const price = (PRICES.craft?.enhance_photo ?? 10) * n;
  return `<button class="check enh" role="checkbox" aria-checked="${on}" data-act="toggle" data-model="${model}"><span class="box">${icon("check")}</span>
    <span><b>Улучшить ${n} ${plural(n, "слабое фото", "слабых фото", "слабых фото")} нейросетью · +${rub(price)}</b>
    <small>Увеличим и сделаем чётче для печати. Нейросеть может чуть «дорисовать» мелкие детали.</small></span></button>`;
}

// Кадр по лицу — та же формула, что photoai.centering на сервере
function focus(ph, aspect, dflt = [0.5, 0.42]) {
  if (!ph?.face || !ph.w || !ph.h) return dflt;
  const [x1, y1, x2, y2] = ph.face, W = ph.w, H = ph.h;
  const [cw, ch] = W / H > aspect ? [H * aspect, H] : [W, W / aspect];
  const axis = (c, crop, full) => (full - crop < 1 ? 0.5 : Math.min(1, Math.max(0, (c - crop / 2) / (full - crop))));
  return [axis((x1 + x2) / 2 * W, cw, W), axis((y1 + y2) / 2 * H, ch, H)];
}
const facePos = (ph, aspect, dflt) => focus(ph, aspect, dflt).map((v) => `${(v * 100).toFixed(1)}%`).join(" ");
function faceCut(ph, aspect) {
  if (!ph?.face) return false;
  const [x1, y1, x2, y2] = ph.face, W = ph.w, H = ph.h;
  const [cw, ch] = W / H > aspect ? [H * aspect, H] : [W, W / aspect];
  return (x2 - x1) * W > cw * 1.02 || (y2 - y1) * H > ch * 1.02;
}

async function thumbBlob(ph, side = 900) {
  if (ph.thumbs?.[side]) return ph.thumbs[side];
  let blob = ph.file;
  try {
    const bmp = await createImageBitmap(ph.file);
    const k = Math.min(1, side / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    bmp.close?.();
    blob = await new Promise((resolve) => c.toBlob((b) => resolve(b || ph.file), "image/jpeg", 0.88));
  } catch (e) { /* отдадим исходный файл */ }
  ph.thumbs = { ...(ph.thumbs || {}), [side]: blob };
  return blob;
}

// Ищем лица на сервере (тот же детектор, что и для печати), чтобы превью кадрировало как на бумаге
async function detectFace(ph) {
  if (!ph?.file || ph.faceChecked) return;
  ph.faceChecked = true;
  try {
    const form = new FormData();
    form.append("photo", await thumbBlob(ph, 640), "thumb.jpg");
    const r = await api("/mapi/faces", { method: "POST", body: form });
    if (r.box) { ph.face = r.box; render(); }
  } catch (e) { /* без лица — кадр по центру */ }
}

// ---------- 3D-превью: карточка крутится, видно лицо и оборот; можно повернуть пальцем ----------

function flip3d(front, back, ar = "63/88") {
  return `<div class="flip3d" data-flip style="--ar:${ar}"><div class="flip-in"><div class="flip-face">${front}</div>
    <div class="flip-face flip-back">${back}</div></div></div>
    <div class="flip-hint">${icon("repeat", "sm")}Покрутите пальцем</div>`;
}
const FLIP = new WeakMap();
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)");
function flipLoop(t) {
  document.querySelectorAll("[data-flip]").forEach((el) => {
    let s = FLIP.get(el);
    if (!s) { s = { a: -24, v: 0.03, drag: false, last: t }; FLIP.set(el, s); }
    const dt = Math.min(64, t - s.last);
    s.last = t;
    if (!s.drag) {
      const base = REDUCED.matches ? 0 : 0.03;
      s.v += (base - s.v) * 0.025;
      s.a += s.v * dt;
    }
    const inner = el.firstElementChild;
    if (inner) inner.style.transform = `rotateX(6deg) rotateY(${s.a.toFixed(2)}deg)`;
  });
  requestAnimationFrame(flipLoop);
}
requestAnimationFrame(flipLoop);
document.addEventListener("pointerdown", (e) => {
  const el = e.target.closest("[data-flip]");
  if (!el) return;
  const s = FLIP.get(el);
  if (!s) return;
  Object.assign(s, { drag: true, x0: e.clientX, a0: s.a, px: e.clientX, pt: performance.now(), v: 0 });
  el.setPointerCapture?.(e.pointerId);
  const move = (ev) => {
    const now = performance.now();
    s.a = s.a0 + (ev.clientX - s.x0) * 0.7;
    s.v = Math.max(-0.8, Math.min(0.8, (ev.clientX - s.px) * 0.7 / Math.max(8, now - s.pt)));
    s.px = ev.clientX; s.pt = now;
  };
  const up = () => { s.drag = false; el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up); };
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", up);
});

// ---------- изделия конструктора (products.py): поля приходят с сервера, экран строится по ним ----------

let CRAFTS = [];
const CRAFT_ART = { memory: "memory", dates: "dates", wishes: "wishes", stickers: "stickers", calendar: "calendar",
  postcards: "postcards", box: "box", game: "game" };
const CRAFT_ICON = { memory: "layers", dates: "heart", wishes: "stars", stickers: "scissors", calendar: "calendar",
  postcards: "letter", box: "box", game: "cards" };
const craftSpec = (key) => CRAFTS.find((c) => c.key === key);

function craftPriceFrom(key) {
  const p = PRICES.craft || {};
  return { memory: (p.memory_base || 0) + 6 * (p.memory_pair || 0), dates: p.dates_sheet, wishes: p.wishes_sheet,
    stickers: p.stickers_sheet, calendar: p.calendar, postcards: p.postcard, box: p.box, game: p.game_sheet }[key] || 0;
}

function registerCrafts(list) {
  CRAFTS = list;
  for (let i = PRODUCTS.length - 1; i >= 0; i--) if (PRODUCTS[i].cat === "gifts") PRODUCTS.splice(i, 1);
  list.forEach((c) => {
    const photos = c.fields.find((f) => f.type === "photos");
    PRODUCTS.push({ id: c.key, cat: "gifts", title: c.title, sub: c.sub, art: CRAFT_ART[c.key] || "memory", craft: c,
      priceFrom: `от ${craftPriceFrom(c.key)} ₽`,
      includes: [[CRAFT_ICON[c.key] || "gift", c.sub],
        ...(photos ? [["photo", photos.max > 1 ? `Фото: от ${photos.min} до ${photos.max}` : "Одно фото"]] : []),
        ["layers", "Бумага на выбор: " + c.papers.map((k) => PAPERS[k]?.title.toLowerCase() || k).join(" или ")]],
      reqs: photos ? ["Лучше от 1000 px по короткой стороне", "JPG или PNG до 20 МБ", "Лица Тюша сама поставит в центр кадра"] : null });
  });
}

function craftDefaults(spec) {
  const v = {};
  spec.fields.forEach((f) => {
    if (f.type === "photos" || f.type === "csv") return;
    if (f.type === "multi") v[f.key] = [...(f.default || [])];
    else if (f.type === "lines" || f.type === "textarea") v[f.key] = "";
    else v[f.key] = f.default ?? "";
  });
  return v;
}

function startCraft(key) {
  const spec = craftSpec(key);
  if (!spec) return false;
  if (!state.craft || state.craft.key !== key) {
    state.craft = { key, photos: [], values: craftDefaults(spec), csv: null, paper: pickPaper(spec.papers), enhance: false,
      pv: null, loading: false, err: "" };
  }
  queuePreview(50);
  return true;
}

let pvTimer = null, pvSeq = 0;
function queuePreview(delay = 450) {
  clearTimeout(pvTimer);
  pvTimer = setTimeout(runPreview, delay);
}
async function runPreview() {
  const c = state.craft;
  if (!c) return;
  const seq = ++pvSeq;
  c.loading = true;
  if (current().name === "craft") render();
  try {
    const form = new FormData();
    form.append("meta", JSON.stringify({ product: c.key, ...c.values, n_photos: c.photos.length,
      names: c.photos.map((p) => p.name), paper: c.paper }));
    const send = c.photos.slice(0, c.key === "game" ? 8 : c.key === "calendar" ? 2 : 1);
    for (const ph of send) form.append("photo", await thumbBlob(ph), ph.name);
    if (c.csv) form.append("csv", new Blob([c.csv.text], { type: "text/csv" }), c.csv.name);
    const r = await api("/mapi/preview", { method: "POST", body: form });
    if (seq !== pvSeq) return;
    c.pv = r.invalid ? { invalid: r.invalid } : r;
    c.err = "";
  } catch (e) {
    if (seq === pvSeq) c.err = e.message;
  } finally {
    if (seq === pvSeq) {
      c.loading = false;
      if (["craft", "review"].includes(current().name)) render();
    }
  }
}

function quoteCraft(c) {
  const enh = c.enhance ? (PRICES.craft?.enhance_photo ?? 10) * weakPhotos(c.photos) : 0;
  const base = c.pv && !c.pv.invalid ? c.pv.amount : 0;
  const lines = c.pv && !c.pv.invalid ? [[c.pv.detail, base]] : [];
  if (enh) lines.push([`Улучшение ${weakPhotos(c.photos)} фото`, enh]);
  return { total: base + enh, lines, valid: !!(c.pv && !c.pv.invalid) && !c.loading };
}

function craftPreviewArt(c, spec) {
  const pv = c.pv;
  const ar = c.key === "memory" ? "1/1" : c.key === "postcards" ? "100/140" : "63/88";
  if (!pv || pv.invalid || !pv.front) {
    return `<div class="pv-skel" style="aspect-ratio:${ar}">${c.loading ? `<span class="spin"></span>` : icon(CRAFT_ICON[c.key] || "gift", "lg")}</div>`;
  }
  const img = (src) => `<img src="${src}" alt="" draggable="false">`;
  if (pv.back && spec.duplex) return flip3d(img(pv.front), img(pv.back), ar);
  if (pv.back) return `<div class="pv-pair">${img(pv.back)}${img(pv.front)}</div>`;  // календарь: обложка и месяц
  return `<div class="pv-one ${c.key}">${img(pv.front)}</div>`;
}

function craftField(c, f) {
  const v = c.values[f.key];
  const lbl = (extra = "") => `<span class="lbl">${esc(f.label)}${extra}</span>`;
  if (f.type === "photos") {
    const n = c.photos.length;
    return `<div class="field">${lbl(`<span class="muted tabular">${n} из ${f.max}${f.min ? ` · нужно от ${f.min}` : ""}</span>`)}
      <div class="photos">${c.photos.map((ph, i) => `<div class="photo" style="${photoStyle(ph)}"><span class="n">${i + 1}</span>
        ${lowRes(ph) ? `<span class="bad" title="Низкое разрешение">${icon("warn")}</span>` : ""}
        <button class="rm" data-act="craft-remove" data-i="${i}" aria-label="Убрать фото ${i + 1}">${icon("close", "sm")}</button></div>`).join("")}
        ${n < f.max ? `<label class="photo add" aria-label="Добавить фото"><input type="file" accept="image/jpeg,image/png" ${f.max > 1 ? "multiple" : ""} data-file="craft">${icon("upload", "lg")}</label>` : ""}</div></div>`;
  }
  if (f.type === "select") {
    return `<div class="field">${lbl()}<div class="chips wrap">${f.options.map(([k, t]) =>
      `<button class="chip ${k === v ? "on" : ""}" data-act="craft-set" data-k="${f.key}" data-v="${esc(k)}">${esc(t)}</button>`).join("")}</div></div>`;
  }
  if (f.type === "multi") {
    return `<div class="field">${lbl()}<div class="chips wrap">${f.options.map(([k, t]) =>
      `<button class="chip ${v.includes(k) ? "on" : ""}" data-act="craft-toggle" data-k="${f.key}" data-v="${esc(k)}">${v.includes(k) ? icon("check", "sm") : ""}${esc(t)}</button>`).join("")}</div></div>`;
  }
  if (f.type === "lines") {
    const n = v.split("\n").filter((x) => x.trim()).length;
    return `<div class="field">${lbl(`<span class="muted tabular ${n > f.max_items ? "over" : ""}">${n} из ${f.max_items}</span>`)}
      <textarea class="input" rows="4" maxlength="${f.max_items * (f.max_chars + 1)}" placeholder="${esc(f.placeholder || "")}" data-model="craft.values.${f.key}">${esc(v)}</textarea>
      <span class="hint">До ${f.max_chars} символов в строке — длинный текст Тюша аккуратно уменьшит.</span></div>`;
  }
  if (f.type === "text") {
    return `<label class="field">${lbl(`<span class="muted tabular">${v.length}/${f.max}</span>`)}
      <input class="input" type="text" maxlength="${f.max}" placeholder="${esc(f.placeholder || "")}" value="${esc(v)}" data-model="craft.values.${f.key}" autocomplete="off"></label>`;
  }
  if (f.type === "textarea") {
    return `<label class="field">${lbl(`<span class="muted tabular">${v.length}/${f.max}</span>`)}
      <textarea class="input" rows="4" maxlength="${f.max}" placeholder="${esc(f.placeholder || "")}" data-model="craft.values.${f.key}">${esc(v)}</textarea></label>`;
  }
  if (f.type === "number") {
    return `<div class="field"><div class="row" style="justify-content:space-between">${lbl()}
      <div class="stepper"><button data-act="craft-step" data-k="${f.key}" data-d="-1" aria-label="Меньше" ${v <= f.min ? "disabled" : ""}>${icon("minus")}</button>
      <output class="tabular">${v}</output><button data-act="craft-step" data-k="${f.key}" data-d="1" aria-label="Больше" ${v >= f.max ? "disabled" : ""}>${icon("plus")}</button></div></div></div>`;
  }
  if (f.type === "back") {
    return `<div class="h-section"><h2>${esc(f.label)} <span class="muted" style="font-weight:500">· ${esc(backTitle(v))}</span></h2></div>
      <div class="backs" role="radiogroup" aria-label="${esc(f.label)}">${BACKS.map((b) => `<button class="back-opt ${b.key === v ? "on" : ""}" role="radio"
        aria-checked="${b.key === v}" data-act="craft-set" data-k="${f.key}" data-v="${b.key}">${cardBack(b.key)}<span>${esc(b.title)}</span></button>`).join("")}</div>`;
  }
  if (f.type === "csv") {
    return `<div class="field">${lbl()}
      <div class="card flat csv-box"><div class="row"><span class="tile-icon">${icon("doc")}</span><div class="grow">
        <div style="font-weight:600">${c.csv ? esc(c.csv.name) : "Таблица не выбрана"}</div>
        <div class="small muted">${c.csv && c.pv?.rows ? `${c.pv.rows} ${plural(c.pv.rows, "строка", "строки", "строк")}, ${c.pv.count} карт` : "Столбцы: название, текст, картинка, количество, цвет, тип"}</div></div>
        <label class="btn soft sm" style="position:relative;overflow:hidden">${c.csv ? "Заменить" : "Выбрать CSV"}<input type="file" accept=".csv,text/csv,text/plain" data-file="csv" style="position:absolute;inset:0;opacity:0"></label></div></div>
      <a class="small" href="${esc(f.sample || "sample_game.csv")}" download>Скачать образец таблицы</a></div>`;
  }
  return "";
}

SCREENS.craft = () => {
  const c = state.craft, spec = craftSpec(c.key);
  const pv = c.pv;
  const q = quoteCraft(c);
  const bad = c.photos.filter(lowRes).length;
  return {
    html: `${topbar(spec.title, c.loading ? "Тюша обновляет образец…" : "")}
    ${steps(["Макет", "Проверка", "Заказ"], 0)}
    <div class="card craft-preview" style="background:${artBg[CRAFT_ART[c.key]] || "#EEF1F7"};box-shadow:none">
      ${craftPreviewArt(c, spec)}
      ${pv && !pv.invalid ? `<div class="small muted" style="text-align:center">${pv.count} шт. · ${pv.sheets} ${plural(pv.sheets, "лист", "листа", "листов")} A4${spec.duplex ? ", с двух сторон" : ""}</div>` : ""}
    </div>
    ${pv?.invalid ? `<div class="notice info">${icon("info")}<div><b>${esc(pv.invalid)}</b><span>Как только всё будет готово, Тюша покажет образец и цену.</span></div></div>` : ""}
    ${c.err ? `<div class="notice warn">${icon("warn")}<div><b>Образец не обновился</b><span>${esc(c.err)}</span></div></div>` : ""}
    ${(pv?.warnings || []).map((w) => `<div class="notice warn">${icon("warn")}<div><span>${esc(w)}</span></div></div>`).join("")}
    ${bad ? `<div class="notice warn">${icon("warn")}<div><b>${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением</b><span>Можно улучшить нейросетью на следующем шаге.</span></div></div>` : ""}
    ${spec.fields.map((f) => craftField(c, f)).join("")}`,
    dock: dockBar(q.valid ? q.total : null, c.loading ? "Обновляем…" : "Проверить заказ", "review-craft", { disabled: !q.valid }),
  };
};

function craftRows(c, spec) {
  const rows = [["Изделие", spec.title]];
  if (c.pv && !c.pv.invalid) rows.push(["Количество", `${c.pv.count} шт.`], ["Листов A4", String(c.pv.sheets) + (spec.duplex ? " (двусторонние)" : "")]);
  spec.fields.forEach((f) => {
    const v = c.values[f.key];
    if (f.type === "photos") rows.push(["Фото", String(c.photos.length)]);
    else if (f.type === "select") rows.push([f.label, (f.options.find((o) => o[0] === v) || [])[1] || ""]);
    else if (f.type === "multi") rows.push([f.label, f.options.filter((o) => v.includes(o[0])).map((o) => o[1].split(" · ")[0]).join(", ") || "—"]);
    else if (f.type === "back") rows.push([f.label, backTitle(v)]);
    else if (f.type === "number") rows.push([f.label, String(v)]);
    else if (f.type === "csv") rows.push([f.label, c.csv?.name || "—"]);
    else if (v) rows.push([f.label.replace(/ \(.*\)$/, "").replace(/ — .*$/, ""), f.type === "lines" ? `${v.split("\n").filter((x) => x.trim()).length} шт.` : v]);
  });
  return rows;
}

// Арт для карточек изделий в каталоге
function craftArt(key, sample) {
  if (key === "wishes") return `<div class="fan">${["Завтрак в постель", "Танец под нашу песню", "Вечер без телефонов"].map((t) =>
    `<div class="pc q wish"><b>♥</b><small>Я желаю</small><span>${esc(t)}</span></div>`).join("")}</div>`;
  if (key === "stickers") return `<div class="stk">${[0, 1, 2].map((i) => `<i style="${photoStyle(sample(i))}"></i>`).join("")}</div>`;
  if (key === "calendar") return `<div class="fan" style="aspect-ratio:210/297;width:42%"><div class="page cal"><i style="${photoStyle(sample(2))}"></i>
    <b class="m">Май</b><span class="grid">${Array.from({ length: 28 }, (_, i) => `<em class="${i % 7 > 4 ? "we" : ""}"></em>`).join("")}</span></div></div>`;
  if (key === "postcards") return `<div class="fan" style="aspect-ratio:100/140;width:40%">
    <div class="pc post back-side"><span></span><span></span><span></span></div>
    <div class="pc post"><i style="${photoStyle(sample(0))}"></i><em>С днём рождения!</em></div></div>`;
  if (key === "box") return `<div class="boxart"><div class="side"></div><div class="front"><i style="${photoStyle(sample(1))}"></i><em>Наша колода</em></div></div>`;
  if (key === "game") return `<div class="fan">${[["Дракон", "#D84B4B"], ["Зелье", "#3F9E5B"], ["Ловушка", "#8457C9"]].map(([t, col], i) =>
    `<div class="pc game" style="--gc:${col}"><b>${t}</b><i style="${photoStyle(sample(i))}"></i><span></span><span></span></div>`).join("")}</div>`;
  return "";
}


SCREENS.home = () => {
  const hour = new Date().getHours();
  const hello = hour < 5 ? "Доброй ночи" : hour < 12 ? "Доброе утро" : hour < 18 ? "Добрый день" : "Добрый вечер";
  const active = state.orders.find((o) => !["issued", "cancelled"].includes(o.status));
  const draftP = byId(state.draft?.pid);
  const svc = [
    { t: "Фото", s: "от 20 ₽", ic: "photo", go: "photo", p: byId("photo") },
    { t: "Документы", s: "от 8 ₽", ic: "doc", go: "doc" },
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
        <p>Фото, документы и колоды игральных карт.</p>
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
      <div class="row small"><div class="grow progress"><i style="width:${Math.round(state.draft.photos / (draftP.maxPhotos || draftP.cards) * 100)}%"></i></div>
        <span class="muted tabular">${state.draft.photos} из ${draftP.maxPhotos || draftP.cards} фото</span></div>
    </button>` : ""}
    ${active ? `<button class="card pressable" data-go="order" data-id="${active.id}" style="text-align:left">
      <div class="row">${orderThumb(active)}<div class="grow"><div class="eyebrow">Заказ №${active.id}</div>
        <div style="font-weight:650">${esc(active.title)}</div></div>${statusPill(active.status)}</div>
      ${activeTrack(active)}
      <div class="small muted">${esc(NEXT_STEP[active.status] || "")}</div>
    </button>` : ""}
    <div class="h-section"><h2>Популярное</h2><a href="#" data-act="tab" data-tab="catalog">Весь каталог</a></div>
    <div class="hscroll">${PRODUCTS.filter((p) => p.cat === "cards").map(productCard).join("")}</div>
    ${PRODUCTS.some((p) => p.cat === "gifts") ? `<div class="h-section"><h2>Подарки из фото</h2><a href="#" data-act="gifts-catalog">Все</a></div>
    <div class="hscroll">${PRODUCTS.filter((p) => p.cat === "gifts").map(productCard).join("")}</div>` : ""}
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
  const cats = [["all", "Все"], ["cards", "Карты"], ["gifts", "Подарки"], ["photo", "Фото"], ["doc", "Документы"]];
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
  const cta = isCards ? ["Собрать колоду", "start-deck"] : p.cat === "gifts" ? ["Создать", "start-craft"] : p.cat === "doc" ? ["Выбрать файл", "go-doc"] : ["Выбрать фото", "go-photo"];
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
    ${p.reqs ? `<div class="card"><div class="eyebrow">${p.cat === "doc" ? "Требования к файлу" : "Требования к фото"}</div><div class="list">${p.reqs.map((t) =>
      `<div class="list-item"><span style="color:var(--ok);--ic2:var(--ok)">${icon("check", "sm")}</span><span>${esc(t)}</span></div>`).join("")}</div></div>` : ""}
    <div class="card flat"><div class="row"><span class="tile-icon">${icon("clock")}</span><div class="grow"><div style="font-weight:600">${a.ok ? "Печатаем после заказа" : "Сейчас закончилась бумага — скоро пополним"}</div>
      <div class="small muted">Напишем в Telegram, когда заказ будет готов.</div></div></div></div>`,
    dock: dockBar(p.price ?? null, a.ok ? cta[0] : "Временно недоступно", cta[1], { sub: "Стоимость", disabled: !a.ok }),
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

// --- печать документа ---

SCREENS.doc = () => {
  const j = state.docJob;
  const q = quoteDoc(j);
  const body = j.checking
    ? `<div class="notice info">${icon("clock")}<div><b>Читаем файл…</b><span>Считаем страницы, чтобы показать цену.</span></div></div>`
    : j.pages
      ? `<div class="card"><div class="row"><span class="tile-icon">${icon("doc")}</span>
          <div class="grow"><div style="font-weight:650;overflow-wrap:anywhere">${esc(j.name)}</div>
            <div class="small muted">${j.pages} ${plural(j.pages, "страница", "страницы", "страниц")}</div></div>
          <label class="btn soft sm" style="position:relative;overflow:hidden">Заменить<input type="file" data-file="doc" accept="application/pdf,image/jpeg,image/png" style="position:absolute;inset:0;opacity:0"></label></div></div>`
      : `<label class="photo add" style="aspect-ratio:auto;padding:28px 12px;flex-direction:column;gap:8px;text-align:center">
          <input type="file" data-file="doc" accept="application/pdf,image/jpeg,image/png">${icon("upload", "lg")}
          <b>Выбрать файл</b><span class="small muted">PDF, JPG или PNG, до 20 МБ</span></label>`;
  return {
    html: `${topbar("Печать документа")}
    ${steps(["Файл", "Настройки", "Проверка", "Заказ"], j.pages ? 1 : 0)}
    ${body}
    ${j.error ? `<div class="notice warn">${icon("warn")}<div><b>Файл не подошёл</b><span>${esc(j.error)}</span></div></div>` : ""}
    <div class="field"><span class="lbl">Цвет</span>${seg("docJob.color", String(j.color), [
      { v: "true", t: "Цветная", s: rub(PRICES.doc.color) + " / стр." }, { v: "false", t: "Чёрно-белая", s: rub(PRICES.doc.bw) + " / стр." }])}</div>
    <div class="field"><div class="row" style="justify-content:space-between"><div><span class="lbl">Копии документа</span></div>
      <div class="stepper"><button data-act="step" data-model="docJob.copies" data-d="-1" aria-label="Меньше">${icon("minus")}</button><output class="tabular">${j.copies}</output>
      <button data-act="step" data-model="docJob.copies" data-d="1" aria-label="Больше">${icon("plus")}</button></div></div></div>`,
    dock: dockBar(q.total, "Проверить заказ", "review-doc", { disabled: !q.valid }),
  };
};

// --- S06: конструктор карт ---

SCREENS.deck = () => {
  const dk = state.deck;
  const p = byId(dk.pid);
  const layout = deckLayout(dk);
  const bad = dk.photos.filter(lowRes).length;
  const maxPhotos = p.maxPhotos || p.cards;
  const uno = isUno(p.id);
  const backs = backsFor(p.id);
  return {
    html: `${topbar(p.title, dk.saved ? "Черновик сохранён" : "")}
    ${steps(["Фото", "Макет", "Проверка", "Заказ"], dk.photos.length ? 1 : 0)}
    <div class="h-section"><h2>Фото <span class="muted tabular" style="font-weight:500">${dk.photos.length} из ${maxPhotos}</span></h2>
      ${dk.photos.length > 1 ? `<a href="#" data-act="shuffle">Перемешать</a>` : ""}</div>
    <div class="photos">${dk.photos.map((ph, i) => `<button class="photo ${state.swapFrom === i ? "sel" : ""}" style="${photoStyle(ph)}" data-act="swap" data-i="${i}" aria-label="Фото ${i + 1}">
        <span class="n">${i + 1}</span>${lowRes(ph) ? `<span class="bad">${icon("warn")}</span>` : ""}</button>`).join("")}
      ${dk.photos.length < maxPhotos ? `<label class="photo add" aria-label="Добавить фото"><input type="file" id="deck-files" accept="image/jpeg,image/png" multiple data-file="deck">${icon("upload", "lg")}</label>` : ""}</div>
    <div class="small muted">${state.swapFrom != null ? "Теперь нажмите на фото, с которым поменять местами." : `Нажмите на два фото, чтобы поменять их местами. ${uno ? "Фото ложатся на карты с цифрами по очереди." : "Фото ложатся на карты по очереди."}`}</div>
    ${bad ? `<div class="notice warn">${icon("warn")}<div><b>${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением</b><span>Отмечены значком. На карте 63×88 мм такое фото может выйти нерезким — на следующем шаге его можно улучшить нейросетью.</span></div></div>` : ""}
    ${(() => { const asp = uno ? .7 : dk.style === "full" ? 63 / 88 : dk.style === "vintage" ? .62 : 42 / 61;
      const cut = dk.photos.filter((ph) => faceCut(ph, asp)).length;
      return cut ? `<div class="notice info">${icon("info")}<div><b>На ${cut} ${plural(cut, "фото", "фото", "фото")} лица крупные</b><span>Тюша держит лица в центре кадра, но такие могут обрезаться по краям. Лучше снимки чуть издалека.</span></div></div>` : ""; })()}
    ${uno ? "" : `<div class="h-section"><h2>Оформление</h2></div>
    <div class="styles" role="radiogroup" aria-label="Оформление карт">${STYLES.map((st) => `<button class="style-opt ${st.key === dk.style ? "on" : ""}" role="radio"
      aria-checked="${st.key === dk.style}" data-act="set" data-model="deck.style" data-value="${st.key}">
      <span class="style-cards">${st.key === "vintage"
        ? playingCard({ rank: "К", suit: 3, vintage: true }) + playingCard({ rank: "7", suit: 1, ph: dk.photos[0], vintage: true })
        : st.key === "full"
        ? playingCard({ rank: "8", suit: 0, ph: dk.photos[0], full: true, ink: "black" }) + playingCard({ rank: "6", suit: 1, ph: dk.photos[1] || dk.photos[0], full: true, ink: "white", style: "background:#24262c" })
        : playingCard({ rank: "В", suit: 1, ph: dk.photos[0] }) + playingCard({ rank: "7", suit: 3, ph: dk.photos[1] || dk.photos[0] })}</span>
      <span class="t">${esc(st.title)}</span>
      <span class="s">${st.key === "vintage" ? "Как типографская колода: фигуры В, Д, К и фото в рамке" : st.key === "full" ? "Фото до краёв, маленький ч/б знак в углу" : "Фото в центре, ранг и масть в углах"}</span></button>`).join("")}</div>
    ${dk.style === "full" ? `<div class="small muted">Чёрные масти Тюша ставит на светлые фото, белые — на тёмные, чтобы знак всегда читался.</div>` : ""}
    ${dk.style === "vintage" ? `<div class="small muted">На вальтах, дамах и королях — классические фигуры, ваши фото — на остальных картах и джокерах.</div>` : ""}`}
    ${uno ? unoDesigner(dk) : ""}
    <div class="h-section"><h2>Рубашка <span class="muted" style="font-weight:500">· ${esc(backTitle(dk.back))}</span></h2></div>
    <div class="backs" role="radiogroup" aria-label="Рубашка карт">${backs.map((b) => `<button class="back-opt ${b.key === dk.back ? "on" : ""}" role="radio"
      aria-checked="${b.key === dk.back}" data-act="set" data-model="deck.back" data-value="${b.key}">${uno ? unoBack({ ...dk, back: b.key }) : cardBack(b.key)}<span>${esc(b.title)}</span></button>`).join("")}</div>
    ${uno ? unoBackEditor(dk) : ""}
    <div class="h-section"><h2>Макет · ${layout.length} ${plural(layout.length, "карта", "карты", "карт")}</h2></div>
    <div class="deck">${layout.map((c) =>
      `<div style="display:block;animation:deal .5s var(--spring) both;animation-delay:${Math.min(c.i * 12, 400)}ms">${c.uno ? unoCard({ ...c, style: "position:relative;aspect-ratio:63/88" }) : playingCard({ rank: c.rank, suit: c.suit, ph: c.ph, full: c.full, ink: c.ink, vintage: c.vintage, style: "position:relative;aspect-ratio:63/88" })}</div>`).join("")}</div>`,
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
    const maxPh = p.maxPhotos || p.cards;
    if (dk.photos.length < maxPh) warns.push(["info", `Фото: ${dk.photos.length} из ${maxPh}`, isUno(p.id) ? "Если фото меньше, чем карт с цифрами, они повторятся по кругу." : "Если фото меньше, чем карт, они повторятся по кругу."]);
    return { p, q, title: p.title, flow: ["Фото", "Макет", "Проверка", "Заказ"],
      rows: [["Набор", p.title], ["Карт", String(p.cards)], ["Фото", String(dk.photos.length)], ...(isUno(p.id) ? [["Цвета", dk.palette === "custom" ? "свои" : (UNO.palettes.find((x) => x.key === dk.palette) || {}).title || ""]] : [["Оформление", styleTitle(dk.style)]]),
        ["Рубашка", backTitle(dk.back)],
        ...(isUno(p.id) && (unoClean(dk.backText, UNO.text_max) || unoClean(dk.backCaption, UNO.caption_max))
          ? [["Надпись", [unoClean(dk.backText, UNO.text_max).toUpperCase(), unoClean(dk.backCaption, UNO.caption_max)].filter(Boolean).join(" · ")]] : []),
        ...(isUno(p.id) && dk.backPhoto ? [["Фото на рубашке", "своё"]] : [])],
      warns, agree: "Макет проверен. После оформления заказ уйдёт оператору.",
      paper: ["deck.paper", PAPER_CHOICES.cards, dk.paper, deckSheets(dk)], enhance: ["deck.enhance", dk.photos, dk.enhance],
      art: (() => {
        const lay = deckLayout(dk);
        const c = isUno(p.id) ? lay.find((x) => x.ph) || lay[1] : lay.find((x) => x.rank === "Д" || x.rank === "Т") || lay[0];
        const front = c.uno ? unoCard({ ...c, style: "position:absolute;inset:0" })
          : playingCard({ rank: c.rank, suit: c.suit, ph: c.ph, full: c.full, ink: c.ink, vintage: c.vintage, zoom: c.o.zoom || 1, x: c.o.x, y: c.o.y, style: "position:absolute;inset:0" });
        const back = isUno(p.id) ? unoBack(dk, "position:absolute;inset:0") : cardBack(dk.back, "position:absolute;inset:0");
        return flip3d(front, back);
      })() };
  }
  if (r.kind === "doc") {
    const d = state.docJob, p = byId("doc"), q = quoteDoc(d);
    return { p, q, title: "Документ", flow: ["Файл", "Настройки", "Проверка", "Заказ"], paper: ["docJob.paper", PAPER_CHOICES.doc, d.paper, d.pages * d.copies],
      rows: [["Файл", d.name], ["Страниц", String(d.pages)], ["Копии", String(d.copies)], ["Цвет", d.color ? "цветная" : "чёрно-белая"]],
      warns: [["info", "Листы A4", "Страницы вписываются в лист с небольшими полями; альбомные поворачиваем."]],
      agree: "Файл и параметры печати проверены." };
  }
  if (r.kind === "craft") {
    const c = state.craft, spec = craftSpec(c.key), p = byId(c.key), q = quoteCraft(c);
    const bad = c.photos.filter(lowRes).length;
    const warns = (c.pv?.warnings || []).map((w) => ["warn", "Обратите внимание", w]);
    if (bad) warns.push(["warn", `${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением`, "Может выйти нерезко — включите улучшение ниже или замените фото."]);
    return { p, q, title: spec.title, flow: ["Макет", "Проверка", "Заказ"], rows: craftRows(c, spec), warns,
      paper: ["craft.paper", spec.papers, c.paper, c.pv?.sheets || 1], enhance: ["craft.enhance", c.photos, c.enhance],
      agree: "Макет проверен. После оформления заказ уйдёт оператору.", art: craftPreviewArt(c, spec) };
  }
  const j = state.photoJob, p = byId("photo"), q = quotePhoto(j);
  const bad = j.photos.filter(lowRes).length;
  return { p, q, title: `Фото ${FORMAT_NAMES[j.format]}`, flow: ["Фото", "Настройки", "Проверка", "Заказ"],
    paper: ["photoJob.paper", PAPER_CHOICES.photo, j.paper, photoSheets(j)], enhance: ["photoJob.enhance", j.photos, j.enhance],
    rows: [["Фото", String(j.photos.length)], ["Размер", FORMAT_NAMES[j.format]], ["Копии", String(j.copies)], ["Цвет", j.color ? "цветная" : "чёрно-белая"], ["Качество", QUALITY_NAMES[j.quality]]],
    warns: bad ? [["warn", `${bad} ${plural(bad, "фото", "фото", "фото")} с низким разрешением`, "Может выйти нерезко."]] : [],
    agree: "Фото и параметры печати проверены." };
}

SCREENS.review = () => {
  const r = reviewData();
  return {
    html: `${topbar("Проверка заказа")}
    ${steps(r.flow, 2)}
    ${r.art ? `<div class="card review-art" style="background:${artBg[r.p.art] || "#EEF1F7"};box-shadow:none;padding:22px 20px">${r.art}</div>` : ""}
    ${r.warns.map(([tone, t, s]) => `<div class="notice ${tone}">${icon(tone === "warn" ? "warn" : "info")}<div><b>${esc(t)}</b><span>${esc(s)}</span></div></div>`).join("")}
    <div class="notice info">${icon("info")}<div><b>Оплаты в приложении пока нет</b><span>Заказ уйдёт оператору, о стоимости и получении он напишет в Telegram.</span></div></div>
    ${r.paper ? paperPicker(...r.paper) : ""}
    ${r.enhance ? enhanceBlock(...r.enhance) : ""}
    <div class="card"><div class="eyebrow">Заказ</div><dl class="kv">${r.rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>
    <div class="card"><div class="eyebrow">Стоимость</div><dl class="kv">${r.q.lines.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${rub(v)}</dd>`).join("")}
      <span class="sep"></span><dt class="total">Итого</dt><dd class="total">${rub(r.q.total)}</dd></dl></div>
    <button class="check" role="checkbox" aria-checked="${state.agreed}" data-act="agree"><span class="box">${icon("check")}</span><span>${esc(r.agree)}</span></button>`,
    dock: dockBar(r.q.total, state.agreed ? "Оформить заказ" : "Отметьте проверку", "place-order", { disabled: !state.agreed || r.q.valid === false }),
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
  "uno-palette": (el) => {
    state.deck.palette = el.dataset.value;
    state.deck.colors = unoPaletteColors(el.dataset.value);
    haptic("select");
    render();
  },
  "uno-back-photo-off": () => { state.deck.backPhoto = null; haptic("select"); render(); },
  "gifts-catalog": () => { state.tab = "catalog"; state.catCat = "gifts"; state.stack = []; render("tab"); window.scrollTo(0, 0); },
  "start-craft": () => { const id = current().params.id; if (startCraft(id)) push("craft"); },
  "review-craft": () => { state.review = { kind: "craft" }; state.agreed = false; push("review"); },
  "craft-set": (el) => { state.craft.values[el.dataset.k] = el.dataset.v; haptic("select"); queuePreview(120); render(); },
  "craft-toggle": (el) => {
    const arr = state.craft.values[el.dataset.k], v = el.dataset.v;
    state.craft.values[el.dataset.k] = arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
    haptic("select"); queuePreview(250); render();
  },
  "craft-step": (el) => {
    const f = craftSpec(state.craft.key).fields.find((x) => x.key === el.dataset.k);
    const v = Math.min(f.max, Math.max(f.min, (+state.craft.values[f.key] || 0) + +el.dataset.d));
    state.craft.values[f.key] = v; haptic("select"); queuePreview(300); render();
  },
  "craft-remove": (el) => { state.craft.photos.splice(+el.dataset.i, 1); haptic("medium"); queuePreview(150); render(); },
  toggle: (el) => {
    const keys = el.dataset.model.split(".");
    let obj = state;
    keys.slice(0, -1).forEach((k) => { obj = obj[k]; });
    obj[keys.at(-1)] = !obj[keys.at(-1)];
    haptic("select");
    render();
  },
  set: (el) => {
    setPath(el.dataset.model, el.dataset.value);
    if (el.dataset.model.startsWith("craft.")) queuePreview(150);
    if (el.dataset.model === "theme") { store("theme", state.theme); applyTheme(); }
    if (/^(photoJob|docJob)\./.test(el.dataset.model)) state.agreed = false;
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
  "go-photo": () => { state.photoJob = state.photoJob || { photos: [], format: "10x15", copies: 1, color: true, quality: "high", paper: pickPaper(PAPER_CHOICES.photo), enhance: false }; push("photo"); },
  "go-doc": () => { state.docJob = state.docJob || { file: null, name: "", pages: 0, copies: 1, color: false, checking: false, error: "", paper: pickPaper(PAPER_CHOICES.doc) }; push("doc"); },
  "review-doc": () => { state.review = { kind: "doc" }; state.agreed = false; push("review"); },
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
    if (o.kind === "craft") { if (startCraft(o.product)) push("craft"); }
    else if (o.kind === "cards") { startDeck(o.title.includes("UNO") ? "uno" : o.title.includes("36") || o.sub.startsWith("36") ? "deck36" : "deck54"); push("deck"); }
    else if (o.kind === "doc") ACT["go-doc"]();
    else ACT["go-photo"]();
    toast(o.kind === "doc" ? "Выберите файл — это будет новый заказ" : "Добавьте фото — это будет новый заказ");
  },
  copy: async (el) => {
    try { await navigator.clipboard.writeText(el.dataset.text); toast("Адрес скопирован"); }
    catch (e) { toast("Не удалось скопировать: выделите адрес вручную", "no"); }
  },
};

function startDeck(pid, photosCount) {
  if (!state.deck || state.deck.pid !== pid) {
    state.deck = { pid, photos: [], edits: {}, saved: false, back: defaultBackFor(pid), style: DEFAULT_STYLE,
      palette: UNO.default_palette, colors: unoPaletteColors(UNO.default_palette), backText: "", backCaption: "", backPhoto: null,
      paper: pickPaper(PAPER_CHOICES.cards), enhance: false };
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
    if (c.uno && Array.isArray(c.uno.palettes)) UNO = { ...UNO, ...c.uno, inks: { ...UNO.inks, ...Object.fromEntries(Object.entries(c.uno.inks || {}).map(([k, v]) => [k, { ...UNO.inks[k], ...v }])) } };
    if (Array.isArray(c.uno_backs) && c.uno_backs.length) { UNO_BACKS = c.uno_backs; UNO_DEFAULT_BACK = c.uno_default_back || UNO_BACKS[0].key; }
    if (c.papers) PAPERS = c.papers;
    if (c.paper_choices) PAPER_CHOICES = c.paper_choices;
    if (c.enhance) ENH = c.enhance;
    if (Array.isArray(c.crafts)) registerCrafts(c.crafts);
    if (Array.isArray(c.styles) && c.styles.length) { STYLES = c.styles; DEFAULT_STYLE = c.default_style || STYLES[0].key; }
    PRODUCTS.forEach((p) => { if (PRICES.cards[p.id]) p.price = PRICES.cards[p.id]; });
    const min = Math.min(...Object.values(PRICES.photo).flatMap((f) => Object.values(f)));
    byId("photo").priceFrom = `от ${min} ₽ за фото`;
    byId("doc").priceFrom = `от ${Math.min(PRICES.doc.color, PRICES.doc.bw)} ₽ за страницу`;
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
  const isDeck = r.kind === "deck", isDoc = r.kind === "doc", isCraft = r.kind === "craft";
  const list = isDoc ? [] : isDeck ? state.deck.photos : isCraft ? state.craft.photos : state.photoJob.photos;
  const meta = isDoc ? { kind: "doc", copies: state.docJob.copies, color: state.docJob.color, paper: state.docJob.paper }
    : isDeck ? { kind: "cards", deck: state.deck.pid, back: state.deck.back || DEFAULT_BACK, style: state.deck.style || DEFAULT_STYLE,
      paper: state.deck.paper, enhance: state.deck.enhance,
      ...(isUno(state.deck.pid) ? { colors: state.deck.colors, back_text: state.deck.backText, back_caption: state.deck.backCaption } : {}) }
    : isCraft ? { kind: "craft", product: state.craft.key, ...state.craft.values, paper: state.craft.paper, enhance: state.craft.enhance }
    : { kind: "photo", format: state.photoJob.format, copies: state.photoJob.copies, color: state.photoJob.color, quality: state.photoJob.quality,
      paper: state.photoJob.paper, enhance: state.photoJob.enhance };
  state.placing = true;
  state.uploadPct = 5;
  state.stack.push({ name: "placing", params: {} });
  render("push");
  try {
    const form = new FormData();
    form.append("meta", JSON.stringify(meta));
    if (isDoc) form.append("document", state.docJob.file, state.docJob.name);
    if (isDeck && isUno(state.deck.pid) && state.deck.backPhoto) form.append("back_photo", await prepareUpload(state.deck.backPhoto, 2200), "back.jpg");
    if (isCraft && state.craft.csv) form.append("csv", new Blob([state.craft.csv.text], { type: "text/csv" }), state.craft.csv.name);
    const maxSide = isDeck ? 2200 : isCraft ? 2600 : 3600;
    for (let i = 0; i < list.length; i++) {
      // у изделий имя файла важно: в таблице карт для игры картинки ищутся по имени
      form.append("photo", await prepareUpload(list[i], maxSide), isCraft ? list[i].name : `photo_${i + 1}.jpg`);
      state.uploadPct = 5 + Math.round((i + 1) / list.length * 60);
      if (current().name === "placing") render();
    }
    state.uploadPct = 70;
    render();
    const { order } = await api("/mapi/orders", { method: "POST", body: form });
    const o = mapOrder(order);
    state.orders.unshift(o);
    loadThumb(o).then(() => render());
    if (isDoc) state.docJob = null; else if (isDeck) { state.draft = null; state.deck = null; } else if (isCraft) state.craft = null; else state.photoJob = null;
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
async function onDocFile(file) {
  const j = state.docJob;
  if (!/^(application\/pdf|image\/(jpeg|png))$/.test(file.type) && !/\.(pdf|jpe?g|png)$/i.test(file.name)) {
    j.error = "Принимаем PDF, JPG и PNG. Word и Excel сохраните как PDF."; render(); return;
  }
  if (file.size > 20 * 1048576) { j.error = "Файл больше 20 МБ."; render(); return; }
  Object.assign(j, { checking: true, error: "" });
  render();
  try {
    const form = new FormData();
    form.append("document", file, file.name);
    const { pages } = await api("/mapi/doc/inspect", { method: "POST", body: form });
    Object.assign(j, { file, name: file.name, pages });
    haptic("success");
  } catch (e) { Object.assign(j, { file: null, name: "", pages: 0, error: e.message }); haptic("error"); }
  j.checking = false;
  state.agreed = false;
  render();
}
async function onPhotoFiles(files, target) {
  if (target === "doc") return onDocFile(files[0]);
  if (target === "unoback") {
    const f = files[0];
    if (!/image\/(jpeg|png)/.test(f.type)) return toast("Для рубашки подойдёт JPG или PNG", "no");
    if (f.size > 20 * 1048576) return toast(`${f.name}: больше 20 МБ`, "no");
    const url = URL.createObjectURL(f);
    const [w, h] = await imageSize(url);
    state.deck.backPhoto = { url, w, h, name: f.name, file: f };
    detectFace(state.deck.backPhoto);
    haptic("success");
    return render();
  }
  if (target === "csv") {
    const f = files[0];
    if (f.size > 512 * 1024) return toast("Таблица больше 512 КБ", "no");
    const buf = await f.arrayBuffer();
    let text = new TextDecoder("utf-8").decode(buf);
    if (text.includes("\uFFFD")) text = new TextDecoder("windows-1251").decode(buf);  // таблица из Excel
    state.craft.csv = { name: f.name, text };
    haptic("success");
    queuePreview(50);
    return render();
  }
  if (target === "craft") {
    const spec = craftSpec(state.craft.key), max = spec.fields.find((x) => x.type === "photos")?.max || 1;
    for (const f of [...files].filter((x) => /image\/(jpeg|png)/.test(x.type))) {
      if (state.craft.photos.length >= max) { toast(`Не больше ${max} фото`, "no"); break; }
      if (f.size > 20 * 1048576) { toast(`${f.name}: больше 20 МБ`, "no"); continue; }
      const url = URL.createObjectURL(f);
      const [w, h] = await imageSize(url);
      const ph = { url, w, h, name: f.name, file: f };
      state.craft.photos.push(ph);
      detectFace(ph);
      render();
    }
    haptic("success");
    queuePreview(200);
    return;
  }
  const list = [...files].filter((f) => /image\/(jpeg|png)/.test(f.type));
  if (list.length < files.length) toast("Часть файлов пропущена: принимаем JPG и PNG", "no");
  for (const f of list) {
    if (f.size > 20 * 1048576) { toast(`${f.name}: больше 20 МБ`, "no"); continue; }
    const url = URL.createObjectURL(f);
    const [w, h] = await imageSize(url);
    const ph = { url, w, h, name: f.name, file: f, lum: target === "deck" ? await cornerLuminance(url) : undefined };
    detectFace(ph);
    if (target === "deck") {
      const max = byId(state.deck.pid).maxPhotos || byId(state.deck.pid).cards;
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
    if (go === "doc") return ACT["go-doc"]();
    return push(go, params);
  }
  ACT[el.dataset.act]?.(el, e);
});

document.addEventListener("input", (e) => {
  const el = e.target;
  if (el.dataset.model) {
    setPath(el.dataset.model, el.value);
    if (el.dataset.model.startsWith("deck.colors.")) state.deck.palette = "custom";
    if (el.dataset.model.startsWith("craft.")) queuePreview(600);
    render();
    return;
  }
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
