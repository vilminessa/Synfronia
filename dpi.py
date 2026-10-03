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
import json
import os
import re
import socket
import ssl
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from i18n import tr
from settings_schema import value as _value

PROBE_HOST = "www.youtube.com"
PROBE_PORT = 443
PROBE_TIMEOUT = 6.0
WINWS_IMAGE = "winws.exe"
# Служебная задача планировщика: её регистрация - единственный запрос прав,
# дальше помощник поднимается через schtasks /Run без диалога UAC.
TASK_NAME = "SynfroniaBypass"
RUNNER_NAME = "bypass_runner.ps1"
# MultipleInstances, которым зарегистрирована задача; маркер лежит рядом с
# кэшем - при смене политики задача перерегистрировывается (один запрос прав)
TASK_POLICY = "parallel"


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


def _bat_path(cfg: DpiConfig, bat: str | None = None) -> str:
    """Путь к файлу стратегии с проверками, дающими переведённый текст ошибки.

    Общая для режима bat и для команды запуска: одна и та же проверка папки
    и файла, чтобы отказ приходил ДО запроса прав администратора.
    """
    if not cfg.dir:
        raise ValueError(cfg.t("sheet.dpi.no_dir"))
    root = Path(cfg.dir)
    if not root.is_dir():
        raise ValueError(cfg.t("sheet.dpi.bad_dir", dir=cfg.dir))
    name = (bat or cfg.bat).strip()
    if not name:
        raise ValueError(cfg.t("sheet.dpi.no_bat", name=name))
    path = Path(name) if os.path.isabs(name) else root / name
    if not path.is_file():
        raise ValueError(cfg.t("sheet.dpi.no_bat", name=str(path)))
    return str(path)


def command(cfg: DpiConfig, bat: str | None = None) -> tuple[str, str]:
    """(exe, параметры) для запуска обхода.

    Режим bat: файл стратегии zapret выполняется через cmd - он сам поднимет
    winws.exe со своими аргументами. Режим args: winws.exe напрямую с
    аргументами пользователя. Непригодная папка даёт ValueError с уже
    переведённым текстом: у исключения i18n нет, поэтому текст должен быть
    готов к показу в журнале и в пояснении. bat - запуск конкретного файла
    стратегии (так подбираем рабочую), иначе берётся настройка cfg.bat.
    """
    if cfg.mode == "args":
        if not cfg.dir:
            raise ValueError(cfg.t("sheet.dpi.no_dir"))
        root = Path(cfg.dir)
        if not root.is_dir():
            raise ValueError(cfg.t("sheet.dpi.bad_dir", dir=cfg.dir))
        exe = root / WINWS_IMAGE
        if not exe.is_file():
            raise ValueError(cfg.t("sheet.dpi.no_winws", dir=str(root)))
        return str(exe), cfg.args.strip()
    path = _bat_path(cfg, bat)
    return os.environ.get("COMSPEC", "cmd.exe"), f'/c "{path}"'


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


def _powershell() -> str:
    """Путь к Windows PowerShell: он есть всегда, в отличие от python в сборке."""
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                       r"System32\WindowsPowerShell\v1.0\powershell.exe")
    return exe if os.path.isfile(exe) else "powershell.exe"


def _schtasks() -> str:
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                       "System32", "schtasks.exe")
    return exe if os.path.isfile(exe) else "schtasks.exe"


def _task_exists(name: str = TASK_NAME) -> bool:
    """Есть ли служебная задача: запрос без повышения прав, работает сразу."""
    try:
        out = subprocess.run([_schtasks(), "/Query", "/TN", name],
                             capture_output=True, timeout=25)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def _register_task(runner: Path) -> bool:
    """Регистрирует служебную задачу - ЕДИНСТВЕННЫЙ запрос прав за весь срок.

    После этого помощник запускается через schtasks /Run: служба
    планировщика поднимает его сама, без диалога UAC. Отказ или ошибка =
    False, и вызывающий уходит на запасной путь runas (как до задачи).
    """
    params = (f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
              f'-File "{runner}" -Probe "{runner.parent}" -Register '
              f'-Policy "{TASK_POLICY}"')
    if not _elevated(_powershell(), params):
        return False
    for _ in range(30):   # регистрация быстрая, но ждём с запасом
        if _task_exists() and _task_policy_ok():
            return True
        time.sleep(0.5)
    return _task_exists() and _task_policy_ok()


def _task_policy_ok() -> bool:
    """Задача зарегистрирована текущей политикой инстансов (см. TASK_POLICY)."""
    try:
        text = (_probe_dir() / "task.policy").read_text(encoding="ascii")
    except OSError:
        return False
    return text.strip() == TASK_POLICY


def _trigger() -> bool:
    """Просит планировщик выполнить задачу - уже без запроса прав.

    Перед запуском гасится остаток прошлого раза: если предыдущий экземпляр
    не завершился (PowerShell дожидается дескрипторы дочерних процессов),
    новый уходит в очередь и не стартует вовсе - так уже было на практике.
    Операции у нас строго по одной, поэтому гасить «выполняющееся» безопасно.
    """
    exe = _schtasks()
    try:
        subprocess.run([exe, "/End", "/TN", TASK_NAME], capture_output=True, timeout=25)
        time.sleep(1.0)
        for _ in range(3):
            out = subprocess.run([exe, "/Run", "/TN", TASK_NAME],
                                 capture_output=True, timeout=30)
            if out.returncode == 0:
                return True
            time.sleep(1.5)   # задача ещё не отпустила прошлый экземпляр
    except (OSError, subprocess.SubprocessError):
        return False
    return False


def _write_runner() -> Path:
    """Держит скрипт помощника свежим: задача ссылается на путь, а содержимое
    меняется вместе с кодом."""
    probe_dir = _probe_dir()
    runner = probe_dir / RUNNER_NAME
    try:
        runner.write_text(_RUNNER_SOURCE, encoding="utf-8", newline="\n")
    except OSError:
        pass
    return runner


def _wait_result(probe_dir: Path, token: str, wait: float) -> dict | None:
    """Ждёт итог помощника: файл пишется атомарно (tmp -> move), поэтому
    читабельный JSON уже готовый результат."""
    path = probe_dir / f"result-{token}.json"
    deadline = time.time() + max(5.0, wait)
    while time.time() < deadline:
        data = _read_json(path)
        if data is not None:
            try:
                path.unlink()
            except OSError:
                pass
            return data
        time.sleep(0.3)
    return None


def _run_action(cfg: DpiConfig, action: str, payload: dict, wait: float,
                log=None) -> dict | None:
    """Одна операция, требующая прав. Итог придёт файлом result-<token>.json.

    Путь запуска: задача есть -> schtasks /Run (без UAC); нет -> регистрация
    (один UAC на весь срок службы); и от неё отказались -> runas, как раньше.
    None = запустить помощника не удалось вообще.
    """
    runner = _write_runner()
    probe_dir = runner.parent
    for stale in list(probe_dir.glob("result-*.json*")) + [probe_dir / "runner.log"]:
        try:
            stale.unlink()
        except OSError:
            pass
    token = str(int(time.time() * 1000))
    req = {"action": action, "token": token, "root": cfg.dir, "target": PROBE_HOST,
           "bat": "", "exe": "", "args": "", "configs": []}
    req.update(payload)
    try:
        (probe_dir / "request.json").write_text(
            json.dumps(req, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        if log:
            log("error", str(exc))
        return {"ok": False, "error": str(exc)}
    if _task_exists() and _task_policy_ok():
        have_task = True
    else:
        if log:
            log("info", cfg.t("sheet.dpi.log.task"))
        have_task = _register_task(runner)   # маркер политики пишет регистрация
    if have_task:
        launched = _trigger()
        # самодиагностика: помощник пишет первую строку сразу. Тишина дольше
        # 20 секунд = задача ушла в очередь или не стартовала - лучше разовый
        # запрос прав, чем молчаливое ожидание до таймаута
        if launched and not _runner_booted(20):
            if log:
                log("warning", cfg.t("sheet.dpi.log.fallback"))
            launched = _elevated(
                _powershell(),
                f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
                f'-File "{runner}" -Probe "{probe_dir}"')
    else:
        # запасной путь: UAC на каждый вызов, если задачу не завели
        launched = _elevated(_powershell(),
                             f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
                             f'-File "{runner}" -Probe "{probe_dir}"')
    if not launched:
        return None
    data = _wait_result(probe_dir, token, wait)
    # таймаут - отдельный ответ: вызывающий сам подбирает свой текст
    return data if data is not None else {"ok": False, "timeout": True}


def _runner_booted(timeout: float) -> bool:
    """Успел ли помощник написать первую строку журнала (значит - запустился)."""
    path = _probe_dir() / "runner.log"
    deadline = time.time() + max(1.0, timeout)
    while time.time() < deadline:
        try:
            if path.is_file() and path.stat().st_size > 0:
                return True
        except OSError:
            pass
        time.sleep(0.4)
    return False


def start(cfg: DpiConfig, log=None, wait: bool = True, bat: str | None = None) -> dict:
    """Поднимает обход и ждёт, пока маршрут откроется. bat - своя стратегия.

    {"ok": True} - обход работает (или уже был запущен);
    {"ok": False, "error": ...} - не поднялось, причина готовым текстом.
    """
    st = status()
    if st["running"]:
        if log:
            log("info", cfg.t("sheet.dpi.log.already"))
        return {"ok": True, "pid": st["pid"], "already": True}
    try:
        # проверки папки и файла - ДО запроса прав: нечего поднимать ради отказа
        if cfg.mode == "args":
            exe, params = command(cfg)
            payload = {"exe": exe, "args": params}
        else:
            payload = {"bat": _bat_path(cfg, bat)}
    except ValueError as exc:
        if log:
            log("error", str(exc))
        return {"ok": False, "error": str(exc)}
    if log:
        log("info", cfg.t("sheet.dpi.log.start"))
    res = _run_action(cfg, "start", payload, wait=60, log=log)
    if res is None:
        err = cfg.t("sheet.dpi.no_uac")
        if log:
            log("error", err)
        return {"ok": False, "error": err}
    if res.get("timeout"):
        err = cfg.t("sheet.dpi.start_timeout")
        if log:
            log("error", err)
        return {"ok": False, "error": err, "running": status()["running"]}
    if not res.get("ok"):
        err = cfg.t("sheet.dpi.start_fail")
        if log:
            log("error", err)
        return {"ok": False, "error": err}
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
    """Гасит обход: winws убивает помощник, права - задача планировщика."""
    st = status()
    if not st["running"]:
        if log:
            log("info", cfg.t("sheet.dpi.log.not_running"))
        return {"ok": True, "running": False}
    res = _run_action(cfg, "stop", {}, wait=45, log=log)
    if res is None or not res.get("ok"):
        err = cfg.t("sheet.dpi.no_uac") if res is None else cfg.t("sheet.dpi.stop_fail")
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


# -- подбор рабочей стратегии ----------------------------------------------
# Автоматика перед загрузкой: маршрут закрыт -> попробовать сохранённую
# стратегию -> если не помогло, прогнать все general*.bat и взять ту, где
# TLS-хендшейк проходит. Перебор идёт в ОДНОЙ сессии с повышением прав:
# построчное подтверждение UAC на каждую стратегию было бы невыносимо.
#
# Скрипт помощник лежит рядом с кэшем и создаётся на месте (ASCII-исходник
# ниже): в собранном приложении python.exe рядом нет, а PowerShell есть
# всегда. Он же меряет хендшейк - чтобы не плодить второй механизм пробы.

_RUNNER_SOURCE = r'''
param(
    [Parameter(Mandatory = $true)][string]$Probe,
    [string]$Policy = "",
    [switch]$Register
)
$ErrorActionPreference = "SilentlyContinue"
$log = Join-Path $Probe "runner.log"
function LG($m) {
    try { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format "HH:mm:ss"), $m) -Encoding ASCII } catch { }
}
# earliest possible trace: if the task context stalls, we still know we booted
try { "boot" | Add-Content -Path $log -Encoding ASCII } catch { }

# zapret opens its releases page on every strategy start unless this is set
# (service.bat: "if defined NO_UPDATE_CHECK exit /b") - that is the source of
# the browser tabs, so it is set before anything is started
$env:NO_UPDATE_CHECK = "1"

Add-Type -Namespace Synf -Name Win -MemberDefinition '[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);'
LG "addtype ok"
$Curl = "$env:SystemRoot\System32\curl.exe"
if (-not (Test-Path $Curl)) { $Curl = "curl.exe" }
$Target = "www.youtube.com"

if ($Register) {
    # One-time task registration: afterwards the app fires schtasks /Run and
    # the scheduler service raises the helper itself - no UAC dialog ever.
    try {
        $ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
        $ps1 = Join-Path $Probe "bypass_runner.ps1"
        $action = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ps1`" -Probe `"$Probe`""
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date
        $principal = New-ScheduledTaskPrincipal -UserId ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME) -RunLevel Highest
        # Parallel: winws остаётся работать после нашего выхода, планировщик
        # же держит задачу «выполняющейся», пока живы дочерние процессы - при
        # IgnoreNew/Queue следующий запуск ушёл бы в очередь и не стартовал
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances Parallel -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName "SynfroniaBypass" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
        # маркер пишет сам регистрационный запуск: приложение сверяет его с
        # текущей политикой и перерегистрирует задачу только при её смене
        if ($Policy) { try { Set-Content -Path (Join-Path $Probe "task.policy") -Value $Policy -Encoding ASCII } catch { } }
        LG "task registered policy=$Policy"
    } catch {
        LG "register failed: $($_.Exception.Message)"
        exit 1
    }
    exit 0
}

$token = "0"
$action = ""
$req = $null
try {
    $req = Get-Content (Join-Path $Probe "request.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $token = "$($req.token)"
    $action = "$($req.action)"
    if ($req.target) { $Target = "$($req.target)" }
    LG "req action=$action token=$token"
} catch {
    LG "request read failed: $($_.Exception.Message)"
}
$outPath = Join-Path $Probe ("result-" + $token + ".json")

function Finish($Payload) {
    try {
        $tmp = "$outPath.tmp"
        $Payload | ConvertTo-Json -Depth 6 | Set-Content -Path $tmp -Encoding UTF8
        Move-Item -Path $tmp -Destination $outPath -Force
        LG "result written action=$action"
    } catch { LG "result write failed: $($_.Exception.Message)" }
}

function Stop-Winws {
    Get-Process -Name "winws" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 500
}

function Hide-Winws {
    # strategy consoles are started minimized by their bat files; the user
    # should not see them at all, so they are hidden a few times in a row
    for ($t = 0; $t -lt 6; $t++) {
        Get-Process -Name "winws" -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.MainWindowHandle -ne 0) { [Synf.Win]::ShowWindow($_.MainWindowHandle, 0) | Out-Null }
        }
        Start-Sleep -Milliseconds 300
    }
}

function Start-Target {
    param($Root, $Bat, $Exe, $WinArgs)
    if ($Bat) {
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$Bat`"" -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
    } elseif ($Exe) {
        Start-Process -FilePath $Exe -ArgumentList $WinArgs -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
    }
}

function Wait-Winws {
    param([int]$Ms = 7000)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $Ms) {
        if (Get-Process -Name "winws" -ErrorAction SilentlyContinue) { return $true }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

function Test-Http {
    # curl (schannel) - the same way the stock zapret tester probes: .NET
    # SslStream answered "not-authenticated" even on a healthy host here
    param([int]$Timeout = 6)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $code = & $Curl -sS -o NUL -m $Timeout --connect-timeout $Timeout --ssl-no-revoke -w "%{http_code}" "https://$Target/" 2>$null
    $exit = $LASTEXITCODE
    $ms = [int]$sw.ElapsedMilliseconds
    $code = ("$code").Trim()
    if (($exit -eq 0) -and $code -and ($code -ne "000")) { return $ms }
    return $null
}

function Test-One {
    # start one strategy by name and probe it: returns ms or $null
    param($Root, $Name)
    Stop-Winws
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$(Join-Path $Root $Name)`"" -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
    $up = Wait-Winws 7000
    if ($up) { Hide-Winws }
    if (-not $up) { return $null }
    Start-Sleep -Milliseconds 700
    $ms = Test-Http 6
    if ($null -eq $ms) { Start-Sleep -Milliseconds 500; $ms = Test-Http 6 }
    return $ms
}

try {
    LG "action=$action token=$token"
    switch ($action) {
        "start" {
            Stop-Winws
            Start-Target -Root $req.root -Bat $req.bat -Exe $req.exe -WinArgs $req.args
            $up = Wait-Winws 7000
            Hide-Winws
            Finish ([PSCustomObject]@{ ok = [bool]$up; action = "start" })
        }
        "stop" {
            Stop-Winws
            Finish ([PSCustomObject]@{ ok = $true; action = "stop" })
        }
        "scan" {
            $root = "$($req.root)"
            $results = New-Object System.Collections.Generic.List[object]
            $bestName = $null
            $bestMs = 2147483647
            foreach ($name in @($req.configs)) {
                $ms = Test-One $root "$name"
                $ok = ($null -ne $ms)
                $results.Add([PSCustomObject]@{ name = "$name"; ok = $ok; ms = $ms })
                LG ("  {0} ms={1}" -f $name, $ms)
                if ($ok -and ([int]$ms -lt $bestMs)) { $bestMs = [int]$ms; $bestName = "$name" }
            }
            # the winner stays running until the app stops it
            if ($bestName) {
                Stop-Winws
                Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$(Join-Path $root $bestName)`"" -WorkingDirectory $root -WindowStyle Hidden | Out-Null
                Wait-Winws 7000 | Out-Null
                Hide-Winws
            } else {
                Stop-Winws
            }
            Finish ([PSCustomObject]@{ ok = [bool]$bestName; action = "scan"; best = $bestName; results = @($results.ToArray()) })
        }
        default {
            Finish ([PSCustomObject]@{ ok = $false; action = $action; error = "unknown action" })
        }
    }
} catch {
    LG "FATAL: $($_.Exception.Message) line=$($_.InvocationInfo.ScriptLineNumber)"
    Finish ([PSCustomObject]@{ ok = $false; action = $action; error = "$($_.Exception.Message)" })
}
# Уход жёстко, а не return: стратегия остаётся работать дочерним процессом и
# держит консольные дескрипторы - без этого PowerShell дожидается их, задача
# вечно «выполняется», а следующие запуски уходят в очередь (так и было).
try { [Environment]::Exit(0) } catch { exit 0 }
'''


def _probe_dir() -> Path:
    """%LOCALAPPDATA%\\Synfronia\\probe - кэш подбора и скрипт помощника."""
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Synfronia" / "probe"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return root


def _natkey(name: str) -> str:
    """Натуральная сортировка: ALT2 раньше ALT10 (как в тестере zapret)."""
    return re.sub(r"(\d+)", lambda m: m.group(1).zfill(8), name).lower()


def strategies(cfg: DpiConfig) -> list[str]:
    """Имена файлов стратегий (general*.bat) в папке zapret, по порядку."""
    if not cfg.dir:
        return []
    root = Path(cfg.dir)
    if not root.is_dir():
        return []
    return sorted((p.name for p in root.glob("general*.bat")), key=_natkey)


def read_cache() -> str | None:
    """Имя стратегии, которая последней открыла YouTube (None - не подбиралась)."""
    try:
        data = json.loads((_probe_dir() / "strategy.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    name = data.get("best") if isinstance(data, dict) else None
    return str(name) if name else None


def write_cache(name: str) -> None:
    try:
        (_probe_dir() / "strategy.json").write_text(
            json.dumps({"best": name}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _remember_strategy(name: str) -> None:
    """Записывает подобранную стратегию в настройку dpi_bat.

    Импорт ленивый: settings тянет схему, а схема лениво тянет этот модуль -
    на уровне модулей это был бы цикл. Ошибка записи не важна: кэш уже
    обновлён, а настройка - только удобство ручного запуска.
    """
    try:
        import settings as settings_mod
        data = settings_mod.load_settings()
        if data.get("dpi_bat") != name:
            data["dpi_bat"] = name
            settings_mod.save_settings(data)
    except Exception:  # noqa: BLE001 - настройка вторична относительно кэша
        pass


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _runner_tail(limit: int = 8) -> list[str]:
    """Последние строки журнала помощника - чтобы ошибка подбора объяснялась."""
    try:
        text = (_probe_dir() / "runner.log").read_text(encoding="utf-8",
                                                        errors="replace")
    except OSError:
        return []
    return [ln for ln in text.splitlines() if ln.strip()][-limit:]


def scan(cfg: DpiConfig, log=None, wait: float | None = None) -> dict:
    """Прогоняет все стратегии и оставляет включённой ту, где соединение лучше.

    Весь перебор - одна операция с правами: помощник по очереди запускает
    general*.bat, по каждой меряет ответ YouTube (две пробы), пишет итог в
    JSON и не гасит победителя. Кэш обновляется.
    {"ok": True, "best": имя, "results": [...]} либо
    {"ok": False, "error": текст, "results": [...]}.
    """
    names = strategies(cfg)
    if not names:
        err = cfg.t("sheet.dpi.scan_none")
        if log:
            log("error", err)
        return {"ok": False, "error": err, "results": []}
    if log:
        log("info", cfg.t("sheet.dpi.scanning"))
    # на стратегию уходит до ~15с (старт, две пробы, спрятать окно); запас
    # даётся с учётом всего списка и старта задачи планировщика
    data = _run_action(cfg, "scan", {"configs": names},
                       wait=wait or (60 + 25 * len(names)), log=log)
    if data is None:
        err = cfg.t("sheet.dpi.no_uac")
        if log:
            log("error", err)
            for line in _runner_tail():
                log("warning", f"scan: {line}")
        return {"ok": False, "error": err, "results": []}
    results = data.get("results") or []
    best = data.get("best")
    if data.get("ok") and best and probe():
        write_cache(best)
        # найденная стратегия становится настроенной: кнопка «Включить обход»
        # и режим без кэша должны работать так же, как только что подобранный
        _remember_strategy(best)
        if log:
            log("info", cfg.t("sheet.dpi.log.scanned", name=best))
        return {"ok": True, "best": str(best), "results": results}
    err = cfg.t("sheet.dpi.scan_fail")
    if data.get("error"):
        err = f"{err} ({data['error']})"
    if log:
        log("error", err)
        for line in _runner_tail():
            log("warning", f"scan: {line}")
    return {"ok": False, "error": err, "results": results}


def auto(cfg: DpiConfig, log=None) -> dict:
    """Обход перед загрузкой: маршрут -> свая стратегия -> полный подбор.

    {"ok": True, "started": False} - доступ уже есть, ничего не трогали;
    {"ok": True, "started": True}  - стратегия поднята нами (гасим после);
    {"ok": False, "error": ...}    - не удалось, причина готовым текстом.
    """
    if resolve(cfg, False) != "start":
        # обход выключен настройками: маршрут даже не проверяем (иначе каждый
        # запуск без флажка опрашивал бы YouTube зря)
        return {"ok": True, "started": False}
    if probe():
        if log:
            log("info", cfg.t("sheet.dpi.log.ok"))
        return {"ok": True, "started": False}
    names = strategies(cfg)
    if not names:
        err = cfg.t("sheet.dpi.scan_none")
        if log:
            log("error", err)
        return {"ok": False, "error": err}
    cached = read_cache()
    # кэш имеет смысл пробовать только в режиме bat и только когда сейчас
    # ничего не запущено: чужой работающий процесс перебор всё равно заменит
    if cfg.mode == "bat" and cached and cached in names and not status()["running"]:
        if log:
            log("info", cfg.t("sheet.dpi.log.cache", name=cached))
        res = start(cfg, log=log, bat=cached)
        if res.get("ok") and probe():
            return {"ok": True, "started": True, "strategy": cached}
    if log:
        log("warning", cfg.t("sheet.dpi.log.scan"))
    res = scan(cfg, log=log)
    if res.get("ok"):
        return {"ok": True, "started": True, "strategy": res.get("best"),
                "results": res.get("results")}
    return {"ok": False, "error": res.get("error") or cfg.t("sheet.dpi.scan_fail")}


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
             {"dom": "dpi-scan", "label": "sheet.dpi.scan"},
             {"dom": "dpi-start", "label": "sheet.dpi.start"},
             {"dom": "dpi-stop", "label": "sheet.dpi.stop"},
         ]},
        {"type": "note", "transient": True, "dom": "dpi-note", "box": "run",
         "row": 2, "inline": True},
    ],
}
