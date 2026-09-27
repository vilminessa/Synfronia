// Headless-проверка блока шрифтов и растягиваемой панели настроек:
// три кнопки в ряд не вылезают за .sheet, подписи переносятся,
// кнопка «Докачать шрифты» есть в 6 языках, ручка тянет ширину панели.
//
//   python tools\ui_probe_page.py %TEMP%\synf_probe_page.html
//   node tools\ui_fonts_probe.js %TEMP%\synf_probe_page.html
//
// Код возврата: 0 - всё влезает и панель тянется, 1 - есть проблемы.

const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PAGE = process.argv[2] || path.join(os.tmpdir(), "synf_probe_page.html");
const PORT = 9337;
const LANGS = ["ru", "en", "ja", "zh-CN", "es", "de"];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Что и как мерить в панели: вкладки переключаются по очереди, в каждой
// проверяем, что блок не вылезает по ширине и ни один control не обрезает текст.
// Панель рисуется из схемы (__SETTINGS_SCHEMA__), поэтому список вкладок берём
// из неё, а не из разметки.
const MEASURE = `(function () {
  var sheet = document.getElementById("settings-sheet");
  sheet.hidden = false;
  document.getElementById("settings-overlay").hidden = false;
  var out = {tabs: [], buttons: 0, labels: [], overflowX: 0, controls: 0, clipped: []};
  out.overflowX = sheet.scrollWidth - sheet.clientWidth;
  var names = SETTINGS_SCHEMA.groups.map(function (g) { return g.id; });
  names.forEach(function (name) {
    switchSettingsTab(name);
    var panel = document.getElementById("panel-" + name);
    var rec = {id: name, controls: 0, overflowX: panel.scrollWidth - panel.clientWidth, clipped: []};
    [].slice.call(panel.querySelectorAll("select, button")).forEach(function (el) {
      if (el.offsetParent === null) return;   // скрытое поле не мешает
      rec.controls++;
      if (el.scrollWidth > el.clientWidth + 1) rec.clipped.push(el.id || el.tagName);
    });
    out.controls += rec.controls;
    out.clipped = out.clipped.concat(rec.clipped);
    out.tabs.push(rec);
  });
  // кнопки шрифтов - предмет старой проверки (нужна активная вкладка «Интерфейс»)
  switchSettingsTab("ui");
  [].slice.call(document.querySelectorAll("#panel-ui .theme-actions")).forEach(function (row) {
    [].slice.call(row.querySelectorAll("button")).forEach(function (b) {
      out.buttons++;
      out.labels.push({text: b.textContent.trim(), clipped: b.scrollWidth > b.clientWidth + 1,
                       h: Math.round(b.getBoundingClientRect().height)});
    });
  });
  switchSettingsTab(names[0]);
  sheet.hidden = true;
  document.getElementById("settings-overlay").hidden = true;
  return out;
})()`;

// Растягивание панели: тянем левую кромку мышью, потом клавишами, проверяем,
// что ручка осталась на кромке панели и ширина подчиняется ожиданию.
const RESIZE = `(function () {
  var sheet = document.getElementById("settings-sheet");
  var handle = document.getElementById("sheet-resize");
  document.getElementById("settings-overlay").hidden = false;
  sheet.hidden = false;
  handle.hidden = false;
  syncSheetEdge();
  var out = {steps: []};
  function geom(tag) {
    var s = sheet.getBoundingClientRect(), h = handle.getBoundingClientRect();
    out.steps.push({tag: tag, w: Math.round(s.width), left: Math.round(s.left),
                    center: Math.round(h.left + h.width / 2), hit: Math.round(h.width),
                    gap: Math.round(Math.abs((h.left + h.width / 2) - s.left))});
  }
  function pe(type, x) {
    handle.dispatchEvent(new PointerEvent(type, {bubbles: true, clientX: x, clientY: 10,
      button: 0, buttons: 1, pointerId: 1, isPrimary: true, pointerType: "mouse"}));
  }
  function key(k) {
    handle.dispatchEvent(new KeyboardEvent("keydown", {key: k, bubbles: true, cancelable: true}));
  }
  geom("открытие");
  var x0 = Math.round(sheet.getBoundingClientRect().left);
  pe("pointerdown", x0); pe("pointermove", x0 - 120); pe("pointerup", x0 - 120);
  geom("перетаскивание-120");
  pe("pointerdown", x0 - 400); pe("pointermove", 10); pe("pointerup", 10);
  geom("перетаскивание-к-левому-краю");
  key("ArrowRight"); key("ArrowRight");
  geom("стрелка-вправо-x2");
  key("Home"); geom("Home-максимум");
  key("End"); geom("End-минимум");
  handle.dispatchEvent(new MouseEvent("dblclick", {bubbles: true}));
  geom("двойной-клик-сброс");
  // тема может отступовать панель от края окна (Liquid Glass: right/bottom 14px) —
  // ручка обязана остаться на кромке
  sheet.style.right = "14px"; applySheetW(400); geom("отступ-темы-14px");
  sheet.style.right = "";
  applySheetW(330);
  out.overflowX = sheet.scrollWidth - sheet.clientWidth;
  out.max = Math.max(260, Math.round(window.innerWidth * 0.92));
  out.min = 260;
  out.default = SHEET_DEFAULT;
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
    // init() асинхронный, а панель рисуется скриптом: ждём, пока отрисуется
    // список шрифтов (getElementById может ещё вернуть null - это не ошибка)
    const READY = '(function () { var el = document.getElementById("font-sans");' +
      ' return !!(el && el.options.length > 0); })()';
    for (let i = 0; i < 40; i++) {
      if (await evaluate(READY)) break;
      await sleep(100);
    }
    if (errors.length) console.error("ошибки при инициализации:", errors);
    if (!(await evaluate(READY))) throw new Error("панель настроек не отрисовалась (font-sans пуст)");
    const seeded = await evaluate('[].slice.call(document.getElementById("font-sans").options).map(function(o){return o.value;}).filter(Boolean)');

    let bad = 0;
    console.log(`шрифты в списке: ${JSON.stringify(seeded)}`);
    for (const lang of LANGS) {
      const m = await evaluate(`(function () {
        curLang = ${JSON.stringify(lang)}; applyI18n(); return ${MEASURE};
      })()`);
      const dl = m.labels.find((l) => /шрифт|font|Schrift|下载|ダウンロード|Descargar/i.test(l.text)) ||
                 m.labels[m.buttons - 1];
      const clipped = m.labels.filter((l) => l.clipped);
      const over = m.overflowX > 0 || m.tabs.some((t) => t.overflowX > 0) || m.clipped.length > 0;
      if (over || clipped.length) bad++;
      console.log(`${lang.padEnd(6)} кнопок=${m.buttons} полей=${m.controls} ` +
        `перелив=${m.overflowX}px вкладки=[${m.tabs.map((t) => `${t.id}:${t.overflowX}/${t.controls}`).join(" ")}] ` +
        `обрезано=${clipped.length + m.clipped.length} dl="${dl.text}" h=${dl.h}`);
      m.tabs.forEach((t) => {
        if (t.overflowX > 0) console.log(`        ${t.id}: вылезает на ${t.overflowX}px`);
      });
      m.clipped.forEach((c) => console.log(`        обрезан control: ${c}`));
      clipped.forEach((l) => console.log(`        обрезана кнопка: "${l.text}"`));
    }
    if (errors.length) { console.error("ошибки страницы:", errors); bad++; }

    // --- видимость по схеме: флажок «Выгружать на FTP» открывает блок полей ---
    const ftp = await evaluate(`(function () {
      var sheet = document.getElementById("settings-sheet");
      var flag = document.getElementById("ftp-active");
      sheet.hidden = false;
      document.getElementById("settings-overlay").hidden = false;
      switchSettingsTab("ftp");
      function count() {
        var panel = document.getElementById("panel-ftp");
        // .settings-box в списке намеренно: пустая рамка «Подключение» с
        // заголовком тоже видна пользователю и тоже считается мусором
        return {visible: [].slice.call(panel.querySelectorAll(
                 "input, select, button, label, .note, .settings-box, .settings-box-title"))
          .filter(function (el) { return el.offsetParent !== null; }).length,
          boxes: [].slice.call(panel.querySelectorAll(".settings-box"))
            .filter(function (el) { return el.offsetParent !== null; }).length,
          overflowX: panel.scrollWidth - panel.clientWidth};
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
      out.clipped = [].slice.call(document.querySelectorAll("#panel-ftp select, #panel-ftp button"))
        .filter(function (el) { return el.offsetParent !== null && el.scrollWidth > el.clientWidth + 1; })
        .map(function (el) { return el.id; });
      flag.checked = false;
      flag.dispatchEvent(new Event("change"));
      out.back = count();
      switchSettingsTab("ui");
      sheet.hidden = true;
      document.getElementById("settings-overlay").hidden = true;
      return out;
    })()`);
    console.log("--- вкладка FTP ---");
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
    console.log(`  флажок выключен: ${ftp.off.visible} полей, рамок ${ftp.off.boxes}; ` +
      `включён: ${ftp.on.visible} полей, рамок ${ftp.on.boxes}; ` +
      `снова выключен: ${ftp.back.visible} полей, рамок ${ftp.back.boxes}, перелив=${ftp.on.overflowX}px`);
    console.log(`  «Режим» ${ftp.modeRu.n} [${ftp.modeRu.texts.join(" | ")}] = "${ftp.modeRu.value}"` +
      ` -> en ${ftp.modeEn.n} [${ftp.modeEn.texts.join(" | ")}] = "${ftp.modeEn.value}"`);
    ftpChecks.forEach(([name, okFlag]) => {
      if (!okFlag) { console.log(`        FAIL: ${name}`); bad++; }
    });
    if (ftp.clipped.length) console.log(`        обрезано: ${ftp.clipped.join(", ")}`);

    // --- растягивание панели настроек ---
    const rz = await evaluate(RESIZE);
    console.log("--- панель настроек ---");
    let rzBad = 0;
    const w0 = rz.steps[0].w;
    // ожидания считаем от фактической стартовой ширины: тема может задать свою
    const expect = {
      "перетаскивание-120": w0 + 120,
      "перетаскивание-к-левому-краю": rz.max,
      "стрелка-вправо-x2": rz.max - 32,
      "Home-максимум": rz.max,
      "End-минимум": rz.min,
      "двойной-клик-сброс": rz.default,
      "отступ-темы-14px": 400
    };
    for (const s of rz.steps) {
      const want = expect[s.tag];
      const okW = want === undefined || Math.abs(s.w - want) <= 1;
      const okGap = s.gap <= 1 && s.hit >= 8;
      if (!okW || !okGap) rzBad++;
      console.log(`  ${s.tag.padEnd(28)} ширина=${s.w}px${want !== undefined ? ` (ожидалось ${want})` : ""} ` +
        `ручка=${s.hit}px расхождение_с_кромкой=${s.gap}px${okW && okGap ? "" : "  <-- FAIL"}`);
    }
    if (rz.overflowX > 0) { console.error(`  панель переполнена на ${rz.overflowX}px при ${rz.default}px`); rzBad++; }
    // окно сузили до 400px при панели 450px -> ширина должна подрезаться до 368 (92% от 400)
    await evaluate('applySheetW(450)');
    await send("Emulation.setDeviceMetricsOverride", { width: 400, height: 700, deviceScaleFactor: 0, mobile: false });
    await sleep(400);
    const narrow = await evaluate('(function () { return {w: Math.round(document.getElementById("settings-sheet").getBoundingClientRect().width), vw: window.innerWidth}; })()');
    const wantNarrow = Math.max(260, Math.round(narrow.vw * 0.92));
    const okNarrow = Math.abs(narrow.w - wantNarrow) <= 1;
    console.log(`  окно ${narrow.vw}px -> панель ${narrow.w}px (ожидалось ${wantNarrow})${okNarrow ? "" : "  <-- FAIL"}`);
    if (!okNarrow) rzBad++;
    await send("Emulation.clearDeviceMetricsOverride");
    // прячем панель обратно, чтобы не мешала остальным замерам
    await evaluate('[document.getElementById("settings-overlay"), document.getElementById("settings-sheet"), document.getElementById("sheet-resize")].forEach(function (el) { el.hidden = true; }); true');
    bad += rzBad;

    // --- кнопка «Скачать»: прогресс, SVG-итог, возврат в idle через 2 с ---
    console.log("--- кнопка «Скачать» ---");
    let dlBad = 0;
    const dlTitles = await evaluate(`(function () {
      curLang = "ru"; applyI18n();
      return {idle: t("btn.download"), busy: t("btn.downloading"), done: t("btn.done"),
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
      ["error: восклицательный знак", err.svg === 1 && /dl-err/.test(err.cls) &&
        err.iconAnim === "dl-shake" && err.title === dlTitles.failed],
      ["cancelled: знак стоп", cancel.svg === 1 && cancel.shapes >= 2 && /dl-cancel/.test(cancel.cls) &&
        cancel.iconAnim === "dl-pop" && cancel.title === dlTitles.cancelled],
      ["иконка помещается в кнопку", ok.iconIn.ok && err.iconIn.ok && cancel.iconIn.ok ||
        `ok=${JSON.stringify(ok.iconIn)} err=${JSON.stringify(err.iconIn)}`],
      ["итог перекрашивает кнопку", ok.color !== idle.color && err.color !== idle.color &&
        cancel.color !== idle.color && ok.color !== err.color],
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
    console.log(dlBad ? "FAIL: кнопка «Скачать» (см. строки выше)" : "OK: кнопка «Скачать» отработала все состояния");
    code = bad ? 1 : 0;
    console.log(code ? "FAIL: есть переполнение/обрезанный текст/сбой растягивания"
                     : "OK: блок шрифтов влезает, панель тянется во всех языках");  } catch (e) {
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
