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

// Что и как мерить внутри .theme-actions (три кнопки шрифтов).
const MEASURE = `(function () {
  var sheet = document.getElementById("settings-sheet");
  sheet.hidden = false;
  document.getElementById("settings-overlay").hidden = false;
  var rows = [].slice.call(document.querySelectorAll("#panel-ui .theme-actions"));
  var out = {rows: [], buttons: 0, labels: [], overflowX: 0};
  out.overflowX = sheet.scrollWidth - sheet.clientWidth;
  rows.forEach(function (row) {
    var r = row.getBoundingClientRect();
    out.rows.push({width: Math.round(r.width), scrollWidth: row.scrollWidth});
    [].slice.call(row.querySelectorAll("button")).forEach(function (b) {
      out.buttons++;
      var t = b.textContent.trim();
      out.labels.push({text: t, clipped: b.scrollWidth > b.clientWidth + 1,
                       h: Math.round(b.getBoundingClientRect().height)});
    });
  });
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
    // init() асинхронный: ждём, пока отрисуется список шрифтов
    for (let i = 0; i < 40; i++) {
      if (await evaluate('document.getElementById("font-sans").options.length > 0')) break;
      await sleep(100);
    }
    const seeded = await evaluate('[].slice.call(document.getElementById("font-sans").options).map(function(o){return o.value;}).filter(Boolean)');

    let bad = 0;
    console.log(`шрифты в списке: ${JSON.stringify(seeded)}`);
    for (const lang of LANGS) {
      const m = await evaluate(`(function () {
        curLang = ${JSON.stringify(lang)}; applyI18n(); return ${MEASURE};
      })()`);
      const dl = m.labels.find((l) => /download|ダウンロード|下载|Descargar|laden|качать/i.test(l.text)) ||
                 m.labels[m.buttons - 1];
      const clipped = m.labels.filter((l) => l.clipped);
      const over = m.overflowX > 0;
      if (over || clipped.length) bad++;
      console.log(`${lang.padEnd(6)} кнопок=${m.buttons} перелив=${m.overflowX}px ` +
        `обрезано=${clipped.length} dl="${dl.text}" h=${dl.h}`);
      m.labels.forEach((l) => { if (l.clipped) console.log(`        обрезана: "${l.text}"`); });
    }
    if (errors.length) { console.error("ошибки страницы:", errors); bad++; }


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
    code = bad ? 1 : 0;
    console.log(code ? "FAIL: есть переполнение/обрезанный текст/сбой растягивания"
                     : "OK: блок шрифтов влезает, панель тянется во всех языках");
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
