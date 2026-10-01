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

    Разбор «тёмного окна» начинается отсюда: свежий дамп Crashpad, модуль и
    исключение из него (по модулю видно, что виновато - наше окно, Chromium
    или чужой внедрённый хук) и число LiveKernelEvent за последний час
    (здоровье GPU-движка системы). PowerShell ограничен таймаутом:
    диагностика не должна подвешивать надзор окна.
    """
    dump = newest_crash_dump()
    return (f"{_crash_dump_info(dump)}; {minidump_fault_line(dump)}; "
            f"LiveKernelEvent за час: {_live_kernel_count()}")


def newest_crash_dump() -> Path | None:
    """Свежий дамп Crashpad профиля приложения (None, если их нет)."""
    reports = (Path(os.environ.get("LOCALAPPDATA", str(base_dir())))
               / "Synfronia" / "webview" / "EBWebView" / "Crashpad" / "reports")
    try:
        dumps = list(reports.glob("*.dmp"))
    except OSError:
        return None
    if not dumps:
        return None
    return max(dumps, key=lambda p: p.stat().st_mtime)


def minidump_fault(path) -> dict | None:
    r"""Разбор minidump: код исключения, адрес и модуль падения.

    Дампы Crashpad читаем без сторонних библиотек: заголовок MDMP -> каталог
    потоков -> ExceptionStream (тип 6) и ModuleListStream (тип 4). Модуль
    падения - тот, чей диапазон BaseOfImage..+SizeOfImage содержит адрес
    исключения: по нему видно, что виновато - наше окно, Chromium или чужая
    DLL (внедрённый хук). Возвращает dict либо None, если дамп не разобрать
    (битый/чужой формат) - вызывающий код обязан переживать это.
    """
    import struct

    try:
        with open(path, "rb") as fh:
            data = fh.read()
        if data[:4] != b"MDMP":
            return None
        u32 = lambda o: struct.unpack_from("<I", data, o)[0]
        u64 = lambda o: struct.unpack_from("<Q", data, o)[0]
        n_streams, dir_rva = u32(8), u32(12)
        streams = {}
        for i in range(n_streams):
            o = dir_rva + i * 12
            streams[u32(o)] = u32(o + 8)
        out: dict = {}
        if 6 in streams:
            er = streams[6] + 8        # MINIDUMP_EXCEPTION_STREAM: ThreadId+align
            out["code"] = u32(er)      # ExceptionRecord.ExceptionCode
            out["address"] = u64(er + 16)
        if 4 in streams and "address" in out:
            rva = streams[4]
            for i in range(u32(rva)):
                o = rva + 4 + i * 108
                base, size, name_rva = u64(o), u32(o + 8), u32(o + 20)
                if base <= out["address"] < base + size:
                    out["module"] = _dump_string(data, name_rva)
                    out["offset"] = out["address"] - base
                    break
        return out or None
    except (OSError, struct.error, ValueError):
        return None


def _dump_string(data: bytes, rva: int) -> str:
    """MINIDUMP_STRING: длина в байтах, затем UTF-16 без терминатора."""
    import struct

    ln = struct.unpack_from("<I", data, rva)[0]
    return data[rva + 4:rva + 4 + ln].decode("utf-16le", "replace").rstrip("\x00")


_EXC_NAMES = {0xC0000005: "ACCESS_VIOLATION", 0xC0000008: "INVALID_HANDLE",
              0xC0000409: "STACK_OVERRUN", 0x80000003: "BREAKPOINT",
              0xC000001D: "ILLEGAL_INSTRUCTION", 0xC00000FD: "STACK_OVERFLOW",
              0xC0000374: "HEAP_CORRUPTION", 0x40000015: "FATAL_APP_EXIT"}


def minidump_fault_line(path) -> str:
    """Строка «модуль: X (+0xY), исключение: Z» для журнала следов."""
    if not path:
        return "дампа нет"
    f = minidump_fault(path)
    if not f:
        return "дамп не разобран"
    module = f.get("module") or "модуль не определён"
    offset = f.get("offset", 0)
    code = f.get("code", 0)
    name = _EXC_NAMES.get(code, "0x%08X" % code)
    if f.get("module"):
        module = f"{module} (+0x{offset:x})"
    return f"модуль: {module}, исключение: {name}"


def _crash_dump_info(path) -> str:
    """Имя свежего дампа и его возраст."""
    if not path:
        return "дамп Crashpad: нет"
    try:
        age = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return "дамп Crashpad: недоступен"
    return f"дамп Crashpad: {path.name} ({age:.0f} c назад)"


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
