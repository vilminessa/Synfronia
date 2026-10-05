r"""Проверка карточки настроек (оверлея) без запуска приложения.

Что проверяем (themes, core, gui.Api, шаблоны ui_src):
  1. страница собирается для каждой темы: все плейсхолдеры подставлены, оверлей
     на месте (список разделов, область полей, крестик), схема доехала в
     settings.js;
  2. тема не может подсунуть свою разметку: entry и slots/settings.html
     игнорируются, но палитра, шрифты и CSS темы в страницу попадают, а
     оверлей, его стиль и скрипт themes._ensure_settings дописывает сам;
  3. Api отдаёт карточке ровно то, что ждёт settings.js, и всё это приходит
     из одного poll(): settings, settings_open, fonts_rev, fonts_dl, ui_rev;
     отдельных poll_settings/open_settings/close_settings/SettingsApi больше
     нет;
  4. карточка не теряется при пересборке страницы (тема со своим entry) и при
     смене языка/шрифта;
  5. папка загрузки не настройка: она не попадает в settings.json, но помнит
     выбор и переживает перезагрузку страницы;
  6. start_download берёт папку и параметры загрузки из настроек сам, поэтому
     поля карточки и главное окно не могут показать разные значения;
  7. офлайн-восстановление базовых тем не трогает то, что уже есть на диске.

Запуск:  python tools/check_settings_overlay.py
"""

import inspect
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# изолируем настройки и темы до импорта приложения
_iso = Path(tempfile.mkdtemp(prefix="synf-check-overlay-"))
os.environ["LOCALAPPDATA"] = str(_iso)

import i18n  # noqa: E402
import themes  # noqa: E402
import ui  # noqa: E402
from core import build_page  # noqa: E402
import gui  # noqa: E402

PLACEHOLDERS = ("__THEME_ROOT__", "__THEME_CSS__", "__FONTS_CSS__", "__APP_CSS__",
                "__MAIN_CSS__", "__SETTINGS_CSS__", "__COMMONJS__", "__APPJS__",
                "__SETTINGS_JS__", "__I18N__", "__THEMES__", "__SETTINGS_SCHEMA__")

_checks = 0
_fails: list[str] = []


def ok(cond: bool, label: str, detail: str = "") -> bool:
    global _checks
    _checks += 1
    if cond:
        print(f"  ok   {label}")
        return True
    print(f"  FAIL {label}{(': ' + detail) if detail else ''}")
    _fails.append(label)
    return False


def section(title: str) -> None:
    print(f"\n{title}")


def settings_css_in(page: str) -> bool:
    """Стиль карточки реально попал в страницу (по узнаваемому правилу)."""
    return "backdrop-filter: blur(10px)" in page and ".settings-card" in page


def main() -> int:
    i18n.load_languages()
    themes.load_themes()
    theme_ids = [k for k, v in themes.themes_embed().items() if not (v or {}).get("hidden")]

    # 1. сборка страницы
    section("1. страница с карточкой собирается")
    ok(bool(theme_ids), "есть темы для проверки")
    for key in theme_ids:
        page = build_page(key)
        left = [p for p in PLACEHOLDERS if p in page]
        ok(not left, f"{key}: все плейсхолдеры подставлены", str(left))
    page = build_page(theme_ids[0] if theme_ids else "scarred_mind")
    for frag, what in (('id="settings-overlay"', "оверлей"),
                       ('id="settings-nav"', "список разделов"),
                       ('id="settings-sections"', "область полей"),
                       ('id="settings-close"', "кнопка закрытия"),
                       ('id="download"', "главное окно"),
                       ('id="log"', "журнал главного окна"),
                       ("<script>", "общий JS")):
        ok(frag in page, f"в странице есть {what}")
    ok(page.count('id="log"') == 1, "журнал в странице один")
    ok("SETTINGS_SCHEMA.groups" in page, "схема доехала в settings.js")
    ok('"groups"' in page and '"fields"' in page, "в схеме есть группы и поля")
    ok("nav-item" in page and "switchSection" in page, "карточка рисует список разделов")
    ok("SLOT:settings" not in page, "в странице нет старого слота панели")
    ok(ui.SETTINGS_HTML.count('id="settings-overlay"') == 1,
       "фрагмент карточки собран один раз")

    # 2. карточка против темы
    section("2. тема не подменяет карточку, но красит её")
    for key in theme_ids:
        t = themes.themes_embed().get(key) or {}
        out = build_page(key)
        ok('id="settings-nav"' in out, f"{key}: свой список разделов на месте")
        if t.get("bg"):
            ok(f"--bg: {t['bg']};" in out or t["bg"] in out,
               f"{key}: палитра темы попала в страницу")
        if t.get("css"):
            ok("__THEME_CSS__" not in out, f"{key}: CSS темы подставлен")
    # тема со своим entry: разметка карточки не меняется, стиль темы остаётся
    saved = dict(themes._LOADED_THEMES)
    entry_dir = ROOT / "themes_test_entry"
    try:
        themes._LOADED_THEMES["__test_entry__"] = {
            "label": "Тест", "bg": "#101010", "text": "#eeeeee",
            "css": "body{background:#101010}", "entry": "index.html",
            "_entry_folder": entry_dir,
        }
        (entry_dir / "slots").mkdir(parents=True, exist_ok=True)
        # свой entry по контракту несёт общие плейсхолдеры приложения, но может
        # не знать про карточку настроек - её дописывает _ensure_settings
        (entry_dir / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>t</title>"
            "<style>:root{__THEME_ROOT__}</style>"
            "<style id=\"theme-style\">__THEME_CSS__</style>"
            "<style>__APP_CSS__</style><style>__MAIN_CSS__</style></head>"
            "<body><p>тема подменила окно</p>"
            "<script>__COMMONJS__</script><script>__APPJS__</script>"
            "<script>__I18N__</script><script>__THEMES__</script></body></html>",
            encoding="utf-8")
        (entry_dir / "slots" / "settings.html").write_text(
            "<p>слот настроек</p>", encoding="utf-8")
        out = build_page("__test_entry__")
        ok("тема подменила окно" in out, "свой entry действительно собирает страницу")
        ok('id="settings-nav"' in out and "слот настроек" not in out,
           "entry темы не подменяет карточку настроек")
        ok("background:#101010" in out and "--bg: #101010" in out,
           "CSS и палитра темы в своей странице остаются")
        ok('id="settings-overlay"' in out and "synfSettingsState" in out
           and settings_css_in(out),
           "карточка, стиль и скрипт дописаны к чужому entry (_ensure_settings)")
    finally:
        themes._LOADED_THEMES = saved
        shutil.rmtree(entry_dir, ignore_errors=True)

    # 3. Api
    section("3. Api отдаёт карточке нужное")
    api = gui.Api()
    init = api.get_initial()
    for field in ("settings", "ffmpeg", "default_dir", "transcoders", "fonts",
                  "settings_open"):
        ok(field in init, f"get_initial отдаёт {field}")
    ok("ui.dest" not in api.settings, "папки загрузки нет в настройках")
    state = api.poll(0)
    for field in ("busy", "status", "result", "progress", "logs", "log_cursor",
                  "fonts_dl", "fonts_rev", "settings", "ui_rev", "lang", "theme"):
        ok(field in state, f"poll отдаёт {field}")
    ok("settings_open" not in state,
       "poll не тащит открытость: после перезагрузки страницы её отдаёт get_initial")
    # регресс: стартовая проверка ffmpeg и poll обязаны говорить одно и то
    # же - раньше _ffmpeg["ok"] оставался False до первой докачки, и первый
    # тик затирал верное значение init (ложное «перекодировка недоступна»
    # даже при установленном ffmpeg). find_ffmpeg подделываем: чек не должен
    # зависеть от наличия ffmpeg на машине, которая гоняет проверку.
    saved_find = gui.find_ffmpeg
    for probe_result in (True, False):
        gui.find_ffmpeg = lambda _r=probe_result: _r
        try:
            init_f = api.get_initial()
            state_f = api.poll(0)
            ok(init_f["ffmpeg"] == state_f["ffmpeg"]["ok"] == probe_result,
               f"find_ffmpeg={probe_result}: get_initial.ffmpeg согласован с poll.ffmpeg.ok",
               f'{init_f["ffmpeg"]} vs {state_f["ffmpeg"]["ok"]}')
        finally:
            gui.find_ffmpeg = saved_find
    ok("transcoders" in state,
       "poll отдаёт transcoders (после докачки карточка раскроет их без перезапуска)")
    ok(isinstance(state["transcoders"], (list, type(None))),
       "transcoders в poll - список или null", repr(state.get("transcoders")))
    for gone in ("poll_settings", "open_settings", "close_settings", "settings_open"):
        ok(not hasattr(api, gone), f"у Api больше нет {gone}()")
    ok(not hasattr(gui, "SettingsApi"), "моста SettingsApi больше нет")
    for name in ("SETTINGS_SIZE", "SETTINGS_MIN_SIZE", "_swap_settings_page"):
        ok(not hasattr(gui, name), f"у модуля нет {name}")
    gui_src = (ROOT / "gui.py").read_text(encoding="utf-8")
    ok("open_settings" not in gui_src, "в gui.py не осталось open_settings")
    ok("if (initData.settings_open) setSettingsOpen(true);"
       in (ROOT / "ui_src" / "app.js").read_text(encoding="utf-8"),
       "страница после перезагрузки возвращает открытую карточку")

    api.synf_settings_state(True)
    ok(api.get_initial()["settings_open"] is True,
       "фронтенд сообщил об открытой карточке, и перезагрузка её вернёт")
    api.synf_settings_state(False)
    ok(api.get_initial()["settings_open"] is False, "закрытие тоже доезжает до Python")

    api._log("info", "строка журнала")
    after = api.poll(0)
    ok(any("строка журнала" in s for s in after["logs"]), "журнал один на оба окна")
    ok(api.poll(after["log_cursor"])["logs"] == [], "курсор не дублирует строки")
    rev0 = api.poll(0)["ui_rev"]
    api.save_setting("language", "en")
    ok(api.poll(0)["ui_rev"] > rev0, "смена языка поднимает ui_rev")
    rev1 = api.poll(0)["ui_rev"]
    api.set_font("font_sans", "JetBrains Mono")
    ok(api.poll(0)["ui_rev"] > rev1, "смена шрифта поднимает ui_rev")
    ok(api.poll(0)["settings"]["font_sans"] == "JetBrains Mono",
       "poll отдаёт и новое значение шрифта")
    ok("open_settings" not in inspect.getsource(gui.Api.set_theme),
       "смена темы не открывает ничего лишнего")
    ok("build_page" in inspect.getsource(gui.Api.set_theme),
       "смена темы пересобирает страницу")

    # 4. одно окно
    section("4. окно у приложения одно")
    created: list[dict] = []

    class _Event:
        def __init__(self) -> None:
            self.handlers: list = []

        def __iadd__(self, fn):
            self.handlers.append(fn)
            return self

        def fire(self) -> None:
            for fn in list(self.handlers):
                fn()

    class _Events:
        def __init__(self) -> None:
            self.closed = _Event()

    class _Win:
        def __init__(self, title: str) -> None:
            self.title = title
            self.events = _Events()
            self.html = ""

        def load_html(self, html: str) -> None:
            self.html = html

        def show(self) -> None:
            pass

        def restore(self) -> None:
            pass

        def destroy(self) -> None:
            self.events.closed.fire()

    real_create, real_start = gui.webview.create_window, gui.webview.start

    def fake_create(title, html=None, js_api=None, **kw):
        win = _Win(title)
        win.html = html or ""
        win.js_api = js_api
        win.kw = kw
        created.append(win)
        return win

    try:
        gui.webview.create_window = fake_create
        gui.webview.start = lambda *a, **k: None
        gui.main()
        ok(len(created) == 1, "main() создаёт одно окно", str(len(created)))
        main_win = created[0]
        ok(isinstance(main_win.js_api, gui.Api), "у окна свой Api")
        ok(main_win.kw.get("min_size") == (780, 560), "у окна есть минимум 780x560")
        ok('id="settings-overlay"' in main_win.html, "карточка приехала в это окно")
        ok('id="download"' in main_win.html, "главное окно живо вместе с карточкой")
        api2 = main_win.js_api
        ok(api2._win_main is main_win, "главное окно зарегистрировано в Api")
        ok(not hasattr(api2, "open_settings"), "открыть настройки можно только кнопкой")
    finally:
        gui.webview.create_window, gui.webview.start = real_create, real_start

    # 5. папка загрузки - не настройка
    section("5. папка загрузки живёт до конца сеанса")
    api.set_dest("D:\\Videos")
    ok(api._dest == "D:\\Videos", "set_dest запомнил выбор")
    ok("ui.dest" not in api.settings, "в settings.json папки нет")
    api.set_theme(next((k for k in theme_ids
                        if not (themes.themes_embed().get(k) or {}).get("entry")),
                       theme_ids[0]))
    ok(api._dest == "D:\\Videos", "перезагрузка страницы не сбрасывает папку")
    ok(api.get_initial()["default_dir"] == "D:\\Videos",
       "главное окно узнаёт папку через get_initial")
    ok(api.set_dest("") is None and api._dest == "", "пустая папка очищается")
    ok("parent" not in inspect.signature(gui.Api.browse_folder).parameters,
       "диалог папки открывается от главного окна")

    # 6. конфиг загрузки собирает Python
    section("6. конфиг загрузки собирает Python")
    src = inspect.getsource(gui.Api.start_download)
    ok('cfg.get("url")' in src, "ссылка берётся из окна")
    ok('cfg.get("dest")' not in src, "папка из окна не принимается")
    for setting in ("dl.subtitles", "dl.quality", "dl.transcode"):
        ok(setting in src, f"{setting} берётся из настроек")
    ok("FtpConfig(self.settings" in src, "FTP берётся из настроек")
    ok("self._dest or str(default_download_dir())" in src,
       "без выбора берётся папка загрузок по умолчанию")
    ok(not gui.settings_schema.has("ui.dest"), "в схеме нет сохраняемой настройки ui.dest")
    ok(not gui.settings_schema.has("dl.dest"), "папка загрузки - не настройка (transient)")
    ok(gui.settings_schema.field("dl.dest")[0]["id"] == "dl", "папка живёт в разделе «Загрузчик»")

    # 7. границы между слоями
    section("7. главное окно и карточка не мешают друг другу")
    app_js = (ROOT / "ui_src" / "app.js").read_text(encoding="utf-8")
    card_js = (ROOT / "ui_src" / "settings.js").read_text(encoding="utf-8")
    ok("start_download" in app_js and "start_download" not in card_js,
       "загрузку запускает только главное окно")
    ok("synfSettingsState(st)" in app_js
       and not any(token in card_js for token in ("api.poll", ".poll(", "synfSettingsPoll")),
       "карточка не опрашивает Python сама - состояние приносит poll() главного окна")
    for name in ("set_dest", "set_theme", "set_font", "save_setting", "synfSettingsInit"):
        ok(name in card_js, f"карточка умеет {name}")
    ok("openSettings" in app_js and "openSettings" not in card_js,
       "карточку открывает кнопка главного окна, а не она сама")
    ok("setSettingsOpen" in app_js, "открытие и закрытие живут в главном окне")
    main_src = gui_src[gui_src.index("def main()"):gui_src.index("def diagnose_freeze")]
    ok("bind_main_window" in main_src, "главное окно регистрируется в Api")

    # 8. офлайн-восстановление базовых тем
    section("8. базовые темы восстанавливаются офлайн")
    root = themes._themes_root()
    ok(root.is_dir() and any(root.iterdir()), "папка тем нашлась")
    victim = next((p for p in sorted(root.iterdir()) if p.is_dir()), None)
    ok(victim is not None, "есть тема для проверки")
    if victim is not None:
        marker = victim / "theme.json"
        was = marker.read_text(encoding="utf-8") if marker.exists() else ""
        result = themes.restore_builtin_themes(on_log=lambda *a: None)
        ok(set(result) == {"added", "skipped", "failed"}, "restore отдаёт сводку",
           str(sorted(result)))
        ok(not result["failed"], "восстановление без ошибок", str(result["failed"]))
        ok(not result["added"], "всё, что есть, не перезаписано", str(result["added"][:3]))
        if was:
            ok(marker.read_text(encoding="utf-8") == was,
               "правленная тема осталась как была")
    src_restore = inspect.getsource(themes.restore_builtin_themes)
    ok("_seed_theme" in src_restore, "восстановление идёт из встроенных данных themes.py")
    ok("shutil.rmtree" not in src_restore and "urlopen" not in src_restore
       and "requests" not in src_restore, "сеть и удаление папок не используются")
    ok("download_themes" in dir(gui.Api) and callable(gui.Api.download_themes),
       "у Api есть команда восстановления тем")
    ok("restore_builtin_themes" in inspect.getsource(gui.Api.download_themes),
       "команда зовёт восстановление из themes.py")

    section("9. перенос staging в установку уважает занятые файлы")
    stage = _iso / "stage" / "bundle"
    (stage / "bin").mkdir(parents=True)
    (stage / "bin" / "winws.exe").write_bytes(b"MZ-same")
    (stage / "bin" / "WinDivert.dll").write_bytes(b"new-bytes")
    (stage / "general.bat").write_text("@echo off", encoding="ascii")
    target = _iso / "install"
    (target / "bin").mkdir(parents=True)
    # занятый, но идентичный: его как раз не надо трогать (это был баг)
    (target / "bin" / "winws.exe").write_bytes(b"MZ-same")
    # занятый и чужой: путь-каталог не даёт открыть файл на запись
    (target / "bin" / "WinDivert.dll").mkdir()
    locked = gui._merge_tree(stage, target)
    ok((target / "general.bat").exists(), "новый файл перенесён")
    ok((target / "bin" / "winws.exe").read_bytes() == b"MZ-same",
       "идентичный занятый файл не перезаписывался")
    ok(bool(locked) and locked[0].startswith("bin/WinDivert.dll"),
       "занятый чужой файл собран в locked", str(locked))
    ok((target / "bin" / "WinDivert.dll").is_dir(),
       "занятый чужой файл остался как был")

    section("10. плашка состояния: локально, без пробы сети")
    api = gui.Api()
    try:
        # негатив главный: dpi_status() не имеет права мерять маршрут -
        # плашка показывает состояние, а не создаёт пинг при каждом poll
        real_probe, real_all = gui.dpi.probe_targets, gui.dpi.probe_all

        def _no_network(timeout=0, names=None):
            raise AssertionError("dpi_status обратился к сети")

        gui.dpi.probe_targets = gui.dpi.probe_all = _no_network
        try:
            state = api.dpi_status()
        finally:
            gui.dpi.probe_targets, gui.dpi.probe_all = real_probe, real_all
        ok(isinstance(state, dict)
           and {"running", "pid", "strategy", "install", "last_probe"} <= set(state),
           "dpi_status отдаёт состояние без обращения к сети", str(sorted(state)))
        # кэш последней пробы: плашка помнит время, ничего не измеряя
        report = {"running": True, "pid": 4242, "strategy": "general.bat",
                  "install": "C:\\zapret", "state": "partial", "count": 3,
                  "total": 4,
                  "targets": {"web": {"ok": True, "ms": 10, "why": ""}},
                  "checked_at": 1791150000}
        api._remember_probe(report)
        cached = api.dpi_status()["last_probe"]
        ok(cached and cached["checked_at"] == 1791150000 and cached["count"] == 3,
           "последняя проба запоминается и возвращается как есть", str(cached))
        api._remember_probe({"ok": False, "error": "нет папки"})   # отказ без пробы
        ok(api.dpi_status()["last_probe"] == cached,
           "отказ до пробы не затирает кэш", str(api.dpi_status()["last_probe"]))
        # состояние уходит в poll только пока открыта карточка
        api._settings_open = False
        ok(api.poll().get("bypass_state") is None,
           "карточка закрыта - состояние в poll не считается")
        api._settings_open = True
        live = api.poll().get("bypass_state")
        ok(isinstance(live, dict) and live.get("running") is not None
           and live.get("last_probe", {}).get("checked_at") == 1791150000,
           "карточка открыта - состояние и время пробы в poll", str(live))
        api._settings_open = False
    finally:
        with api._lock:
            api._last_probe = None
            api._settings_open = False

    print(f"\nитог: {_checks - len(_fails)}/{_checks} ok")
    if _fails:
        print("провалено: " + ", ".join(_fails))
        return 1
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_iso, ignore_errors=True)
    raise SystemExit(code)
