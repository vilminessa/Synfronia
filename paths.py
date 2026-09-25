r"""Пути приложения и файловый лог.

Общие для всех модулей locations:
  base_dir()          — папка приложения (exe или исходники);
  ffmpeg_local_dir()  — %LOCALAPPDATA%\Synfronia\bin (ffmpeg);
  logs_dir()          — %LOCALAPPDATA%\Synfronia\logs;
"""

import os
import sys
import threading
import time
from pathlib import Path


# -- пути и логи --------------------------------------------------------------
def base_dir() -> Path:
    """Папка приложения: рядом с exe (frozen) или с исходниками."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ffmpeg_local_dir() -> Path:
    r"""Каталог, куда приложение скачивает ffmpeg: %LOCALAPPDATA%\Synfronia\bin."""
    return Path(os.environ.get("LOCALAPPDATA", str(base_dir()))) / "Synfronia" / "bin"


def logs_dir() -> Path:
    r"""Каталог логов: %LOCALAPPDATA%\Synfronia\logs."""
    return Path(os.environ.get("LOCALAPPDATA", str(base_dir()))) / "Synfronia" / "logs"


_LOG_LOCK = threading.Lock()


def _file_log(level: str, msg: str) -> None:
    r"""Дописывает строку в дневной лог-файл: %LOCALAPPDATA%\Synfronia\logs\app_YYYY-MM-DD.log."""
    try:
        logs_dir().mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    day = time.strftime("%Y-%m-%d")
    path = logs_dir() / f"app_{day}.log"
    try:
        with _LOG_LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"[{stamp}] [{level}] {msg}\n")
    except OSError:
        pass
