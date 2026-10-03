"""CLI-обёртка над core.Downloader."""

import argparse
import sys

import dpi
from core import (
    LANGUAGES,
    QUALITY_FORMATS,
    SUBTITLE_OPTIONS,
    TRANSCODERS,
    Downloader,
    FtpConfig,
    default_download_dir,
    is_playlist,
    load_settings,
    tr,
)


def _raise_bypass(mode: str, settings: dict, lang: str, log):
    """Поднимает обход по флагу --bypass. Возвращает конфиг для гашения или None.

    auto - только по настройке dpi_auto и только когда маршрут закрыт;
    on - поднять явно, даже если YouTube уже открыт; off - не трогать.
    Ошибка запуска не роняет загрузку: причину пишем в журнал и идём дальше.
    """
    cfg = dpi.DpiConfig(settings, lang)
    if mode == "off" or (mode == "auto" and not cfg.auto):
        return None
    if mode == "auto" and dpi.probe():
        log("info", tr(lang, "sheet.dpi.log.ok"))
        return None
    res = dpi.start(cfg, log=log)
    if res.get("ok"):
        return cfg
    log("error", res.get("error") or tr(lang, "sheet.dpi.start_fail"))
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка видео/плейлистов с YouTube")
    parser.add_argument("url", help="ссылка на видео или плейлист")
    parser.add_argument("--dest", default=str(default_download_dir()), help="папка для сохранения")
    parser.add_argument("--playlist", action="store_true", help="качать весь плейлист целиком")
    parser.add_argument("--no-group", action="store_true", help="не класть плейлист в подпапку")
    parser.add_argument("--subtitles", choices=SUBTITLE_OPTIONS, default="en")
    parser.add_argument("--quality", choices=QUALITY_FORMATS, default="lossless")
    parser.add_argument("--transcode", choices=TRANSCODERS, default="none",
                        help="перекодировка: none (нет), libx265, nvenc, amf, qsv")
    parser.add_argument("--lang", choices=LANGUAGES, default="en")
    parser.add_argument("--no-ftp", action="store_true",
                        help="не выгружать на FTP, даже если он включён в настройках")
    parser.add_argument("--bypass", choices=("auto", "on", "off"), default="auto",
                        help="обход блокировок: auto - по настройке dpi_auto и только "
                             "когда YouTube закрыт, on - поднять явно, off - не трогать")
    args = parser.parse_args()

    playlist = args.playlist or is_playlist(args.url)

    def _log(level: str, msg: str) -> None:
        print(f"[{level}] {msg}")

    settings = load_settings()
    ftp = None
    if not args.no_ftp:
        ftp = FtpConfig(settings, args.lang)
        if not ftp.enabled and settings.get("ftp_active"):
            print(f"[warning] {tr(args.lang, 'ftp.no_host')}")

    dl = Downloader(on_log=_log, lang=args.lang)
    bypass = _raise_bypass(args.bypass, settings, args.lang, _log)
    try:
        dl.download(
            args.url,
            args.dest,
            playlist=playlist,
            group=not args.no_group,
            subtitles=args.subtitles,
            quality=args.quality,
            transcode=args.transcode,
            ftp=ftp,
        )
    finally:
        # обход гасим в любом исходе: и после ошибки, и после Ctrl+C
        if bypass is not None:
            dpi.stop(bypass, log=_log)
    return 0 if not dl.stopped else 1


if __name__ == "__main__":
    sys.exit(main())