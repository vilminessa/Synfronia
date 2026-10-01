// Headless-проверка интерфейса Synfronia: карточка настроек (оверлей) и
// главное окно. Окно у приложения одно, поэтому страница одна: карточку
// открывает сценарий, а не второй экземпляр.
//
// Карточка: лежит по центру, разделы переключаются кликом, поля не вылезают
// по ширине, кнопки с иконками без подписи (смысл в подсказке), подсказки
// появляются с задержкой, тянутся за курсором с инерцией, «нить»-SVG с
// наконечником соединяет их с краем элемента и подсказка не накрывает его,
// после перерисовки карточки висящих подсказок не бывает, флажок FTP открывает
// блок полей и убирает его обратно, режим выгрузки - переключатель, значения
// сохраняются по change, папка уходит в Python через set_dest, элементы не
// сливаются с фоном (контраст), карточка переживает минимальный размер окна.
// Главное окно: кнопка «Скачать» во всех состояниях, один журнал.
//
//   python tools\ui_probe_page.py
//   node tools\ui_fonts_probe.js
//
// Код возврата: 0 - всё влезает и ведёт себя как ожидается, 1 - есть проблемы.

const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

// Кандидаты: путь к Edge зависит от разрядности Windows и версии - на CI
// и чужих машинах может быть другим.
const EDGE_CANDIDATES = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge Dev\\Application\\msedge.exe",
];
const EDGE = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
if (!EDGE) {
  console.error("msedge.exe не найден, пробовали:\n  " + EDGE_CANDIDATES.join("\n  "));
  process.exit(1);
}
// Всё служебное пробника - в %LOCALAPPDATA%\Synfronia\probe, в %TEMP% ничего
// не пишем (страница и профили headless Edge).
const PROBE_DIR = path.join(process.env.LOCALAPPDATA, "Synfronia", "probe");
const PAGE = process.argv[2] || path.join(PROBE_DIR, "page.html");
const PORT = 9337;
const LANGS = ["ru", "en", "ja", "zh-CN", "es", "de"];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Общие для карточки замеры: разделы переключаются по очереди, в каждом
// проверяем, что содержимое не вылезает по ширине и ни один control не обрезает
// текст. Поля рисуются из схемы (__SETTINGS_SCHEMA__), поэтому список разделов
// берём из неё, а не из разметки.
const WIN_MEASURE = `(function () {
  var host = document.getElementById("settings-sections");
  var nav = document.getElementById("settings-nav");
  var out = {sections: [], buttons: 0, controls: 0, labels: [], icons: [], navLabels: [],
             cards: 0, titled: [],
             overflowX: host.scrollWidth - host.clientWidth,
             navOverflowX: nav.scrollWidth - nav.clientWidth, clipped: [], titles: []};
  var names = SETTINGS_SCHEMA.groups.map(function (g) { return g.id; });
  out.navLabels = [].slice.call(nav.querySelectorAll(".nav-item")).map(function (b) {
    return {id: b.id, text: b.textContent.trim(),
            w: Math.round(b.getBoundingClientRect().width),
            h: Math.round(b.getBoundingClientRect().height),
            clipped: b.scrollWidth > b.clientWidth + 1};
  });
  names.forEach(function (name) {
    switchSection(name);
    var sec = document.getElementById("section-" + name);
    var rec = {id: name, controls: 0, overflowX: sec.scrollWidth - sec.clientWidth, clipped: []};
    [].slice.call(sec.querySelectorAll("select, button, input")).forEach(function (el) {
      if (el.offsetParent === null) return;   // скрытое поле не мешает
      rec.controls++;
      if (el.scrollWidth > el.clientWidth + 1) rec.clipped.push(el.id || el.tagName);
    });
    out.controls += rec.controls;
    out.clipped = out.clipped.concat(rec.clipped);
    out.sections.push(rec);
  });
  // кнопки тем и шрифтов - предмет старой проверки (нужен раздел «Интерфейс»)
  switchSection("ui");
  [].slice.call(document.querySelectorAll("#section-ui .theme-actions")).forEach(function (row) {
    [].slice.call(row.querySelectorAll("button")).forEach(function (b) {
      out.buttons++;
      var svg = b.querySelectorAll(".ico svg").length;
      out.labels.push({id: b.id, text: b.textContent.trim(), svg: svg,
                       tip: b.getAttribute("data-tip") || "",
                       aria: b.getAttribute("aria-label") || "",
                       title: b.getAttribute("title") || "",
                       clipped: b.scrollWidth > b.clientWidth + 1,
                       h: Math.round(b.getBoundingClientRect().height)});
      if (svg) {
        out.icons.push({id: b.id, tip: b.getAttribute("data-tip") || "",
                        aria: b.getAttribute("aria-label") || "",
                        cls: b.className, w: Math.round(b.getBoundingClientRect().width)});
      }
    });
  });
  out.cards = document.querySelectorAll("#settings-sections .field-card").length;
  out.titled = [].slice.call(document.querySelectorAll("#settings-sections .field-card-title"))
    .map(function (t) { return t.textContent.trim(); });
  // нативных подсказок в карточке быть не должно - рисует браузер, не мы
  out.titles = [].slice.call(document.querySelectorAll("#settings-overlay [title]"))
    .map(function (el) { return el.id || el.tagName; });
  switchSection(names[0]);
  return out;
})()`;

// Открытие/закрытие карточки: фокус уходит внутрь, остальная страница
// становится inert, клик по фону и Escape закрывают, клик по карточке - нет.
const OVERLAY_READ = `(function () {
  var ov = document.getElementById("settings-overlay");
  var card = document.querySelector(".settings-card");
  var kids = [].slice.call(document.body.children).filter(function (n) { return n !== ov; });
  var r = card.getBoundingClientRect();
  return {hidden: ov.hidden,
          covers: Math.round(r.width) < window.innerWidth && Math.round(r.height) < window.innerHeight,
          centered: Math.abs((r.left + r.right) / 2 - window.innerWidth / 2) < 2 &&
                    Math.abs((r.top + r.bottom) / 2 - window.innerHeight / 2) < 2,
          blur: getComputedStyle(ov).backdropFilter || getComputedStyle(ov).webkitBackdropFilter,
          inert: kids.every(function (n) { return !!n.inert; }),
          disabled: ["tab-video", "url-video", "download", "settings-btn"]
            .filter(function (id) { return document.getElementById(id).disabled; }),
          focusInCard: card.contains(document.activeElement),
          logInCard: document.querySelectorAll("#settings-overlay #log").length,
          logs: document.querySelectorAll("#log").length,
          reported: window.__probe.settingsOpen};
})()`;
const OVERLAY_OPEN = `document.getElementById("settings-btn").click(); true`;

// Автосохранение: правка поля уходит в save_setting, папка - в set_dest
// (она не настройка и в settings.json не пишется).
const AUTOSAVE = `(function () {
  window.__probe.saved = []; window.__probe.dest = "";
  var retries = document.getElementById("retries");
  retries.value = "77";
  retries.dispatchEvent(new Event("change"));
  var dest = document.getElementById("dest");
  dest.value = "D:\\\\Videos";
  dest.dispatchEvent(new Event("change"));
  return {saved: window.__probe.saved.slice(), dest: window.__probe.dest};
})()`;

// Тема: css-only тема применяется на лету, палитра карточки едет вместе с ней.
const THEME_SWITCH = `(function () {
  var sel = document.getElementById("theme");
  var pick = Object.keys(THEMES).filter(function (k) {
    return THEMES[k] && !THEMES[k].entry && !THEMES[k].hidden;
  });
  var before = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
  var key = pick[0] || sel.value;
  sel.value = key;
  sel.dispatchEvent(new Event("change"));
  return {key: key, before: before,
          after: getComputedStyle(document.documentElement).getPropertyValue("--bg").trim(),
          want: THEMES[key] ? THEMES[key].bg : null,
          saved: window.__probe.saved.slice(-1)[0] || null};
})()`;

// Видимость по схеме: флажок «Выгружать на FTP» открывает блок полей, а сама
// карточка «Подключение» вместе с ним убирается. Режим выгрузки -
// переключатель из двух коротких слов, а не выпадающий список.
const FTP_VIS = `(function () {
  switchSection("ftp");
  var flag = document.getElementById("ftp-active");
  function tip(el) { return el ? (el.getAttribute("data-tip") || "") : ""; }
  function captionOf(id) {
    var el = document.getElementById(id);
    return el ? el.parentElement.querySelector("span[data-i18n]") : null;
  }
  function connCard() {
    var cards = [].slice.call(document.querySelectorAll("#section-ftp .field-card"));
    for (var i = 0; i < cards.length; i++) {
      var title = cards[i].querySelector(".field-card-title");
      if (title && /\\u041f\\u043e\\u0434\\u043a\\u043b\\u044e\\u0447|onnection/i.test(title.textContent)) return cards[i];
    }
    return null;
  }
  function count() {
    var sec = document.getElementById("section-ftp");
    // .field-card намеренно: пустая рамка «Подключение» с заголовком тоже
    // видна пользователю и тоже считается мусором
    return {visible: [].slice.call(sec.querySelectorAll(
              "input, select, button, label, .note, .field-card, .field-card-title"))
        .filter(function (el) { return el.offsetParent !== null; }).length,
        boxes: [].slice.call(sec.querySelectorAll(".field-card"))
          .filter(function (el) { return el.offsetParent !== null; }).length,
        conn: connCard() ? connCard().offsetParent !== null : null,
        connRows: connCard() ? connCard().querySelectorAll(".row, .range-row").length : 0,
        overflowX: sec.scrollWidth - sec.clientWidth};
  }
  function mode() {
    var wrap = document.getElementById("ftp-mode");
    var btns = [].slice.call(wrap.querySelectorAll("button"));
    var on = wrap.querySelector(".on");
    return {n: btns.length, texts: btns.map(function (b) { return b.textContent.trim(); }),
            values: btns.map(function (b) { return b.getAttribute("data-value"); }),
            value: on ? on.getAttribute("data-value") : "",
            tips: btns.map(function (b) { return b.getAttribute("data-tip") || ""; }),
            titles: btns.map(function (b) { return b.getAttribute("title") || ""; }),
            wide: wrap.scrollWidth - wrap.clientWidth};
  }
  var out = {off: count()};
  flag.checked = true;
  flag.dispatchEvent(new Event("change"));
  out.on = count();
  out.modeRu = mode();
  // переключение режима сохраняет значение и двигает подсветку
  var per = [].slice.call(document.getElementById("ftp-mode").querySelectorAll("button"))
    .filter(function (b) { return b.getAttribute("data-value") === "per_file"; })[0];
  per.click();
  out.clicked = mode();
  out.saved = window.__probe.saved.slice(-1)[0] || null;
  [].slice.call(document.getElementById("ftp-mode").querySelectorAll("button"))
    .filter(function (b) { return b.getAttribute("data-value") === "batch"; })[0].click();
  // смена языка: подписи переключателя должны переехать вместе с интерфейсом
  var was = curLang;
  curLang = "en"; applyI18n();
  out.modeEn = mode();
  curLang = was; applyI18n();
  out.clipped = [].slice.call(document.querySelectorAll("#section-ftp select, #section-ftp button"))
    .filter(function (el) { return el.offsetParent !== null && el.scrollWidth > el.clientWidth + 1; })
    .map(function (el) { return el.id; });
  flag.checked = false;
  flag.dispatchEvent(new Event("change"));
  out.back = count();
  // подсказки полей и доступность пиксельного переключателя выгрузки. Цвета
  // тумблера обязаны браться из темы: если переменной нет, fill падает в
  // чёрный (rgb(0,0,0)) и на тёмной карточке тумблер просто не виден.
  var active = flag.parentElement;
  var pxNode = active ? active.querySelector(".px") : null;
  function pxView(sel, prop) {
    var n = pxNode ? pxNode.querySelector(sel) : null;
    return n ? (getComputedStyle(n).getPropertyValue(prop) || "").trim() : "";
  }
  function pxRect(sel) {
    var n = pxNode ? pxNode.querySelector(sel) : null;
    if (!n) return [0, 0];
    var r = n.getBoundingClientRect();
    return [Math.round(r.width), Math.round(r.height)];
  }
  // Невидимый тумблер ловился только на пикселях: если svg создан через
  // createElement (HTML-namespace), его innerHTML парсится как HTML, фигуры
  // получают box 0x0 и ничего не рисуют, а computed-стили остаются «верными».
  // Поэтому меряем namespace и геометрию самих фигур.
  var SVG_NS = "http://www.w3.org/2000/svg";
  var pxNs = pxNode ? pxNode.namespaceURI : "";
  var pxKidsNs = pxNode ? [].slice.call(pxNode.querySelectorAll("*"))
    .map(function(n) { return n.namespaceURI; }) : [];
  var trackFill = pxView(".px-track", "fill"), trackStroke = pxView(".px-track", "stroke"),
      knobOff = pxView(".px-knob-fill", "fill"), checkStroke = pxView(".px-check", "stroke");
  flag.checked = true;
  flag.dispatchEvent(new Event("change"));
  var knobOn = pxView(".px-knob-fill", "fill"), checkOpacity = pxView(".px-check", "opacity");
  flag.checked = false;
  flag.dispatchEvent(new Event("change"));
  out.hints = {
    tls: tip(captionOf("ftp-tls")),
    tlsVerify: tip(captionOf("ftp-tls-verify")),
    pasv: tip(captionOf("ftp-pasv")),
    activeAria: active ? active.getAttribute("aria-label") || "" : "",
    activeTip: active ? active.getAttribute("data-tip") || "" : "",
    activePixel: active ? active.classList.contains("pixel-toggle") : false,
    // rect носителя data-tip = куда целится нить подсказки: бокс обязан
    // обнимать тумблер (40x20), а не тянуться на всю строку карточки
    activeBox: active ? [Math.round(active.getBoundingClientRect().width),
                         Math.round(active.getBoundingClientRect().height)] : [0, 0],
    activeText: active ? active.textContent.trim() : "",
    pxNs: pxNs, pxKidsNs: pxKidsNs, trackRect: pxRect(".px-track"),
    knobRect: pxRect(".px-knob-fill"),
    trackFill: trackFill, trackStroke: trackStroke, knobOff: knobOff,
    knobOn: knobOn, checkStroke: checkStroke, checkOpacity: checkOpacity
  };
  return out;
})()`;

// Контраст: элементы не должны сливаться с фоном. Считаем относительную
// яркость фона карточки, блока и поля - если разница меньше порога, глаз не
// различает границу.
const CONTRAST = `(function () {
  function lum(color) {
    var m = /rgba?\\(([^)]+)\\)/.exec(color || "");
    if (!m) return null;
    var p = m[1].split(",").map(function (x) { return parseFloat(x); });
    if (p.length > 3 && p[3] < 0.05) return null;   // прозрачный - ищем выше
    var f = p.slice(0, 3).map(function (v) {
      v = v / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
  }
  function bgOf(el) {
    for (var n = el; n; n = n.parentElement) {
      var l = lum(getComputedStyle(n).backgroundColor);
      if (l !== null) return l;
    }
    return null;
  }
  switchSection("dl");
  var card = document.querySelector("#settings-overlay .settings-card");
  var block = document.querySelector("#section-dl .field-card");
  var input = document.getElementById("quality");
  // карточка поднята над окном: её фон обязан отличаться от фона окна, иначе
  // оверлей не читается как отдельный слой
  var d1 = Math.abs(bgOf(card) - bgOf(block));
  var d2 = Math.abs(bgOf(block) - bgOf(input));
  var d3 = Math.abs(bgOf(document.body) - bgOf(card));
  switchSection("ui");
  return {cardBlock: Math.round(d1 * 1000) / 1000, blockInput: Math.round(d2 * 1000) / 1000,
          bodyCard: Math.round(d3 * 1000) / 1000,
          cardL: Math.round(bgOf(card) * 1000), blockL: Math.round(bgOf(block) * 1000),
          inputL: Math.round(bgOf(input) * 1000), bodyL: Math.round(bgOf(document.body) * 1000)};
})()`;

// Кнопка «Скачать»: сценарий poll() гоняем через window.__probe.dlState,
// tick() сам подхватит состояние за ~200 мс. Проверяем заливку, проценты,
// SVG-иконки итога, возврат в idle через 2 с и блокировку «Отмены». Своей
// подсказки у кнопки нет: состояние объясняет доступное имя (aria-label).
const DL_SET = (st) => `(function () { window.__probe.dlState = ${JSON.stringify(st)}; return true; })()`;
const DL_READ = `(function () {
  var b = document.getElementById("download");
  var fill = b.querySelector(".dl-fill"), lbl = b.querySelector(".dl-label"),
      pct = b.querySelector(".dl-pct"), ico = b.querySelector(".dl-icon");
  var r = b.getBoundingClientRect();
  return {
    cls: b.className, w: Math.round(r.width), h: Math.round(r.height),
    pct: pct.textContent, label: lbl.textContent,
    // подпись в потоке задаёт кнопке высоту: если её оторвать в absolute,
    // в потоке не останется ничего и высота схлопнется до отступов
    labelInFlow: getComputedStyle(lbl).position === "relative" &&
      lbl.getBoundingClientRect().height > 8,
    svg: ico.querySelectorAll("svg").length,
    shapes: ico.querySelectorAll("svg path, svg circle").length,
    iconOpacity: +parseFloat(getComputedStyle(ico).opacity),
    labelOpacity: +parseFloat(getComputedStyle(lbl).opacity),
    fillW: Math.round(fill.getBoundingClientRect().width),
    fillPct: b.style.getPropertyValue("--dl-pct"),
    fillAnim: getComputedStyle(fill).animationName,
    sheenAnim: getComputedStyle(b, "::after").animationName,
    iconAnim: getComputedStyle(ico).animationName,
    color: getComputedStyle(b).color,
    fillBg: getComputedStyle(fill).backgroundColor,
    iconIn: (function () { var i = ico.getBoundingClientRect();
      return {ok: i.width > 8 && i.height > 8 && i.top >= r.top - 2 && i.bottom <= r.bottom + 2 &&
             i.left >= r.left - 2 && i.right <= r.right + 2,
              i: [Math.round(i.left), Math.round(i.top), Math.round(i.width), Math.round(i.height)],
              b: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]}; })(),
    // состояние кнопки объясняет доступное имя, а не нативная всплывашка
    tip: b.getAttribute("data-tip"), title: b.getAttribute("title") || "",
    aria: b.getAttribute("aria-label"),
    dlDisabled: b.disabled, stopDisabled: document.getElementById("stop").disabled,
    key: DL_TITLE
  };
})()`;

async function waitForPage() {
  for (let i = 0; i < 80; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch (e) { /* ждём */ }
    await sleep(250);
  }
  throw new Error("Edge CDP не поднялся");
}

(async () => {
  if (!fs.existsSync(PAGE)) throw new Error(`нет страницы: ${PAGE} (сначала tools/ui_probe_page.py)`);
  const profile = path.join(PROBE_DIR, "profiles", "probe-" + Date.now());
  fs.mkdirSync(profile, { recursive: true });
  const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run",
    "--no-default-browser-check", "--hide-scrollbars", `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
  let code = 1;
  try {
    const wsUrl = await waitForPage();
    const ws = new WebSocket(wsUrl);
    let id = 0;
    const pending = new Map();
    const errors = [];
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.method === "Runtime.exceptionThrown") {
        var det = msg.params.exceptionDetails || {};
        errors.push((det.exception && det.exception.description) || det.text || "exception");
      }
      if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
    });
    await new Promise((r) => ws.addEventListener("open", r));
    const send = (method, params = {}) => new Promise((res) => {
      const n = ++id;
      pending.set(n, res);
      ws.send(JSON.stringify({ id: n, method, params }));
    });
    const evaluate = async (expr) => {
      const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
      if (r.result && r.result.exceptionDetails) {
        const d = r.result.exceptionDetails;
        throw new Error((d.exception && d.exception.description) || d.text || "exception");
      }
      return r.result.result.value;
    };

    await send("Page.enable");
    await send("Runtime.enable");
    await send("Page.navigate", { url: "file:///" + path.resolve(PAGE).replace(/\\/g, "/") });
    // CI-раннеры отдают prefers-reduced-motion: reduce - все CSS-анимации
    // погашены, и проверки «анимация играют» ложно падают. Зонд принудительно
    // нормализует среду до состояния обычного десктопа.
    await send("Emulation.setEmulatedMedia", {
      features: [{ name: "prefers-reduced-motion", value: "no-preference" }],
    });
    // init() асинхронный, а поля рисует скрипт. Ждём и главное окно, и поля
    // карточки (ручки шрифтов наполняются позициями из get_initial).
    const READY = '(function () { return !!(window.__initDone && document.getElementById("download")' +
      ' && document.getElementById("font-sans")' +
      ' && document.getElementById("font-sans").querySelectorAll(".knob-tick").length > 1); })()';
    for (let i = 0; i < 40; i++) {
      if (await evaluate(READY)) break;
      await sleep(100);
    }
    if (errors.length) console.error("ошибки при инициализации:", errors);
    if (!(await evaluate(READY))) throw new Error("страница не инициализировалась");

    let bad = 0;
    const fail = (msg) => { console.log(`        FAIL: ${msg}`); bad++; };

    // ================= карточка настроек =================
    console.log("--- открытие и закрытие карточки ---");
    const ovBefore = await evaluate(OVERLAY_READ);
    await evaluate(OVERLAY_OPEN);
    await sleep(500);
    const ovDuring = await evaluate(OVERLAY_READ);
    const clickCard = await evaluate(
      '(function () { document.querySelector(".settings-card").click(); return true; })()');
    await sleep(200);
    const afterCardClick = await evaluate(OVERLAY_READ);
    await evaluate('document.getElementById("settings-overlay").click(); true');
    await sleep(200);
    const afterBackdrop = await evaluate(OVERLAY_READ);
    await evaluate(OVERLAY_OPEN);
    await sleep(400);
    await evaluate('(function () {' +
      ' var ev = new KeyboardEvent("keydown", {key: "Escape", bubbles: true});' +
      ' document.getElementById("settings-overlay").dispatchEvent(ev); return true; })()');
    await sleep(300);
    const ovAfter = await evaluate(OVERLAY_READ);
    const ovChecks = [
      ["карточка скрыта, пока её не открыли", ovBefore.hidden === true && !ovBefore.inert],
      ["карточка по центру и меньше окна", ovDuring.hidden === false && ovDuring.centered &&
        ovDuring.covers],
      ["фон под карточкой размыт", /blur/.test(ovDuring.blur || "")],
      ["пока открыто - остальная страница inert", ovDuring.inert || ovDuring.disabled.length >= 3],
      ["фокус уехал в карточку", ovDuring.focusInCard === true],
      ["Python узнал об открытии", ovDuring.reported === true],
      ["клик по карточке не закрывает", afterCardClick.hidden === false],
      ["клик по фону закрывает", afterBackdrop.hidden === true && !afterBackdrop.inert],
      ["Escape закрывает", ovAfter.hidden === true && !ovAfter.inert && !ovAfter.disabled.length],
      ["журнал в карточке не дублируется", ovDuring.logInCard === 0 && ovDuring.logs === 1],
    ];
    ovChecks.forEach(([name, okFlag]) => { if (!okFlag) fail(name); });
    console.log(`  до: скрыта=${ovBefore.hidden} inert=${ovBefore.inert} | открыта: скрыта=${ovDuring.hidden}` +
      ` по_центру=${ovDuring.centered} размыт=${/blur/.test(ovDuring.blur || "")} inert=${ovDuring.inert}` +
      ` фокус_в_карточке=${ovDuring.focusInCard} python=${ovDuring.reported}` +
      ` | клик_по_карточке=${afterCardClick.hidden} клик_по_фону=${afterBackdrop.hidden}` +
      ` Escape=${ovAfter.hidden} | журналов=${ovDuring.logs}`);

    console.log("--- разделы и поля ---");
    await evaluate(OVERLAY_OPEN);
    await sleep(300);
    const seeded = await evaluate('[].slice.call(document.getElementById("font-sans").querySelectorAll(".knob-tick")).map(function(n){return n.getAttribute("data-value");}).filter(Boolean)');
    console.log(`шрифты в списке: ${JSON.stringify(seeded)}`);
    // две колонки карточки шрифтов: слева панелька 2x2 из ручек, справа
    // предпросмотр строкой «{заголовок} - {выбранное семейство}»
    const fontCols = await evaluate(`(function () {
      function rect(n) {
        if (!n) return null;
        var r = n.getBoundingClientRect();
        return {l: Math.round(r.left), t: Math.round(r.top),
                r: Math.round(r.right), b: Math.round(r.bottom),
                role: n.getAttribute("role") || "",
                ticks: n.querySelectorAll(".knob-tick").length};
      }
      var prev = rect(document.getElementById("font-preview"));
      var groups = ["font-heading", "font-sans", "font-mono", "font-weight"].map(function(id) {
        return rect(document.getElementById(id));
      });
      var cells = [].slice.call(document.querySelectorAll(".knob-cell")).map(rect);
      var txt = document.getElementById("font-preview");
      var s = txt ? txt.textContent.replace(/\\s+/g, " ") : "";
      return {prev: prev, groups: groups, cells: cells,
              text: s.trim().length,
              heads: ["Заголовок - ", "Основной текст - ", "Консоль - "].filter(function(h) {
                return s.indexOf(h) >= 0; }).length,
              noValue: !document.querySelector(".knob-value")};
    })()`);
    const colChecks = [
      ["карточка шрифтов: четыре ручки slider, у трех есть риски",
        fontCols.groups.length === 4 &&
          fontCols.groups.every(function(g) { return g && g.role === "slider"; }) &&
          fontCols.groups.slice(0, 3).every(function(g) { return g.ticks > 1; })],
      ["панелька 2x2: две строки по две ячейки",
        fontCols.cells.length === 4 &&
          fontCols.cells[0].t === fontCols.cells[1].t &&
          fontCols.cells[2].t === fontCols.cells[3].t &&
          fontCols.cells[0].l === fontCols.cells[2].l &&
          fontCols.cells[1].l === fontCols.cells[3].l &&
          fontCols.cells[0].l < fontCols.cells[1].l &&
          fontCols.cells[2].t > fontCols.cells[0].t],
      ["левая колонка: все ручки слева от предпросмотра",
        !!fontCols.prev && fontCols.groups.every(function(g) {
          return g && g.l < fontCols.prev.l && g.r <= fontCols.prev.l + 1; })],
      ["предпросмотр в правой колонке напротив панельки",
        !!fontCols.prev && fontCols.prev.t <= fontCols.groups[0].b],
      ["предпросмотр: три строки «{заголовок} - {шрифт}»",
        fontCols.heads === 3 && fontCols.text >= 30],
      ["число веса убрано в подсказку (.knob-value нет)", fontCols.noValue],
      ["общий шрифт = системный + семейства",
        fontCols.groups[1] && fontCols.groups[1].ticks === seeded.length + 1],
    ];
    colChecks.forEach(([name, okFlag]) => { if (!okFlag) fail(name); });
    console.log(`  панелька шрифтов: риски=[${fontCols.groups.map(function(g) {
      return g ? g.ticks : "x"; }).join(",")}] ячеек=${fontCols.cells.length}` +
      ` предпросмотр l=${fontCols.prev ? fontCols.prev.l : "?"} строк=${fontCols.heads}`);
    // ручка шрифта: колесо меняет семейство - сохраняется, попадает в
    // предпросмотр строкой «Заголовок - {семейство}», подсказка ручки
    // набрана этим же семейством
    await evaluate('document.getElementById("font-heading").scrollIntoView({block: "center"}); true');
    await sleep(80);
    const hBox = await evaluate(`(function () {
      var k = document.getElementById("font-heading");
      var r = k.getBoundingClientRect();
      return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2),
              v0: k.value, ticks: k.querySelectorAll(".knob-tick").length};
    })()`);
    await send("Input.dispatchMouseEvent", {type: "mouseMoved", x: hBox.x, y: hBox.y});
    await sleep(80);
    await send("Input.dispatchMouseEvent", {type: "mouseWheel", x: hBox.x, y: hBox.y,
      deltaX: 0, deltaY: -120});
    await sleep(350);   // больше TIP_DELAY(220): подсказка успевает показаться
    const fontWheel = await evaluate(`(function () {
      var k = document.getElementById("font-heading");
      var s = (window.__probe.saved || []).filter(function (x) {
        return x[0] === "font_heading"; }).slice(-1)[0];
      var prev = document.getElementById("font-preview").textContent.replace(/\\s+/g, " ");
      var tip = document.getElementById("tip");
      return {v: k.value, saved: s,
              inPreview: prev.indexOf("Заголовок - " + k.value) >= 0,
              tipHidden: tip.hidden, tipText: (tip.textContent || "").trim(),
              tipFont: getComputedStyle(tip).fontFamily};
    })()`);
    if (!(typeof fontWheel.v === "string" && fontWheel.v && fontWheel.v !== hBox.v0 &&
          fontWheel.saved && fontWheel.saved[1] === fontWheel.v && fontWheel.inPreview)) {
      fail("ручка шрифта: колесо не сменило семейство/не сохранилось/нет в предпросмотре: " +
           JSON.stringify({hBox: hBox, fontWheel: fontWheel}));
    }
    if (!(fontWheel.tipHidden === false && fontWheel.tipText === fontWheel.v &&
          fontWheel.tipFont.indexOf(fontWheel.v) >= 0)) {
      fail("подсказка ручки шрифта не показана её же шрифтом: " + JSON.stringify(fontWheel));
    }
    // возвращаем семейство: ниже заголовки меряются в шести языках
    await send("Input.dispatchMouseEvent", {type: "mouseWheel", x: hBox.x, y: hBox.y,
      deltaX: 0, deltaY: 120});
    await sleep(200);
    // упоры шкалы: дуга конечна - вниз от нуля и вверх от максимума
    // колесо не двигает позицию (зацикливания нет)
    const readFontKnob = () => evaluate('document.getElementById("font-heading").value');
    const vAtStop = await readFontKnob();
    await send("Input.dispatchMouseEvent", {type: "mouseWheel", x: hBox.x, y: hBox.y,
      deltaX: 0, deltaY: 120});                     // вниз: у нулевой точки
    await sleep(150);
    const vLow = await readFontKnob();
    await send("Input.dispatchMouseEvent", {type: "mouseWheel", x: hBox.x, y: hBox.y,
      deltaX: 0, deltaY: -120});                    // до максимума...
    await sleep(150);
    await send("Input.dispatchMouseEvent", {type: "mouseWheel", x: hBox.x, y: hBox.y,
      deltaX: 0, deltaY: -120});                    // ...и ещё вверх: упор
    await sleep(150);
    const vHigh = await readFontKnob();
    await send("Input.dispatchMouseEvent", {type: "mouseWheel", x: hBox.x, y: hBox.y,
      deltaX: 0, deltaY: 120});                     // обратно к нулю
    await sleep(150);
    const vBack = await readFontKnob();
    if (!(vAtStop === "" && vLow === "" && vHigh !== "" && vHigh !== vLow && vBack === "")) {
      fail("упоры шкалы шрифта не работают (циклирование?): " + JSON.stringify(
        {vAtStop: vAtStop, vLow: vLow, vHigh: vHigh, vBack: vBack}));
    }
    console.log(`  упоры шкалы: "${vAtStop}" -> вниз "${vLow}" -> вверх "${vHigh}" -> "${vBack}"`);
    // бесконечная ручка толщины: слайдер с диапазоном100..900, колесо и
    // горизонтальное перетаскивание крутят её, шаг квантован
    // (scrollIntoView: ручка в конце карточки - ниже фолда, CDP-мышь
    //  не дотянется до координат за пределами вьюпорта)
    await evaluate('document.getElementById("font-weight").scrollIntoView({block: "center"}); true');
    await sleep(80);
    const knobBox = await evaluate(`(function () {
      var k = document.getElementById("font-weight");
      if (!k) return null;
      var r = k.getBoundingClientRect();
      var at = document.elementFromPoint(Math.round(r.left + r.width / 2),
                                         Math.round(r.top + r.height / 2));
      return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2),
              v0: k.value, role: k.getAttribute("role"),
              min: k.getAttribute("aria-valuemin"), max: k.getAttribute("aria-valuemax"),
              ind: !!k.querySelector(".knob-ind"),
              at: at ? (at.id || at.className || at.tagName) : null,
              inKnob: !!(at && (at === k || k.contains(at)))};
    })()`);
    if (!(knobBox && knobBox.role === "slider" && knobBox.min === "100" &&
          knobBox.max === "900" && knobBox.ind)) {
      fail("ручка толщины не slider/без диапазона/без индикатора: " + JSON.stringify(knobBox));
    } else {
      await send("Input.dispatchMouseEvent",
        {type: "mouseMoved", x: knobBox.x, y: knobBox.y});
      await sleep(80);
      await send("Input.dispatchMouseEvent", {type: "mouseWheel", x: knobBox.x,
        y: knobBox.y, deltaX: 0, deltaY: -120});
      await sleep(120);
      const v1 = await evaluate('document.getElementById("font-weight").value');
      if (!(typeof v1 === "number" && v1 !== knobBox.v0 && v1 >= 100 && v1 <= 900 &&
            v1 % 10 === 0)) {
        fail("колесо не крутит ручку: " + JSON.stringify({v0: knobBox.v0, v1: v1,
          at: knobBox.at, inKnob: knobBox.inKnob, xy: [knobBox.x, knobBox.y]}));
      }
      // горизонтальное перетаскивание зажатой мышью
      await send("Input.dispatchMouseEvent", {type: "mousePressed", x: knobBox.x,
        y: knobBox.y, button: "left", buttons: 1, clickCount: 1});
      await send("Input.dispatchMouseEvent", {type: "mouseMoved", x: knobBox.x + 170,
        y: knobBox.y, button: "left", buttons: 1});
      await sleep(80);
      await send("Input.dispatchMouseEvent", {type: "mouseReleased", x: knobBox.x + 170,
        y: knobBox.y, button: "left", buttons: 0, clickCount: 1});
      await sleep(120);
      const v2 = await evaluate(`(function () {
        var k = document.getElementById("font-weight");
        var s = (window.__probe.saved || []).filter(function (x) {
          return x[0] === "font_weight"; }).slice(-1)[0];
        return {v: k.value, saved: s};
      })()`);
      if (!(typeof v2.v === "number" && v2.v !== v1 && v2.v >= 100 && v2.v <= 900 &&
            v2.v % 10 === 0 && v2.saved && v2.saved[1] === v2.v)) {
        fail("перетаскивание не круто или не сохранилось: " +
             JSON.stringify({v1: v1, v2: v2}));
      }
      console.log(`  ручка толщины: ${knobBox.v0} -> колесо ${v1} -> перетаскивание ${v2.v}` +
        ` сохранено=${JSON.stringify(v2.saved)}`);
      // число убрано из-под ручки - подсказка показывает вес в процентах
      await send("Input.dispatchMouseEvent",
        {type: "mouseMoved", x: knobBox.x, y: knobBox.y});
      await sleep(350);
      const wTip = await evaluate(`(function () {
        var t = document.getElementById("tip");
        return {hidden: t.hidden, text: (t.textContent || "").trim()};
      })()`);
      if (!(wTip.hidden === false && wTip.text.indexOf("%") === wTip.text.length - 1 &&
            wTip.text.indexOf("Толщина") >= 0)) {
        fail("подсказка веса не «Толщина шрифта - N%»: " + JSON.stringify(wTip));
      }
      console.log(`  подсказка веса: "${wTip.text}"`);
    }
    for (const lang of LANGS) {
      const m = await evaluate(`(function () {
        curLang = ${JSON.stringify(lang)}; applyI18n(); return ${WIN_MEASURE};
      })()`);
      const clipped = m.labels.filter((l) => l.clipped);
      const over = m.overflowX > 0 || m.navOverflowX > 0 ||
                   m.sections.some((s) => s.overflowX > 0) || m.clipped.length > 0;
      if (over || clipped.length) fail(`${lang}: перелив или обрезка`);
      if (m.titles.length) fail(`${lang}: нативные title в карточке: ${m.titles.join(", ")}`);
      if (m.icons.some((i) => !i.tip || !i.aria)) {
        fail(`${lang}: кнопка с иконкой без подсказки: ${JSON.stringify(m.icons)}`);
      }
      if (m.labels.some((l) => l.svg && (l.text || !l.tip || !l.aria))) {
        fail(`${lang}: кнопка с иконкой без текста/подсказки: ${JSON.stringify(m.labels)}`);
      }
      if (m.cards < 3) fail(`${lang}: карточек всего ${m.cards} — группировка потеряна`);
      if (!m.titled.length) fail(`${lang}: у карточек нет заголовков`);
      console.log(`${lang.padEnd(6)} кнопок=${m.buttons} (иконок ${m.icons.length}) полей=${m.controls} ` +
        `карточек=${m.cards} заголовки=[${m.titled.join(" | ")}] ` +
        `перелив=${m.overflowX}px список=[${m.sections.map((s) => `${s.id}:${s.overflowX}/${s.controls}`).join(" ")}] ` +
        `обрезано=${clipped.length + m.clipped.length}`);
      m.sections.forEach((s) => { if (s.overflowX > 0) console.log(`        ${s.id}: вылезает на ${s.overflowX}px`); });
      m.clipped.forEach((c) => console.log(`        обрезан control: ${c}`));
    }

    console.log("--- подсказки ---");
    await evaluate('curLang = "ru"; applyI18n(); true');
    // Подсказки живут от настоящего указателя: живость по :hover и pointermove.
    // Синтетический pointerover курсор не двигает, поэтому мышь водим через CDP.
    const tipBtn = await evaluate(`(function () {
      var b = document.getElementById("reload-themes");
      b.scrollIntoView({block: "center"});
      var r = b.getBoundingClientRect();
      return {cx: Math.round(r.left + r.width / 2), cy: Math.round(r.top + r.height / 2),
              left: r.left, top: r.top, w: r.width, h: r.height};
    })()`);
    const mouseMove = (x, y) => send("Input.dispatchMouseEvent",
      {type: "mouseMoved", x: Math.round(x), y: Math.round(y)});
    await mouseMove(6, 6);                                // на фон - чистая база
    await sleep(120);
    await mouseMove(tipBtn.cx, tipBtn.cy);                // наводимся на кнопку
    await sleep(120);
    const tipEarly = await evaluate(
      '(function () { var t = document.getElementById("tip");' +
      ' return {hidden: t.hidden, x: Math.round(TIP.x), tx: Math.round(TIP.tx)}; })()');
    await sleep(900);
    const tip = await evaluate(`(function () {
      var t = document.getElementById("tip");
      var b = document.getElementById("reload-themes").getBoundingClientRect();
      var r = t.getBoundingClientRect();
      var head = document.querySelector(".tip-thread-head");
      var line = document.querySelector(".tip-thread-line");
      var thread = document.getElementById("tip-thread");
      var d = head ? head.getAttribute("d") : "";
      // носик наконечника должен сидеть на бордюре элемента (запас на штрих)
      var m = d.match(/L\\s*(-?[\\d.]+)\\s+(-?[\\d.]+)\\s+L/);
      var onBorder = !!m && (Math.abs(parseFloat(m[1]) - b.left) < 1.5 ||
                             Math.abs(parseFloat(m[1]) - b.right) < 1.5 ||
                             Math.abs(parseFloat(m[2]) - b.top) < 1.5 ||
                             Math.abs(parseFloat(m[2]) - b.bottom) < 1.5);
      // подсказка держится снаружи раздутой рамки элемента, не накрывая его
      var inflated = {left: b.left - 9, right: b.right + 9, top: b.top - 9, bottom: b.bottom + 9};
      var overlap = !(r.right <= inflated.left || r.left >= inflated.right ||
                      r.bottom <= inflated.top || r.top >= inflated.bottom);
      return {hidden: t.hidden, on: t.classList.contains("tip-on"),
              text: t.querySelector(".tip-text").textContent,
              described: document.getElementById("reload-themes").getAttribute("aria-describedby"),
              settled: Math.abs(TIP.x - TIP.tx) < 0.5 && Math.abs(TIP.y - TIP.ty) < 0.5,
              thread: !!thread && !thread.hidden && thread.classList.contains("tip-on") &&
                      !!line && line.getAttribute("d").length > 0 && d.length > 0,
              onBorder: onBorder, overlap: overlap,
              x: Math.round(r.left), y: Math.round(r.top),
              inView: r.left >= 0 && r.right <= window.innerWidth + 1 && r.top >= 0};
    })()`);
    // волшебная обводка мерцает (прозрачность меняется между замерами) и
    // крутится, из-под подсказки в каждый момент светится пылинка
    const magicRead = `(function () {
      var t = document.getElementById("tip");
      var cs = getComputedStyle(t, "::before");
      var d = [].slice.call(t.querySelectorAll("i.dust"));
      var lit = d.filter(function (n) { return parseFloat(getComputedStyle(n).opacity) > 0.05; }).length;
      return {anim: cs.animationName, play: cs.animationPlayState,
              op: parseFloat(cs.opacity), n: d.length, lit: lit};
    })()`;
    const magic1 = await evaluate(magicRead);
    await sleep(400);
    const magic2 = await evaluate(magicRead);
    const tipChecks = [
      ["появляется не сразу (задержка)", tipEarly.hidden === true],
      ["показывается по наведению", tip.hidden === false && tip.on === true],
      ["текст подсказки совпадает с подписью", tip.text.length > 0],
      ["доезжает до места и встаёт", tip.settled === true],
      ["нить видна (линия + наконечник)", tip.thread],
      ["носик наконечника на бордюре элемента", tip.onBorder],
      ["подсказка не накрывает элемент", !tip.overlap],
      ["подсказка помещается в окно", tip.inView],
      ["элемент связан с подсказкой", tip.described === "tip"],
      ["волшебная обводка есть, крутится и мерцает",
        magic1.anim.indexOf("tipSpin") >= 0 &&
        magic1.play.indexOf("running") >= 0 &&
        Math.abs(magic1.op - magic2.op) > 0.005],
      ["пылинки исходят из-под подсказки",
        magic1.n >= 6 && (magic1.lit >= 1 || magic2.lit >= 1)],
    ];
    tipChecks.forEach(([name, okFlag]) => { if (!okFlag) fail(name); });
    // wiggle реплики кликера: каждые 500-й клик показывает комментарий с
    // анимацией msg-wiggle, и она правда двигает текст (замер трансформа)
    await evaluate(`(function () {
      var btn = document.getElementById("clicker");
      for (var i = 0; i < 500; i++) btn.click();
      return true;
    })()`);
    await sleep(300);
    const wig = await evaluate(`(function () {
      var m = document.getElementById("clicker-msg");
      var cs = getComputedStyle(m);
      return {shown: m.classList.contains("show"), anim: cs.animationName,
              t1: cs.transform, text: (m.textContent || "").trim().length > 0};
    })()`);
    await sleep(150);
    const wig2 = await evaluate(
      'getComputedStyle(document.getElementById("clicker-msg")).transform');
    if (!(wig.shown && wig.anim.indexOf("msg-wiggle") >= 0 && wig.text && wig.t1 !== wig2)) {
      fail("реплика кликера без wiggle: " + JSON.stringify({wig: wig, t2: wig2}));
    }
    // курсор ушёл с кнопки - подсказка обязана исчезнуть вместе с нитью
    await mouseMove(6, 6);
    await sleep(250);
    const tipGone = await evaluate(`(function () {
      var t = document.getElementById("tip");
      var b = document.getElementById("reload-themes");
      return {hidden: t.hidden, described: b.getAttribute("aria-describedby"),
              line: document.querySelector(".tip-thread-line").getAttribute("d").length === 0,
              head: document.querySelector(".tip-thread-head").getAttribute("d").length === 0};
    })()`);
    const goneOk = tipGone.hidden && !tipGone.described && tipGone.line && tipGone.head;
    if (!goneOk) fail("подсказка не скрылась после ухода курсора");
    // За крупным элементом подсказка тянется с инерцией: временная кнопка,
    // курсор гуляет внутри неё - подсказка ездит по бордюру, нить не срывается.
    await evaluate(`(function () {
      var b = document.createElement("button");
      b.id = "probe-tip-big";
      b.setAttribute("data-tip", "временная кнопка");
      b.style.cssText = "position:fixed;left:40px;top:160px;width:280px;height:80px;z-index:2147483000;";
      document.body.appendChild(b);
      return true;
    })()`);
    const bigBtn = await evaluate(`(function () {
      var b = document.getElementById("probe-tip-big").getBoundingClientRect();
      return {cx: Math.round(b.left + b.width / 2), cy: Math.round(b.top + b.height / 2)};
    })()`);
    await mouseMove(bigBtn.cx, bigBtn.cy);
    await sleep(900);
    const bigBefore = await evaluate(`(function () {
      var t = document.getElementById("tip");
      return {shown: !t.hidden && t.classList.contains("tip-on"), x: TIP.x, y: TIP.y, tx: TIP.tx, ty: TIP.ty};
    })()`);
    if (!bigBefore.shown) fail("подсказка не появилась на временной кнопке");
    await mouseMove(bigBtn.cx + 25, bigBtn.cy + 30);
    await sleep(110);
    const bigMid = await evaluate('({x: TIP.x, tx: TIP.tx, rm: reducedMotion()})');
    await sleep(600);
    const bigEnd = await evaluate(`(function () {
      var t = document.getElementById("tip");
      var b = document.getElementById("probe-tip-big").getBoundingClientRect();
      var r = t.getBoundingClientRect();
      var head = document.querySelector(".tip-thread-head");
      var d = head ? head.getAttribute("d") : "";
      var m = d.match(/L\\s*(-?[\\d.]+)\\s+(-?[\\d.]+)\\s+L/);
      var onBorder = !!m && (Math.abs(parseFloat(m[1]) - b.left) < 1.5 ||
                             Math.abs(parseFloat(m[1]) - b.right) < 1.5 ||
                             Math.abs(parseFloat(m[2]) - b.top) < 1.5 ||
                             Math.abs(parseFloat(m[2]) - b.bottom) < 1.5);
      return {x: TIP.x, y: TIP.y, tx: TIP.tx, ty: TIP.ty,
              moved: Math.hypot(TIP.x - ${bigBefore.x}, TIP.y - ${bigBefore.y}) > 3,
              settled: Math.abs(TIP.x - TIP.tx) < 0.5 && Math.abs(TIP.y - TIP.ty) < 0.5,
              onBorder: onBorder,
              inView: r.left >= 0 && r.right <= window.innerWidth + 1 && r.top >= 0};
    })()`);
    const bigMoved = Math.hypot(bigEnd.tx - bigBefore.x, bigEnd.ty - bigBefore.y) > 3;
    if (bigMid.rm) {
      if (!(bigMoved && bigEnd.moved && bigEnd.settled && bigEnd.onBorder && bigEnd.inView)) {
        fail("подсказка не следует за курсором (reduced motion)");
      }
    } else if (bigMoved && bigEnd.moved && bigEnd.settled) {
      if (Math.abs(bigMid.tx - bigMid.x) < 1) fail("инерция не видна: подсказка подскочила мгновенно");
      if (!(bigEnd.onBorder && bigEnd.inView)) fail("нить или подсказка уехали от элемента");
    } else {
      fail("подсказка не потянулась за курсором");
    }
    // Орбита: курсор по осям - подсказка переходит на другие грани, и нить
    // после перехода целится в грань, а не в угол. Слева у кнопки (left: 40)
    // нет места - там подсказка уходит на смежную грань, поэтому верх, право
    // и низ.
    const orbitSides = [];
    for (const [ox, oy] of [[0, -30], [100, 0], [0, 30]]) {
      await mouseMove(bigBtn.cx + ox, bigBtn.cy + oy);
      await sleep(450);
      orbitSides.push(await evaluate(`(function () {
        var t = document.getElementById("tip").getBoundingClientRect();
        var b = document.getElementById("probe-tip-big").getBoundingClientRect();
        if (t.top >= b.bottom - 1) return "bottom";
        if (t.bottom <= b.top + 1) return "top";
        if (t.left >= b.right - 1) return "right";
        if (t.right <= b.left + 1) return "left";
        return "overlap";
      })()`));
    }
    if (new Set(orbitSides).size < 3 || orbitSides.includes("overlap")) {
      fail("подсказка не крутится вокруг элемента: " + orbitSides.join(","));
    }
    const orbitArrow = await evaluate(`(function () {
      var d = document.querySelector(".tip-thread-head").getAttribute("d") || "";
      var m = d.match(/L\\s*(-?[\\d.]+)\\s+(-?[\\d.]+)\\s+L/);
      var b = document.getElementById("probe-tip-big").getBoundingClientRect();
      if (!m) return {ok: false};
      var x = parseFloat(m[1]), y = parseFloat(m[2]);
      var onEdge = Math.abs(y - b.top) < 1.5 || Math.abs(y - b.bottom) < 1.5 ||
                   Math.abs(x - b.left) < 1.5 || Math.abs(x - b.right) < 1.5;
      var atCorner = (Math.abs(x - b.left) < 1.5 || Math.abs(x - b.right) < 1.5) &&
                     (Math.abs(y - b.top) < 1.5 || Math.abs(y - b.bottom) < 1.5);
      return {ok: onEdge && !atCorner, x: Math.round(x), y: Math.round(y)};
    })()`);
    if (!orbitArrow.ok) fail("нить целится не в грань (орбита): " + JSON.stringify(orbitArrow));
    // угол кольца достижим (наконечник - в угол объекта), а строка начинается
    // строго от края подсказки, а не из её центра
    await mouseMove(bigBtn.cx + 80, bigBtn.cy - 23);
    await sleep(450);
    const cornerRing = await evaluate(`(function () {
      var b = document.getElementById("probe-tip-big").getBoundingClientRect();
      var t = document.getElementById("tip").getBoundingClientRect();
      var hd = document.querySelector(".tip-thread-head").getAttribute("d") || "";
      var hm = hd.match(/L\\s*(-?[\\d.]+)\\s+(-?[\\d.]+)\\s+L/);
      var ld = document.querySelector(".tip-thread-line").getAttribute("d") || "";
      var lm = ld.match(/^M\\s*(-?[\\d.]+)\\s+(-?[\\d.]+)/);
      var atCorner = false;
      if (hm) {
        var x = parseFloat(hm[1]), y = parseFloat(hm[2]);
        atCorner = Math.abs(x - b.right) < 1.5 && Math.abs(y - b.top) < 1.5;
      }
      var startOk = false;
      if (lm) {
        var sx = parseFloat(lm[1]), sy = parseFloat(lm[2]);
        startOk = Math.abs(sx - t.left) < 0.7 || Math.abs(sx - t.right) < 0.7 ||
                  Math.abs(sy - t.top) < 0.7 || Math.abs(sy - t.bottom) < 0.7;
      }
      return {atCorner: atCorner, startOk: startOk,
              arrow: hm ? [Math.round(parseFloat(hm[1])), Math.round(parseFloat(hm[2]))] : null};
    })()`);
    if (!cornerRing.atCorner) fail("угол кольца недоступен: " + JSON.stringify(cornerRing));
    if (!cornerRing.startOk) fail("нить начинается не от края подсказки: " + JSON.stringify(cornerRing));
    // Перерисовка карточки: элемент исчезает из-под курсора без pointerout,
    // подсказка не имеет права висеть на мёртвом узле.
    await evaluate('var b = document.getElementById("probe-tip-big"); if (b) b.remove(); true');
    await mouseMove(12, bigBtn.cy + 5);
    await sleep(200);
    const tempGone = await evaluate(`(function () {
      var t = document.getElementById("tip");
      return {hidden: t.hidden,
              line: document.querySelector(".tip-thread-line").getAttribute("d").length === 0,
              head: document.querySelector(".tip-thread-head").getAttribute("d").length === 0};
    })()`);
    await evaluate('var b = document.getElementById("probe-tip-big"); if (b) b.remove(); true');
    const detachOk = tempGone.hidden && tempGone.line && tempGone.head;
    if (!detachOk) fail("подсказка висит после перерисовки элемента");
    console.log(`  задержка=${tipEarly.hidden ? "есть" : "нет"} текст="${tip.text}" ` +
      `нить=${tip.thread} наконечник_у_элемента=${tip.onBorder} ` +
      `следует_за_курсором=${bigMoved && bigEnd.settled} скрыта_после_ухода=${goneOk} ` +
      `орбита=[${orbitSides.join(",")}] наконечник_в_грани=${orbitArrow.ok} ` +
      `угол_кольца=${cornerRing.atCorner} старт_от_края=${cornerRing.startOk} ` +
      `обводка=${magic1.anim.indexOf("tipSpin") >= 0 && magic1.play.indexOf("running") >= 0 ? "ok" : "BAD"}` +
      `(мерцание ${Math.abs(magic1.op - magic2.op).toFixed(3)})` +
      ` пылинки=${magic1.n}/${magic2.n} lit=${magic1.lit}+${magic2.lit}`);

    // Магнитные силы подсказок (карточка «Подсказки» раздела «Интерфейс»):
    // поля есть и переводятся, дефолты 50/100, правка сохраняется и применяется
    // сразу, а поведение правда меняется: repel держит подсказку вне элемента,
    // pull ускоряет схождение за курсором.
    console.log("--- силы подсказок ---");
    const forceFields = await evaluate(`(function () {
      var pull = document.getElementById("tip-pull"), repel = document.getElementById("tip-repel");
      var pr = document.getElementById("tip-pull-range"), rr = document.getElementById("tip-repel-range");
      function tipAttr(n) { return n ? (n.getAttribute("data-i18n-tip") || "") : ""; }
      var row = pull ? pull.closest(".range-row") : null;
      return {pull: !!pull, repel: !!repel, range: !!pr && !!rr,
              pullType: pull ? pull.type : "",
              pullTip: tipAttr(pull), repelTip: tipAttr(repel),
              label: row ? !!row.querySelector("label") : false,
              force: {pull: TIP_FORCE.pull, repel: TIP_FORCE.repel}};
    })()`);
    const forceChecks = [
      ["поля сил подсказок есть (число + ползунок)",
        forceFields.pull && forceFields.repel && forceFields.range &&
        forceFields.pullType === "number" && forceFields.label],
      ["поля сил подсказок переведены", forceFields.pullTip.length > 0 && forceFields.repelTip.length > 0],
      ["силы по умолчанию 50/100",
        forceFields.force.pull === 50 && forceFields.force.repel === 100],
    ];
    forceChecks.forEach(([name, okFlag]) => { if (!okFlag) fail(name); });
    const forceSaved = await evaluate(`(function () {
      window.__probe.saved = [];
      var n = document.getElementById("tip-pull");
      n.value = "85"; n.dispatchEvent(new Event("change"));
      return {saved: window.__probe.saved.slice(-1)[0], pull: TIP_FORCE.pull};
    })()`);
    if (!forceSaved.saved || forceSaved.saved[0] !== "tip_pull" || +forceSaved.saved[1] !== 85) {
      fail("правка силы притяжения не сохраняется");
    }
    if (forceSaved.pull !== 85) fail("сила притяжения не применилась сразу после правки");
    // поведение: временная кнопка под курсором, замер перекрытия и скорости.
    // Кнопка стоит высоко: окно пробника низкое, прижатие к нижнему краю окна
    // (clamp) не даст вытолкнуть подсказку вниз и проверка соврала бы.
    await evaluate(`(function () {
      var b = document.createElement("button");
      b.id = "probe-tip-force";
      b.setAttribute("data-tip", "проверка сил");
      b.style.cssText = "position:fixed;left:40px;top:120px;width:360px;height:80px;z-index:2147483000;";
      document.body.appendChild(b);
      return true;
    })()`);
    const forceBtn = await evaluate(`(function () {
      var b = document.getElementById("probe-tip-force").getBoundingClientRect();
      return {cx: Math.round(b.left + b.width / 2), cy: Math.round(b.top + b.height / 2)};
    })()`);
    // Силы задаются через стаб настроек, а не только setTipForces: poll() каждые
    // 200 мс возвращает TIP_FORCE из настроек и затирал бы временные значения.
    async function setForces(pull, repel) {
      await evaluate(`(function () {
        pywebview.api.save_setting("tip_pull", ${pull});
        pywebview.api.save_setting("tip_repel", ${repel});
        setTipForces(${pull}, ${repel});
        var a = document.getElementById("tip-pull"), b = document.getElementById("tip-repel");
        if (a) a.value = ${pull};
        if (b) b.value = ${repel};
        return TIP_FORCE.pull + "/" + TIP_FORCE.repel;
      })()`);
    }
    async function forceProbe(pull, repel) {
      await setForces(pull, repel);
      await mouseMove(forceBtn.cx - 9, forceBtn.cy - 7);   // встряска: иначе
      await sleep(80);                                     // pointermove в точку
      await mouseMove(forceBtn.cx, forceBtn.cy);           // не перезапускает кадры
      // углу нужно сойтись к новой стороне (0.45 рад/кадр ~6 кадров); под
      // нагрузкой кадры идут медленнее -800 мс запас против флаки
      await sleep(800);
      return evaluate(`(function () {
        var t = document.getElementById("tip"), el = document.getElementById("probe-tip-force");
        var tr = t.getBoundingClientRect(), er = el.getBoundingClientRect();
        var overlap = !(tr.right <= er.left || tr.left >= er.right ||
                        tr.bottom <= er.top || tr.top >= er.bottom);
        return {hidden: t.hidden, overlap: overlap,
                tx: TIP.tx, ty: TIP.ty,
                ang: Math.round(TIP.ang * 180 / Math.PI),
                target: TIP.target ? (TIP.target.id || "") : "",
                raf: TIP.raf,
                force: {pull: TIP_FORCE.pull, repel: TIP_FORCE.repel},
                rect: [Math.round(tr.left), Math.round(tr.top),
                       Math.round(tr.width), Math.round(tr.height)]};
      })()`);
    }
    const repelOff = await forceProbe(50, 0);
    if (repelOff.hidden || !repelOff.overlap) {
      fail("repel=0 не ослабляет отталкивание (подсказка не ляжет на элемент)");
    }
    const repelOn = await forceProbe(50, 100);
    if (repelOn.hidden || repelOn.overlap) {
      fail("repel=100 не держит подсказку вне элемента " + JSON.stringify(repelOn));
    }
    // pull: подсказка уже показана на кнопке, прыжок курсора внутри неё -
    // хвост расстояния через 150 мс должен быть больше при слабом притяжении
    async function lagAt(pull) {
      await setForces(pull, 100);
      await mouseMove(forceBtn.cx - 90, forceBtn.cy + 10);
      await sleep(500);                                  // показ и схождение
      const before = await evaluate('({x: Math.round(TIP.x), tx: Math.round(TIP.tx), shown: TIP.node.classList.contains("tip-on")})');
      await mouseMove(forceBtn.cx + 90, forceBtn.cy + 10);
      await sleep(150);
      const after = await evaluate('({lag: Math.hypot(TIP.tx - TIP.x, TIP.ty - TIP.y), ' +
        'pull: TIP_FORCE.pull, rm: reducedMotion(), mode: TIP.mode, raf: TIP.raf, ' +
        'at: [Math.round(TIP.x), Math.round(TIP.y)], tx: [Math.round(TIP.tx), Math.round(TIP.ty)], ' +
        'cx: Math.round(TIP.cx), cy: Math.round(TIP.cy), ' +
        'target: TIP.target ? (TIP.target.id || TIP.target.tagName) : "нет", ' +
        'hover: TIP.target ? TIP.target.matches(":hover") : null, ' +
        'hidden: document.getElementById("tip").hidden, ' +
        'shown: document.getElementById("tip").classList.contains("tip-on")})');
      after.before = before;
      return after;
    }
    const lagLow = await lagAt(0), lagHigh = await lagAt(100);
    if (lagLow.rm) {
      // при prefers-reduced-motion подсказка снапится мгновенно (snapTip) -
      // «хвост схождения» не существует, сравнивать нечего
      console.log("  притяжение: проверка скорости пропущена (reduced motion)");
    } else if (!(lagLow.lag > lagHigh.lag + 4)) {
      fail(`притяжение не влияет на скорость: pull=0 -> ${lagLow.lag.toFixed(1)}px, ` +
           `pull=100 -> ${lagHigh.lag.toFixed(1)}px ` + JSON.stringify({lagLow, lagHigh}));
    }
    // прогрессия притяжения: на том же repel подсказка при pull=0 стоит
    // заметно дальше курсора (центр кнопки), чем при pull=100
    const far = await forceProbe(0, 100);
    const near = await forceProbe(100, 100);
    const distCur = (p) => Math.hypot(p.rect[0] + p.rect[2] / 2 - forceBtn.cx,
                                      p.rect[1] + p.rect[3] / 2 - forceBtn.cy);
    if (far.hidden || near.hidden || !(distCur(far) > distCur(near) + 15)) {
      fail("pull не меняет расстояние до курсора в прогрессии: " +
           JSON.stringify({far: Math.round(distCur(far)), near: Math.round(distCur(near)),
             farA: far.ang, nearA: near.ang, farF: far.force, nearF: near.force,
             farT: far.target, farRaf: far.raf, farRect: far.rect}));
    }
    await setForces(50, 100);                            // вернуть дефолты
    await evaluate('var b = document.getElementById("probe-tip-force"); if (b) b.remove(); true');
    await mouseMove(12, 12);
    await sleep(200);
    console.log(`  поля=есть сохранение=${JSON.stringify(forceSaved.saved)} ` +
      `repel: 0->на_элементе=${repelOff.overlap} 100->вне=${!repelOn.overlap} ` +
      `pull хвост: 0=${lagLow.lag.toFixed(1)}px 100=${lagHigh.lag.toFixed(1)}px ` +
      `дистанция: 0=${Math.round(distCur(far))}px 100=${Math.round(distCur(near))}px`);

    // -- массовая вкладка ----------------------------------------------------
    console.log("--- массовая вкладка ---");
    await evaluate('switchTab("batch"); true');
    await sleep(150);
    const bulkUI = await evaluate(`(function () {
      var p = document.getElementById("panel-batch");
      return {visible: !!p && !p.hidden,
              tab: !!document.getElementById("tab-batch"),
              video: document.getElementById("panel-video").hidden,
              playlist: document.getElementById("panel-playlist").hidden};
    })()`);
    if (!(bulkUI.visible && bulkUI.tab && bulkUI.video && bulkUI.playlist)) {
      fail("вкладка Массовая не открывает свою панель: " + JSON.stringify(bulkUI));
    }
    // счётчик: пустые строки, "#" и не-URL пропускаются, дедуп по порядку
    await evaluate(`(function () {
      var box = document.getElementById("url-batch");
      box.value = "https://youtu.be/one\\n\\n# comment\\nhttps://youtu.be/two\\n" +
                  "https://youtu.be/one\\nnot a link";
      box.dispatchEvent(new Event("input"));
      return true;
    })()`);
    const bulkCount = await evaluate('document.getElementById("batch-count").textContent');
    if (bulkCount.indexOf("2") < 0) {
      fail("счётчик не посчитал 2 (дедуп/пропуски): " + bulkCount);
    }
    // пустой ввод: старт не происходит, статус объясняет почему
    await evaluate(`(function () {
      var box = document.getElementById("url-batch");
      box.value = ""; box.dispatchEvent(new Event("input"));
      return true;
    })()`);
    await evaluate('document.getElementById("download").click(); true');
    const bulkEmpty = await evaluate(`(function () {
      return {started: (window.__probe.saved || []).filter(function (x) {
                return x[0] === "bulk"; }).length,
              status: document.getElementById("status").textContent};
    })()`);
    if (bulkEmpty.started !== 0 || !bulkEmpty.status) {
      fail("пустой ввод повёл себя неверно: " + JSON.stringify(bulkEmpty));
    }
    // старт: три ссылки уходят в Api по порядку, статус [1/3], busy с кнопками
    await evaluate(`(function () {
      var box = document.getElementById("url-batch");
      box.value = "https://youtu.be/a\\nhttps://youtu.be/b\\nhttps://youtu.be/c";
      box.dispatchEvent(new Event("input"));
      return true;
    })()`);
    await evaluate('document.getElementById("download").click(); true');
    await sleep(450);
    const bulkStart = await evaluate(`(function () {
      var saved = (window.__probe.saved || []).filter(function (x) { return x[0] === "bulk"; });
      return {list: saved.length ? saved[0][1] : null,
              status: document.getElementById("status").textContent,
              stopOk: document.getElementById("stop").disabled === false,
              dlLocked: document.getElementById("download").disabled === true};
    })()`);
    const bulkListOk = Array.isArray(bulkStart.list) && bulkStart.list.length === 3 &&
      bulkStart.list[0] === "https://youtu.be/a" && bulkStart.list[2] === "https://youtu.be/c";
    if (!(bulkListOk && bulkStart.status.indexOf("[1/3]") === 0 &&
          bulkStart.stopOk && bulkStart.dlLocked)) {
      fail("массовый старт прошёл не так: " + JSON.stringify(bulkStart));
    }
    // Стоп: кнопка блокируется до реального завершения (итог придёт в poll)
    await evaluate('document.getElementById("stop").click(); true');
    const stopLocked = await evaluate('document.getElementById("stop").disabled');
    if (stopLocked !== true) fail("Стоп не заблокировался после клика");
    // убираем «висячее» busy стаба и возвращаем кнопку в idle,
    // чтобы следующие разделы шли с чистым состоянием
    await evaluate(`(function () {
      window.__probe.dlState = {busy: false, status: "", result: null,
                                progress: {mode: "determinate", value: 0}};
      if (typeof setDownloadState === "function") setDownloadState("idle", 0, false);
      return true;
    })()`);
    await sleep(450);
    console.log(`  массовая: панель=${bulkUI.visible} счётчик="${bulkCount}" ` +
      `ссылки=${JSON.stringify(bulkStart.list)} статус="${bulkStart.status}" стоп=${stopLocked}`);

    // -- черновик списка ссылок (localStorage) --------------------------
    console.log("--- черновик списка ---");
    await evaluate(`(function () {
      var box = document.getElementById("url-batch");
      box.value = "https://youtu.be/draft\\nhttps://youtu.be/draft2";
      box.dispatchEvent(new Event("input"));
      return true;
    })()`);
    const draft = await evaluate('localStorage.getItem("synf.bulk_draft") || ""');
    if (draft.indexOf("youtu.be/draft2") < 0) {
      fail("черновик не сохранён в localStorage: " + JSON.stringify(draft));
    }
    console.log(`  черновик: ${draft.length}б`);

    // -- массовая: разбивка вставки и построчная подсветка ------------
    console.log("--- массовая: вставка и статусы ---");
    // защита от порчи файла переводов: в 02eba49 семь русских ключей
    // массовой вкладки записались знаками '?'. Ни один язык не должен
    // содержать '??' в значениях, и ключи массовой обязаны быть у всех.
    const i18nBad = await evaluate(`(function () {
      var out = [];
      var langs = window.I18N || {};
      if (!Object.keys(langs).length) out.push("словарь пуст");
      var keys = ["tab.batch", "url.batch.label", "bulk.hint", "bulk.count",
                  "bulk.clear", "bulk.failed_btn", "bulk.back_btn",
                  "status.enter.bulk", "p.bulk_skip"];
      Object.keys(langs).forEach(function (lang) {
        var d = langs[lang] || {};
        keys.forEach(function (k) {
          var v = d[k];
          if (typeof v !== "string" || !v) out.push(lang + "." + k + "=нет");
          else if (v.indexOf("??") !== -1) out.push(lang + "." + k + "=мусор");
        });
      });
      return out;
    })()`);
    if (i18nBad.length) {
      fail("i18n: " + i18nBad.join(", "));
    }
    // unit: куча ссылок через пробел/запятую/; -> по строкам, запятая
    // и точка с запятой ВНУТРИ url не рвут ссылку
    const pasteNorm = await evaluate(`JSON.stringify(normalizeBulkPaste(
      "https://a.com/x https://b.com/y, https://c.com/z?a=1,2;https://d.com/w.").split("\\n"))`);
    const pl = JSON.parse(pasteNorm);
    if (!(pl.length === 4 && pl[1] === "https://b.com/y" &&
          pl[2] === "https://c.com/z?a=1,2" && pl[3] === "https://d.com/w")) {
      fail("normalizeBulkPaste разобрал неверно: " + pasteNorm);
    }
    // swap: старт массовой прячет textarea и строит список строк
    await evaluate(`(function () {
      switchTab("batch");
      var box = document.getElementById("url-batch");
      box.value = "https://youtu.be/v1\\nhttps://youtu.be/v2\\nhttps://youtu.be/v3";
      box.dispatchEvent(new Event("input"));
      return true;
    })()`);
    await evaluate('document.getElementById("download").click(); true');
    await sleep(450);
    const swap = await evaluate(`(function () {
      var view = document.getElementById("bulk-view");
      var box = document.getElementById("url-batch");
      return {view: !view.hidden, rows: view.children.length, boxHidden: box.hidden,
              icons: !!view.querySelector("svg.bulk-ico path.ico-ok") &&
                     !!view.querySelector("svg.bulk-ico path.ico-fail") &&
                     !!view.querySelector("svg.bulk-ico g.ico-load")};
    })()`);
    if (!(swap.view && swap.rows === 3 && swap.boxHidden)) {
      fail("swap в режим просмотра не случился: " + JSON.stringify(swap));
    }
    if (!swap.icons) {
      fail("SVG-значки состояний не встроены в строки списка");
    }
    // статусы из poll красят строки в цвета темы (--ok/--err/акцент)
    await evaluate(`(function () {
      window.__probe.bulk = {total: 3, index: 2, statuses: ["o", "l", "f"]};
      return true;
    })()`);
    await sleep(450);
    const classes = await evaluate(`(function () {
      var rows = document.getElementById("bulk-view").children;
      return [rows[0].className, rows[1].className, rows[2].className];
    })()`);
    if (!(classes[0].indexOf("is-ok") >= 0 && classes[1].indexOf("is-load") >= 0 &&
          classes[2].indexOf("is-fail") >= 0)) {
      fail("статусы не покрасили строки: " + JSON.stringify(classes));
    }
    // итог: busy -> false: список остаётся с финальными отметками, кнопка
    // «неудавшихся» видна, возврат к полю - кнопкой «К списку ссылок»
    await evaluate(`(function () {
      window.__probe.bulkFailed = ["https://youtu.fail/b", "https://youtu.fail/c"];
      window.__probe.bulkStatuses = ["o", "f", "f"];
      // как в приложении: воркер в finally гасит bulk вместе с busy, в том же
      // тике poll отдаёт bulk=null - итог рисуется только по bulk_statuses
      window.__probe.bulk = null;
      window.__probe.dlState = {busy: false, status: "done", result: "error",
                                progress: {mode: "determinate", value: 100}};
      return true;
    })()`);
    await sleep(450);
    const afterBulk = await evaluate(`(function () {
      var view = document.getElementById("bulk-view");
      var box = document.getElementById("url-batch");
      var fbtn = document.getElementById("bulk-failed");
      var back = document.getElementById("bulk-back");
      var rows = view.children;
      return {viewShown: !view.hidden, boxHidden: box.hidden,
              btnShown: !!fbtn && !fbtn.hidden, backShown: !!back && !back.hidden,
              colors: rows.length >= 3
                ? [rows[0].className, rows[1].className, rows[2].className]
                : ["нет строк: " + rows.length]};
    })()`);
    if (!(afterBulk.viewShown && afterBulk.boxHidden && afterBulk.backShown)) {
      fail("итог не остался на экране с кнопкой возврата: " + JSON.stringify(afterBulk));
    }
    if (!(afterBulk.colors[0].indexOf("is-ok") >= 0 &&
          afterBulk.colors[1].indexOf("is-fail") >= 0 &&
          afterBulk.colors[2].indexOf("is-fail") >= 0)) {
      fail("финальные статусы не покрасили строки: " + JSON.stringify(afterBulk.colors));
    }
    // клик по кнопке подставляет только упавшие ссылки и закрывает список
    await evaluate('document.getElementById("bulk-failed").click(); true');
    const kept = await evaluate(`(function () {
      var view = document.getElementById("bulk-view");
      return {value: document.getElementById("url-batch").value,
              viewHidden: view.hidden, boxShown: !document.getElementById("url-batch").hidden};
    })()`);
    if (kept.value !== "https://youtu.fail/b\nhttps://youtu.fail/c") {
      fail("«Оставить неудавшиеся» подставило неверно: " + JSON.stringify(kept.value));
    }
    if (!(kept.viewHidden && kept.boxShown)) {
      fail("клик «неудавшихся» не закрыл список: " + JSON.stringify(kept));
    }
    // повторный запуск и «К списку ссылок»: итог снова висит, возврат гасит его
    await evaluate('document.getElementById("download").click(); true');
    await sleep(450);
    await evaluate(`(function () {
      window.__probe.bulk = null;
      window.__probe.bulkStatuses = ["o", "o", "o"];
      window.__probe.dlState = {busy: false, status: "done", result: "ok",
                                progress: {mode: "determinate", value: 100}};
      return true;
    })()`);
    await sleep(450);
    const again = await evaluate(`(function () {
      var view = document.getElementById("bulk-view");
      var back = document.getElementById("bulk-back");
      return {viewShown: !view.hidden, backShown: !!back && !back.hidden};
    })()`);
    if (!(again.viewShown && again.backShown)) {
      fail("повторный итог не остался на экране: " + JSON.stringify(again));
    }
    await evaluate('document.getElementById("bulk-back").click(); true');
    const backToBox = await evaluate(`(function () {
      var view = document.getElementById("bulk-view");
      var box = document.getElementById("url-batch");
      var back = document.getElementById("bulk-back");
      return {viewHidden: view.hidden, boxShown: !box.hidden, backHidden: back.hidden};
    })()`);
    if (!(backToBox.viewHidden && backToBox.boxShown && backToBox.backHidden)) {
      fail("«К списку ссылок» не вернул поле: " + JSON.stringify(backToBox));
    }
    // уборка стаба и поля
    await evaluate(`(function () {
      window.__probe.bulk = null;
      window.__probe.bulkFailed = [];
      window.__probe.bulkStatuses = [];
      var box = document.getElementById("url-batch");
      box.value = ""; box.dispatchEvent(new Event("input"));
      return true;
    })()`);
    console.log(`  вставка/статусы: paste=${pl.length} строк, swap=${swap.rows} строк, ` +
      `итог: список=${afterBulk.viewShown} цвета=${afterBulk.colors.map(c => c.indexOf("is-fail") >= 0 ? "f" : c.indexOf("is-ok") >= 0 ? "o" : "-").join("")} ` +
      `кнопка-неудач=${afterBulk.btnShown} возврат: ${backToBox.viewHidden}`);

    console.log("--- раздел FTP ---");
    const ftp = await evaluate(FTP_VIS);
    const ftpChecks = [
      ["флажок открывает и снова закрывает поля", ftp.on.visible > ftp.off.visible &&
        ftp.back.visible === ftp.off.visible],
      ["карточка «Подключение» едет за флажком", ftp.off.conn === false && ftp.on.conn === true &&
        ftp.back.conn === false],
      ["«Режим» — два коротких варианта", ftp.modeRu.n === 2 && ftp.modeRu.wide <= 0 &&
        ftp.modeRu.texts.every((x) => x && x.length <= 12)],
      ["выбран «пакет»", ftp.modeRu.value === "batch"],
      ["клик по варианту сохраняет значение", ftp.clicked.value === "per_file" &&
        ftp.saved && ftp.saved[0] === "ftp_mode" && ftp.saved[1] === "per_file"],
      ["«Режим» и его подсказки переводятся при смене языка",
        ftp.modeEn.texts.join("|") !== ftp.modeRu.texts.join("|") &&
        ftp.modeEn.texts.every(Boolean) && ftp.modeEn.tips.every(Boolean) &&
        ftp.modeEn.tips.join("|") !== ftp.modeRu.tips.join("|")],
      ["у FTPS/сертификата/PASV есть подсказки", ftp.hints.tls.length > 0 &&
        ftp.hints.tlsVerify.length > 0 && ftp.hints.pasv.length > 0],
      ["выгрузка: пиксельный переключатель без подписи",
        ftp.hints.activePixel && !ftp.hints.activeText &&
        ftp.hints.activeAria.length > 0 && ftp.hints.activeTip.length > 0],
      ["бокс подсказки тумблера обнимает переключатель, а не строку карточки",
        ftp.hints.activeBox[0] <= 48 && ftp.hints.activeBox[1] <= 28],
      ["тумблер рисуется: SVG-namespace и размеры фигур > 0",
        ftp.hints.pxNs === "http://www.w3.org/2000/svg" &&
        ftp.hints.pxKidsNs.length === 4 &&
        ftp.hints.pxKidsNs.every(function(n) { return n === "http://www.w3.org/2000/svg"; }) &&
        ftp.hints.trackRect[0] > 0 && ftp.hints.trackRect[1] > 0 &&
        ftp.hints.knobRect[0] > 0 && ftp.hints.knobRect[1] > 0],
      ["тумблер виден: цвета из темы, не прозрачные",
        /^rgba?\(/.test(ftp.hints.trackFill) && ftp.hints.trackFill !== "rgb(0, 0, 0)" &&
        ftp.hints.trackStroke !== "none" && ftp.hints.trackStroke !== "" &&
        /^rgba?\(/.test(ftp.hints.knobOff) && ftp.hints.knobOff !== "rgb(0, 0, 0)"],
      ["цвет выключенного ползунка и акцентной галочки различаются",
        ftp.hints.knobOn !== ftp.hints.knobOff && ftp.hints.checkOpacity === "1"],
      ["нет переполнения и обрезки подписей", ftp.on.overflowX <= 0 && !ftp.clipped.length],
    ];
    ftpChecks.forEach(([name, okFlag]) => { if (!okFlag) fail(name); });
    console.log(`  флажок выключен: ${ftp.off.visible} полей, карточек ${ftp.off.boxes}` +
      ` (подключение видно=${ftp.off.conn}); включён: ${ftp.on.visible} полей, карточек ${ftp.on.boxes}` +
      ` (подключение видно=${ftp.on.conn}, строк ${ftp.on.connRows}); ` +
      `снова выключен: ${ftp.back.visible} полей, карточек ${ftp.back.boxes}, перелив=${ftp.on.overflowX}px`);
    console.log(`  «Режим» ${ftp.modeRu.n} [${ftp.modeRu.texts.join(" | ")}] = "${ftp.modeRu.value}"` +
      ` -> en ${ftp.modeEn.n} [${ftp.modeEn.texts.join(" | ")}]` +
      ` -> клик "${ftp.clicked.value}" сохранено=${JSON.stringify(ftp.saved)}`);
    console.log(`  выгрузка: пиксельный=${ftp.hints.activePixel} подпись="${ftp.hints.activeText}" ` +
      `aria="${ftp.hints.activeAria}" подсказка=${ftp.hints.activeTip.length > 0} ` +
      `бокс=${ftp.hints.activeBox.join("x")}; ` +
      `svg-ns=${ftp.hints.pxNs === "http://www.w3.org/2000/svg" ? "ok" : "BAD"} ` +
      `дорожка=${ftp.hints.trackRect.join("x")} ползунок=${ftp.hints.knobRect.join("x")}; ` +
      `цвета: дорожка=${ftp.hints.trackFill}/${ftp.hints.trackStroke} ползунок ${ftp.hints.knobOff}->${ftp.hints.knobOn}` +
      ` галочка=${ftp.hints.checkOpacity}; ` +
      `подсказки: FTPS=${!!ftp.hints.tls.length} сертификат=${!!ftp.hints.tlsVerify.length} PASV=${!!ftp.hints.pasv.length}`);
    if (ftp.clipped.length) console.log(`        обрезано: ${ftp.clipped.join(", ")}`);
    // ползунок едет с шагами (transition .09s), поэтому конечный transform
    // читаем после завершения анимации, а не в том же тике
    const PX_RUN = `(function () {
      var flag = document.getElementById("ftp-active");
      var s = flag.parentElement.querySelector(".px");
      var knob = s.querySelector(".px-knob"), check = s.querySelector(".px-check");
      flag.checked = false; flag.dispatchEvent(new Event("change"));
      var before = getComputedStyle(knob).transform;
      flag.checked = true; flag.dispatchEvent(new Event("change"));
      return new Promise(function (done) {
        setTimeout(function () {
          done({before: before, after: getComputedStyle(knob).transform,
                opacity: getComputedStyle(check).opacity, checked: flag.checked,
                tip: flag.parentElement.getAttribute("data-tip") || ""});
        }, 260);
      });
    })()`;
    const pxMove = await evaluate(PX_RUN);
    const pxMoveOk = /20/.test(pxMove.after) && pxMove.before !== pxMove.after &&
      pxMove.checked === true && pxMove.opacity === "1";
    if (!pxMoveOk) fail("тумблер едет: transform добирается до translate(20px)");
    await evaluate('var f = document.getElementById("ftp-active"); f.checked = false; f.dispatchEvent(new Event("change")); true');
    console.log(`  тумблер: transform ${pxMove.before} -> ${pxMove.after} галочка=${pxMove.opacity}`);

    console.log("--- подсказки схемы ---");
    const hints = await evaluate(`(function () {
      switchSection("dl");
      var trans = document.getElementById("transcode");
      var transLabel = null;
      if (trans) {
        var labels = trans.parentElement.querySelectorAll("label[data-i18n]");
        for (var i = 0; i < labels.length; i++) {
          if (labels[i].htmlFor === "transcode") { transLabel = labels[i]; break; }
        }
      }
      var transNote = document.getElementById("transcode-note");
      // пустой контейнер не должен занимать место: когда доступны все
      // кодировщики, пояснение очищается и скрывается
      transAvailability = {ffmpeg: true, avail: ["libx265", "nvenc", "amf", "qsv"]};
      buildTranscodeOptions();
      var noteAllHidden = transNote ? transNote.hidden : null;
      var noteAllText = transNote ? transNote.textContent.trim() : "";
      transAvailability = {ffmpeg: true, avail: ["libx265", "nvenc"]};
      buildTranscodeOptions();
      switchSection("ui");
      var navItems = [].slice.call(document.querySelectorAll("#settings-nav .nav-item"));
      var gear = document.getElementById("settings-btn");
      var close = document.getElementById("settings-close");
      var browse = document.getElementById("browse");
      function tip(el) { return el ? el.getAttribute("data-tip") || "" : ""; }
      return {
        transcode: tip(trans),
        transLabelTip: tip(transLabel),
        transNoteHidden: transNote ? transNote.hidden : null,
        transNoteText: transNote ? transNote.textContent.trim() : "",
        transNoteAllHidden: noteAllHidden, transNoteAllText: noteAllText,
        navTips: navItems.map(tip),
        gearTip: tip(gear), gearAria: gear ? gear.getAttribute("aria-label") || "" : "",
        closeTip: tip(close), closeAria: close ? close.getAttribute("aria-label") || "" : "",
        browseTip: tip(browse), browseIcon: browse ? !!browse.querySelector(".ico") : false
      };
    })()`);
    const hintChecks = [
      ["«Перекодировка»: подсказка на поле, а не на подписи",
        hints.transcode.length > 0 && !hints.transLabelTip],
      ["пояснение под перекодировщиком: с текстом видно, пустое скрыто",
        hints.transNoteHidden === (hints.transNoteText.length === 0) &&
        hints.transNoteAllHidden === true && hints.transNoteAllText === ""],
      ["разделы без подсказок", hints.navTips.every((x) => !x)],
      ["шестерёнка без подсказки, имя для доступности есть",
        !hints.gearTip && hints.gearAria.length > 0],
      ["крестик без подсказки, имя для доступности есть",
        !hints.closeTip && hints.closeAria.length > 0],
      ["«Обзор…» без подсказки (текстовая кнопка)", !hints.browseTip && !hints.browseIcon],
    ];
    hintChecks.forEach(([name, okFlag]) => { if (!okFlag) fail(name); });
    console.log(`  перекодировка=${hints.transcode.length > 0 ? "есть" : "нет"}` +
      ` (подпись без подсказки=${!hints.transLabelTip}, пояснение скрыто=${hints.transNoteHidden}); ` +
      `разделы=${hints.navTips.filter(Boolean).length}; шестерёнка: подсказка=${!!hints.gearTip} aria="${hints.gearAria}"; ` +
      `крестик: подсказка=${!!hints.closeTip} aria="${hints.closeAria}"; «Обзор…»: подсказка=${!!hints.browseTip}`);

    console.log("--- контраст элементов ---");
    const contrast = await evaluate(CONTRAST);
    // палитра темы может быть любой, но границы слоёв должны читаться:
    // разница меньше 1.5% по относительной яркости - глаз уже не различает
    const contrastChecks = [
      ["карточка отличается от фона окна", contrast.bodyCard >= 0.015],
      ["блок отличается от карточки", contrast.cardBlock >= 0.015],
      ["поле отличается от блока", contrast.blockInput >= 0.015],
    ];
    contrastChecks.forEach(([name, okFlag]) => { if (!okFlag) fail(name); });
    console.log(`  окно/карточка=${contrast.bodyCard} карточка/блок=${contrast.cardBlock}` +
      ` блок/поле=${contrast.blockInput} (яркости окно ${contrast.bodyL}, карточка ${contrast.cardL},` +
      ` блок ${contrast.blockL}, поле ${contrast.inputL})`);

    console.log("--- автосохранение ---");
    const auto = await evaluate(AUTOSAVE);
    const destKey = auto.saved.filter(([k]) => k === "dest").length;
    const autoChecks = [
      ["числовое поле сохраняется по change", auto.saved.some(([k, v]) => k === "retries" && v === "77")],
      ["папка не пишется в settings.json", destKey === 0],
      ["папка уходит в Python через set_dest", auto.dest === "D:\\Videos"],
    ];
    autoChecks.forEach(([name, okFlag]) => { if (!okFlag) fail(name); });
    console.log(`  save_setting=${JSON.stringify(auto.saved)} set_dest="${auto.dest}"`);

    console.log("--- тема ---");
    const th = await evaluate(THEME_SWITCH);
    if (th.want && th.after === th.before) {
      fail(`палитра не сменилась (${th.before} -> ${th.after}, ждали ${th.want})`);
    }
    console.log(`  тема ${th.key}: --bg ${th.before} -> ${th.after}` +
      ` сохранено=${JSON.stringify(th.saved)}`);

    console.log("--- восстановление тем офлайн ---");
    const reseed = await evaluate(`(function () {
      document.getElementById("download-themes").click();
      return true;
    })()`);
    await sleep(500);
    const reseedOut = await evaluate(`(function () {
      var note = document.getElementById("themes-dl-note");
      return {busy: document.getElementById("download-themes").classList.contains("busy"),
              note: note.textContent, hidden: note.hidden};
    })()`);
    const reseedChecks = [
      ["кнопка вернулась из busy", reseedOut.busy === false],
      ["пояснение заполнено", !reseedOut.hidden && reseedOut.note.length > 0],
    ];
    reseedChecks.forEach(([name, okFlag]) => { if (!okFlag) fail(name); });
    console.log(`  пояснение="${reseedOut.note}" busy=${reseedOut.busy}`);

    console.log("--- журнал из одного poll ---");
    await evaluate('window.__probe.logs = ["[info] строка 1", "[error] строка 2"]; true');
    await sleep(700);
    const log = await evaluate('(function () { var t = document.getElementById("log");' +
      ' return {text: t.value, rows: t.rows, h: Math.round(t.getBoundingClientRect().height)}; })()');
    const logOk = /строка 1/.test(log.text) && /строка 2/.test(log.text);
    if (!logOk) fail(`журнал не пришёл в поле (${JSON.stringify(log.text)})`);
    console.log(`  строк в поле=${log.rows} высота=${log.h}px${logOk ? "" : "  <-- FAIL"}`);

    console.log("--- минимальный размер окна (780x560) ---");
    await send("Emulation.setDeviceMetricsOverride", { width: 780, height: 560, deviceScaleFactor: 0, mobile: false });
    await sleep(400);
    const narrow = await evaluate(`(function () {
      var out = {vw: window.innerWidth, bad: []};
      ["ui", "dl", "ftp"].forEach(function (name) {
        switchSection(name);
        var sec = document.getElementById("section-" + name);
        if (sec.scrollWidth - sec.clientWidth > 0) out.bad.push(name + ":" + (sec.scrollWidth - sec.clientWidth));
      });
      switchSection("ui");
      var nav = document.getElementById("settings-nav");
      out.navW = Math.round(nav.getBoundingClientRect().width);
      out.navOverflow = nav.scrollWidth - nav.clientWidth;
      out.items = [].slice.call(nav.querySelectorAll(".nav-item"))
        .filter(function (b) { return b.getBoundingClientRect().height > 10; }).length;
      out.secOverflow = document.getElementById("settings-sections").scrollWidth -
                        document.getElementById("settings-sections").clientWidth;
      var card = document.querySelector(".settings-card").getBoundingClientRect();
      out.fits = card.height <= window.innerHeight - 8 && card.width <= window.innerWidth - 8;
      return out;
    })()`);
    if (narrow.bad.length || narrow.navOverflow > 0 || narrow.secOverflow > 0) {
      fail(`перелив при ${narrow.vw}px: ${narrow.bad.join(", ")}`);
    }
    if (!narrow.fits) fail("карточка не помещается в окно 780x560");
    console.log(`  ${narrow.vw}px: список=${narrow.navW}px (пунктов видно ${narrow.items}) ` +
      `перелив=${narrow.secOverflow}px карточка_помещается=${narrow.fits}`);
    await send("Emulation.clearDeviceMetricsOverride");

    // ================= главное окно =================
    console.log("--- кнопка «Скачать» ---");
    let dlBad = 0;
    const dlTitles = await evaluate(`(function () {
      curLang = "ru"; applyI18n();
      return {idle: t("btn.download"), busy: t("btn.downloading"), done: t("btn.done"),
              partial: t("btn.partial"), warn: t("btn.warn"),
              failed: t("btn.failed"), cancelled: t("btn.cancelled")};
    })()`);
    const read = async () => await evaluate(DL_READ);
    // 700 мс: два тика (tick() ходит в poll каждые 200 мс) плюс запас на
    // анимацию итога (420 мс) - иначе геометрию меряем в перелёте
    const step = async (st, label) => {
      await evaluate(DL_SET(st));
      await sleep(700);
      const m = await read();
      console.log(`  ${label.padEnd(22)} класс="${m.cls}" ширина=${m.w}px ` +
        `заливка=${m.fillPct}/${m.fillW}px аним=[${m.fillAnim}|${m.sheenAnim}] ` +
        `значок=${m.iconOpacity}(${m.iconAnim}) текст=${m.labelOpacity} процент="${m.pct}" ` +
        `svg=${m.svg}/${m.shapes} кнопка_выкл=${m.dlDisabled} отмена_выкл=${m.stopDisabled}`);
      return m;
    };
    const idle = await step({busy: false, status: "Готов.", result: null,
      progress: {mode: "determinate", value: 0}}, "idle");
    const indet = await step({busy: true, status: "Качаю…", result: null,
      progress: {mode: "indeterminate"}}, "busy indeterminate");
    const det = await step({busy: true, status: "Качаю…", result: null,
      progress: {mode: "determinate", value: 42.4}}, "busy 42%");
    // 2-й файл плейлиста: yt-dlp отсчитывает процент от размера этого файла,
    // поэтому значение меньше 42 - заливка и число обязаны остаться на 42
    const back = await step({busy: true, status: "Качаю…", result: null,
      progress: {mode: "determinate", value: 11}}, "следующий файл 11%");
    // постобработка: процент неизвестен, но рекорд не должен пропадать
    const post = await step({busy: true, status: "Свожу дорожки…", result: null,
      progress: {mode: "indeterminate"}}, "свожу (неопр.)");
    const full = await step({busy: true, status: "Качаю…", result: null,
      progress: {mode: "determinate", value: 100}}, "готово 100%");
    const ok = await step({busy: false, status: "Готов.", result: "ok",
      progress: {mode: "determinate", value: 100}}, "итог ok");
    const err = await step({busy: false, status: "Готов.", result: "error",
      progress: {mode: "determinate", value: 100}}, "итог error");
    const warn = await step({busy: false, status: "Готов.", result: "warn",
      progress: {mode: "determinate", value: 100}}, "итог warn");
    const fail2 = await step({busy: false, status: "Не удалось скачать.", result: "failed",
      progress: {mode: "determinate", value: 100}}, "итог failed");
    const cancel = await step({busy: false, status: "Готов.", result: "cancelled",
      progress: {mode: "determinate", value: 100}}, "итог cancelled");
    // 2 с сброса: result из poll() остаётся прежним - иконка не должна мигать
    await evaluate(DL_SET({busy: false, status: "Готов.", result: "cancelled",
      progress: {mode: "determinate", value: 100}}));
    await sleep(2600);
    const after = await read();
    await sleep(700);
    const after2 = await read();
    console.log(`  ${"через 2.6 с".padEnd(22)} класс="${after.cls}" процент="${after.pct}" ` +
      `svg=${after.svg} имя="${after.aria}" native_title="${after.title}"` +
      `${after.cls.indexOf("dl-idle") > -1 ? "" : "  <-- FAIL"}`);
    if (after.cls.indexOf("dl-idle") === -1) dlBad++;
    if (after2.cls.indexOf("dl-idle") === -1) { console.log(`        через 3.3 с снова "${after2.cls}"  <-- FAIL (мигает)`); dlBad++; }

    const all = [idle, indet, det, back, post, full, ok, err, cancel, after];
    const widths = all.map((m) => m.w);
    const wMin = Math.min(...widths), wMax = Math.max(...widths);
    console.log(`  ширина кнопки ${wMin}..${wMax}px (разброс ${wMax - wMin}px)` +
      `${wMax - wMin <= 1 ? "" : "  <-- FAIL (прыгает)"}`);
    if (wMax - wMin > 1) dlBad++;
    // высота: подпись в потоке держит кнопку такой же, как соседняя «Отмена»
    const hMin = Math.min(...all.map((m) => m.h));
    const stopH = await evaluate(
      `Math.round(document.getElementById("stop").getBoundingClientRect().height)`);
    console.log(`  высота кнопки ${hMin}px, «Отмена» ${stopH}px` +
      `${hMin >= 28 ? "" : "  <-- FAIL (схлопнулась)"}`);
    if (hMin < 28) dlBad++;
    if (Math.abs(hMin - stopH) > 1) {
      console.log(`        высота «Скачать» ${hMin}px != «Отмена» ${stopH}px  <-- FAIL`);
      dlBad++;
    }

    const checks = [
      ["idle: нет иконки, заливка 0", idle.svg === 0 && idle.fillPct === "0%" && idle.pct === ""],
      ["idle: без подсказки и title, имя для доступности есть", !idle.tip &&
        idle.title === "" && idle.aria === dlTitles.idle],
      ["idle: кнопка активна", idle.dlDisabled === false && idle.stopDisabled === true],
      ["высота: подпись в потоке", all.every((m) => m.labelInFlow)],
      ["индикатор: класс + блик", /dl-busy/.test(indet.cls) && /dl-indeterminate/.test(indet.cls)],
      ["индикатор: многоточие, заливка не едет", indet.pct === "\u2026" &&
        indet.sheenAnim === "dl-sheen" && indet.fillAnim === "none" && indet.fillPct === "0%"],
      ["индикатор: заливка непрозрачна", det.fillBg !== "rgba(0, 0, 0, 0)" && indet.fillBg !== "rgba(0, 0, 0, 0)"],
      ["индикатор: кнопка выкл, отмена вкл", indet.dlDisabled === true && indet.stopDisabled === false],
      ["42%: округление и ширина заливки", det.pct === "42%" &&
        Math.abs(parseFloat(det.fillPct) - 42.4) < 0.05 && det.fillW > 0 &&
        Math.abs(det.fillW - Math.round(det.w * 0.424)) <= 2 && det.fillAnim === "none"],
      ["11% не откатывает 42%", back.pct === "42%" &&
        Math.abs(parseFloat(back.fillPct) - parseFloat(det.fillPct)) < 0.05 &&
        Math.abs(back.fillW - det.fillW) <= 2],
      ["свожу: остаётся 42% + блик", post.pct === "42%" &&
        Math.abs(parseFloat(post.fillPct) - parseFloat(det.fillPct)) < 0.05 &&
        /dl-indeterminate/.test(post.cls) && post.sheenAnim === "dl-sheen" &&
        Math.abs(post.fillW - det.fillW) <= 2],
      ["100% заливает кнопку", full.pct === "100%" && full.fillPct === "100%" &&
        Math.abs(full.fillW - full.w) <= 2],
      ["ok: лайк, анимация, подпись", ok.svg === 1 && /dl-ok/.test(ok.cls) &&
        ok.iconAnim === "dl-pop" && ok.iconOpacity === 1 && ok.labelOpacity === 0 &&
        !ok.tip && ok.aria === dlTitles.done && ok.fillPct === "0%"],
      ["error: восклицательный знак, «не всё»", err.svg === 1 && /dl-err/.test(err.cls) &&
        err.iconAnim === "dl-shake" && !err.tip && err.aria === dlTitles.partial],
      ["warn: тот же знак, своя подпись", warn.svg === 1 && /dl-warn/.test(warn.cls) &&
        warn.iconAnim === "dl-shake" && !warn.tip && warn.aria === dlTitles.warn && warn.shapes === err.shapes],
      ["failed: крест и выпячивание", fail2.svg === 1 && fail2.shapes === 2 &&
        /dl-fail/.test(fail2.cls) && fail2.iconAnim === "dl-bulge" &&
        !fail2.tip && fail2.aria === dlTitles.failed && fail2.iconOpacity === 1 && fail2.labelOpacity === 0],
      ["failed: другой цвет и знак, чем у «!»", fail2.color !== err.color && fail2.color !== idle.color],
      ["cancelled: знак стоп", cancel.svg === 1 && cancel.shapes >= 2 && /dl-cancel/.test(cancel.cls) &&
        cancel.iconAnim === "dl-pop" && !cancel.tip && cancel.aria === dlTitles.cancelled],
      ["иконка помещается в кнопку", ok.iconIn.ok && err.iconIn.ok && warn.iconIn.ok &&
        fail2.iconIn.ok && cancel.iconIn.ok ||
        `ok=${JSON.stringify(ok.iconIn)} err=${JSON.stringify(err.iconIn)} ` +
        `warn=${JSON.stringify(warn.iconIn)} fail=${JSON.stringify(fail2.iconIn)}`],
      ["итог перекрашивает кнопку", ok.color !== idle.color && err.color !== idle.color &&
        cancel.color !== idle.color && ok.color !== err.color && warn.color === err.color],
      ["сброс: текст вернулся", after.label === dlTitles.idle && after.pct === ""]
    ];
    checks.forEach(([name, okFlag]) => {
      if (!okFlag) { console.log(`        FAIL: ${name}`); dlBad++; }
    });

    // «Отмена» блокируется после нажатия и ждёт реального завершения
    await evaluate(`(function () {
      window.__probe.dlState = {busy: true, status: "Качаю…", result: null,
        progress: {mode: "determinate", value: 10}};
      return true;
    })()`);
    await sleep(500);
    const before = await read();
    await evaluate('document.getElementById("stop").click()');
    await sleep(300);
    const pressed = await read();
    await evaluate(DL_SET({busy: false, status: "Готов.", result: "cancelled",
      progress: {mode: "determinate", value: 100}}));
    await sleep(500);
    const done = await read();
    console.log(`  отмена: до=${before.stopDisabled} нажатие=${pressed.stopDisabled} ` +
      `после_завершения=${done.stopDisabled} итог="${done.aria}" svg=${done.svg}`);
    if (before.stopDisabled !== false || pressed.stopDisabled !== true || done.stopDisabled !== true) {
      console.log("        FAIL: «Отмена» активна только пока идёт загрузка");
      dlBad++;
    }
    if (done.svg !== 1 || done.aria !== dlTitles.cancelled) {
      console.log("        FAIL: после отмены ожидался знак стоп");
      dlBad++;
    }
    bad += dlBad;
    console.log(dlBad ? "FAIL: кнопка «Скачать» (см. строки выше)"
                      : "OK: кнопка «Скачать» отработала все состояния");

    if (errors.length) { console.error("ошибки страницы:", errors); bad++; }
    code = bad ? 1 : 0;
  } catch (e) {
    console.error("probe error:", e.message);
  } finally {
    edge.kill();
    // Edge держит профиль ещё секунду после kill - уборка не критична.
    await sleep(400);
    try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); }
    catch (e) { /* профиль удалит Cleaning OS */ }
  }
  process.exit(code);
})();
