"""Настройки: значения по умолчанию, based_settings.json, settings.json."""

import json
import os
import sys
from pathlib import Path

from paths import base_dir


DEFAULT_SETTINGS = {
    "theme": "scarred_mind",
    "subtitles": "en",       # off / ru / en / all
    "quality": "lossless",   # lossless / 8k / 4k / 2k / 1080 / 720 / 480 / 240
    "retries": 10,           # количество повторов при сетевых ошибках (yt-dlp)
    "socket_timeout": 20,    # таймаут сокета в секундах (yt-dlp)
    "transcode": "none",     # none / libx265 / nvenc / amf / qsv
    "group_playlist": True,
    "language": "en",
}


def based_settings() -> dict:
    """Дефолтные настройки из based_settings.json (приоритет: рядом с exe -> рядом
    с кодом -> встроенные). Пользовательские ключи в файле переопределяют дефолты."""
    base = dict(DEFAULT_SETTINGS)
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(base_dir() / "based_settings.json")
    candidates.append(Path(__file__).resolve().parent / "based_settings.json")
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            for key in DEFAULT_SETTINGS:
                if key in data:
                    base[key] = data[key]
            break
    return base


def default_download_dir() -> Path:
    """Базовая папка скачивания — downloads рядом с приложением."""
    return base_dir() / "downloads"


def settings_path() -> Path:
    r"""Путь к файлу настроек: %LOCALAPPDATA%\Synfronia\settings.json."""
    root = Path(os.environ.get("LOCALAPPDATA", str(base_dir()))) / "Synfronia"
    root.mkdir(parents=True, exist_ok=True)
    return root / "settings.json"


def load_settings() -> dict:
    settings = based_settings()
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            if "hevc" in data and "transcode" not in data:
                settings["transcode"] = "libx265" if data["hevc"] else "none"
            for key in DEFAULT_SETTINGS:
                if key in data:
                    settings[key] = data[key]
    except (OSError, json.JSONDecodeError):
        pass
    save_settings(settings)
    return settings


def save_settings(settings: dict) -> None:
    settings_path().write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
