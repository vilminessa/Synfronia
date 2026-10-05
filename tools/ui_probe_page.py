r"""Собирает страницу Synfronia со стабом pywebview для headless-проверок вёрстки.

Зачем: app.js и settings.js живут внутри <script> и сразу дёргают pywebview.api,
поэтому для проверки разметки нужен настоящий DOM + заглушка API. Стаб
подставляется перед первым <script>, дальше страницу открывает tools/ui_*.js
через CDP. Проверяется одна страница: окно у приложения одно, а карточка
настроек лежит в ней оверлеем, поэтому сценарий открывает её сам (--settings
или клик по шестерёнке).

    python tools/ui_probe_page.py     -> %LOCALAPPDATA%\Synfronia\probe\page.html
    python tools/ui_probe_page.py out.html             -> свой путь
    python tools/ui_probe_page.py --settings           -> карточка настроек открыта
    python tools/ui_probe_page.py --theme liquid_glass --lang de
"""

import json
import sys
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import settings_schema  # noqa: E402
import i18n  # noqa: E402
from paths import logs_dir  # noqa: E402
from themes import build_page  # noqa: E402

# Страница пробника - в %LOCALAPPDATA%\Synfronia\probe: в %TEMP% ничего не пишем.
PROBE_DIR = logs_dir().parent / "probe"

# Настройки в стабе берём из схемы: так пробник проверяет настоящие умолчания,
# а не отдельный список (он уже расходился с приложением).
def stub_settings(lang: str, theme: str = "scarred_mind") -> str:
    # тему тоже отдаём: applyTheme при старте красит :root по settings.theme,
    # и без неё ВСЕ скриншоты получались бы в дефолтной Scarred Mind,
    # как бы страница ни собиралась флагом --theme
    data = {**settings_schema.defaults(), "dest": r"C:\Downloads",
            "language": lang, "theme": theme}
    return json.dumps(data, ensure_ascii=False).replace("\\", "\\\\")


# Стаб API: init() и tick() должны пройти целиком, чтобы мы мерили реальную
# разметку, а не падение скрипта. Значения повторяют ответы Api.get_initial и
# Api.poll.
STUB = """<script>
(function () {
  var FONTS = {families: ["JetBrains Mono"], mono: ["JetBrains Mono"],
               count: 3, folder: "C:\\\\Synfronia\\\\fonts"};
  var state = {lang: "%(lang)s", css: "", fontsRev: 0, dl: null,
               // ответ poll() для кнопки «Скачать»: сценарий задаёт probe.dl
               dlState: {busy: false, status: "", result: null,
                         progress: {mode: "determinate", value: 0}},
               // массовая: построчные статусы и упавшие ссылки (задаёт сценарий)
               bulk: null, bulkFailed: [],
               // финальные статусы последней массовой (поле bulk_statuses)
               bulkStatuses: [],
               settingsOpen: %(settings_open)s, saved: [], dest: "", logs: []};
  var settings = __SETTINGS__;
  // Реалистичные данные обхода: список установок, стратегии активной и релизы -
  // иначе селектор стратегий и диалог выбора в зонде пустуют, а проверки
  // не находят своих элементов.
  var STRATS = ["general (ALT).bat", "general (ALT2).bat", "general (ALT3).bat",
                "general (ALT4).bat", "general (ALT5).bat", "general (ALT6).bat",
                "general (ALT7).bat", "general (ALT8).bat", "general (ALT9).bat",
                "general (ALT10).bat", "general (ALT11).bat", "general (ALT12).bat",
                "general (ALT13).bat", "general (EXP).bat", "general (FAKE TLS AUTO).bat",
                "general (SIMPLE FAKE ALT).bat", "general (SIMPLE FAKE).bat",
                "general.bat", "preset1.cmd", "preset2.cmd"];
  var BYPASSES = [
    {id: "zapret-1-10-3", path: "C:\\\\Users\\\\me\\\\AppData\\\\Local\\\\Synfronia\\\\Bypass\\\\zapret-discord-youtube-1.10.3",
     layout: "flowseal", source: "bundled", ok: true, issues: [], strategies: STRATS},
    {id: "zapret-1-9-6", path: "C:\\\\zapret-discord-youtube-1.9.6",
     layout: "flowseal", source: "local", ok: false, strategies: [],
     issues: ["Не хватает файлов, которые требуются стратегиям (фейки или списки)."]}
  ];
  var RELEASES = [
    {tag: "1.10.3", name: "1.10.3", url: "https://example.invalid/1.10.3.zip",
     asset: "zapret-discord-youtube-1.10.3.zip", size: 1510219, branch: false},
    {tag: "1.10.2", name: "1.10.2", url: "https://example.invalid/1.10.2.zip",
     asset: "zapret-discord-youtube-1.10.2.zip", size: 1508077, branch: false},
    {tag: "master", name: "master", url: "https://example.invalid/master.zip",
     asset: "master.zip", size: 0, branch: true}
  ];
  state.bypasses = BYPASSES;
  state.bypassActive = BYPASSES[0].id;
  // Отчёт пробы для заглушек: форма ответа - как у настоящего status_report
  function makeReport(stateName, running) {
    var marks = {web: true, media: true, short: true, thumb: true};
    if (stateName === "partial") marks.media = false;
    if (stateName === "none") marks = {web: false, media: false, short: false, thumb: false};
    var targets = {}, count = 0;
    Object.keys(marks).forEach(function(k) {
      targets[k] = {ok: marks[k], ms: marks[k] ? 240 + k.length * 27 : 6000,
                    why: marks[k] ? "" : "timeout"};
      if (marks[k]) count++;
    });
    return {running: running !== false, pid: 4242, strategy: "general (ALT9).bat",
            install: BYPASSES[0].path, state: stateName, count: count, total: 4,
            targets: targets, checked_at: Math.floor(Date.now() / 1000)};
  }
  // Состояние для плашки: локально (winws) + кэш последней пробы.
  // Живёт в state, чтобы тумблер и проба реально меняли картинку -
  // статичная заглушка не показала бы ни смену вкл/выкл, ни «не проверялся»
  var BYPASS = {running: true, probe: null};
  function makeStatus() {
    return {running: BYPASS.running, pid: BYPASS.running ? 4242 : null,
            strategy: "general (ALT9).bat", install: BYPASSES[0].path,
            last_probe: BYPASS.probe};
  }
  // Цвета для списка: часть стратегий уже «проверена» (точки и бейдж),
  // одна специально остаётся непроверенной - её серый вид тоже надо уметь
  var TESTS = {};
  STRATS.forEach(function(name, idx) {
    if (idx === 18) return;
    var stateName = idx < 12 ? "full" : (idx < 17 ? "partial" : "none");
    TESTS[name] = {state: stateName,
                   ts: Math.floor(Date.now() / 1000) - idx * 600,
                   count: stateName === "full" ? 4 : (stateName === "partial" ? 3 : 0),
                   ms: 900 + idx * 13};
  });
  var SCAN_RESULTS = STRATS.map(function(name) {
    var rec = TESTS[name];
    return {name: name, ok: !!rec && rec.state === "full",
            ms: rec ? rec.ms : null, state: rec ? rec.state : "none",
            targets: null};
  });
  function ok(r) { return Promise.resolve(r === undefined ? {} : r); }
  function uiState() {
    return {lang: state.lang, theme: settings.theme, ui_rev: 1, settings: settings,
            fonts_rev: state.fontsRev};
  }
  window.pywebview = {api: {
    get_initial: function () { return Promise.resolve({settings: settings, ffmpeg: true,
      default_dir: settings.dest, transcoders: ["libx265", "nvenc"], fonts: FONTS,
      bypasses: state.bypasses, bypass_active: state.bypassActive,
      settings_open: state.settingsOpen}); },
    poll: function () { return Promise.resolve(Object.assign({
      logs: state.logs, log_cursor: state.logs.length,
      bulk: state.bulk, bulk_failed: state.bulkFailed,
      bulk_statuses: state.bulkStatuses,
      // как настоящий poll: состояние обхода приходит только пока открыта
      // карточка (снимок процессов Python делает лишь для неё)
      bypass_state: state.settingsOpen ? makeStatus() : null,
      ffmpeg: {downloading: false, extracting: false, pct: 0, ok: true, error: null},
      fonts_dl: {downloading: false, pct: 0, error: null}}, uiState(), state.dlState)); },
    synf_settings_state: function (open) { state.settingsOpen = !!open; return ok(); },
    set_dest: function (path) { state.dest = path; return ok(); },
    set_font: function (key, value) { settings[key] = value;
      state.saved.push([key, value]); return ok({css: state.css}); },
    reload_fonts: function () { return ok({fonts: FONTS, css: state.css}); },
    font_face_css: function () { return ok(state.css); },
    download_fonts: function () { state.dl = "started"; return ok("started"); },
    download_themes: function () { return ok({added: ["technology_day"], skipped: [], failed: []}); },
    apply_theme_css: function () { return ok(); },
    set_theme: function (id) { settings.theme = id; state.saved.push(["theme", id]); return ok("ok"); },
    switch_theme: function () { return ok(); },
    // как настоящий reload_themes: отдаём перечитанный список тем
    reload_themes: function () { return ok(Object.assign({}, THEMES)); },
    set_language: function (lang) { settings.language = lang; return ok(); },
    save_setting: function (key, value) { state.saved.push([key, value]);
      // как в приложении: значение сохраняется, и следующий poll() покажет
      // его (иначе fillSettings() на поллу откатил бы переключатель назад)
      settings[key] = value; return ok(); },
    start_download: function () { return ok({}); },
    start_ffmpeg_download: function () { return ok({}); },
    // обход: одна стратегия и «Прервать» перебора - заглушка формы ответа,
    // сеть в зонде не меряется
    dpi_test_one: function (name) {
      var report = makeReport("full");
      report.strategy = name || report.strategy;
      BYPASS.probe = report;
      return ok({ok: true, state: "full", strategy: report.strategy,
                 started: false, report: report});
    },
    dpi_cancel: function () { return ok({ok: true}); },
    // как настоящий start_bulk: парсинг теми же правилами, busy и статус [i/N]
    start_bulk: function (cfg) {
      var lines = String((cfg && cfg.urls) || "").split("\\n")
        .map(function(s) { return s.trim(); })
        .filter(function(s) { return s && s.charAt(0) !== "#" && /^https?:\\/\\//i.test(s); });
      if (!lines.length) return Promise.resolve({error: "empty"});
      state.saved.push(["bulk", lines]);
      state.dlState = {busy: true, status: "[1/" + lines.length + "] " + lines[0],
                       result: null, progress: {mode: "indeterminate", value: 0}};
      // первая строка уже «качается», остальные ждут (как в воркере)
      state.bulk = {total: lines.length, index: 1,
                    statuses: ["l"].concat(new Array(lines.length - 1).fill("p"))};
      state.bulkFailed = [];
      state.bulkStatuses = [];
      return ok({});
    },
    stop_download: function () { return ok(); },
    browse_folder: function () { return ok("C:\\\\Downloads"); },
    test_ftp: function () { return ok({error: "test"}); },
    open_fonts_folder: function () { return ok(); },
    open_themes_folder: function () { return ok(); },
    // -- обход: панель, диалог выбора и загрузка версий ----------------------
    dpi_status: function () { return ok(makeStatus()); },
    dpi_probe: function () {
      BYPASS.probe = makeReport("full");
      return ok({ok: true, report: BYPASS.probe});
    },
    dpi_start: function () {
      BYPASS.running = true;
      return ok({ok: true, already: false, pid: 4242, report: makeReport("full")});
    },
    dpi_stop: function () {
      BYPASS.running = false;
      BYPASS.probe = makeReport("full", false);
      return ok({ok: true, running: false, report: BYPASS.probe});
    },
    dpi_scan: function () {
      var tally = {n: SCAN_RESULTS.length, full: 0, partial: 0, none: 0};
      SCAN_RESULTS.forEach(function(r) {
        tally[r.state === "full" ? "full" : (r.state === "partial" ? "partial" : "none")]++;
      });
      return ok({ok: tally.full > 0, best: tally.full ? "general (ALT9).bat" : null,
                 results: SCAN_RESULTS, tally: tally, cancelled: false});
    },
    bypass_list: function () {
      return ok({active: state.bypassActive, items: state.bypasses, tests: TESTS});
    },
    bypass_validate: function (path) {
      var hit = state.bypasses.filter(function (b) { return b.path === path; })[0];
      return ok(hit || {path: path, ok: false, layout: null, winws: "",
                        strategies: [], issues: ["нет установки"]});
    },
    bypass_detect: function () { return ok({found: []}); },
    bypass_add: function (path, select) {
      var item = {id: "added-" + state.bypasses.length, path: path, layout: "flowseal",
                  source: "local", ok: true, issues: [], strategies: STRATS};
      state.bypasses.push(item);
      if (select !== false) state.bypassActive = item.id;
      return ok({ok: true, item: item, strategies: STRATS});
    },
    bypass_select: function (id) {
      state.bypassActive = id;
      return ok({ok: true, item: {id: id}});
    },
    bypass_remove: function (id) {
      state.bypasses = state.bypasses.filter(function (b) { return b.id !== id; });
      if (state.bypassActive === id && state.bypasses.length) {
        state.bypassActive = state.bypasses[0].id;
      }
      return ok({ok: true});
    },
    bypass_repos: function () {
      return ok({repos: ["Flowseal/zapret-discord-youtube", "bol-van/zapret-win-bundle"]});
    },
    bypass_releases: function (repo) {
      return ok({ok: true, entries: RELEASES});
    },
    bypass_download: function (repo, tag) {
      var item = {id: "dl-" + tag, path: "C:\\\\Synfronia\\\\Bypass\\\\zapret-" + tag,
                  layout: "flowseal", source: "github", ok: true, issues: [],
                  strategies: STRATS};
      state.bypasses.push(item);
      state.bypassActive = item.id;
      return ok({ok: true, item: item, strategies: STRATS});
    }
  }};
  window.__probe = state;
  // Этап5 (события + heartbeat): запись сценария в стаб - это «событие»
  // настоящего Api._ping, поэтому будим страницу сразу, а не ждём heartbeat
  // (иначе зонд после каждой установки ждал бы секунду вместо мгновения).
  // Пингуют и ответы API (кроме poll/get_initial - иначе петля пробуждений:
  // tick сам зовёт poll). Поля, которые тест читает напрямую (saved/dest),
  // пинг не требуют.
  ["dlState", "bulk", "bulkFailed", "bulkStatuses", "logs"].forEach(function (k) {
    var v = state[k];
    Object.defineProperty(state, k, {
      get: function () { return v; },
      set: function (nv) { v = nv; if (window.__synfPing) window.__synfPing(); },
      enumerable: true, configurable: true
    });
  });
  Object.keys(window.pywebview.api).forEach(function (name) {
    if (name === "poll" || name === "get_initial") return;
    var orig = window.pywebview.api[name];
    window.pywebview.api[name] = function () {
      var r = orig.apply(this, arguments);
      if (window.__synfPing) window.__synfPing();
      return r;
    };
  });
})();
</script>
"""


# Состояние для скриншотов (флаг --state): страница сама доводит себя до
# вида, который снимает headless Edge (msedge --screenshot --window-size).
# Скрипт кладётся в самый конец страницы - после стаба и всех скриптов
# приложения, поэтому можно пользоваться их публичными API (кнопки,
# switchTab, __synfPing, __probe). Без --state не вставляется вовсе -
# зонды работают как прежде.
DEMO = """<script>
(function () {
  var state = "__STATE__";
  function click(id) { var el = document.getElementById(id); if (el) el.click(); }
  if (state === "main" || !state) {
    var u = document.getElementById("url-video");
    if (u) u.value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
    return;
  }
  if (state === "bulk") {
    switchTab("batch");
    var box = document.getElementById("url-batch");
    box.value = ["https://youtu.be/first", "https://youtu.be/second",
                 "https://youtu.be/third", "https://youtu.be/fourth"].join("\\n");
    box.dispatchEvent(new Event("input"));
    click("download");
    // итоговая роспись строк: скачано, скачано, прервано отменой, в очереди
    setTimeout(function () {
      window.__probe.bulk = {total: 4, index: 4,
                             statuses: ["o", "o", "c", "p"]};
      if (window.__synfPing) window.__synfPing();
    }, 500);
    return;
  }
  // состояния с открытой карточкой настроек (сама карточка - флаг --state,
  // выше: для этих состояний settings_open выставляется автоматически)
  click("settings-btn");
  setTimeout(function () {
    var nav = {bypass: "nav-dpi", strategies: "nav-dpi",
               downloader: "nav-dl", ftp: "nav-ftp"}[state];
    if (nav) click(nav);
    if (state === "strategies") {
      setTimeout(function () { click("bypass-choose"); }, 400);
    }
    if (state === "ftp") {
      setTimeout(function () {
        var host = document.getElementById("ftp-host");
        if (host) {
          host.value = "ftp.example.com";
          host.dispatchEvent(new Event("change", {bubbles: true}));
        }
        var dir = document.getElementById("ftp-dir");
        if (dir) {
          dir.value = "media/{playlist}";
          dir.dispatchEvent(new Event("change", {bubbles: true}));
        }
        var act = document.getElementById("ftp-active");
        if (act && !act.checked) act.click();
      }, 400);
    }
  }, 300);
})();
</script>
"""


def inject_demo(page: str, state: str) -> str:
    """Скрипт состояния - в самый конец страницы, после всех скриптов."""
    block = DEMO.replace("__STATE__", state)
    if "</body>" in page:
        return page.replace("</body>", block + "\n</body>", 1)
    return page + block


def build_page_with_stub(theme: str = "scarred_mind", lang: str = "ru",
                         settings_open: bool = False) -> str:
    """Страница приложения со стабом API; settings_open - сразу открытая карточка."""
    # приложение грузит языковые файлы до сборки страницы: без этого в I18N нет
    # thisLang, список языков в настройках пуст и мы меряем не то, что видит юзер.
    # Сами значения берём встроенные: файлы в %LOCALAPPDATA% могли достаться от
    # прежней версии и содержать старые подписи, а проверка должна смотреть на
    # текст из поставки.
    i18n.load_languages()
    i18n.use_builtin_languages()
    out = build_page(theme)
    marker = "<script>"
    idx = out.find(marker)
    if idx < 0:
        raise SystemExit("не найден <script> для вставки стаба")
    stub = STUB % {"lang": lang, "settings_open": "true" if settings_open else "false"}
    stub = stub.replace("__SETTINGS__", stub_settings(lang, theme))
    return out[:idx] + stub + out[idx:]


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a]
    theme, lang, state = "scarred_mind", "ru", ""
    settings_open = False
    out: Path | None = None
    i = 0
    while i < len(args):
        if args[i] == "--theme":
            theme = args[i + 1] if i + 1 < len(args) else theme
            i += 2
        elif args[i] == "--lang":
            lang = args[i + 1] if i + 1 < len(args) else lang
            i += 2
        elif args[i] == "--state":
            state = args[i + 1] if i + 1 < len(args) else state
            i += 2
        elif args[i] == "--settings":
            settings_open = True
            i += 1
        elif args[i] == "--page":
            raise SystemExit("страница одна: карточка настроек открывается флагом --settings")
        else:
            out = Path(args[i])
            i += 1
    known = ("", "main", "bulk", "bypass", "strategies", "downloader", "ftp")
    if state not in known:
        raise SystemExit(f"неизвестное состояние {state!r}, допустимы: {', '.join(known[1:])}")
    if state and state not in ("main", "bulk"):
        settings_open = True   # состояния с карточкой начинаются с её открытия
    out = out or PROBE_DIR / "page.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    page = build_page_with_stub(theme=theme, lang=lang, settings_open=settings_open)
    if state:
        page = inject_demo(page, state)
    out.write_text(page, encoding="utf-8")
    print(f"{out} (карточка настроек={'открыта' if settings_open else 'закрыта'}, "
          f"тема={theme}, язык={lang}, состояние={state or '-'})")
    return 0



if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
