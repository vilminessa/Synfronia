// Headless-проверка интерфейса Synfronia: окно настроек и главное окно.
//
// Окно настроек (--kind settings): список разделов слева, поля не вылезают,
// кнопки шрифтов влезают, флажок FTP открывает блок полей, значения
// сохраняются по событию change, папка уходит в Python через set_dest,
// журнал появляется из poll_settings, окно переживает минимальный размер.
//
// Главное окно (--kind main): кнопка «Скачать» во всех состояниях.
//
//   python tools\ui_probe_page.py
//   node tools\ui_fonts_probe.js
//   python tools\ui_probe_page.py --page settings
//   node tools\ui_fonts_probe.js %TEMP%\synf_probe_settings.html settings
//
// Код возврата: 0 - всё влезает и ведёт себя как ожидается, 1 - есть проблемы.

const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const KIND = process.argv[3] || "main";
const DEFAULT_PAGE = KIND === "settings" ? "synf_probe_settings.html" : "synf_probe_page.html";
const PAGE = process.argv[2] || path.join(os.tmpdir(), DEFAULT_PAGE);
const PORT = 9337;
const LANGS = ["ru", "en", "ja", "zh-CN", "es", "de"];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Что и как мерить в окне настроек: разделы переключаются по очереди, в каждом
// проверяем, что содержимое не вылезает по ширине и ни один control не обрезает
// текст. Поля рисуются из схемы (__SETTINGS_SCHEMA__), поэтому список разделов
// берём из неё, а не из разметки.
const WIN_MEASURE = `(function () {
  var host = document.getElementById("settings-sections");
  var nav = document.getElementById("settings-nav");
  var out = {sections: [], buttons: 0, controls: 0, labels: [], navLabels: [],
             overflowX: host.scrollWidth - host.clientWidth,
             navOverflowX: nav.scrollWidth - nav.clientWidth, clipped: []};
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
    [].slice.call(sec.querySelectorAll("select, button")).forEach(function (el) {
      if (el.offsetParent === null) return;   // скрытое поле не мешает
      rec.controls++;
      if (el.scrollWidth > el.clientWidth + 1) rec.clipped.push(el.id || el.tagName);
    });
    out.controls += rec.controls;
    out.clipped = out.clipped.concat(rec.clipped);
    out.sections.push(rec);
  });
  // кнопки шрифтов и тем - предмет старой проверки (нужен раздел «Интерфейс»)
  switchSection("ui");
  [].slice.call(document.querySelectorAll("#section-ui .theme-actions")).forEach(function (row) {
    [].slice.call(row.querySelectorAll("button")).forEach(function (b) {
      out.buttons++;
      out.labels.push({text: b.textContent.trim(), clipped: b.scrollWidth > b.clientWidth + 1,
                       h: Math.round(b.getBoundingClientRect().height)});
    });
  });
  switchSection(names[0]);
  return out;
})()`;

// Переключение разделов кликом по списку: активен ровно один, видим ровно он.
const NAV_CLICK = `(function () {
  document.getElementById("nav-dl").click();
  var out = {visible: [], active: []};
  SETTINGS_SCHEMA.groups.forEach(function (g) {
    if (!document.getElementById("section-" + g.id).hidden) out.visible.push(g.id);
    if (document.getElementById("nav-" + g.id).classList.contains("active")) out.active.push(g.id);
  });
  out.head = document.querySelector(".win-title").textContent.trim();
  out.closeW = Math.round(document.getElementById("settings-close").getBoundingClientRect().width);
  out.logH = Math.round(document.getElementById("log").getBoundingClientRect().height);
  out.logVisible = document.getElementById("log").offsetParent !== null;
  return out;
})()`;

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

// Тема: css-only тема применяется на лету, палитра окна едет вместе с ней.
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

// Видимость по схеме: флажок «Выгружать на FTP» открывает блок полей, а сам
// блок с заголовком убирается, когда скрыты все поля внутри.
const FTP_VIS = `(function () {
  switchSection("ftp");
  var flag = document.getElementById("ftp-active");
  function count() {
    var sec = document.getElementById("section-ftp");
    // .settings-box намеренно: пустая рамка «Подключение» с заголовком тоже
    // видна пользователю и тоже считается мусором
    return {visible: [].slice.call(sec.querySelectorAll(
              "input, select, button, label, .note, .settings-box, .settings-box-title"))
        .filter(function (el) { return el.offsetParent !== null; }).length,
        boxes: [].slice.call(sec.querySelectorAll(".settings-box"))
          .filter(function (el) { return el.offsetParent !== null; }).length,
        overflowX: sec.scrollWidth - sec.clientWidth};
  }
  function mode() {
    var s = document.getElementById("ftp-mode");
    return {n: s.options.length, texts: [].slice.call(s.options).map(function (o) { return o.textContent; }),
            value: s.value};
  }
  var out = {off: count()};
  flag.checked = true;
  flag.dispatchEvent(new Event("change"));
  out.on = count();
  out.modeRu = mode();
  // смена языка: подписи опций должны переехать вместе с интерфейсом
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
    title: b.title, aria: b.getAttribute("aria-label"),
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
    // init() асинхронный, а поля рисует скрипт. В окне настроек ждём
    // заполненный список шрифтов, в главном окне - саму кнопку «Скачать»
    // (её настройки больше не рисуются в нём).
    const READY = KIND === "settings"
      ? '(function () { var el = document.getElementById("font-sans");' +
        ' return !!(el && el.options.length > 0); })()'
      : '(function () { return !!(window.__initDone && document.getElementById("download")); })()';
    for (let i = 0; i < 40; i++) {
      if (await evaluate(READY)) break;
      await sleep(100);
    }
    if (errors.length) console.error("ошибки при инициализации:", errors);
    if (!(await evaluate(READY))) {
      throw new Error(KIND === "settings"
        ? "настройки не отрисовались (font-sans пуст)"
        : "главное окно не инициализировалось (нет кнопки «Скачать»)");
    }

    let bad = 0;
    if (KIND === "settings") {
      // ================= окно настроек =================
      const seeded = await evaluate('[].slice.call(document.getElementById("font-sans").options).map(function(o){return o.value;}).filter(Boolean)');
      console.log(`шрифты в списке: ${JSON.stringify(seeded)}`);

      console.log("--- разделы и поля ---");
      for (const lang of LANGS) {
        const m = await evaluate(`(function () {
          curLang = ${JSON.stringify(lang)}; applyI18n(); return ${WIN_MEASURE};
        })()`);
        const dl = m.labels.find((l) => /шрифт|font|Schrift|下载|フォント|Descargar/i.test(l.text)) ||
                   m.labels[m.buttons - 1];
        const clipped = m.labels.filter((l) => l.clipped);
        const over = m.overflowX > 0 || m.navOverflowX > 0 ||
                     m.sections.some((s) => s.overflowX > 0) || m.clipped.length > 0;
        if (over || clipped.length) bad++;
        console.log(`${lang.padEnd(6)} кнопок=${m.buttons} полей=${m.controls} ` +
          `перелив=${m.overflowX}px список=[${m.sections.map((s) => `${s.id}:${s.overflowX}/${s.controls}`).join(" ")}] ` +
          `обрезано=${clipped.length + m.clipped.length} разделы=[${m.navLabels.map((n) => n.text).join(" | ")}] ` +
          `dl="${dl.text}" h=${dl.h}`);
        m.sections.forEach((s) => {
          if (s.overflowX > 0) console.log(`        ${s.id}: вылезает на ${s.overflowX}px`);
        });
        m.clipped.forEach((c) => console.log(`        обрезан control: ${c}`));
        clipped.forEach((l) => console.log(`        обрезана кнопка: "${l.text}"`));
      }

      console.log("--- список разделов ---");
      const nav = await evaluate(NAV_CLICK);
      const navChecks = [
        ["клик по разделу открывает ровно его", nav.visible.length === 1 && nav.visible[0] === "dl"],
        ["активен ровно один пункт списка", nav.active.length === 1 && nav.active[0] === "dl"],
        ["в шапке есть заголовок", nav.head === "Загрузчик" || nav.head.length > 0],
        ["кнопка закрытия на месте", nav.closeW >= 24],
        ["полоса журнала видна", nav.logVisible && nav.logH >= 30],
      ];
      navChecks.forEach(([name, okFlag]) => {
        if (!okFlag) { console.log(`        FAIL: ${name}`); bad++; }
      });
      console.log(`  заголовок="${nav.head}" закрытие=${nav.closeW}px журнал=${nav.logH}px ` +
        `заголовки=[${nav.visible.join(",")}]`);

      console.log("--- раздел FTP ---");
      const ftp = await evaluate(FTP_VIS);
      const ftpChecks = [
        ["флажок открывает и снова закрывает поля", ftp.on.visible > ftp.off.visible &&
          ftp.back.visible === ftp.off.visible],
        ["выключенный флажок убирает рамку «Подключение»", ftp.off.boxes === 0 &&
          ftp.on.boxes === 1 && ftp.back.boxes === 0],
        ["«Режим» заполнен двумя вариантами", ftp.modeRu.n === 2 && ftp.modeEn.n === 2 &&
          ftp.modeRu.value === "batch" && ftp.modeRu.texts.every(Boolean)],
        ["«Режим» переводится при смене языка", ftp.modeEn.texts.every(Boolean) &&
          ftp.modeEn.texts.join("|") !== ftp.modeRu.texts.join("|")],
        ["нет переполнения и обрезки подписей", ftp.on.overflowX <= 0 && !ftp.clipped.length]
      ];
      ftpChecks.forEach(([name, okFlag]) => {
        if (!okFlag) { console.log(`        FAIL: ${name}`); bad++; }
      });
      console.log(`  флажок выключен: ${ftp.off.visible} полей, рамок ${ftp.off.boxes}; ` +
        `включён: ${ftp.on.visible} полей, рамок ${ftp.on.boxes}; ` +
        `снова выключен: ${ftp.back.visible} полей, рамок ${ftp.back.boxes}, перелив=${ftp.on.overflowX}px`);
      console.log(`  «Режим» ${ftp.modeRu.n} [${ftp.modeRu.texts.join(" | ")}] = "${ftp.modeRu.value}"` +
        ` -> en ${ftp.modeEn.n} [${ftp.modeEn.texts.join(" | ")}] = "${ftp.modeEn.value}"`);
      if (ftp.clipped.length) console.log(`        обрезано: ${ftp.clipped.join(", ")}`);

      console.log("--- автосохранение ---");
      const auto = await evaluate(AUTOSAVE);
      const destKey = auto.saved.filter(([k]) => k === "dest").length;
      const autoChecks = [
        ["числовое поле сохраняется по change", auto.saved.some(([k, v]) => k === "retries" && v === "77")],
        ["папка не пишется в settings.json", destKey === 0],
        ["папка уходит в Python через set_dest", auto.dest === "D:\\Videos"],
      ];
      autoChecks.forEach(([name, okFlag]) => {
        if (!okFlag) { console.log(`        FAIL: ${name}`); bad++; }
      });
      console.log(`  save_setting=${JSON.stringify(auto.saved)} set_dest="${auto.dest}"`);

      console.log("--- тема ---");
      const th = await evaluate(THEME_SWITCH);
      const themeOk = th.want ? th.after !== th.before : true;
      if (!themeOk) { console.log(`        FAIL: палитра не сменилась (${th.before} -> ${th.after}, ждали ${th.want})`); bad++; }
      console.log(`  тема ${th.key}: --bg ${th.before} -> ${th.after}` +
        `${themeOk ? "" : "  <-- FAIL"} сохранено=${JSON.stringify(th.saved)}`);

      console.log("--- журнал из poll_settings ---");
      await evaluate('window.__probe.logs = ["[info] строка 1", "[error] строка 2"]; true');
      await sleep(700);
      const log = await evaluate('(function () { var t = document.getElementById("log");' +
        ' return {text: t.value, rows: t.rows, h: Math.round(t.getBoundingClientRect().height)}; })()');
      const logOk = /строка 1/.test(log.text) && /строка 2/.test(log.text);
      if (!logOk) { console.log(`        FAIL: журнал не пришёл в поле (${JSON.stringify(log.text)})`); bad++; }
      console.log(`  строк в поле=${log.rows} высота=${log.h}px${logOk ? "" : "  <-- FAIL"}`);

      console.log("--- минимальный размер окна (720x520) ---");
      await send("Emulation.setDeviceMetricsOverride", { width: 720, height: 520, deviceScaleFactor: 0, mobile: false });
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
        return out;
      })()`);
      const narrowOk = narrow.bad.length === 0 && narrow.navOverflow <= 0 && narrow.secOverflow <= 0;
      if (!narrowOk) { console.log(`        FAIL: перелив при ${narrow.vw}px: ${narrow.bad.join(", ")}`); bad++; }
      console.log(`  ${narrow.vw}px: список=${narrow.navW}px (пунктов видно ${narrow.items}) ` +
        `перелив=${narrow.secOverflow}px${narrowOk ? "" : "  <-- FAIL"}`);
      await send("Emulation.clearDeviceMetricsOverride");
      if (errors.length) { console.error("ошибки страницы:", errors); bad++; }
      console.log(bad ? "FAIL: окно настроек (см. строки выше)"
                       : "OK: окно настроек влезает и работает во всех языках");
    } else {
      // ================= главное окно =================
      console.log("--- оверлей окна настроек ---");
      const readBlocked = `(function () {
        var veil = document.getElementById("settings-block");
        var kids = [].slice.call(document.body.children).filter(function (n) { return n !== veil; });
        // фокус не должен уезжать под оверлей: ни inert, ни disabled
        var input = document.getElementById("url-video");
        input.focus();
        var covers = veil ? (function () {
          var r = veil.getBoundingClientRect();
          return Math.round(r.width) >= window.innerWidth - 1 && Math.round(r.height) >= window.innerHeight - 1;
        })() : null;
        input.blur();
        return {veil: veil ? !veil.hidden : null, covers: covers,
                inert: kids.every(function (n) { return !!n.inert; }),
                disabled: ["tab-video", "url-video", "download", "settings-btn"]
                  .filter(function (id) { return document.getElementById(id).disabled; }),
                focusedBehind: document.activeElement === input};
      })()`;
      const ovBefore = await evaluate(readBlocked);
      await evaluate('document.getElementById("settings-btn").click(); true');
      await sleep(500);
      const ovDuring = await evaluate(readBlocked);
      // окно закрыли (крестиком ОС или из окна) - poll() должен снять блокировку
      await evaluate('window.__probe.settingsOpen = false; true');
      await sleep(600);
      const ovAfter = await evaluate(readBlocked);
      const ovChecks = [
        ["оверлей скрыт, пока окно настроек не открыто", ovBefore.veil === false && !ovBefore.inert],
        ["оверлей показан и закрывает окно", ovDuring.veil === true && ovDuring.covers === true],
        ["пока открыто - поля под оверлеем заблокированы",
          ovDuring.inert || ovDuring.disabled.length >= 3],
        ["после закрытия окна всё разблокировано", ovAfter.veil === false &&
          !ovAfter.inert && !ovAfter.disabled.length],
      ];
      ovChecks.forEach(([name, okFlag]) => {
        if (!okFlag) { console.log(`        FAIL: ${name}`); bad++; }
      });
      const lock = (m) => (m.inert ? "inert" : "выкл=" + m.disabled.length);
      console.log(`  до: оверлей=${ovBefore.veil} ${lock(ovBefore)} фокус_под_оверлеем=${ovBefore.focusedBehind}` +
        ` | открыто: оверлей=${ovDuring.veil} на всё окно=${ovDuring.covers} ${lock(ovDuring)} ` +
        `фокус_под_оверлеем=${ovDuring.focusedBehind}` +
        ` | закрыто: оверлей=${ovAfter.veil} ${lock(ovAfter)}`);

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
      const fail = await step({busy: false, status: "Не удалось скачать.", result: "failed",
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
        `svg=${after.svg} заголовок="${after.title}"` +
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
        ["idle: заголовок «Скачать»", idle.title === dlTitles.idle && idle.aria === dlTitles.idle],
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
          ok.title === dlTitles.done && ok.fillPct === "0%"],
        ["error: восклицательный знак, «не всё»", err.svg === 1 && /dl-err/.test(err.cls) &&
          err.iconAnim === "dl-shake" && err.title === dlTitles.partial],
        ["warn: тот же знак, своя подпись", warn.svg === 1 && /dl-warn/.test(warn.cls) &&
          warn.iconAnim === "dl-shake" && warn.title === dlTitles.warn && warn.shapes === err.shapes],
        ["failed: крест и выпячивание", fail.svg === 1 && fail.shapes === 2 &&
          /dl-fail/.test(fail.cls) && fail.iconAnim === "dl-bulge" &&
          fail.title === dlTitles.failed && fail.iconOpacity === 1 && fail.labelOpacity === 0],
        ["failed: другой цвет и знак, чем у «!»", fail.color !== err.color && fail.color !== idle.color],
        ["cancelled: знак стоп", cancel.svg === 1 && cancel.shapes >= 2 && /dl-cancel/.test(cancel.cls) &&
          cancel.iconAnim === "dl-pop" && cancel.title === dlTitles.cancelled],
        ["иконка помещается в кнопку", ok.iconIn.ok && err.iconIn.ok && warn.iconIn.ok &&
          fail.iconIn.ok && cancel.iconIn.ok ||
          `ok=${JSON.stringify(ok.iconIn)} err=${JSON.stringify(err.iconIn)} ` +
          `warn=${JSON.stringify(warn.iconIn)} fail=${JSON.stringify(fail.iconIn)}`],
        ["итог перекрашивает кнопку", ok.color !== idle.color && err.color !== idle.color &&
          cancel.color !== idle.color && ok.color !== err.color && warn.color === err.color],
        ["сброс: текст вернулся", after.label === dlTitles.idle && after.pct === ""]
      ];
      checks.forEach(([name, okFlag]) => {
        if (!okFlag) { console.log(`        FAIL: ${name}`); dlBad++; }
      });

      // «Отмена» блокируется после нажатия и ждёт реального завершения
      const stopFlow = await evaluate(`(function () {
        var stop = document.getElementById("stop");
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
        `после_завершения=${done.stopDisabled} итог="${done.title}" svg=${done.svg}`);
      if (before.stopDisabled !== false || pressed.stopDisabled !== true || done.stopDisabled !== true) {
        console.log("        FAIL: «Отмена» активна только пока идёт загрузка");
        dlBad++;
      }
      if (done.svg !== 1 || done.title !== dlTitles.cancelled) {
        console.log("        FAIL: после отмены ожидался знак стоп");
        dlBad++;
      }
      if (stopFlow !== true) dlBad++;
      bad += dlBad;
      console.log(dlBad ? "FAIL: кнопка «Скачать» (см. строки выше)"
                        : "OK: кнопка «Скачать» отработала все состояния");
    }
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
