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
    """Оркестрация обхода по флагу --bypass. Возвращает контекст или None.

    off - не трогать; on - включить явно; auto - по настройке dpi_orch;
    ask - в терминале диалог невозможен, поэтому ведёт себя как on, но с
    честной строкой в журнале. Что делать потом, решает dpi_after
    (см. dpi.finish): как было / оставить / выключить.
    """
    cfg = dpi.DpiConfig(settings, lang)
    if mode == "off":
        return None
    force = mode in ("on", "ask")
    if mode == "ask":
        log("warning", tr(lang, "sheet.dpi.log.cli_ask"))
    try:
        res = dpi.auto(cfg, log=log, force=force)
    except Exception as exc:  # noqa: BLE001 - обход не должен ломать загрузку
        log("error", str(exc))
        return None
    if not res.get("ok"):
        log("error", res.get("error") or tr(lang, "sheet.dpi.start_fail"))
        return None
    return {"cfg": cfg, "original": res.get("original") or {}} if res.get("started") else None


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
    parser.add_argument("--bypass", choices=("auto", "ask", "on", "off"), default="auto",
                        help="обход блокировок: auto - по настройке dpi_orch, "
                             "ask - как auto, но с пометкой в журнале (в терминале "
                             "диалога нет), on - включить явно, off - не трогать")
    args = parser.parse_args()

    playlist = args.playlist or is_playlist(args.url)

    def _log(level: str, msg: str) -> None:
        print(f"[{level}] {msg}")

    dpi.registry_autofill(on_log=_log)   # свои установки (службы, типовые папки)
    dpi.seed_bundled_bypass(on_log=_log)   # вшитый обход доступен и без графики
    settings = load_settings()
    if dpi.pending_restore():
        # хвост от прерванной загрузки: возвращаем снятое состояние,
        # иначе чужой обход останется выключенным
        dpi.restore(dpi.DpiConfig(settings, args.lang), log=_log)
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
        # оркестрацию закрываем в любом исходе - и после ошибки, и после
        # Ctrl+C: dpi_after решает, вернуть прежнее, оставить своё или
        # погасить всё (тот же путь, что в gui._bypass_end)
        if bypass is not None:
            dpi.finish(bypass["cfg"], log=_log)
    return 0 if not dl.stopped else 1


if __name__ == "__main__":
    sys.exit(main())