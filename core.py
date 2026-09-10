"""Библиотека загрузки: обвязка над yt-dlp с логом, прогрессом и остановкой."""

import os
import re
import shutil
import threading
from pathlib import Path

from yt_dlp import YoutubeDL

_PLAYLIST_RE = re.compile(r"[?&]list=")

SUBTITLE_LANGS = ["ru"]


def find_ffmpeg() -> str | None:
    """Ищет ffmpeg в PATH и типовых местах установки (например, winget)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    candidates = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/ffmpeg.exe",
        Path(os.environ.get("ProgramFiles", "")) / "ffmpeg/bin/ffmpeg.exe",
    )
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def is_playlist(url: str) -> bool:
    """Простая эвристика: признак ссылки на плейлист по ?list=."""
    return bool(_PLAYLIST_RE.search(url or ""))


class _StopDownload(Exception):
    pass


class Downloader:
    """Запускает yt-dlp в рабочем потоке и стучится в UI через колбэки."""

    def __init__(self, on_log=None, on_progress=None):
        self._on_log = on_log or (lambda *_: None)
        self._on_progress = on_progress or (lambda *_: None)
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    # -- колбэки в yt-dlp ---------------------------------------------------
    def _log(self, level: str, msg: str) -> None:
        self._on_log(level, msg)

    class _Logger:
        def __init__(self, owner: "Downloader"):
            self._owner = owner

        def debug(self, msg): self._owner._log("debug", msg)
        def info(self, msg): self._owner._log("info", msg)
        def warning(self, msg): self._owner._log("warning", msg)
        def error(self, msg): self._owner._log("error", msg)

    def _hook(self, d: dict) -> None:
        if self._stop.is_set():
            raise _StopDownload()
        status = d.get("status")
        if status in ("downloading", "finished"):
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            recvd = d.get("downloaded_bytes") or 0
            percent = (recvd / total * 100) if total else None
            self._on_progress(
                {
                    "status": status,
                    "filename": os.path.basename(d.get("filename") or ""),
                    "downloaded": recvd,
                    "total": total,
                    "percent": percent,
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                }
            )
        elif status == "postprocessing":
            self._on_progress(
                {
                    "status": "postprocessing",
                    "filename": "",
                    "percent": None,
                    "msg": "Постобработка (ffmpeg: слияние/метаданные/субтитры/обложка)...",
                }
            )

    # -- опции yt-dlp --------------------------------------------------------
    def _build_opts(self, dest: str, playlist: bool) -> dict:
        if playlist:
            outtmpl = os.path.join(dest, "%(playlist_title)s", "%(title)s [%(id)s].%(ext)s")
        else:
            outtmpl = os.path.join(dest, "%(title)s [%(id)s].%(ext)s")
        return {
            "outtmpl": outtmpl,
            "format": "bv*[height<=1080]+ba/b[height<=1080]",
            "merge_output_format": "mp4",
            "restrictfilenames": True,
            "noplaylist": not playlist,
            "overwrites": True,
            "noprogress": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": SUBTITLE_LANGS,
            "writethumbnail": True,
            "postprocessors": [
                {"key": "FFmpegEmbedSubtitle"},
                {"key": "FFmpegMetadata"},
                {"key": "EmbedThumbnail"},
            ],
            "logger": self._Logger(self),
            "progress_hooks": [self._hook],
            "ignoreerrors": True,
        }

    def _add_ffmpeg(self, opts: dict) -> dict:
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        else:
            self._log("warning", "ffmpeg не найден: слияние/субтитры/метаданные будут недоступны.")
        return opts

    # -- запуск --------------------------------------------------------------
    def download(self, url: str, dest: str, playlist: bool = False) -> None:
        os.makedirs(dest, exist_ok=True)
        playlist = playlist or is_playlist(url)
        self._log("info", f"Режим: {'плейлист целиком' if playlist else 'одно видео'}")
        try:
            with YoutubeDL(self._add_ffmpeg(self._build_opts(dest, playlist))) as ydl:
                info = ydl.extract_info(url, download=True)
                short = None
                if info and info.get("_type") == "playlist":
                    done = [e for e in info.get("entries", []) if e]
                    short = f"Готово: {len(done)} видео -> {os.path.basename(dest)}"
                elif info:
                    short = f"Готово: {info.get('title', '?')}"
                if short:
                    self._log("info", short)
        except _StopDownload:
            self._log("warning", "Загрузка отменена пользователем.")
        except Exception as exc:  # noqa: BLE001
            self._log("error", f"Ошибка: {exc}")
        finally:
            self._stop.clear()
            self._on_progress({"status": "done"})


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Загрузка через core.py")
    parser.add_argument("url")
    parser.add_argument("--dest", default="downloads")
    parser.add_argument("--playlist", action="store_true")
    args = parser.parse_args()

    def _log(level, msg):
        print(f"[{level}] {msg}")

    dl = Downloader(on_log=_log)
    dl.download(args.url, args.dest, args.playlist)