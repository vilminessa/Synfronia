"""Настройки: based_settings.json, settings.json, переносы старых ключей.

Что за настройки бывают, какие у них типы и границы - описано в
settings_schema: там же лежат фрагменты модулей (ftp.py, downloader.py).
Этот модуль отвечает только за пути файлов, чтение, запись и переносы.
"""

import json
import os
import sys
from pathlib import Path

import settings_schema
from paths import base_dir
from version import __version__

# Переносы старых ключей в новые: (старый, новый, значение по старому ключу).
MIGRATIONS = (
    ("hevc", "transcode", lambda value: "libx265" if value else "none"),
    # Оркестрация обхода вместо «вкл/выкл»: старое поведение сохраняется,
    # но у новых установок уже спрашивают, а не вмешиваются молча.
    ("dpi_auto", "dpi_orch", lambda value: "auto" if value else "off"),
    ("dpi_stop_after", "dpi_after", lambda value: "restore" if value else "keep"),
)


def based_settings() -> dict:
    """Дефолтные настройки из based_settings.json (приоритет: рядом с exe -> рядом
    с кодом -> встроенные). Пользовательские ключи в файле переопределяют дефолты."""
    base = settings_schema.defaults()
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
            for key in list(base):
                if key in data:
                    base[key] = settings_schema.coerce(key, data[key])
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
    """Читает settings.json поверх based_settings.json, приводя значения к типам.

    Файл переписывается только когда это нужно: его нет, он битый, в нём не
    хватает новых ключей, в нём остался старый переносимый ключ или значение
    не совпадает с типом из схемы. Обычное чтение файл не трогает.
    """
    settings = based_settings()
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    if not isinstance(data, dict):
        save_settings(settings)
        return settings
    changed = False
    for old, new, mapper in MIGRATIONS:
        if old in data and new not in data:
            data[new] = mapper(data[old])
            changed = True
    for key in list(settings):
        if key not in data:
            changed = True
            continue
        fixed = settings_schema.coerce(key, data[key])
        if fixed != data[key]:
            changed = True  # например, retries: 999 -> 50
        settings[key] = fixed
    # Версия, записавшая настройки: поднимаем молча (без логов), чтобы
    # settings.json всегда знал, какой версией он последний раз сохранён.
    if settings.get("app_version") != __version__:
        settings["app_version"] = __version__
        changed = True
    if changed:
        save_settings(settings)  # миграция: дописываем и чиним значения
    return settings


def save_settings(settings: dict) -> None:
    """Записывает настройки, оставляя в файле только ключи, известные схеме."""
    clean = {}
    for key in settings_schema.defaults():
        if key in settings:
            clean[key] = settings_schema.coerce(key, settings[key])
    settings_path().write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
