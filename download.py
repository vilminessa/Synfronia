"""CLI-обёртка над core.Downloader."""

import argparse
import sys

from core import Downloader, is_playlist


def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка видео/плейлистов с YouTube")
    parser.add_argument("url", help="ссылка на видео или плейлист")
    parser.add_argument("--dest", default="downloads", help="папка для сохранения")
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="качать весь плейлист целиком",
    )
    args = parser.parse_args()

    playlist = args.playlist or is_playlist(args.url)

    def _log(level: str, msg: str) -> None:
        print(f"[{level}] {msg}")

    dl = Downloader(on_log=_log)
    dl.download(args.url, args.dest, playlist)
    return 0 if not dl.stopped else 1


if __name__ == "__main__":
    sys.exit(main())