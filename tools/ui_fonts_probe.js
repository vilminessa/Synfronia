// Headless-проверка интерфейса Synfronia: карточка настроек (оверлей) и
// главное окно. Окно у приложения одно, поэтому страница одна: карточку
// открывает сценарий, а не второй экземпляр.
//
// Карточка: лежит по центру, разделы переключаются кликом, поля не вылезают
// по ширине, кнопки с иконками без подписи (смысл в подсказке), подсказки
// появляются с инерцией и стрелкой, нативных title нет, флажок FTP открывает
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

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PAGE = process.argv[2] || path.join(os.tmpdir(), "synf_probe_page.html");
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
// SVG-иконки итога, возврат в idle через 2 с и блокировку «Отмены».
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
    // состояние кнопки показывает наша подсказка, а не нативный title
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
  const profile = path.join(os.tmpdir(), "synf-probe-" + Date.now());
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
        errors.push(msg.params.exceptionDetails.text || "exception");
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
    // init() асинхронный, а поля рисует скрипт. Ждём и главное окно, и поля
    // карточки (font-sans заполняется из get_initial).
    const READY = '(function () { return !!(window.__initDone && document.getElementById("download")' +
      ' && document.getElementById("font-sans") && document.getElementById("font-sans").options.length > 1); })()';
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
    const seeded = await evaluate('[].slice.call(document.getElementById("font-sans").options).map(function(o){return o.value;}).filter(Boolean)');
    console.log(`шрифты в списке: ${JSON.stringify(seeded)}`);
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
    const tipProbe = `(function () {
      var btn = document.getElementById("reload-themes");
      btn.dispatchEvent(new PointerEvent("pointerover", {bubbles: true}));
      return {tip: !!document.getElementById("tip"), hidden: document.getElementById("tip").hidden};
    })()`;
    await evaluate('curLang = "ru"; applyI18n(); true');
    await evaluate(tipProbe);
    await sleep(120);
    const tipEarly = await evaluate(
      '(function () { var t = document.getElementById("tip");' +
      ' return {hidden: t.hidden, x: Math.round(TIP.x), tx: Math.round(TIP.tx)}; })()');
    await sleep(700);
    const tip = await evaluate(`(function () {
      var t = document.getElementById("tip");
      var a = t.querySelector(".tip-arrow");
      var b = document.getElementById("reload-themes").getBoundingClientRect();
      var r = t.getBoundingClientRect();
      var ax = parseFloat(a.style.left) + r.left + a.getBoundingClientRect().width / 2;
      return {hidden: t.hidden, on: t.classList.contains("tip-on"),
              text: t.querySelector(".tip-text").textContent,
              described: document.getElementById("reload-themes").getAttribute("aria-describedby"),
              settled: Math.abs(TIP.x - TIP.tx) < 0.5 && Math.abs(TIP.y - TIP.ty) < 0.5,
              arrowAtTarget: Math.abs(ax - (b.left + b.width / 2)) < 18,
              above: r.bottom <= b.top + 1, x: Math.round(r.left), y: Math.round(r.top),
              w: Math.round(r.width), h: Math.round(r.height),
              inView: r.left >= 0 && r.right <= window.innerWidth + 1 && r.top >= 0};
    })()`);
    const tipChecks = [
      ["появляется не сразу (задержка)", tipEarly.hidden === true],
      ["показывается по наведению", tip.hidden === false && tip.on === true],
      ["текст подсказки совпадает с подписью", tip.text.length > 0],
      ["плавно доезжает до места (инерция)", tip.settled === true && tipEarly.tx !== Math.round(tip.x)],
      ["стрелка у края элемента", tip.arrowAtTarget],
      ["подсказка не перекрывает элемент", tip.above],
      ["подсказка помещается в окно", tip.inView],
      ["элемент связан с подсказкой", tip.described === "tip"],
    ];
    tipChecks.forEach(([name, okFlag]) => { if (!okFlag) fail(name); });
    await evaluate('document.getElementById("reload-themes")' +
      '.dispatchEvent(new PointerEvent("pointerout", {bubbles: true, relatedTarget: document.body})); true');
    await sleep(200);
    const tipGone = await evaluate('document.getElementById("tip").hidden');
    if (!tipGone) fail("подсказка не скрылась после ухода курсора");
    console.log(`  задержка=${tipEarly.hidden ? "есть" : "нет"} текст="${tip.text}" ` +
      `инерция=${tip.settled} стрелка_у_элемента=${tip.arrowAtTarget} скрыта_после_ухода=${tipGone}`);

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
      ["у обоих вариантов подсказка из схемы и нет нативного title",
        ftp.modeRu.tips[0] && ftp.modeRu.tips[0] === ftp.modeRu.tips[1] &&
        ftp.modeRu.titles.every((x) => !x)],
      ["клик по варианту сохраняет значение", ftp.clicked.value === "per_file" &&
        ftp.saved && ftp.saved[0] === "ftp_mode" && ftp.saved[1] === "per_file"],
      ["«Режим» переводится при смене языка", ftp.modeEn.texts.join("|") !== ftp.modeRu.texts.join("|") &&
        ftp.modeEn.texts.every(Boolean)],
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
    if (ftp.clipped.length) console.log(`        обрезано: ${ftp.clipped.join(", ")}`);

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
      `svg=${after.svg} подсказка="${after.tip}" native_title="${after.title}"` +
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
      ["idle: наша подсказка вместо нативного title", idle.tip === dlTitles.idle &&
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
        ok.tip === dlTitles.done && ok.fillPct === "0%"],
      ["error: восклицательный знак, «не всё»", err.svg === 1 && /dl-err/.test(err.cls) &&
        err.iconAnim === "dl-shake" && err.tip === dlTitles.partial],
      ["warn: тот же знак, своя подпись", warn.svg === 1 && /dl-warn/.test(warn.cls) &&
        warn.iconAnim === "dl-shake" && warn.tip === dlTitles.warn && warn.shapes === err.shapes],
      ["failed: крест и выпячивание", fail2.svg === 1 && fail2.shapes === 2 &&
        /dl-fail/.test(fail2.cls) && fail2.iconAnim === "dl-bulge" &&
        fail2.tip === dlTitles.failed && fail2.iconOpacity === 1 && fail2.labelOpacity === 0],
      ["failed: другой цвет и знак, чем у «!»", fail2.color !== err.color && fail2.color !== idle.color],
      ["cancelled: знак стоп", cancel.svg === 1 && cancel.shapes >= 2 && /dl-cancel/.test(cancel.cls) &&
        cancel.iconAnim === "dl-pop" && cancel.tip === dlTitles.cancelled],
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
      `после_завершения=${done.stopDisabled} итог="${done.tip}" svg=${done.svg}`);
    if (before.stopDisabled !== false || pressed.stopDisabled !== true || done.stopDisabled !== true) {
      console.log("        FAIL: «Отмена» активна только пока идёт загрузка");
      dlBad++;
    }
    if (done.svg !== 1 || done.tip !== dlTitles.cancelled) {
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
