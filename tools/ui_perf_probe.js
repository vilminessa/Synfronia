// Headless-чек производительности Synfronia: «покой» и композитор.
//
// Зачем: этап 0 большой переработки (Alpine + Motion) требует baseline - с
// какими затратами страница живёт сейчас, чтобы потом сравнивать. Чек меряет
// то, что реально важно для WebView2-окна:
//
//   * ПОКОЙ (10 с без действий): LayoutDuration/RecalcStyleDuration должны
//     быть почти нулевыми (иначе что-то постоянно перестраивается), а
//     ScriptDuration показывает цену текущего poll (сейчас интервал 200 мс =
//     ~5 пробуждений в секунду; порог «<= 1/с» включается в Этапе 5,
//     когда опрос превратится в heartbeat - здесь он только печатается);
//   * АНИМАЦИЯ (3.6 с WAAPI-transform на кнопке): пока она идёт, счётчики
//     LayoutCount/LayoutDuration не должны расти - это и есть прокси «анимация
//     живёт на композиторе» (чистый GPU-трек чек не видит - он в DevTools);
//   * память/CPU печатаются в каждый снапшот (JSHeapUsedSize, TaskDuration)
//     как baseline.
//
// Ограничения: Edge headless с --disable-gpu (как и ui_fonts_probe), поэтому
// цифры сравнимы только сам с собой; чек ловит регрессии компоновки и цены
// опроса, а не GPU-производительность.
//
//   python tools\ui_probe_page.py
//   node tools\ui_perf_probe.js
//
// Код выхода: 0 - все проверки прошли, 1 - есть провалы.

const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

// Тот же браузер, что у ui_fonts_probe (на раздельной Windows-установке -
// на CI всегда есть один из вариантов).
const EDGE_CANDIDATES = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge Dev\\Application\\msedge.exe",
];
const EDGE = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
if (!EDGE) {
  console.error("msedge.exe не найден, кандидаты:\n  " + EDGE_CANDIDATES.join("\n  "));
  process.exit(1);
}
const PROBE_DIR = path.join(process.env.LOCALAPPDATA, "Synfronia", "probe");
const PAGE = process.argv[2] || path.join(PROBE_DIR, "page.html");
const PORT = 9338;   // у ui_fonts_probe 9337 - чеки могут идти параллельно
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
  const profile = path.join(PROBE_DIR, "profiles", "perf-" + Date.now());
  fs.mkdirSync(profile, { recursive: true });
  const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run",
    "--no-default-browser-check", "--hide-scrollbars", `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
  let bad = 0;
  const fail = (msg) => { console.log(`        FAIL: ${msg}`); bad++; };
  try {
    const wsUrl = await waitForPage();
    const ws = new WebSocket(wsUrl);
    let id = 0;
    const pending = new Map();
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
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
    await send("Performance.enable");
    await send("Page.navigate", { url: "file:///" + path.resolve(PAGE).replace(/\\/g, "/") });
    await send("Emulation.setEmulatedMedia", {
      features: [{ name: "prefers-reduced-motion", value: "no-preference" }],
    });
    const READY = '(function () { return !!(window.__initDone && document.getElementById("download")); })()';
    for (let i = 0; i < 60; i++) {
      if (await evaluate(READY)) break;
      await sleep(100);
    }
    if (!(await evaluate(READY))) throw new Error("страница не инициализировалась");

    // счётчик пробуждений: оборачиваем штатный poll (app.js зовёт его как
    // свойство объекта, поэтому перехват ловит каждый тик)
    await evaluate(`(function () {
      window.__perfPoll = 0;
      var orig = window.pywebview.api.poll;
      window.pywebview.api.poll = function () {
        window.__perfPoll++;
        return orig.apply(this, arguments);
      };
      return true;
    })()`);
    await sleep(1500);   // даём первым тикам и шрифтам успокоиться

    const metricsOf = async () => {
      const r = await send("Performance.getMetrics");
      const m = {};
      (r.result.metrics || []).forEach((x) => { m[x.name] = x.value; });
      return m;
    };
    const delta = (a, b) => ({
      LayoutCount: (b.LayoutCount || 0) - (a.LayoutCount || 0),
      RecalcStyleCount: (b.RecalcStyleCount || 0) - (a.RecalcStyleCount || 0),
      LayoutDuration: Math.round(((b.LayoutDuration || 0) - (a.LayoutDuration || 0)) * 1000) / 1000,
      RecalcStyleDuration: Math.round(((b.RecalcStyleDuration || 0) - (a.RecalcStyleDuration || 0)) * 1000) / 1000,
      ScriptDuration: Math.round(((b.ScriptDuration || 0) - (a.ScriptDuration || 0)) * 1000) / 1000,
      TaskDuration: Math.round(((b.TaskDuration || 0) - (a.TaskDuration || 0)) * 1000) / 1000,
      JSHeapUsedSize: Math.round(((b.JSHeapUsedSize || 0) - (a.JSHeapUsedSize || 0)) / 1048576 * 100) / 100,
    });

    // ---- фаза 1: покой 10 с ----
    console.log("--- фаза 1: покой (10 с) ---");
    const pollsBefore = await evaluate("window.__perfPoll");
    const t0 = Date.now();
    const a = await metricsOf();
    await sleep(10000);
    const b = await metricsOf();
    const idleSecs = (Date.now() - t0) / 1000;
    const pollsAfter = await evaluate("window.__perfPoll");
    const idle = delta(a, b);
    const pollRate = Math.round(((pollsAfter - pollsBefore) / idleSecs) * 100) / 100;
    console.log(`  layout=${idle.LayoutDuration}с/${idle.LayoutCount}шт ` +
      `recalc=${idle.RecalcStyleDuration}с/${idle.RecalcStyleCount}шт ` +
      `script=${idle.ScriptDuration}с task=${idle.TaskDuration}с ` +
      `heap+${idle.JSHeapUsedSize}МБ poll=${pollRate}/с`);
    // пороги с запасом (~x3 к ожидаемому): ловят «что-то постоянно перестраи-
    // вается/крутится», но не мешают медленным CI-машинам
    if (idle.LayoutCount > 5) {
      fail(`покой: LayoutCount ${idle.LayoutCount} > 5`);
      // диагностика виновника: что прямо сейчас анимировано и видимо
      const anims = await evaluate(`(function () {
        if (!document.getAnimations) return ["getAnimations недоступен"];
        return document.getAnimations().slice(0, 40).map(function (a) {
          var t = a.effect && a.effect.target;
          if (!t) return "без цели";
          var r = t.getBoundingClientRect();
          var cs = getComputedStyle(t);
          return (t.tagName + "." + String(t.className || "").split(" ").slice(0, 2).join("."))
            + " | name=" + (a.animationName || a.constructor.name)
            + " dur=" + (a.effect.getTiming() || {}).duration
            + " visible=" + (r.width > 0 && r.height > 0 && cs.display !== "none"
                             && cs.visibility !== "hidden");
        });
      })()`) || [];
      console.log("  активных анимаций: " + anims.length);
      anims.forEach((s) => console.log("    * " + s));
    }
    if (idle.LayoutDuration > 0.15) fail(`покой: LayoutDuration ${idle.LayoutDuration}с > 0.15с`);
    if (idle.RecalcStyleDuration > 1.0) fail(`покой: RecalcStyleDuration ${idle.RecalcStyleDuration}с > 1.0с`);
    if (idle.ScriptDuration > 2.5) fail(`покой: ScriptDuration ${idle.ScriptDuration}с > 2.5с`);
    if (pollRate < 0.5) fail(`покой: опрос почти встал (${pollRate}/с)`);
    if (pollRate > 6.5) fail(`покой: опрос чаще штатных 200 мс (${pollRate}/с)`);
    // NB: критерий «пробуждений <= 1/с» включается в Этапе 5 (heartbeat),
    // сейчас при poll 200 мс он физически недостижим - значение печатается.

    // ---- фаза 2: анимация 3.6 с не должна трогать layout ----
    console.log("--- фаза 2: анимация transform (3.6 с) ---");
    const c = await metricsOf();
    await evaluate(`(function () {
      var btn = document.getElementById("download");
      window.__perfAnim = btn.animate(
        [{ transform: "translateY(0px)" }, { transform: "translateY(-8px)" }],
        { duration: 1200, iterations: 3, direction: "alternate", easing: "ease-in-out" });
      return true;
    })()`);
    await sleep(3700);
    const d = await metricsOf();
    await evaluate("window.__perfAnim && window.__perfAnim.cancel(); true");
    const anim = delta(c, d);
    console.log(`  layout=${anim.LayoutDuration}с/${anim.LayoutCount}шт ` +
      `recalc=${anim.RecalcStyleDuration}с/${anim.RecalcStyleCount}шт ` +
      `script=${anim.ScriptDuration}с heap+${anim.JSHeapUsedSize}МБ`);
    // transform-анимация идёт через композитор: layout работать не должен
    if (anim.LayoutCount > 2) fail(`анимация: LayoutCount ${anim.LayoutCount} > 2 - анимация не на композиторе`);
    if (anim.LayoutDuration > 0.05) fail(`анимация: LayoutDuration ${anim.LayoutDuration}с > 0.05с`);

    console.log(bad ? `итог: провалено ${bad}` : "итог: OK (baseline зафиксирован)");
  } finally {
    try { edge.kill(); } catch (e) { /* уже убит */ }
  }
  process.exit(bad ? 1 : 0);
})().catch((e) => {
  console.error("ошибка:", e.message);
  process.exit(1);
});
