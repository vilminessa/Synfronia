r"""Собирает страницу Synfronia со стабом pywebview для headless-проверок вёрстки.

Зачем: app.js и settings.js живут внутри <script> и сразу дёргают pywebview.api,
поэтому для проверки разметки нужен настоящий DOM + заглушка API. Стаб
подставляется перед первым <script>, дальше страницу открывает tools/ui_*.js
через CDP. Обе страницы (главная и окно настроек) проверяются одним стабом:
методы лишнего окна просто не вызываются.

    python tools/ui_probe_page.py                      -> %TEMP%\synf_probe_page.html
    python tools/ui_probe_page.py out.html             -> свой путь
    python tools/ui_probe_page.py --page settings      -> окно настроек
    python tools/ui_probe_page.py --page main --theme liquid_glass --lang de
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
from themes import build_page, build_settings_page  # noqa: E402

# Настройки в стабе берём из схемы: так пробник проверяет настоящие умолчания,
# а не отдельный список (он уже расходился с приложением).
def stub_settings(lang: str) -> str:
    data = {**settings_schema.defaults(), "dest": r"C:\Downloads", "language": lang}
    return json.dumps(data, ensure_ascii=False).replace("\\", "\\\\")


# Стаб API: init() и tick() должны пройти целиком, чтобы мы мерили реальную
# разметку, а не падение скрипта. Значения повторяют ответы Api.get_initial,
# Api.poll и Api.poll_settings.
STUB = """<script>
(function () {
  var FONTS = {families: ["Inter", "JetBrains Mono", "Noto Sans"], mono: ["JetBrains Mono"],
               count: 3, folder: "C:\\\\Synfronia\\\\fonts"};
  var state = {lang: "%(lang)s", css: "", fontsRev: 0, dl: null, page: "%(page)s",
               // ответ poll() для кнопки «Скачать»: сценарий задаёт probe.dl
               dlState: {busy: false, status: "", result: null,
                         progress: {mode: "determinate", value: 0}},
               settingsOpen: %(settings_open)s, saved: [], dest: "", logs: []};
  var settings = __SETTINGS__;
  function ok(r) { return Promise.resolve(r === undefined ? {} : r); }
  function uiState() {
    return {lang: state.lang, theme: settings.theme, ui_rev: 1,
            settings_open: state.settingsOpen, fonts_rev: state.fontsRev};
  }
  window.pywebview = {api: {
    get_initial: function () { return Promise.resolve({settings: settings, ffmpeg: true,
      default_dir: settings.dest, transcoders: ["libx265", "nvenc"], fonts: FONTS}); },
    poll: function () { return Promise.resolve(Object.assign({
      logs: [], log_cursor: 0, ffmpeg: {downloading: false, extracting: false, pct: 0, ok: true, error: null},
      fonts_dl: {downloading: false, pct: 0, error: null}}, uiState(), state.dlState)); },
    poll_settings: function () { return Promise.resolve(Object.assign({
      logs: state.logs || [], log_cursor: (state.logs || []).length,
      fonts_dl: {downloading: false, pct: 0, error: null}}, uiState())); },
    open_settings: function () { state.settingsOpen = true; return ok("created"); },
    close_settings: function () { state.settingsOpen = false; return ok(); },
    set_dest: function (path) { state.dest = path; return ok(); },
    set_font: function () { return ok({css: state.css}); },
    reload_fonts: function () { return ok({fonts: FONTS, css: state.css}); },
    font_face_css: function () { return ok(state.css); },
    download_fonts: function () { state.dl = "started"; return ok("started"); },
    apply_theme_css: function () { return ok(); },
    set_theme: function () { return ok("ok"); },
    switch_theme: function () { return ok(); },
    reload_themes: function () { return ok([]); },
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
                         page: str = "main") -> str:
    """Страница приложения (главная или окно настроек) со стабом API."""
    # приложение грузит языковые файлы до сборки страницы: без этого в I18N нет
    # thisLang, список языков в окне настроек пуст и мы меряем не то, что видит юзер
    i18n.load_languages()
    builder = build_settings_page if page == "settings" else build_page
    out = builder(theme)
    marker = "<script>"
    idx = out.find(marker)
    if idx < 0:
        raise SystemExit(f"{page}: не найден <script> для вставки стаба")
    stub = STUB % {"lang": lang, "page": page,
                   "settings_open": "false" if page == "main" else "true"}
    stub = stub.replace("__SETTINGS__", stub_settings(lang))
    return out[:idx] + stub + out[idx:]


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a]
    theme, lang, page = "scarred_mind", "ru", "main"
    out: Path | None = None
    i = 0
    while i < len(args):
        if args[i] == "--theme":
            theme = args[i + 1] if i + 1 < len(args) else theme
            i += 2
        elif args[i] == "--lang":
            lang = args[i + 1] if i + 1 < len(args) else lang
            i += 2
        elif args[i] == "--page":
            page = args[i + 1] if i + 1 < len(args) else page
            i += 2
        else:
            out = Path(args[i])
            i += 1
    if page not in ("main", "settings"):
        raise SystemExit(f"неизвестная страница: {page} (main или settings)")
    default_name = "synf_probe_page.html" if page == "main" else "synf_probe_settings.html"
    out = out or Path(tempfile.gettempdir()) / default_name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page_with_stub(theme=theme, lang=lang, page=page), encoding="utf-8")
    print(f"{out} (страница={page}, тема={theme}, язык={lang})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
