"""CLI-обёртка над core.Downloader."""

import argparse
import sys

from core import (
    LANGUAGES,
    QUALITY_FORMATS,
    SUBTITLE_OPTIONS,
    TRANSCODERS,
    Downloader,
    default_download_dir,
    is_playlist,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка видео/плейлистов с YouTube")
    parser.add_argument("url", help="ссылка на видео или плейлист")
    parser.add_argument("--dest", default=str(default_download_dir()), help="папка для сохранения")
    parser.add_argument("--playlist", action="store_true", help="качать весь плейлист целиком")
    parser.add_argument("--no-group", action="store_true", help="не класть плейлист в подпапку")
    parser.add_argument("--subtitles", choices=SUBTITLE_OPTIONS, default="ru")
    parser.add_argument("--quality", choices=QUALITY_FORMATS, default="lossless")
    parser.add_argument("--transcode", choices=TRANSCODERS, default="none",
                        help="перекодировка: none (нет), libx265, nvenc, amf, qsv")
    parser.add_argument("--lang", choices=LANGUAGES, default="ru")
    args = parser.parse_args()

    playlist = args.playlist or is_playlist(args.url)

    def _log(level: str, msg: str) -> None:
        print(f"[{level}] {msg}")

    dl = Downloader(on_log=_log, lang=args.lang)
    dl.download(
        args.url,
        args.dest,
        playlist=playlist,
        group=not args.no_group,
        subtitles=args.subtitles,
        quality=args.quality,
        transcode=args.transcode,
    )
    return 0 if not dl.stopped else 1


if __name__ == "__main__":
    sys.exit(main())