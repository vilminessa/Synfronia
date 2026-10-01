r"""Пути приложения и файловый лог.

Общие для всех модулей locations:
  base_dir()          — папка приложения (exe или исходники);
  ffmpeg_local_dir()  — %LOCALAPPDATA%\Synfronia\bin (ffmpeg);
  logs_dir()          — %LOCALAPPDATA%\Synfronia\logs;
"""

import os
import subprocess
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


def webview_child_running(pid: int) -> bool:
    r"""Есть ли у процесса дочерний msedgewebview2.exe.

    Сигнатура «живого содержимого» окна: окно pywebview создаётся до
    инициализации WebView2 и переживает его краш - если потомка нет,
    пользователь видит тёмное окно без страницы («зависло»). Снапшот
    процессов через toolhelp - без подпроцессов и сторонних библиотек.
    """
    import ctypes
    from ctypes import wintypes

    class _Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == 0xFFFFFFFFFFFFFFFF:
        return False
    try:
        entry = _Entry()
        entry.dwSize = ctypes.sizeof(_Entry)
        if not k32.Process32FirstW(snap, ctypes.byref(entry)):
            return False
        while True:
            if (entry.th32ParentProcessID == pid
                    and entry.szExeFile.lower() == "msedgewebview2.exe"):
                return True
            if not k32.Process32NextW(snap, ctypes.byref(entry)):
                return False
    finally:
        k32.CloseHandle(snap)


def crash_evidence() -> str:
    r"""Следы падения WebView2 одной строкой - для gui_diag.log.

    Разбор «тёмного окна» начинается отсюда: свежий дамп Crashpad (в нём
    причина падения - обычно 0xC0000005 в GPU/ DXGI-пути) и число
    LiveKernelEvent за последний час (здоровье GPU-движка системы, до
    краша WebView2 бывает сломано само). PowerShell ограничен таймаутом:
    диагностика не должна подвешивать надзор окна.
    """
    return f"{_crash_dump_info()}; LiveKernelEvent за час: {_live_kernel_count()}"


def _crash_dump_info() -> str:
    """Самый свежий дамп Crashpad профиля приложения и его возраст."""
    reports = (Path(os.environ.get("LOCALAPPDATA", str(base_dir())))
               / "Synfronia" / "webview" / "EBWebView" / "Crashpad" / "reports")
    try:
        dumps = list(reports.glob("*.dmp"))
        if not dumps:
            return "дамп Crashpad: нет"
        newest = max(dumps, key=lambda p: p.stat().st_mtime)
        age = max(0.0, time.time() - newest.stat().st_mtime)
    except OSError:
        return "дамп Crashpad: недоступен"
    return f"дамп Crashpad: {newest.name} ({age:.0f} c назад)"


def _live_kernel_count(timeout: float = 8.0) -> str:
    """Сколько LiveKernelEvent в журнале Application за час ('n/a' при ошибке)."""
    cmd = ("try { (Get-WinEvent -FilterHashtable @{LogName='Application'; "
           "StartTime=(Get-Date).AddHours(-1)} -ErrorAction Stop | "
           "Where-Object { $_.ProviderName -eq 'Windows Error Reporting' -and "
           "$_.Message -match 'LiveKernelEvent' } | "
           "Measure-Object).Count } catch { 'n/a' }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                             capture_output=True, timeout=timeout)
        return out.stdout.decode("utf-8", "replace").strip() or "n/a"
    except Exception:  # noqa: BLE001 - диагностика не должна ронять надзор
        return "n/a"
