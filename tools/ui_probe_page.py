r"""Собирает страницу Synfronia со стабом pywebview для headless-проверок вёрстки.

Зачем: app.js живёт внутри одной <script> и сразу дёргает pywebview.api, поэтому
для проверки разметки нужен настоящий DOM + заглушка API. Стаб подставляется
перед <script> приложения, дальше страницу открывает tools/ui_*.js через CDP.

    python tools/ui_probe_page.py            -> %TEMP%\synf_probe_page.html
    python tools/ui_probe_page.py out.html   -> свой путь
"""

import json
import sys
import tempfile
from pathlib import Path

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
# разметку, а не падение скрипта. Значения повторяют ответы Api.get_initial/poll.
STUB = """<script>
(function () {
  var FONTS = {families: ["Inter", "JetBrains Mono", "Noto Sans"], mono: ["JetBrains Mono"],
               count: 3, folder: "C:\\\\Synfronia\\\\fonts"};
  var state = {lang: "%(lang)s", css: "", fontsRev: 0, dl: null};
  var settings = __SETTINGS__;
  function ok(r) { return Promise.resolve(r === undefined ? {} : r); }
  window.pywebview = {api: {
    get_initial: function () { return Promise.resolve({settings: settings, ffmpeg: true,
      default_dir: settings.dest, transcoders: ["libx265", "nvenc"], fonts: FONTS}); },
    poll: function () { return Promise.resolve({busy: false, status: "", progress: {mode: "determinate", value: 0},
      logs: [], log_cursor: 0, ffmpeg: {downloading: false, extracting: false, pct: 0, ok: true, error: null},
      fonts_dl: {downloading: false, pct: 0, error: null}, fonts_rev: state.fontsRev}); },
    set_font: function () { return ok({css: state.css}); },
    reload_fonts: function () { return ok({fonts: FONTS, css: state.css}); },
    download_fonts: function () { state.dl = "started"; return ok("started"); },
    apply_theme_css: function () { return ok(); },
    switch_theme: function () { return ok(); },
    reload_themes: function () { return ok([]); },
    set_language: function (lang) { settings.language = lang; return ok(); },
    save_setting: function () { return ok(); },
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


def build_page_with_stub(theme: str = "scarred_mind", lang: str = "ru") -> str:
    """Страница приложения со стабом API перед основным <script>."""
    # приложение грузит языковые файлы до сборки страницы: без этого в I18N нет
    # thisLang, список языков в панели пуст и мы меряем не то, что видит юзер
    i18n.load_languages()
    page = build_page(theme)
    marker = "<script>"
    idx = page.find(marker)
    if idx < 0:
        raise SystemExit("build_page: не найден <script> для вставки стаба")
    stub = STUB % {"lang": lang}
    stub = stub.replace("__SETTINGS__", stub_settings(lang))
    return page[:idx] + stub + page[idx:]


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a]
    theme, lang = "scarred_mind", "ru"
    out: Path | None = None
    i = 0
    while i < len(args):
        if args[i] == "--theme":
            theme = args[i + 1] if i + 1 < len(args) else theme
            i += 2
        elif args[i] == "--lang":
            lang = args[i + 1] if i + 1 < len(args) else lang
            i += 2
        else:
            out = Path(args[i])
            i += 1
    out = out or Path(tempfile.gettempdir()) / "synf_probe_page.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page_with_stub(theme=theme, lang=lang), encoding="utf-8")
    print(f"{out} (тема={theme}, язык={lang})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
