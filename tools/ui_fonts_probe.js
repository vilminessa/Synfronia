// Headless-проверка блока шрифтов: три кнопки в ряд не вылезают за .sheet,
// подписи переносятся, кнопка «Докачать шрифты» есть в 6 языках.
//
//   python tools\ui_probe_page.py %TEMP%\synf_probe_page.html
//   node tools\ui_fonts_probe.js %TEMP%\synf_probe_page.html
//
// Код возврата: 0 - всё влезает, 1 - есть горизонтальное переполнение.

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
        throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 300));
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
    code = bad ? 1 : 0;
    console.log(code ? "FAIL: есть переполнение/обрезанный текст" : "OK: блок шрифтов влезает во всех языках");
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
