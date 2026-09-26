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
    "font_sans": "",          # шрифт интерфейса ("" = системный)
    "font_mono": "",          # моноширинный шрифт ("" = системный)
    # выгрузка на FTP/FTPS (см. ftp.py)
    "ftp_active": False,
    "ftp_mode": "batch",      # batch / per_file
    "ftp_host": "",
    "ftp_port": 21,
    "ftp_user": "anonymous",
    "ftp_password": "",       # хранится в settings.json как есть
    "ftp_tls": False,         # FTPS (явный TLS)
    "ftp_tls_verify": True,
    "ftp_pasv": True,         # пассивный режим
    "ftp_dir": "",
    "ftp_template": "{title}{ext}",
    "ftp_delete_local": False,
    "ftp_timeout": 60,
    "ftp_retries": 3,
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
    """Читает settings.json поверх based_settings.json.

    Файл переписывается только когда это нужно: его нет, он битый,
    в нём не хватает новых ключей или старая опция hevc ещё не переведена
    в transcode. Обычное чтение файл не трогает.
    """
    settings = based_settings()
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    if not isinstance(data, dict):
        save_settings(settings)
        return settings
    legacy = "hevc" in data and "transcode" not in data
    if legacy:
        settings["transcode"] = "libx265" if data["hevc"] else "none"
    for key in DEFAULT_SETTINGS:
        if key in data:
            settings[key] = data[key]
    if legacy or any(key not in data for key in DEFAULT_SETTINGS):
        save_settings(settings)  # миграция: дописываем недостающие ключи
    return settings


def save_settings(settings: dict) -> None:
    settings_path().write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
