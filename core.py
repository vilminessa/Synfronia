"""Библиотека загрузки: обвязка над yt-dlp с логом, прогрессом и остановкой."""

import json
import os
import re
import shutil
import sys
import threading
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.embedthumbnail import EmbedThumbnailPP
from yt_dlp.postprocessor.ffmpeg import FFmpegEmbedSubtitlePP, FFmpegMetadataPP, FFmpegPostProcessor

_PLAYLIST_RE = re.compile(r"[?&]list=")

# -- темы --------------------------------------------------------------------
THEMES = {
    "scary_forest": {
        "label": "Scary Forest (тёмная)",
        "bg": "#0c1622",
        "surface": "#1f2b29",
        "widget": "#23444b",
        "text": "#dcdedd",
        "accent": "#628d7c",
    },
    "technology_day": {
        "label": "Technology day (тёмно-бирюзовая)",
        "bg": "#00181a",
        "surface": "#00585a",
        "widget": "#003638",
        "text": "#dcdedd",
        "accent": "#00989b",
    },
    "technology_pinks": {
        "label": "Technology Pinks (светлая)",
        "bg": "#ffebec",
        "surface": "#ffcbe2",
        "widget": "#ffffff",
        "text": "#5d2547",
        "accent": "#c15f9b",
    },
}

DEFAULT_SETTINGS = {
    "theme": "scary_forest",
    "subtitles": "ru",       # off / ru / en / all
    "quality": "lossless",   # lossless / 1080 / 720 / 240
    "hevc": False,
    "group_playlist": True,
}

SUBTITLE_OPTIONS = {
    "off": None,
    "ru": ["ru"],
    "en": ["en"],
    "all": ["all"],
}

QUALITY_FORMATS = {
    "lossless": "bv*+ba/b",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]",
    "720": "bv*[height<=720]+ba/b[height<=720]",
    "240": "bv*[height<=240]+ba/b[height<=240]",
}

HEVC_PRESET = "medium"
HEVC_CRF = 23


# -- пути и настройки --------------------------------------------------------
def base_dir() -> Path:
    """Папка приложения: рядом с exe (frozen) или с исходниками."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def default_download_dir() -> Path:
    """Базовая папка скачивания — downloads рядом с приложением."""
    return base_dir() / "downloads"


def settings_path() -> Path:
    return base_dir() / "settings.json"


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in DEFAULT_SETTINGS:
                if key in data:
                    settings[key] = data[key]
    except (OSError, json.JSONDecodeError):
        pass
    return settings


def save_settings(settings: dict) -> None:
    settings_path().write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


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


class HEVCConvertPP(FFmpegPostProcessor):
    """Перекодирует видео в HEVC (H.265): запускается после слияния, до встраивания."""

    def __init__(self, downloader=None):
        super().__init__(downloader)

    @FFmpegPostProcessor._restrict_to(images=False)
    def run(self, info):
        filename = info.get("filepath")
        if not filename or info.get("ext", "").lower() != "mp4":
            self.to_screen("Пропуск HEVC-конвертации: файл не в mp4.")
            return [], info
        temp = f"{filename}.tmp.mp4"
        self.to_screen("Конвертация в HEVC (H.265)...")
        self.run_ffmpeg(
            filename,
            temp,
            [
                "-map", "0",
                "-c:v", "libx265",
                "-tag:v", "hvc1",
                "-preset", HEVC_PRESET,
                "-crf", str(HEVC_CRF),
                "-c:a", "copy",
            ],
        )
        os.replace(temp, filename)
        return [], info


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

    # -- колбэки в yt-dlp -----------------------------------------------------
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
                    "msg": "Постобработка (ffmpeg: слияние/HEVC/метаданные/субтитры/обложка)...",
                }
            )

    # -- опции yt-dlp ---------------------------------------------------------
    def _build_opts(
        self,
        dest: str,
        playlist: bool,
        group: bool,
        subtitles: str,
        quality: str,
    ) -> dict:
        if playlist and group:
            outtmpl = os.path.join(dest, "%(playlist_title)s", "%(title)s [%(id)s].%(ext)s")
        else:
            outtmpl = os.path.join(dest, "%(title)s [%(id)s].%(ext)s")

        subs_langs = SUBTITLE_OPTIONS.get(subtitles)
        opts = {
            "outtmpl": outtmpl,
            "format": QUALITY_FORMATS.get(quality, QUALITY_FORMATS["lossless"]),
            "merge_output_format": "mp4",
            "restrictfilenames": True,
            "noplaylist": not playlist,
            "overwrites": True,
            "noprogress": True,
            "writethumbnail": True,
            "logger": self._Logger(self),
            "progress_hooks": [self._hook],
            "ignoreerrors": True,
        }
        if subs_langs:
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = True
            opts["subtitleslangs"] = subs_langs
        return opts

    def _add_ffmpeg(self, opts: dict) -> dict:
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        else:
            self._log("warning", "ffmpeg не найден: слияние/субтитры/метаданные будут недоступны.")
        return opts

    def _register_pps(self, ydl: YoutubeDL, subs_on: bool, hevc: bool) -> None:
        if hevc:
            ydl.add_post_processor(HEVCConvertPP(ydl))
        if subs_on:
            ydl.add_post_processor(FFmpegEmbedSubtitlePP(ydl))
        ydl.add_post_processor(FFmpegMetadataPP(ydl))
        ydl.add_post_processor(EmbedThumbnailPP(ydl))

    # -- запуск ---------------------------------------------------------------
    def download(
        self,
        url: str,
        dest: str,
        playlist: bool = False,
        group: bool = True,
        subtitles: str = "ru",
        quality: str = "lossless",
        hevc: bool = False,
    ) -> None:
        os.makedirs(dest, exist_ok=True)
        opts = self._build_opts(dest, playlist, group, subtitles, quality)
        subs_on = bool(SUBTITLE_OPTIONS.get(subtitles))
        self._log("info", f"Режим: {'плейлист' if playlist else 'одно видео'} "
                          f"(группировка {'вкл' if playlist and group else 'выкл'})")
        if hevc:
            self._log("info", "HEVC: видео будет перекодировано в H.265.")
        try:
            with YoutubeDL(self._add_ffmpeg(opts)) as ydl:
                self._register_pps(ydl, subs_on, hevc)
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
    parser.add_argument("--dest", default=str(default_download_dir()))
    parser.add_argument("--playlist", action="store_true")
    parser.add_argument("--no-group", action="store_true")
    parser.add_argument("--subtitles", choices=list(SUBTITLE_OPTIONS), default="ru")
    parser.add_argument("--quality", choices=list(QUALITY_FORMATS), default="lossless")
    parser.add_argument("--hevc", action="store_true")
    args = parser.parse_args()

    def _log(level, msg):
        print(f"[{level}] {msg}")

    dl = Downloader(on_log=_log)
    dl.download(
        args.url, args.dest,
        playlist=args.playlist,
        group=not args.no_group,
        subtitles=args.subtitles,
        quality=args.quality,
        hevc=args.hevc,
    )