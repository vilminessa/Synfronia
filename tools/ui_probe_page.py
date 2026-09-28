r"""Собирает страницу Synfronia со стабом pywebview для headless-проверок вёрстки.

Зачем: app.js и settings.js живут внутри <script> и сразу дёргают pywebview.api,
поэтому для проверки разметки нужен настоящий DOM + заглушка API. Стаб
подставляется перед первым <script>, дальше страницу открывает tools/ui_*.js
через CDP. Проверяется одна страница: окно у приложения одно, а карточка
настроек лежит в ней оверлеем, поэтому сценарий открывает её сам (--settings
или клик по шестерёнке).

    python tools/ui_probe_page.py                      -> %TEMP%\synf_probe_page.html
    python tools/ui_probe_page.py out.html             -> свой путь
    python tools/ui_probe_page.py --settings           -> карточка настроек открыта
    python tools/ui_probe_page.py --theme liquid_glass --lang de
"""

import json
import sys
import tempfile
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import settings_schema  # noqa: E402
import i18n  # noqa: E402
from themes import build_page  # noqa: E402

# Настройки в стабе берём из схемы: так пробник проверяет настоящие умолчания,
# а не отдельный список (он уже расходился с приложением).
def stub_settings(lang: str) -> str:
    data = {**settings_schema.defaults(), "dest": r"C:\Downloads", "language": lang}
    return json.dumps(data, ensure_ascii=False).replace("\\", "\\\\")


# Стаб API: init() и tick() должны пройти целиком, чтобы мы мерили реальную
# разметку, а не падение скрипта. Значения повторяют ответы Api.get_initial и
# Api.poll.
STUB = """<script>
(function () {
  var FONTS = {families: ["Inter", "JetBrains Mono", "Noto Sans"], mono: ["JetBrains Mono"],
               count: 3, folder: "C:\\\\Synfronia\\\\fonts"};
  var state = {lang: "%(lang)s", css: "", fontsRev: 0, dl: null,
               // ответ poll() для кнопки «Скачать»: сценарий задаёт probe.dl
               dlState: {busy: false, status: "", result: null,
                         progress: {mode: "determinate", value: 0}},
               settingsOpen: %(settings_open)s, saved: [], dest: "", logs: []};
  var settings = __SETTINGS__;
  function ok(r) { return Promise.resolve(r === undefined ? {} : r); }
  function uiState() {
    return {lang: state.lang, theme: settings.theme, ui_rev: 1, settings: settings,
            fonts_rev: state.fontsRev};
  }
  window.pywebview = {api: {
    get_initial: function () { return Promise.resolve({settings: settings, ffmpeg: true,
      default_dir: settings.dest, transcoders: ["libx265", "nvenc"], fonts: FONTS,
      settings_open: state.settingsOpen}); },
    poll: function () { return Promise.resolve(Object.assign({
      logs: state.logs, log_cursor: state.logs.length,
      ffmpeg: {downloading: false, extracting: false, pct: 0, ok: true, error: null},
      fonts_dl: {downloading: false, pct: 0, error: null}}, uiState(), state.dlState)); },
    synf_settings_state: function (open) { state.settingsOpen = !!open; return ok(); },
    set_dest: function (path) { state.dest = path; return ok(); },
    set_font: function () { return ok({css: state.css}); },
    reload_fonts: function () { return ok({fonts: FONTS, css: state.css}); },
    font_face_css: function () { return ok(state.css); },
    download_fonts: function () { state.dl = "started"; return ok("started"); },
    download_themes: function () { return ok({added: ["scary_forest"], skipped: [], failed: []}); },
    apply_theme_css: function () { return ok(); },
    set_theme: function (id) { settings.theme = id; state.saved.push(["theme", id]); return ok("ok"); },
    switch_theme: function () { return ok(); },
    // как настоящий reload_themes: отдаём перечитанный список тем
    reload_themes: function () { return ok(Object.assign({}, THEMES)); },
    set_language: function (lang) { settings.language = lang; return ok(); },
    save_setting: function (key, value) { state.saved.push([key, value]); return ok(); },
    start_download: function () { return ok({}); },
    stop_download: function () { return ok(); },
    browse_folder: function () { return ok("C:\\\\Downloads"); },
    test_ftp: function () { return ok({error: "test"}); },
    open_fonts_folder: function () { return ok(); },
    open_themes_folder: function () { return ok(); }
  }};
  window.__probe = state;
})();
</script>
"""


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
    stub = stub.replace("__SETTINGS__", stub_settings(lang))
    return out[:idx] + stub + out[idx:]


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a]
    theme, lang = "scarred_mind", "ru"
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
        elif args[i] == "--settings":
            settings_open = True
            i += 1
        elif args[i] == "--page":
            raise SystemExit("страница одна: карточка настроек открывается флагом --settings")
        else:
            out = Path(args[i])
            i += 1
    out = out or Path(tempfile.gettempdir()) / "synf_probe_page.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page_with_stub(theme=theme, lang=lang, settings_open=settings_open),
                   encoding="utf-8")
    print(f"{out} (карточка настроек={'открыта' if settings_open else 'закрыта'}, "
          f"тема={theme}, язык={lang})")
    return 0



if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
