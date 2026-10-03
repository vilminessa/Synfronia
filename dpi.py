r"""Обход блокировок: проверка маршрута и управление zapret.

Модуль самодостаточный: разбор настроек, проверка доступности YouTube,
запуск и остановка winws.exe с повышением прав. Диагностика не поднимается
наружу исключениями - вызывающий получает отчёт (словарь с "ok" и готовым
текстом ошибки) и читает журнал.

Ничего не скачивает и не ставит: папку с zapret (winws.exe и файлы
стратегий) указывает сам пользователь, бинарники в проект не входят -
WinDivert штатно детектируется антивирусами как RiskTool. Если папка
непригодна, причину отдаём текстом, а не падением.

Проверка маршрута - TLS-хендшейк к youtube.com: DPI рвёт рукопожатие,
поэтому по нему и видно, нужен ли обход. Если рукопожатие проходит,
обход не трогаем вовсе.

Плоские имена в settings.json: dpi_auto, dpi_stop_after, dpi_dir,
dpi_mode, dpi_bat, dpi_args, dpi_timeout.
"""

import ctypes
import os
import socket
import ssl
import time
from ctypes import wintypes
from pathlib import Path

from i18n import tr
from settings_schema import value as _value

PROBE_HOST = "www.youtube.com"
PROBE_PORT = 443
PROBE_TIMEOUT = 6.0
WINWS_IMAGE = "winws.exe"


# -- проверка маршрута ----------------------------------------------------
def probe(host: str = PROBE_HOST, port: int = PROBE_PORT,
          timeout: float = PROBE_TIMEOUT) -> bool:
    """True, если по адресу доводится до конца TLS-хендшейк.

    Сертификат не проверяем: важен сам факт прохождения рукопожатия, а не
    чьи-то подписи. Недоступный адрес даёт False, а не исключение - сбои
    сети и обрыв на середине рукопожатия для нас одно и то же.
    """
    try:
        raw = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return False
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    wrapped = None
    try:
        wrapped = ctx.wrap_socket(raw, server_hostname=host)
        return True
    except (OSError, ssl.SSLError):
        return False
    finally:
        # закрытие обёртки закрывает и нижний сокет, поэтому вторую закрываем
        # только если рукопожатие не состоялось
        (wrapped if wrapped is not None else raw).close()


def resolve(data, reachable: bool) -> str:
    """Нужно ли поднимать обход перед загрузкой: "start" или "skip".

    Решалка отдельно от запуска, чтобы её можно было проверить без сети
    и без прав: обход включается только при включённом флажке и закрытом
    маршруте - никаких сюрпризов при работающем YouTube.
    """
    cfg = data if isinstance(data, DpiConfig) else DpiConfig(data)
    if not cfg.auto:
        return "skip"
    return "skip" if reachable else "start"


class DpiConfig:
    """Значения настроек обхода, приведённые к типам схемы."""

    def __init__(self, data: dict | None = None, lang: str = "ru") -> None:
        data = data or {}
        self.lang = lang
        self.auto = bool(_value(data, "dpi.auto"))
        self.stop_after = bool(_value(data, "dpi.stop_after"))
        self.dir = str(_value(data, "dpi.dir") or "")
        self.mode = str(_value(data, "dpi.mode"))
        self.bat = str(_value(data, "dpi.bat") or "")
        self.args = str(_value(data, "dpi.args") or "")
        self.timeout = int(_value(data, "dpi.timeout"))

    def t(self, key: str, **kwargs) -> str:
        return tr(self.lang, key, **kwargs)


def command(cfg: DpiConfig) -> tuple[str, str]:
    """(exe, параметры) для запуска обхода.

    Режим bat: файл стратегии zapret выполняется через cmd - он сам поднимет
    winws.exe со своими аргументами. Режим args: winws.exe напрямую с
    аргументами пользователя. Непригодная папка даёт ValueError с уже
    переведённым текстом: у исключения i18n нет, поэтому текст должен быть
    готов к показу в журнале и в пояснении.
    """
    if not cfg.dir:
        raise ValueError(cfg.t("sheet.dpi.no_dir"))
    root = Path(cfg.dir)
    if not root.is_dir():
        raise ValueError(cfg.t("sheet.dpi.bad_dir", dir=cfg.dir))
    if cfg.mode == "args":
        exe = root / WINWS_IMAGE
        if not exe.is_file():
            raise ValueError(cfg.t("sheet.dpi.no_winws", dir=str(root)))
        return str(exe), cfg.args.strip()
    if not cfg.bat.strip():
        raise ValueError(cfg.t("sheet.dpi.no_bat", name=cfg.bat))
    bat = Path(cfg.bat) if os.path.isabs(cfg.bat) else root / cfg.bat
    if not bat.is_file():
        raise ValueError(cfg.t("sheet.dpi.no_bat", name=str(bat)))
    return os.environ.get("COMSPEC", "cmd.exe"), f'/c "{bat}"'


def status() -> dict:
    r"""{"running": bool, "pid": int|None} по процессу winws.exe.

    Снапшот процессов через toolhelp - без подпроцессов и всплывающих окон
    (тот же приём, что в paths.webview_child_running). Оба режима запуска
    сводятся к одному winws.exe, поэтому статус у них общий.
    """

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
        return {"running": False, "pid": None}
    try:
        entry = _Entry()
        entry.dwSize = ctypes.sizeof(_Entry)
        if not k32.Process32FirstW(snap, ctypes.byref(entry)):
            return {"running": False, "pid": None}
        while True:
            if entry.szExeFile.lower() == WINWS_IMAGE:
                return {"running": True, "pid": int(entry.th32ProcessID)}
            if not k32.Process32NextW(snap, ctypes.byref(entry)):
                return {"running": False, "pid": None}
    finally:
        k32.CloseHandle(snap)


def _elevated(exe: str, params: str) -> bool:
    """Запуск с повышением прав (запрос UAC).

    WinDivert работает только от администратора, поэтому и обход, и его
    остановка идут через runas. False - пользователь отклонил запрос, путь
    не найден или иная ошибка Windows: ShellExecuteW отдаёт код <= 32,
    исключений не бросает.
    """
    shell = ctypes.windll.shell32
    shell.ShellExecuteW.restype = ctypes.c_void_p
    shell.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, ctypes.c_int]
    try:
        code = shell.ShellExecuteW(None, "runas", exe, params, None, 1) or 0
    except (OSError, ValueError):
        return False
    return code > 32


def start(cfg: DpiConfig, log=None, wait: bool = True) -> dict:
    """Поднимает обход и ждёт, пока маршрут откроется.

    {"ok": True} - обход работает (или уже был запущен);
    {"ok": False, "error": ...} - не поднялось, причина готовым текстом.
    """
    st = status()
    if st["running"]:
        if log:
            log("info", cfg.t("sheet.dpi.log.already"))
        return {"ok": True, "pid": st["pid"], "already": True}
    try:
        exe, params = command(cfg)
    except ValueError as exc:
        if log:
            log("error", str(exc))
        return {"ok": False, "error": str(exc)}
    if not _elevated(exe, params):
        err = cfg.t("sheet.dpi.no_uac")
        if log:
            log("error", err)
        return {"ok": False, "error": err}
    if log:
        log("info", cfg.t("sheet.dpi.log.start"))
    if not wait:
        return {"ok": True, "pid": status()["pid"]}
    # драйвер и ловушка поднимаются за доли секунды, но первый проб может
    # пройти мимо - ждём до cfg.timeout, проверяя маршрут каждые полсекунды
    deadline = time.time() + max(5, cfg.timeout)
    while time.time() < deadline:
        if probe():
            return {"ok": True, "pid": status()["pid"]}
        time.sleep(0.5)
    err = cfg.t("sheet.dpi.start_timeout")
    if log:
        log("error", err)
    return {"ok": False, "error": err, "running": status()["running"]}


def stop(cfg: DpiConfig, log=None) -> dict:
    """Гасит обход: taskkill по winws.exe с повышением прав."""
    st = status()
    if not st["running"]:
        if log:
            log("info", cfg.t("sheet.dpi.log.not_running"))
        return {"ok": True, "running": False}
    if not _elevated(os.environ.get("COMSPEC", "cmd.exe"),
                     f"/c taskkill /f /t /im {WINWS_IMAGE}"):
        err = cfg.t("sheet.dpi.no_uac")
        if log:
            log("error", err)
        return {"ok": False, "error": err}
    if log:
        log("info", cfg.t("sheet.dpi.log.stop"))
    for _ in range(10):   # процесс умирает почти сразу, но не обещаем
        if not status()["running"]:
            break
        time.sleep(0.3)
    return {"ok": True, "running": status()["running"]}


# Панель настроек модуля: порядок строк = порядок полей, у флажков и полей
# условия видимости относительные (схема превращает их в абсолютные пути).
_WHEN_AUTO = {"key": "auto", "equals": True}
_WHEN_MODE_BAT = {"key": "mode", "equals": "bat"}
_WHEN_MODE_ARGS = {"key": "mode", "equals": "args"}

SETTINGS = {
    "id": "dpi",
    "label": "sheet.tab.dpi",
    "order": 25,
    "flat_prefix": "dpi_",
    "boxes": {"run": "sheet.dpi.run"},
    "fields": [
        {"key": "auto", "type": "bool", "label": "sheet.dpi.auto",
         "default": False, "check": True, "live": True,
         "title": "sheet.dpi.auto.hint"},
        {"key": "stop_after", "type": "bool", "label": "sheet.dpi.stop_after",
         "default": True, "check": True, "live": True,
         "visible_if": _WHEN_AUTO, "title": "sheet.dpi.stop_after.hint"},
        {"key": "dir", "type": "text", "label": "sheet.dpi.dir", "default": "",
         "placeholder": "C:\\zapret", "live": True, "title": "sheet.dpi.dir.hint"},
        {"key": "mode", "type": "choice_buttons", "label": "sheet.dpi.mode",
         "default": "bat",
         "option_hints": {"bat": "sheet.dpi.mode.bat.hint",
                          "args": "sheet.dpi.mode.args.hint"},
         "options": [["bat", "sheet.dpi.mode.bat"], ["args", "sheet.dpi.mode.args"]],
         "row": 1},
        {"key": "bat", "type": "text", "label": "sheet.dpi.bat",
         "default": "general.bat", "placeholder": "general.bat", "live": True,
         "visible_if": _WHEN_MODE_BAT, "title": "sheet.dpi.bat.hint"},
        {"key": "args", "type": "text", "label": "sheet.dpi.args", "default": "",
         "placeholder": "--wf-tcp=80,443 --filter-udp=443 ...", "live": True,
         "visible_if": _WHEN_MODE_ARGS, "title": "sheet.dpi.args.hint"},
        {"key": "timeout", "type": "int", "label": "sheet.dpi.timeout",
         "default": 45, "min": 5, "max": 300, "step": 5,
         "box": "run", "row": 1, "title": "sheet.dpi.timeout.hint"},
        {"type": "actions", "transient": True, "box": "run", "row": 2,
         "buttons": [
             {"dom": "dpi-probe", "label": "sheet.dpi.probe"},
             {"dom": "dpi-start", "label": "sheet.dpi.start"},
             {"dom": "dpi-stop", "label": "sheet.dpi.stop"},
         ]},
        {"type": "note", "transient": True, "dom": "dpi-note", "box": "run",
         "row": 2, "inline": True},
    ],
}
