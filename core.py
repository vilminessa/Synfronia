"""Общий API Synfronia — фасад над модулями.

Логика разложена по файлам:
  paths.py      — пути приложения и файловый лог;
  settings.py   — настройки (based_settings.json / settings.json);
  i18n.py       — переводы и языковые файлы;
  themes.py     — модульные темы и сборка страницы;
  fonts.py      — модульные шрифты из папки fonts (@font-face, data:URI);
  ftp.py        — выгрузка готовых файлов на FTP/FTPS;
  downloader.py — загрузка через yt-dlp, постпроцессоры, ffmpeg.

Этот файл только реэкспортирует имена, чтобы `from core import ...`
продолжал работать (gui.py, download.py, `python core.py`).
"""

from downloader import (
    ENCODER_NAMES,
    FFMPEG_DOWNLOAD_URL,
    QUALITY_FORMATS,
    QUALITY_LIMITS,
    SUBTITLE_OPTIONS,
    TRANSCODERS,
    Downloader,
    QualitySuffixPP,
    TranscodePP,
    _StopDownload,
    available_transcoders,
    download_ffmpeg,
    find_ffmpeg,
    is_playlist,
)
from fonts import (
    FONT_FORMATS,
    MAX_FONT_BYTES,
    _fonts_root,
    font_css,
    font_vars,
    fonts_embed,
    load_fonts,
    seed_bundled_fonts,
)
from ftp import (
    DEFAULT_TEMPLATE,
    TEMPLATE_FIELDS,
    FtpConfig,
    FtpError,
    clean_name,
    render_name,
    render_path,
    test_connection,
    upload_files,
)
from i18n import I18N, LANGUAGES, SELF_NAMES, _lang_root, load_languages, tr
from paths import _file_log, base_dir, ffmpeg_local_dir, logs_dir
from settings import (
    DEFAULT_SETTINGS,
    based_settings,
    default_download_dir,
    load_settings,
    save_settings,
    settings_path,
)
from themes import (
    THEMES,
    _THEME_DEFAULTS,
    _themes_root,
    build_page,
    load_themes,
    themes_embed,
)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Загрузка через core.py")
    parser.add_argument("url")
    parser.add_argument("--dest", default=str(default_download_dir()))
    parser.add_argument("--playlist", action="store_true")
    parser.add_argument("--no-group", action="store_true")
    parser.add_argument("--subtitles", choices=list(SUBTITLE_OPTIONS), default="en")
    parser.add_argument("--quality", choices=list(QUALITY_FORMATS), default="lossless")
    parser.add_argument("--transcode", choices=list(TRANSCODERS), default="none")
    parser.add_argument("--lang", choices=list(LANGUAGES), default="en")
    args = parser.parse_args()

    def _log(level, msg):
        print(f"[{level}] {msg}")

    dl = Downloader(on_log=_log, lang=args.lang)
    dl.download(
        args.url, args.dest,
        playlist=args.playlist,
        group=not args.no_group,
        subtitles=args.subtitles,
        quality=args.quality,
        transcode=args.transcode,
    )
