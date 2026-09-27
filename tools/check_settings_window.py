r"""Проверка окна настроек без запуска приложения.

Что проверяем (themes, core, gui.Api/SettingsApi, шаблоны ui_src):
  1. окно собирается для каждой темы: плейсхолдеры все подставлены, разметка
     наша (список разделов, поля, журнал), а не кусок темы;
  2. тема не может подсунуть своё окно: entry и slots/settings.html игнорируются,
     но палитра, шрифты и CSS темы в окно попадают;
  3. Api отдаёт окну ровно то, что ждёт settings.js: get_initial, poll_settings,
     open_settings, close_settings, set_dest, save_setting, set_theme, set_font;
  4. SettingsApi не торчит наружу лишним (нет start_download/stop_download/poll),
     а диалог папки открывается от окна настроек;
  5. папка загрузки не настройка: она не попадает в settings.json, но помнит
     выбор и переживает смену темы (её не сбрасывает перезагрузка страницы);
  6. start_download берёт папку и параметры загрузки из настроек сам, поэтому
     окна не могут показать разные значения;
  7. main.js/app.js и settings.js не знают друг о друге лишнего (см. также
     раздел 10 в tools/check_settings.py).

Запуск:  python tools/check_settings_window.py
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
_iso = Path(tempfile.mkdtemp(prefix="synf-check-win-"))
os.environ["LOCALAPPDATA"] = str(_iso)

import i18n  # noqa: E402
import themes  # noqa: E402
import ui  # noqa: E402
from core import build_page, build_settings_page  # noqa: E402
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


def main() -> int:
    i18n.load_languages()
    themes.load_themes()
    theme_ids = [k for k, v in themes.themes_embed().items() if not (v or {}).get("hidden")]

    # 1. сборка окна
    section("1. окно собирается")
    ok(bool(theme_ids), "есть темы для проверки")
    for key in theme_ids:
        page = build_settings_page(key)
        left = [p for p in PLACEHOLDERS if p in page]
        ok(not left, f"{key}: все плейсхолдеры подставлены", str(left))
    page = build_settings_page(theme_ids[0] if theme_ids else "scarred_mind")
    for frag, what in (('id="settings-nav"', "список разделов"),
                       ('id="settings-sections"', "область полей"),
                       ('id="log"', "полоса журнала"),
                       ('id="settings-close"', "кнопка закрытия"),
                       ('<script>', "общий JS")):
        ok(frag in page, f"в окне есть {what}")
    ok("SETTINGS_SCHEMA.groups" in page, "схема доехала в settings.js")
    ok('"groups"' in page and '"fields"' in page, "в схеме есть группы и поля")
    ok("nav-item" in page and "switchSection" in page, "окно рисует список разделов")
    ok("SLOT:settings" not in page and "__APPJS__" not in page,
       "в окне нет ни слота панели, ни логики главного окна")
    ok(len(page) > 20000, "окно не пустое", f"{len(page)} символов")

    # 2. окно против темы
    section("2. тема не подменяет окно, но красит его")
    for key in theme_ids:
        t = themes.themes_embed().get(key) or {}
        out = build_settings_page(key)
        ok('id="settings-nav"' in out, f"{key}: свой список разделов на месте")
        if t.get("bg"):
            ok(f"--bg: {t['bg']};" in out or t["bg"] in out,
               f"{key}: палитра темы попала в окно")
        if t.get("css"):
            ok("__THEME_CSS__" not in out, f"{key}: CSS темы подставлен")
    # тема с entry и со слотом settings: разметка окна не меняется
    saved = dict(themes._LOADED_THEMES)
    try:
        themes._LOADED_THEMES["__test_entry__"] = {
            "label": "Тест", "bg": "#101010", "text": "#eeeeee",
            "css": "body{background:#101010}", "entry": "index.html",
            "_entry_folder": ROOT / "themes_test_entry",
        }
        (ROOT / "themes_test_entry").mkdir(exist_ok=True)
        (ROOT / "themes_test_entry" / "index.html").write_text(
            "<html><body><p>тема подменила окно</p></body></html>", encoding="utf-8")
        (ROOT / "themes_test_entry" / "slots").mkdir(exist_ok=True)
        (ROOT / "themes_test_entry" / "slots" / "settings.html").write_text(
            "<p>слот настроек</p>", encoding="utf-8")
        out = build_settings_page("__test_entry__")
        ok('id="settings-nav"' in out and "тема подменила окно" not in out,
           "entry темы не подменяет окно настроек")
        ok("слот настроек" not in out, "slots/settings.html игнорируется")
        ok("background:#101010" in out, "CSS темы в окне остаётся")
    finally:
        themes._LOADED_THEMES = saved
        shutil.rmtree(ROOT / "themes_test_entry", ignore_errors=True)

    # 3. Api для окна
    section("3. Api отдаёт окну нужное")
    api = gui.Api()
    init = api.get_initial()
    for field in ("settings", "ffmpeg", "default_dir", "transcoders", "fonts"):
        ok(field in init, f"get_initial отдаёт {field}")
    ok("ui.dest" not in api.settings, "папки загрузки нет в настройках")
    state = api.poll_settings(0)
    for field in ("logs", "log_cursor", "fonts_dl", "fonts_rev", "ui_rev",
                  "lang", "theme", "settings_open"):
        ok(field in state, f"poll_settings отдаёт {field}")
    ok("busy" not in state and "progress" not in state,
       "в окне нет прогресса загрузки (окно модальное)")
    main_state = api.poll(0)
    for field in ("busy", "status", "result", "progress", "logs", "ui_rev",
                  "settings_open", "theme"):
        ok(field in main_state, f"poll отдаёт главному окну {field}")
    ok(api.settings_open() is False, "окно настроек закрыто")
    api._log("info", "строка журнала")
    after = api.poll_settings(0)
    ok(any("строка журнала" in s for s in after["logs"]), "журнал окна общий с главным")
    ok(api.poll_settings(after["log_cursor"])["logs"] == [], "курсор не дублирует строки")
    rev0 = api.poll(0)["ui_rev"]
    api.save_setting("language", "en")
    ok(api.poll(0)["ui_rev"] > rev0, "смена языка поднимает ui_rev")
    rev1 = api.poll(0)["ui_rev"]
    api.set_font("font_sans", "Inter")
    ok(api.poll(0)["ui_rev"] > rev1, "смена шрифта поднимает ui_rev")

    # 4. SettingsApi
    section("4. мост окна настроек")
    bridge = gui.SettingsApi(api)
    for name in ("get_initial", "poll_settings", "save_setting", "set_dest",
                 "browse_folder", "test_ftp", "set_theme", "reload_themes",
                 "open_themes_folder", "font_face_css", "set_font", "reload_fonts",
                 "download_fonts", "open_fonts_folder", "close_settings"):
        ok(hasattr(bridge, name), f"SettingsApi.{name}")
        ok(callable(getattr(bridge, name, None)), f"SettingsApi.{name} вызываем")
    for name in ("start_download", "stop_download", "poll"):
        ok(not hasattr(bridge, name), f"окну настроек не нужно {name}")
    gui_src = (ROOT / "gui.py").read_text(encoding="utf-8")
    bridge_src = gui_src[gui_src.index("class SettingsApi"):gui_src.index("def main()")]
    ok("def __getattr__" not in bridge_src, "мост перечисляет методы, а не подставляет любые")
    ok("self._api.browse_folder(self._win)" in bridge_src,
       "диалог папки открывается от окна настроек")
    ok("self._win" in inspect.getsource(gui.Api.browse_folder),
       "диалог папки умеет работать с чужим родительским окном")
    open_src = inspect.getsource(gui.Api.open_settings)
    ok("self._bridge.bind_window(win)" in open_src,
       "мост получает своё окно сразу после create_window")
    ok("events.closed" in open_src, "закрытие окна ОС отслеживается")
    ok("width=SETTINGS_SIZE[0]" in open_src,
       "окно создаётся заданного размера")
    ok("min_size=SETTINGS_MIN_SIZE" in open_src,
       "у окна есть минимальный размер")
    ok(gui.SETTINGS_SIZE[0] >= 800 and gui.SETTINGS_MIN_SIZE[0] <= 720,
       "размер окна достаточен для трёх разделов",
       f"{gui.SETTINGS_SIZE} / {gui.SETTINGS_MIN_SIZE}")

    # 5. папка загрузки - не настройка
    section("5. папка загрузки живёт до конца сеанса")
    api.set_dest("D:\\Videos")
    ok(api._dest == "D:\\Videos", "set_dest запомнил выбор")
    ok("ui.dest" not in api.settings, "в settings.json папки нет")
    api.set_theme(next((k for k in theme_ids
                        if not (themes.themes_embed().get(k) or {}).get("entry")), theme_ids[0]))
    ok(api._dest == "D:\\Videos", "перезагрузка страницы не сбрасывает папку")
    ok(api.get_initial()["default_dir"] == "D:\\Videos",
       "главное окно узнаёт папку через get_initial")
    ok(api.set_dest("") is None and api._dest == "", "пустая папка очищается")

    # 6. конфиг загрузки собирает Python
    section("6. конфиг загрузки собирает Python")
    src = inspect.getsource(gui.Api.start_download)
    ok('cfg.get("url")' in src, "ссылка берётся из окна")
    ok("cfg.get(\"dest\")" not in src, "папка из окна не принимается")
    for setting in ("dl.subtitles", "dl.quality", "dl.transcode"):
        ok(setting in src, f"{setting} берётся из настроек")
    ok("FtpConfig(self.settings" in src, "FTP берётся из настроек")
    ok("self._dest or str(default_download_dir())" in src,
       "без выбора берётся папка загрузок по умолчанию")
    check = gui.settings_schema.has("ui.dest")
    ok(not check, "в схеме нет сохраняемой настройки ui.dest")

    # 7. границы между окнами
    section("7. окна не знают друг о друге лишнего")
    app_js = (ROOT / "ui_src" / "app.js").read_text(encoding="utf-8")
    win_js = (ROOT / "ui_src" / "settings.js").read_text(encoding="utf-8")
    ok("start_download" in app_js and "start_download" not in win_js,
       "загрузку запускает только главное окно")
    ok("poll_settings" in win_js and "poll_settings" not in app_js,
       "журнал окна настроек не мешает главному")
    for name in ("close_settings", "set_dest", "set_theme",
                 "set_font", "save_setting"):
        ok(name in win_js, f"окно настроек умеет {name}")
    ok("open_settings" in app_js, "главное окно умеет открыть настройки")
    ok("open_settings" not in win_js,
       "окно настроек не открывает само себя - это кнопка главного окна")
    ok("close_settings" not in app_js,
       "закрывает окно оно само или Python, а не главное окно")
    theme_src = inspect.getsource(gui.Api.set_theme)
    ok("build_page" in theme_src and "build_settings_page" in theme_src,
       "смена темы пересобирает оба окна")
    main_src = gui_src[gui_src.index("def main()"):gui_src.index("def diagnose_freeze")]
    ok("bind_main_window" in main_src,
       "главное окно регистрируется в Api")

    # 8. окна создаются и закрываются (pywebview подменён заглушкой)
    section("8. создание и закрытие окон")
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
            self.shown = False
            self.destroyed = False
            self.html = ""

        def load_html(self, html: str) -> None:
            self.html = html

        def show(self) -> None:
            self.shown = True

        def restore(self) -> None:
            pass

        def destroy(self) -> None:
            self.destroyed = True
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
        ok(isinstance(main_win.js_api, gui.Api), "у главного окна свой Api")
        ok(main_win.kw.get("min_size") == (780, 560), "у главного окна есть минимум")
        api2 = main_win.js_api
        ok(api2._win_main is main_win, "главное окно зарегистрировано в Api")

        state = api2.open_settings()
        ok(state == "created" and len(created) == 2, "open_settings создал второе окно", state)
        win = created[1]
        ok(isinstance(win.js_api, gui.SettingsApi), "у окна настроек свой мост")
        ok(win.js_api._api is api2, "мост ссылается на тот же Api")
        ok(win.js_api._win is win, "мост знает своё окно (диалог папки)")
        ok(win.kw.get("width") == gui.SETTINGS_SIZE[0] and
           win.kw.get("height") == gui.SETTINGS_SIZE[1],
           "окно настроек создано заданного размера", str(win.kw.get("size")))
        ok(win.kw.get("min_size") == gui.SETTINGS_MIN_SIZE, "у окна настроек есть минимум")
        ok('id="settings-nav"' in win.html, "в окно загружена страница настроек")
        ok('id="download"' not in win.html, "а логики главного окна в ней нет")
        ok(api2.settings_open() is True, "Api знает, что окно открыто")

        ok(api2.open_settings() == "shown" and len(created) == 2,
           "повторное нажатие не плодит окна")
        ok(win.shown, "уже открытое окно просто показано")

        api2.close_settings()
        ok(win.destroyed, "close_settings закрывает окно")
        ok(api2._win_settings is None and api2.settings_open() is False,
           "после закрытия Api забыл окно (главное снимет оверлей по poll)")
    finally:
        gui.webview.create_window, gui.webview.start = real_create, real_start

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
