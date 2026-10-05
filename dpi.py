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
import hashlib
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import time
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from ctypes import wintypes
from pathlib import Path

from i18n import tr
from paths import base_dir
from settings_schema import value as _value

PROBE_HOST = "www.youtube.com"
PROBE_PORT = 443
PROBE_TIMEOUT = 6.0
# Веб может открываться, пока CDN не отдаёт видео (ровно так зависала
# третья тестовая качка: TLS до googlevideo проходил, тело не шло).
# Пустой ответ по этому адресу = медиапоток закрыт.
PROBE_MEDIA = "https://redirector.googlevideo.com/videoplayback"
WINWS_IMAGE = "winws.exe"
# Служебная задача планировщика: её регистрация - единственный запрос прав,
# дальше помощник поднимается через schtasks /Run без диалога UAC.
# Политику инстансов читаем из XML самой задачи (см. _task_policy_ok).
TASK_NAME = "SynfroniaBypass"
RUNNER_NAME = "bypass_runner.ps1"


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


# Четыре цели компактного набора: сам YouTube, медиапоток, короткие ссылки
# и обложки. Идея та же, что у tester из service.bat (12. Run Tests), только
# без семнадцати целей и минут ожидания - четыре пробы идут параллельно и
# по их составу рисуется состояние (зелёный/оранжевый/красный).
PROBE_TARGETS = (
    ("web", "https://www.youtube.com/"),
    ("media", "https://redirector.googlevideo.com/videoplayback"),
    ("short", "https://youtu.be/"),
    ("thumb", "https://i.ytimg.com/"),
)


def probe_url(url: str, timeout: float = PROBE_TIMEOUT) -> dict:
    """{ok, ms, why} по одной цели: TLS-хендшейк и GET, успех = любой ответ.

    Сертификат не проверяем (важен факт прохождения), код не разбираем:
    404 на videoplayback - успех, ровно как в tester zapret. why - короткая
    причина отказа (conn/tls/timeout/http/empty): для строки состояния и
    журнала важнее того, ЧТО не ответило, - почему не ответило.
    """
    started = time.time()

    def out(ok: bool, why: str = "") -> dict:
        return {"ok": bool(ok), "ms": int((time.time() - started) * 1000),
                "why": why}

    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    try:
        raw = socket.create_connection((host, 443), timeout=timeout)
    except OSError:
        return out(False, "conn")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    wrapped = None
    try:
        wrapped = ctx.wrap_socket(raw, server_hostname=host)
    except TimeoutError:
        # таймаут рукопожатия - это тишина по маршруту (блокировка), а не
        # «плохой TLS»: строка состояния должна называть причину честно
        raw.close()
        return out(False, "timeout")
    except (OSError, ssl.SSLError):
        raw.close()
        return out(False, "tls")
    try:
        wrapped.settimeout(timeout)
        request = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                   f"User-Agent: Synfronia\r\nAccept: */*\r\n"
                   f"Connection: close\r\n\r\n")
        wrapped.sendall(request.encode("ascii", "ignore"))
        answer = wrapped.recv(4096)
        if not answer:
            return out(False, "empty")
        if not answer.startswith(b"HTTP/"):
            return out(False, "http")
        return out(True)
    except TimeoutError:
        return out(False, "timeout")
    except OSError:
        return out(False, "conn")
    finally:
        wrapped.close()


def probe_media(timeout: float = PROBE_TIMEOUT) -> bool:
    """Проба googlevideo одной boolean-функцией (старый контракт вызовов)."""
    return probe_url(PROBE_MEDIA, timeout)["ok"]


def probe_targets(timeout: float = PROBE_TIMEOUT, names=None) -> dict:
    """Все цели разом, параллельно: {state, ok, count, total, targets}.

    Параллельно не ради спешки, а ради честности: закрытый маршрут раньше
    обрывался на первой пробе, и кнопка не могла сказать, ЧТО именно не
    ответило. state: full - все цели, partial - часть, none - ни одной.
    """
    chosen = [(n, u) for n, u in PROBE_TARGETS if names is None or n in names]
    if not chosen:
        return {"state": "none", "ok": False, "count": 0, "total": 0,
                "targets": {}}
    targets: dict = {}
    pool = ThreadPoolExecutor(max_workers=len(chosen))
    futures: dict = {}
    try:
        futures = {pool.submit(probe_url, url, timeout): name
                   for name, url in chosen}
        # общий потолок на все цели: даже зависший DNS (getaddrinfo не
        # слушает таймаут сокета) или подменённый чужой поток не должен
        # держать кнопку «Проверить» дольше таймаута - поздние цели
        # помечаются таймаутом, а не ждутся вечно
        for future in as_completed(futures, timeout=timeout + 2.0):
            name = futures[future]
            try:
                targets[name] = future.result()
            except Exception as exc:  # noqa: BLE001 - цель сорвалась - остальные идут
                targets[name] = {"ok": False, "ms": 0,
                                 "why": f"error:{exc}"[:40]}
    except TimeoutError:
        for future, name in futures.items():
            if name not in targets:
                targets[name] = {"ok": False, "ms": int(timeout * 1000),
                                 "why": "timeout"}
    finally:
        # без wait: замок на ожидании как раз и завис бы на зависшем воркере
        pool.shutdown(wait=False, cancel_futures=True)
    count = sum(1 for target in targets.values() if target.get("ok"))
    # порядок целей - как в PROBE_TARGETS: иначе строка журнала и карточка
    # меняли бы вид при каждом замере (parallel as_completed)
    order = {name: i for i, (name, _url) in enumerate(PROBE_TARGETS)}
    targets = dict(sorted(targets.items(), key=lambda kv: order.get(kv[0], 99)))
    if count == len(chosen):
        state = "full"
    elif count == 0:
        state = "none"
    else:
        state = "partial"
    return {"state": state, "ok": state == "full", "count": count,
            "total": len(chosen), "targets": targets}


def probe_all(timeout: float = PROBE_TIMEOUT) -> dict:
    """Старый контракт (ok/web/media) плюс детали для журнала и статуса.

    ok = полный доступ (и веб, и поток, и остальное) - как раньше, только
    теперь видно, при какой цели и с какой причиной случился отказ.
    """
    rep = probe_targets(timeout)
    targets = rep["targets"]
    return {"ok": rep["ok"], "web": bool(targets.get("web", {}).get("ok")),
            "media": bool(targets.get("media", {}).get("ok")),
            "state": rep["state"], "count": rep["count"],
            "total": rep["total"], "targets": targets}


def probe_line(report: dict) -> str:
    """Строка журнала: маршрут одной строкой, без интерпретации.

    Такое писание и делает расхождения видимыми: надпись в карточке и
    запись в журнале складываются из одних и тех же ms и причин.
    """
    parts = []
    for name, target in (report.get("targets") or {}).items():
        if target.get("ok"):
            parts.append(f"{name}=ok({int(target.get('ms') or 0)}ms)")
        else:
            parts.append(f"{name}=fail({target.get('why') or 'unknown'},"
                         f"{int(target.get('ms') or 0)}ms)")
    head = f"probe state={report.get('state', 'none')} {' '.join(parts)}".rstrip()
    winws = "on" if report.get("running") else "off"
    return (f"{head} winws={winws} pid={report.get('pid')}"
            f" стратегия={report.get('strategy')!r}"
            f" установка={report.get('install')!r}")


def _status(cfg, st: dict, rep: dict) -> dict:
    """Сводка для карточки и журнала: winws + свежая проба + что меряем."""
    return {"running": bool(st.get("running")), "pid": st.get("pid"),
            "strategy": cfg.bat, "install": cfg.dir,
            "state": rep.get("state", "none"),
            "count": int(rep.get("count") or 0),
            "total": int(rep.get("total") or 0),
            "targets": rep.get("targets") or {},
            "checked_at": int(time.time())}


def status_report(cfg, timeout: float = PROBE_TIMEOUT, log=None) -> dict:
    """Одно место правды: свежая проба всех целей плюс состояние winws.

    Каждое действие (проверка, включение, выключение, тест стратегии)
    возвращает именно такой отчёт, поэтому строка в карточке не может
    разойтись с тем, что реально ответило сети.
    """
    report = _status(cfg, status(), probe_targets(timeout))
    if log:
        log("info", probe_line(report))
    return report


def resolve(data, reachable: bool) -> str:
    """Нужно ли поднимать обход перед загрузкой: "start" или "skip".

    Решалка отдельно от запуска, чтобы её можно было проверить без сети
    и без прав: вмешательство нужно только при включённой оркестрации и
    закрытом маршруте - никаких сюрпризов при работающем YouTube.
    """
    cfg = data if isinstance(data, DpiConfig) else DpiConfig(data)
    if cfg.orch == "off":
        return "skip"
    return "skip" if reachable else "start"


def after_action(cfg) -> str:
    """Что делать с обходом после загрузки: restore | keep | off."""
    return cfg.after if cfg.after in ("restore", "keep", "off") else "restore"


class DpiConfig:
    """Значения настроек обхода, приведённые к типам схемы."""

    def __init__(self, data: dict | None = None, lang: str = "ru") -> None:
        data = data or {}
        self.lang = lang
        # оркестрация: off - не трогать, ask - спросить при закрытом
        # маршруте, auto - поднимать молча; после загрузки: restore/keep/off
        self.orch = str(_value(data, "dpi.orch"))
        self.after = str(_value(data, "dpi.after"))
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
              f'-File "{runner}" -Probe "{runner.parent}" -Register')
    if not _elevated(_powershell(), params):
        return False
    for _ in range(30):   # регистрация быстрая, но ждём с запасом
        if _task_exists() and _task_policy_ok():
            return True
        time.sleep(0.5)
    return _task_exists() and _task_policy_ok()


def _task_policy_ok() -> bool:
    """Политика инстансов задачи - читаем её из самой задачи, а не из файла.

    Маркер-файл оказался хрупким: любая чистка папки probe обнуляла его, и
    приложение начинало спрашивать права администратора на каждый запуск
    вместо тихого срабатывания. XML задачи читается без прав и всегда
    отражает факт. Важна одна строчка: Queue (политика старых регистраций)
    означает, что запуск застрянет за «висячим» экземпляром.
    """
    try:
        out = subprocess.run([_schtasks(), "/Query", "/TN", TASK_NAME, "/XML"],
                             capture_output=True, timeout=25)
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0:
        return False
    text = (out.stdout or b"").decode("utf-8", "replace")
    found = re.search(r"<MultipleInstancesPolicy>([^<]+)</MultipleInstancesPolicy>", text)
    if not found:   # в этом XML настройки нет - считаем политику не мешающей
        return True
    return found.group(1).strip() != "Queue"


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


def _wait_result(probe_dir: Path, token: str, wait: float,
                 on_progress=None) -> dict | None:
    """Ждёт итог помощника: файл пишется атомарно (tmp -> move), поэтому
    читабельный JSON уже готовый результат.

    Пока помощник работает, он кладёт промежуточные итоги в progress-<token>:
    каждый новый отдаётся в on_progress - карточка рисует ход перебора, а
    проверенные стратегии попадают в кэш цветов прямо по ходу (обрыв
    прогона не теряет уже измеренное).
    """
    path = probe_dir / f"result-{token}.json"
    progress = probe_dir / f"progress-{token}.json"
    deadline = time.time() + max(5.0, wait)
    last = None
    while time.time() < deadline:
        data = _read_json(path)
        if data is not None:
            for stale in (path, progress):
                try:
                    stale.unlink()
                except OSError:
                    pass
            return data
        if on_progress is not None:
            current = _read_json(progress)
            if current is not None and current != last:
                last = current
                try:
                    on_progress(current)
                except Exception:  # noqa: BLE001 - прогресс не должен валить ожидание
                    pass
        time.sleep(0.3)
    return None


def _run_action(cfg: DpiConfig, action: str, payload: dict, wait: float,
                log=None, on_progress=None) -> dict | None:
    """Одна операция, требующая прав. Итог придёт файлом result-<token>.json.

    Путь запуска: задача есть -> schtasks /Run (без UAC); нет -> регистрация
    (один UAC на весь срок службы); и от неё отказались -> runas, как раньше.
    None = запустить помощника не удалось вообще.
    """
    runner = _write_runner()
    probe_dir = runner.parent
    stale_files = (list(probe_dir.glob("result-*.json*"))
                   + list(probe_dir.glob("progress-*.json*"))
                   # хвост отмены убираем в первую очередь: оставшийся
                   # cancel.flag убил бы уже следующий прогон
                   + [probe_dir / "cancel.flag", probe_dir / "runner.log"])
    for stale in stale_files:
        try:
            stale.unlink()
        except OSError:
            pass
    token = str(int(time.time() * 1000))
    req = {"action": action, "token": token, "root": cfg.dir, "target": PROBE_HOST,
           "media": PROBE_MEDIA, "bat": "", "exe": "", "args": "", "configs": []}
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
    data = _wait_result(probe_dir, token, wait, on_progress=on_progress)
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

    {"ok": True, "report": ...} - обход работает и маршрут проверен;
    {"ok": False, "error": ..., "report": ...} - причина готовым текстом.

    Уже запущенный обход НЕ считается успехом без проверки: раньше такой
    возврат отдавал «обход включён - YouTube отвечает», хотя никто ничего
    не мерял, а маршрут мог быть закрыт - и кнопка «Проверить» тут же
    опровергала кнопку «Включить». Теперь оба рисуют один и тот же отчёт.
    """
    st = status()
    if st["running"]:
        report = _status(cfg, st, probe_targets())
        if log:
            log("info", cfg.t("sheet.dpi.log.already"))
            log("info", probe_line(report))
        return {"ok": report["state"] == "full", "pid": st["pid"],
                "already": True, "report": report}
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
        report = status_report(cfg, log=log)
        err = cfg.t("sheet.dpi.start_timeout")
        if log:
            log("error", err)
        return {"ok": False, "error": err, "running": report["running"],
                "report": report}
    if not res.get("ok"):
        report = status_report(cfg, log=log)
        err = cfg.t("sheet.dpi.start_fail")
        if log:
            log("error", err)
        return {"ok": False, "error": err, "running": report["running"],
                "report": report}
    if not wait:
        report = status_report(cfg, log=log)
        return {"ok": True, "pid": report["pid"], "report": report}
    # драйвер и ловушка поднимаются за доли секунды, но первый проб может
    # пройти мимо - ждём до cfg.timeout, проверяя маршрут каждые полсекунды
    deadline = time.time() + max(5, cfg.timeout)
    last: dict = {}
    while time.time() < deadline:
        # проверяем все цели: веб может открыться раньше потока, и тогда
        # «успех» скрыл бы зависшую качку
        last = probe_all(timeout=4)
        if last["ok"]:
            report = _status(cfg, status(), last)
            if log:
                log("info", probe_line(report))
            return {"ok": True, "pid": status()["pid"], "report": report}
        time.sleep(0.5)
    # таймаут: отчёт о том, что отвечало в последние полсекунды - по нему
    # видно, открылся ли веб без потока или не открылось ничего
    last = probe_all(timeout=4)
    report = _status(cfg, status(), last)
    err = cfg.t("sheet.dpi.start_timeout")
    if log:
        log("error", err)
        log("info", probe_line(report))
    return {"ok": False, "error": err, "running": report["running"],
            "report": report}


def stop(cfg: DpiConfig, log=None) -> dict:
    """Гасит обход: winws убивает помощник, права - задача планировщика.

    И здесь возвращается отчёт маршрута: после выключения строка состояния
    честно показывает, что осталось отвечать («выкл · маршрут открыт» или
    «выкл · цели молчат»), а не просто «Обход выключен».
    """
    st = status()
    if not st["running"]:
        if log:
            log("info", cfg.t("sheet.dpi.log.not_running"))
        return {"ok": True, "running": False,
                "report": status_report(cfg, log=log)}
    res = _run_action(cfg, "stop", {}, wait=45, log=log)
    if res is None or not res.get("ok"):
        err = cfg.t("sheet.dpi.no_uac") if res is None else cfg.t("sheet.dpi.stop_fail")
        if log:
            log("error", err)
        return {"ok": False, "error": err, "report": status_report(cfg, log=log)}
    if log:
        log("info", cfg.t("sheet.dpi.log.stop"))
    for _ in range(10):   # процесс умирает почти сразу, но не обещаем
        if not status()["running"]:
            break
        time.sleep(0.3)
    return {"ok": True, "running": status()["running"],
            "report": status_report(cfg, log=log)}


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
$MediaTarget = "https://redirector.googlevideo.com/videoplayback"

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
        LG "task registered (MultipleInstances=Parallel)"
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
    if ($req.media) { $MediaTarget = "$($req.media)" }
    LG "req action=$action token=$token"
} catch {
    LG "request read failed: $($_.Exception.Message)"
}
$outPath = Join-Path $Probe ("result-" + $token + ".json")
# Живой ход перебора и кнопка «Прервать»: карточка читает прогресс через
# Python (опрос идёт каждые 300 мс), а отмена - обычный файл, который
# помощник замечает между стратегиями и честно доходит до Finish.
$ProgressPath = Join-Path $Probe ("progress-" + $token + ".json")
$CancelPath = Join-Path $Probe "cancel.flag"

function Finish($Payload) {
    try {
        $tmp = "$outPath.tmp"
        $Payload | ConvertTo-Json -Depth 8 | Set-Content -Path $tmp -Encoding UTF8
        Move-Item -Path $tmp -Destination $outPath -Force
        LG "result written action=$action"
    } catch { LG "result write failed: $($_.Exception.Message)" }
}

function Write-Progress {
    # Промежуточный итог после каждой стратегии: тот же атомарный приём,
    # что у Finish, - Python читает только целый JSON. Карточка по нему
    # рисует «12/22», полоску и точки стратегий прямо во время прогона
    param($Payload)
    try {
        $tmp = "$ProgressPath.tmp"
        $Payload | ConvertTo-Json -Depth 8 | Set-Content -Path $tmp -Encoding UTF8
        Move-Item -Path $tmp -Destination $ProgressPath -Force
    } catch { LG "progress write failed: $($_.Exception.Message)" }
}

function Test-Cancel {
    return (Test-Path $CancelPath)
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
    # SslStream answered "not-authenticated" even on a healthy host here.
    # Both targets answer with a status code when the route is open: youtube
    # gives 200, the media endpoint gives 404 without query parameters.
    param([string]$Url, [int]$Timeout = 6)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $code = & $Curl -sS -o NUL -m $Timeout --connect-timeout $Timeout --ssl-no-revoke -w "%{http_code}" $Url 2>$null
    $exit = $LASTEXITCODE
    $ms = [int]$sw.ElapsedMilliseconds
    $code = ("$code").Trim()
    if (($exit -eq 0) -and $code -and ($code -ne "000")) { return $ms }
    return $null
}

function New-TargetResult {
    param($Ms)
    if ($null -eq $Ms) { return [PSCustomObject]@{ ok = $false; ms = 0; why = "timeout" } }
    return [PSCustomObject]@{ ok = $true; ms = [int]$Ms; why = "" }
}

function Measure-Targets {
    # Компактный набор из четырёх целей - по образцу «12. Run Tests» из
    # service.bat, но быстрее: веб, медиапоток, короткие ссылки, обложки.
    # Веб открывается раньше потока, поэтому успехом считается только ответ
    # ВСЕХ четырёх: частичный ответ - это оранжевый, а не «работает».
    param([int]$Timeout = 4)
    $web   = Test-Http ("https://$Target/") $Timeout
    $media = Test-Http $MediaTarget $Timeout
    $short = Test-Http "https://youtu.be/" $Timeout
    $thumb = Test-Http "https://i.ytimg.com/" $Timeout
    $targets = [PSCustomObject]@{
        web   = (New-TargetResult $web)
        media = (New-TargetResult $media)
        short = (New-TargetResult $short)
        thumb = (New-TargetResult $thumb)
    }
    $good = 0
    foreach ($p in $targets.PSObject.Properties) { if ($p.Value.ok) { $good++ } }
    $state = "partial"
    if ($good -eq 4) { $state = "full" } elseif ($good -eq 0) { $state = "none" }
    return [PSCustomObject]@{ state = $state; ok = ($state -eq "full"); count = $good; targets = $targets }
}

function Test-One {
    # start one strategy by name and probe it: measurement or $null
    param($Root, $Name)
    Stop-Winws
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$(Join-Path $Root $Name)`"" -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
    $up = Wait-Winws 7000
    if ($up) { Hide-Winws }
    if (-not $up) { return $null }
    Start-Sleep -Milliseconds 700
    $m = Measure-Targets 4
    # первый замер сразу после старта бывает мимо (маршрут ещё поднимается):
    # повторяем только полный отказ, частичный ответ - честный результат
    if ($m.state -eq "none") { Start-Sleep -Milliseconds 500; $m = Measure-Targets 4 }
    return $m
}

# -- состояние обхода: что запущено сейчас и как это вернуть ------------------
$Record = Join-Path $Probe "orchestrator.json"

function Read-Record {
    try {
        if (Test-Path $Record) {
            return (Get-Content $Record -Raw -Encoding UTF8 | ConvertFrom-Json)
        }
    } catch { LG "record read failed: $($_.Exception.Message)" }
    return $null
}

function Write-Record {
    param($Rec)
    try {
        $Rec | ConvertTo-Json -Depth 5 | Set-Content -Path $Record -Encoding UTF8
        LG "record saved kind=$($Rec.kind) services=$($Rec.services -join ',')"
        return $true
    } catch {
        LG "record save failed: $($_.Exception.Message)"
        return $false
    }
}

function Get-BypassServices {
    # Службы, чей путь указывает на winws.exe. Имя НЕ захардкожено:
    # service.bat и service*.cmd называют службу по-разному.
    $found = @()
    try {
        foreach ($svc in (Get-CimInstance Win32_Service)) {
            if ($svc.PathName -and ($svc.PathName -like "*winws.exe*")) {
                $found += [PSCustomObject]@{
                    name    = $svc.Name
                    running = ($svc.State -eq "Running")
                }
            }
        }
    } catch { LG "service list failed: $($_.Exception.Message)" }
    return $found
}

function Get-State {
    $all = @(Get-BypassServices)
    $running = @($all | Where-Object { $_.running })
    $proc = Get-Process -Name "winws" -ErrorAction SilentlyContinue | Select-Object -First 1
    $cmdline = $null
    try {
        $wmi = Get-CimInstance Win32_Process -Filter "Name='winws.exe'" | Select-Object -First 1
        if ($wmi) { $cmdline = $wmi.CommandLine }
    } catch { }
    $exe = $null
    $winArgs = ""
    if ($cmdline) {
        if ($cmdline -match '^\s*"([^"]+)"\s*(.*)$') {
            $exe = $Matches[1]; $winArgs = $Matches[2]
        } elseif ($cmdline -match '^\s*(\S*?winws\.exe)\s*(.*)$') {
            $exe = $Matches[1]; $winArgs = $Matches[2]
        }
    }
    $kind = "none"
    if ($running.Count -gt 0) { $kind = "service" } elseif ($proc) { $kind = "process" }
    $holder = 0
    if ($proc) { $holder = $proc.Id }
    return [PSCustomObject]@{
        taken    = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        kind     = $kind
        services = @($running | ForEach-Object { $_.name })
        exe      = $exe
        args     = $winArgs
        pid      = $holder
        cmdline  = $cmdline
    }
}

function Stop-All {
    # Службу гасим через SCM (иначе она уйдёт в «прервана» и не стартанёт
    # при восстановлении), процесс - силой; winws живёт с фильтром WinDivert,
    # поэтому ждём, пока драйвер отпустит, а не убиваем мгновенно.
    foreach ($svc in (Get-BypassServices)) {
        if ($svc.running) {
            try {
                Stop-Service -Name $svc.name -Force -ErrorAction Stop
                LG "stopped service $($svc.name)"
            } catch { LG "stop-service $($svc.name) failed: $($_.Exception.Message)" }
        }
    }
    $wait = [Diagnostics.Stopwatch]::StartNew()
    while ($wait.ElapsedMilliseconds -lt 8000) {
        if (-not (Get-Process -Name "winws" -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 400
    }
    Get-Process -Name "winws" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 700
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
        "state" {
            Finish ([PSCustomObject]@{ ok = $true; action = "state"; original = (Get-State) })
        }
        "suspend" {
            # снимаем исходное состояние и гасим его: поднимать дальше
            # будем выбранный обход, а прежний вернёт restore
            $rec = Get-State
            Stop-All
            Write-Record $rec | Out-Null
            Finish ([PSCustomObject]@{ ok = $true; action = "suspend"; original = $rec })
        }
        "restore" {
            $rec = Read-Record
            Stop-All
            if ($rec) {
                if ($rec.kind -eq "service") {
                    foreach ($name in @($rec.services)) {
                        if (-not $name) { continue }
                        try { Start-Service -Name $name -ErrorAction Stop; LG "started service $name" }
                        catch { LG "start-service $name failed: $($_.Exception.Message)" }
                    }
                } elseif ($rec.kind -eq "process" -and $rec.exe) {
                    try {
                        Start-Process -FilePath $rec.exe -ArgumentList $rec.args -WindowStyle Hidden | Out-Null
                        LG "started $($rec.exe)"
                    } catch { LG "start process failed: $($_.Exception.Message)" }
                } else {
                    LG "record says nothing was running - staying off"
                }
            } else {
                LG "no record: stopping only"
            }
            Remove-Item -Path $Record -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 1500
            Finish ([PSCustomObject]@{ ok = $true; action = "restore"; original = $rec; now = (Get-State) })
        }
        "scan" {
            $root = "$($req.root)"
            $results = New-Object System.Collections.Generic.List[object]
            $bestName = $null
            $bestMs = 2147483647
            $configs = @($req.configs)
            $total = $configs.Count
            $i = 0
            foreach ($name in $configs) {
                # «Прервать»: помощник замечает файл между стратегиями и
                # доходит до Finish с тем, что успел - проверенное не теряется
                if (Test-Cancel) { LG "scan cancelled at $i of $total"; break }
                $i++
                $m = Test-One $root "$name"
                $state = "none"
                $ok = $false
                $ms = $null
                $targets = $null
                if ($m) {
                    $state = "$($m.state)"
                    $ok = [bool]$m.ok
                    $targets = $m.targets
                    if ($ok) {
                        $sum = 0
                        foreach ($p in $m.targets.PSObject.Properties) { $sum += [int]$p.Value.ms }
                        $ms = $sum
                    }
                }
                $results.Add([PSCustomObject]@{ name = "$name"; ok = $ok; ms = $ms; state = $state; targets = $targets })
                LG ("  {0} state={1} ms={2}" -f $name, $state, $ms)
                if ($ok -and ([int]$ms -lt $bestMs)) { $bestMs = [int]$ms; $bestName = "$name" }
                Write-Progress ([PSCustomObject]@{
                    i = $i; n = $total; name = "$name"; state = $state
                    results = @($results.ToArray())
                })
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
            Finish ([PSCustomObject]@{ ok = [bool]$bestName; action = "scan"; best = $bestName; cancelled = (Test-Cancel); results = @($results.ToArray()) })
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
    """Файлы стратегий активной установки (относительные пути, оба layout-а)."""
    if not cfg.dir:
        return []
    return strategies_in(cfg.dir)


def _cache_path() -> Path:
    return _probe_dir() / "strategy.json"


def _cache_key(install: str | None) -> str:
    """Ключ кэша - путь установки.

    Стратегии у версий разные (1.9.x и 1.10.x набирают по-своему), поэтому
    один общий кэш на все папки врал бы: выигравшая стратегия действительна
    только внутри своей установки.
    """
    if install:
        return str(install)
    data = registry_load()
    item = next((i for i in data["items"] if i.get("id") == data.get("active")), None)
    return str(item.get("path") or "") if item else ""


def read_cache(install: str | None = None) -> str | None:
    """Стратегия, которая последней открыла YouTube для этой установки."""
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    legacy = data.get("best")
    if legacy:   # старый общий кэш - берём и вытесняем при следующей записи
        return str(legacy)
    entry = data.get(_cache_key(install))
    if isinstance(entry, dict) and entry.get("strategy"):
        return str(entry["strategy"])
    return None


def write_cache(name: str, install: str | None = None, ms: int = 0) -> None:
    """Запоминает выигравшую стратегию для конкретной установки."""
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    if not isinstance(data, dict):
        data = {}
    data.pop("best", None)   # старый формат вытесняется записью по установке
    data[_cache_key(install)] = {"strategy": str(name), "ms": int(ms or 0),
                                 "checked": int(time.time())}
    try:
        _cache_path().write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except OSError:
        pass


# -- кэш проверок стратегий: цвета в списке выбора -------------------------
# Отдельный файл от кэша подбора: подбор помнит одну лучшую стратегию,
# здесь - результат каждой проверенной (полный/частичный/нет доступа) со
# временем, чтобы в списке горели точки, а не догадки.
TESTS_TTL = 24 * 3600   # возраст проверки: и маршрут, и стратегии меняются


def _tests_path() -> Path:
    return _probe_dir() / "strategy_tests.json"


def _count_from_targets(targets) -> int:
    """Сколько целей ответило в словаре {имя: {ok, ms, why}}."""
    if not isinstance(targets, dict):
        return 0
    return sum(1 for target in targets.values()
               if isinstance(target, dict) and target.get("ok"))


def _sum_ok(targets) -> int:
    """Сумма мс по ответившим целям - рейтинг для выбора лучшей."""
    if not isinstance(targets, dict):
        return 0
    return sum(int(target.get("ms") or 0) for target in targets.values()
               if isinstance(target, dict) and target.get("ok"))


def tally(results) -> dict:
    """{n, full, partial, none} - строка «✓ 12 · △ 6 · ✗ 4 из 22»."""
    out = {"n": len(results or []), "full": 0, "partial": 0, "none": 0}
    for record in results or []:
        state = str((record or {}).get("state") or "none")
        if state not in ("full", "partial"):
            state = "none"
        out[state] += 1
    return out


def tests_load(install: str | None = None) -> dict:
    """{стратегия: {state, ts, count, ms}} одной установки - для цветов.

    Ключ - путь установки (как в кэше подбора: стратегии у версий свои),
    протухшие записи старше TESTS_TTL выкидываются при чтении.
    """
    try:
        data = json.loads(_tests_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    own = data.get(_cache_key(install))
    if not isinstance(own, dict):
        return {}
    now = time.time()
    fresh = {str(name): record for name, record in own.items()
             if isinstance(record, dict)
             and now - float(record.get("ts") or 0) <= TESTS_TTL}
    if fresh != own:
        data[_cache_key(install)] = fresh
        try:
            _tests_path().write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        except OSError:
            pass
    return fresh


def tests_record(install, name, state, targets=None, ms=None) -> dict:
    """Помечает стратегию результатом проверки (сразу после замера)."""
    state = state if state in ("full", "partial", "none") else "none"
    record = {"state": state, "ts": int(time.time()),
              "count": _count_from_targets(targets), "ms": int(ms or 0)}
    try:
        data = json.loads(_tests_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    key = _cache_key(install)
    own = dict(data.get(key) or {}) if isinstance(data.get(key), dict) else {}
    own[str(name)] = record
    data[key] = own
    try:
        _tests_path().write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except OSError:
        pass
    return record


def cancel_scan() -> dict:
    """Просит помощник остановить перебор после текущей стратегии.

    Отмена - обычный файл: помощник замечает его между стратегиями и всё
    равно доходит до Finish, поэтому проверенное не теряется, а окна и
    лишних запросов прав не появляется.
    """
    try:
        (_probe_dir() / "cancel.flag").write_text("1", encoding="ascii")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


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


def scan(cfg: DpiConfig, log=None, wait: float | None = None,
         progress=None) -> dict:
    """Прогоняет все стратегии и оставляет включённой ту, где доступ полный.

    Это и есть кнопка «Проверить все»: помощник по очереди запускает
    стратегии, меряет четыре цели, пишет ход в progress-файл и итог в JSON,
    победителя не гасит. Каждый результат сразу уходит в кэш цветов, а
    callback progress получает промежуточные итоги - карточка рисует
    «12/22», полоску и точки стратегий, пока перебор идёт.
    {"ok": True, "best": имя, "results": [...], "tally": {...}} либо
    {"ok": False, "error": текст, "results": [...], "tally": {...}}.
    """
    names = strategies(cfg)
    if not names:
        err = cfg.t("sheet.dpi.scan_none")
        if log:
            log("error", err)
        return {"ok": False, "error": err, "results": [], "tally": tally([])}

    def _tick(payload: dict) -> None:
        # каждая измеренная стратегия сразу в кэш и в журнал: обрыв
        # прогона не должен стирать уже проверенное
        results = payload.get("results") or []
        for record in results:
            tests_record(cfg.dir, record.get("name"), record.get("state"),
                         record.get("targets"), ms=record.get("ms"))
        if log and results:
            last = results[-1]
            log("info", f"test [{payload.get('i')}/{payload.get('n')}] "
                        f"{last.get('name')!r} state={last.get('state')} "
                        f"ms={last.get('ms')}")
        if progress:
            progress(payload)

    if log:
        log("info", cfg.t("sheet.dpi.scanning"))
    # на стратегию уходит до ~20с (старт, четыре пробы, спрятать окно); запас
    # даётся с учётом всего списка и старта задачи планировщика
    data = _run_action(cfg, "scan", {"configs": names},
                       wait=wait or (90 + 30 * len(names)), log=log,
                       on_progress=_tick)
    if data is None:
        err = cfg.t("sheet.dpi.no_uac")
        if log:
            log("error", err)
            for line in _runner_tail():
                log("warning", f"scan: {line}")
        return {"ok": False, "error": err, "results": [], "tally": tally([])}
    results = data.get("results") or []
    for record in results:
        tests_record(cfg.dir, record.get("name"), record.get("state"),
                     record.get("targets"), ms=record.get("ms"))
    summary = tally(results)
    cancelled = bool(data.get("cancelled"))
    if log:
        log("info", f"test done: full={summary['full']} "
                    f"partial={summary['partial']} none={summary['none']} "
                    f"of {summary['n']}" + (" cancelled" if cancelled else ""))
    best = data.get("best")
    if data.get("ok") and best and probe_all(timeout=4)["ok"]:
        best_ms = next((int(r.get("ms") or 0) for r in results if r.get("name") == best), 0)
        write_cache(best, install=cfg.dir, ms=best_ms)
        # найденная стратегия становится настроенной: кнопка «Включить обход»
        # и режим без кэша должны работать так же, как только что подобранный
        _remember_strategy(best)
        if log:
            log("info", cfg.t("sheet.dpi.log.scanned", name=best))
        return {"ok": True, "best": str(best), "results": results,
                "tally": summary, "cancelled": cancelled}
    err = cfg.t("sheet.dpi.scan_fail")
    if data.get("error"):
        err = f"{err} ({data['error']})"
    if log:
        log("error", err)
        for line in _runner_tail():
            log("warning", f"scan: {line}")
    return {"ok": False, "error": err, "results": results,
            "tally": summary, "cancelled": cancelled}


def test_one(cfg: DpiConfig, name: str = "", log=None) -> dict:
    """Проверка одной выбранной стратегии - цвет для неё в списке.

    Если обход уже работает, мерится живой маршрут: процесс трогать незачем,
    а важнее знать, отвечает ли то, что запущено прямо сейчас. Если обхода
    нет - выбранная стратегия поднимается и после замера остаётся
    включённой (выключается той же кнопкой «Выключить обход»).
    {"ok", "state", "report", "strategy", "started"} либо
    {"ok": False, "error", "report"}.
    """
    name = str(name or cfg.bat)
    st = status()
    started = False
    if not st["running"]:
        res = start(cfg, log=log, wait=True, bat=name)
        if not res.get("ok"):
            report = res.get("report") or status_report(cfg, log=log)
            tests_record(cfg.dir, name, "none", report.get("targets"))
            return {"ok": False,
                    "error": res.get("error") or cfg.t("sheet.dpi.start_fail"),
                    "report": report, "strategy": name}
        started = True
        # отчёт start - свежий замер (не старше секунды), второй не нужен
        report = res.get("report") or status_report(cfg, log=log)
    else:
        report = status_report(cfg, log=log)
    tests_record(cfg.dir, name, report.get("state"), report.get("targets"),
                 ms=_sum_ok(report.get("targets")))
    if log:
        log("info", f"test one {name!r} started={started}")
    return {"ok": report.get("state") == "full", "state": report.get("state"),
            "report": report, "strategy": name, "started": started}


def orchestrator_path() -> Path:
    r"""Запись о снятом исходном состоянии: %LOCALAPPDATA%\Synfronia\probe."""
    return _probe_dir() / "orchestrator.json"


def pending_restore() -> bool:
    """Остался ли хвост прерванной загрузки - тогда исходное пора вернуть."""
    try:
        return orchestrator_path().is_file()
    except OSError:
        return False


def forget() -> None:
    """Забыть исходное состояние: после keep/off восстанавливать нечего."""
    try:
        orchestrator_path().unlink()
    except OSError:
        pass


def suspend(cfg: DpiConfig, log=None) -> dict:
    """Снимает исходное состояние (службу или процесс) и останавливает его.

    {"ok": True, "original": {...}} - запись сохранена: restore() вернёт
    всё как было; {"ok": False, "error"} - не вышло (снимает помощник,
    поэтому чужое в этом случае не трогалось).
    """
    data = _run_action(cfg, "suspend", {}, wait=90, log=log)
    if data is None:
        err = cfg.t("sheet.dpi.no_uac")
        if log:
            log("error", err)
        return {"ok": False, "error": err}
    if not data.get("ok"):
        err = cfg.t("sheet.dpi.stop_fail")
        if log:
            log("error", err)
        return {"ok": False, "error": err}
    original = data.get("original") or {}
    if log:
        log("info", cfg.t("sheet.dpi.log.suspend", kind=original.get("kind", "none")))
    return {"ok": True, "original": original}


def restore(cfg: DpiConfig, log=None) -> dict:
    """Возвращает исходное состояние и убирает хвост прерванной загрузки."""
    data = _run_action(cfg, "restore", {}, wait=120, log=log)
    if data is None:
        err = cfg.t("sheet.dpi.no_uac")
        if log:
            log("error", err)
        return {"ok": False, "error": err}
    if not data.get("ok"):
        err = cfg.t("sheet.dpi.stop_fail")
        if log:
            log("error", err)
        return {"ok": False, "error": err}
    now = data.get("now") or {}
    if log:
        log("info", cfg.t("sheet.dpi.log.restore", kind=now.get("kind", "none")))
    forget()
    return {"ok": True, "original": data.get("original"), "now": now}


def finish(cfg: DpiConfig, log=None) -> dict:
    """Завершение оркестрации после загрузки - по настройке dpi_after.

    restore - вернуть снятое состояние (службу запустить заново, ручной
    запуск повторить с теми же аргументами), keep - оставить поднятую
    стратегию и забыть о прежнем, off - погасить всё и ничего не возвращать.
    """
    after = after_action(cfg)
    if after == "restore":
        return restore(cfg, log=log)
    if after == "off":
        forget()
        return stop(cfg, log=log)
    forget()
    if log:
        log("info", cfg.t("sheet.dpi.log.keep"))
    return {"ok": True, "action": "keep"}


def auto(cfg: DpiConfig, log=None, force: bool = False) -> dict:
    """Обход перед загрузкой: маршрут -> снятие исходного -> стратегия.

    {"ok": True, "started": False} - обход не нужен или не разрешён;
    {"ok": True, "started": True, "original": {...}, "strategy": имя} -
    подняли выбранную стратегию, исходное состояние снято и сохранено;
    {"ok": False, "error": ..., "restored": bool} - не вышло; если что-то
    уже снимали, исходное возвращено обратно.

    force=True - вмешаться, даже когда настройка говорит «выключено» или
    «спрашивать» (явный выбор в диалоге либо флаг в CLI).
    """
    if not force and (resolve(cfg, False) != "start" or cfg.orch == "ask"):
        # выключено или «спрашивать» без явного выбора: не трогаем и, что
        # важнее, не опрашиваем YouTube при каждом запуске
        return {"ok": True, "started": False}
    if probe_all(timeout=4)["ok"]:
        if log:
            log("info", cfg.t("sheet.dpi.log.ok"))
        return {"ok": True, "started": False}
    names = strategies(cfg)
    if not names:
        err = cfg.t("sheet.dpi.scan_none")
        if log:
            log("error", err)
        return {"ok": False, "error": err}
    # снимаем исходное ДО любых попыток: и подбор, и старт убивают winws,
    # поэтому без сохранённой записи вернуть прежнее было бы нечем
    sus = suspend(cfg, log=log)
    if not sus.get("ok"):
        return {"ok": False, "error": sus.get("error")}
    original = sus.get("original") or {}
    cached = read_cache(install=cfg.dir)
    if cfg.mode == "bat" and cached in names:
        if log:
            log("info", cfg.t("sheet.dpi.log.cache", name=cached))
        res = start(cfg, log=log, bat=cached)
        if res.get("ok") and probe_all(timeout=4)["ok"]:
            return {"ok": True, "started": True, "strategy": cached,
                    "original": original}
        # кэш маршрут не открыл - идём в полный подбор по этой установке
    if log:
        log("warning", cfg.t("sheet.dpi.log.scan"))
    res = scan(cfg, log=log)
    if res.get("ok"):
        return {"ok": True, "started": True, "strategy": res.get("best"),
                "results": res.get("results"), "original": original}
    # ничего не сработало: возвращаем то, что было, и говорим прямо
    back = restore(cfg, log=log)
    err = res.get("error") or cfg.t("sheet.dpi.scan_fail")
    if log:
        log("error", err)
    return {"ok": False, "error": err, "restored": bool(back.get("ok")),
            "original": original}


# -- реестр установок: несколько версий и папок обхода -----------------------
# Вшитый пакет раскладывается в %LOCALAPPDATA%\Synfronia\Bypass, свои папки
# добавляются вручную. Реестр отвечает «какой обход включать», валидация -
# «есть ли там вообще обходники»: winws.exe, файлы стратегий и (для layout-а
# Flowseal) списки. Всё считается относительно папки установки, поэтому
# бандл с версией в имени и чужая распаковка zapret-win-bundle одинаково
# опознаются.

LAYOUT_FLOWSEAL = "flowseal"   # general*.bat + bin\winws.exe + lists\
LAYOUT_WINWS = "winws"         # preset*.cmd + winws.exe (zapret-win-bundle)
_MAX_SCAN_DIRS = 60


def bypass_root() -> Path:
    r"""%LOCALAPPDATA%\Synfronia\Bypass - куда раскладывается вшитый обход."""
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Synfronia" / "Bypass"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return root


def _bundled_dir() -> Path:
    """Папка со вшитыми пакетами: assets/bypass (рядом с исходниками или в _MEIPASS)."""
    here = Path(__file__).resolve().parent
    for root in (here, base_dir()):
        path = root / "assets" / "bypass"
        if path.is_dir():
            return path
    return here / "assets" / "bypass"


def registry_path() -> Path:
    r"""Реестр установок лежит рядом с кэшем: %LOCALAPPDATA%\Synfronia\bypasses.json."""
    return _probe_dir().parent / "bypasses.json"


def _install_dirs(path: Path) -> list[Path]:
    """Сама папка и её подкаталоги до глубины 3: бандл кладёт всё в свою папку."""
    out, frontier = [path], [path]
    for _ in range(3):
        nxt = []
        for d in frontier:
            try:
                kids = [p for p in d.iterdir() if p.is_dir()][:25]
            except OSError:
                continue
            for kid in kids:
                if kid not in out:
                    out.append(kid)
                    nxt.append(kid)
            if len(out) >= _MAX_SCAN_DIRS:
                break
        if len(out) >= _MAX_SCAN_DIRS or not nxt:
            break
        frontier = nxt
    return out[:_MAX_SCAN_DIRS]


def _missing_payload(root: Path, strategies: list) -> list:
    """Файлы-фейки и списки, на которые ссылаются стратегии, но которых нет.

    Ровно та поломка, из-за которой обход умирал мгновенно: из установки
    пропали ACTIVE_*.bin, winws не находил файл из --dpi-desync-fake-* и
    выходил сразу - а проверка смотрела только на наличие папки lists.
    """
    missing = set()
    for rel in strategies:
        try:
            text = (root / str(rel)).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for var, name in re.findall(r"%(\w+)%([^%\r\n\"]+\.\w+)", text):
            folder = {"BIN": "bin", "LISTS": "lists"}.get(var.upper())
            if not folder:
                continue
            target = root / folder / name.strip().strip('"').strip()
            if target.is_file():
                continue
            # *-user.txt service.bat создаёт ДО старта winws (шаблон
            # «Never leave this file empty»), поэтому в свежей распаковке их
            # отсутствие - норма, а не поломка; файлы BIN/ напротив нужны
            # сразу, и именно их отсутствие убивало winws
            if target.name.endswith("-user.txt"):
                continue
            missing.add(f"{var.upper()}/{target.name}")
    return sorted(missing)


def _repair_from_zip(zf, install: Path, top: str) -> int:
    """Дописывает из архива ТОЛЬКО отсутствующие файлы (ничего не затирая).

    Раскладка вшитого пакета могла пострадать от чистки: winws.exe и DLL
    были блокированы и уцелели, а файлы-фейки - нет. Существующие файлы
    не трогаем (пользователь мог их заменить), чужие пути отбрасываем.
    """
    restored = 0
    prefix = f"{top}/"
    base = str(install.resolve()) + os.sep
    for info in zf.infolist():
        name = info.filename
        if info.is_dir() or not name.startswith(prefix):
            continue
        rel = name[len(prefix):]
        if not rel or rel.endswith("/"):
            continue
        target = install / rel
        if target.exists():
            continue
        if not str(target.resolve()).startswith(base):
            continue   # zip-slip: наружу не пишем
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            restored += 1
        except OSError:
            continue   # файл заблокирован (работает winws) - не мешаем
    return restored


def _scan_install(path) -> dict:
    """Разбор установки одним проходом: winws, стратегии, списки, layout."""
    rep = {"path": str(path), "ok": False, "layout": None, "winws": "",
           "strategies": [], "lists": False, "issues": []}
    root = Path(path)
    if not root.is_dir():
        rep["issues"].append("folder")
        return rep
    dirs = _install_dirs(root)
    winws_dir = next((d for d in dirs if (d / WINWS_IMAGE).is_file()), None)
    if winws_dir is None:
        rep["issues"].append("winws")
        return rep
    rep["winws"] = str(winws_dir / WINWS_IMAGE)

    def collect(pattern: str) -> list[str]:
        found: list[str] = []
        for d in dirs:
            for f in sorted(d.glob(pattern), key=lambda p: _natkey(p.name)):
                if f.is_file():
                    found.append(f.relative_to(root).as_posix())
        return found

    bat = collect("general*.bat")
    preset = collect("preset*.cmd")
    if bat:
        rep["layout"], rep["strategies"] = LAYOUT_FLOWSEAL, bat
        rep["lists"] = any((d / "lists").is_dir() for d in dirs)
        if not rep["lists"]:
            rep["issues"].append("lists")
    elif preset:
        rep["layout"], rep["strategies"] = LAYOUT_WINWS, preset
    else:
        rep["issues"].append("strategies")
    # последняя проверка и по совпадению с реальностью: на что ссылаются
    # стратегии и есть ли эти файлы (списки ACTIVE_*.bin как раз так и
    # пропадают - winws при этом умирает сразу после старта)
    missing = _missing_payload(root, rep["strategies"])
    if missing:
        rep["payload"] = missing
        rep["issues"].append("payload")
    rep["ok"] = not rep["issues"]
    return rep


def validate_install(path) -> dict:
    """«Есть ли обходники в папке»: issues - коды, перевод делает фронтенд."""
    return _scan_install(path)


def strategies_in(path) -> list[str]:
    """Относительные пути файлов стратегий установки (натуральный порядок)."""
    return _scan_install(path)["strategies"]


def _item_id(path: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", Path(path).name.lower()).strip("-") or "bypass"
    digest = hashlib.sha1(path.encode("utf-8", "replace")).hexdigest()[:8]
    return f"{slug}-{digest}"


def registry_load() -> dict:
    """Реестр установок: {"active": id|None, "items": [...]}. Битый файл - пусто."""
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    if not isinstance(data, dict):
        data = {}
    items = [i for i in (data.get("items") or [])
             if isinstance(i, dict) and i.get("path")]
    ids = {i.get("id") for i in items}
    active = data.get("active")
    if active not in ids:
        active = items[0].get("id") if items else None
    return {"active": active, "items": items}


def registry_save(data: dict) -> None:
    try:
        registry_path().write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    except OSError:
        pass


def _sync_active_setting(item) -> None:
    """Зеркало активной установки в dpi_dir: панель и CLI читают его же.

    Импорт ленивый: settings тянет схему, схема лениво тянет этот модуль.
    """
    path = (item or {}).get("path", "")
    try:
        import settings as settings_mod
        data = settings_mod.load_settings()
        if data.get("dpi_dir") != path:
            data["dpi_dir"] = path
            settings_mod.save_settings(data)
    except Exception:  # noqa: BLE001 - зеркало вторично относительно реестра
        pass


def registry_add(path, source: str = "local", repo: str = "", tag: str = "",
                 select: bool = True) -> dict:
    """Регистрирует установку после валидации. {"ok": True, "item", "report"}
    либо {"ok": False, "issues": [...], "report"} - битую папку не берём."""
    rep = _scan_install(path)
    if not rep["ok"]:
        return {"ok": False, "issues": rep["issues"], "report": rep}
    resolved = str(Path(path).resolve())
    data = registry_load()
    item = next((i for i in data["items"]
                 if str(Path(str(i["path"])).resolve()) == resolved), None)
    if item is None:
        item = {"id": _item_id(resolved), "path": resolved, "source": source,
                "repo": repo, "tag": tag, "layout": rep["layout"],
                "added": int(time.time())}
        data["items"].append(item)
    elif source != "local" or tag:
        # повторная регистрация после загрузки: происхождение обновляем,
        # иначе установка из GitHub навсегда числится «local» без тега.
        # Обычное же добавление папки (без источника) теги не затирает.
        item.update({"source": source, "repo": repo, "tag": tag})
    item["layout"] = rep["layout"]   # после обновления layout мог измениться
    item["last_seen"] = int(time.time())
    if select or data["active"] not in {i.get("id") for i in data["items"]}:
        data["active"] = item["id"]
    registry_save(data)
    if data["active"] == item["id"]:
        _sync_active_setting(item)
    return {"ok": True, "item": item, "report": rep}


def registry_select(item_id: str) -> dict:
    data = registry_load()
    item = next((i for i in data["items"] if i.get("id") == item_id), None)
    if item is None:
        return {"ok": False, "error": "not_found"}
    data["active"] = item_id
    registry_save(data)
    _sync_active_setting(item)
    return {"ok": True, "item": item}


def registry_remove(item_id: str) -> dict:
    """Убирает установку из реестра (папку на диске не трогает)."""
    data = registry_load()
    before = len(data["items"])
    data["items"] = [i for i in data["items"] if i.get("id") != item_id]
    if len(data["items"]) == before:
        return {"ok": False, "error": "not_found"}
    if data["active"] == item_id:
        data["active"] = data["items"][0].get("id") if data["items"] else None
    registry_save(data)
    active = next((i for i in data["items"] if i.get("id") == data["active"]), None)
    _sync_active_setting(active)
    return {"ok": True, "registry": data}


def _service_dirs() -> list[str]:
    """Папки, на которые указывают службы с winws.exe (service.bat и т.п.).

    Путь службы читается из реестра - без прав администратора; имя службы
    не захардкожено, потому что service*.cmd от разных авторов называют её
    по-разному.
    """
    try:
        import winreg
    except ImportError:
        return []
    out: set[str] = set()
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SYSTEM\CurrentControlSet\Services")
    except OSError:
        return []
    try:
        count = winreg.QueryInfoKey(key)[0]
        for index in range(count):
            try:
                sub = winreg.OpenKey(key, winreg.EnumKey(key, index))
                image = str(winreg.QueryValueEx(sub, "ImagePath")[0])
                winreg.CloseKey(sub)
            except OSError:
                continue
            found = (re.search(r'"([^"]*winws\.exe)"', image, re.I)
                     or re.search(r"(\S*winws\.exe)", image, re.I))
            if found:
                out.add(str(Path(found.group(1)).parent))
    finally:
        winreg.CloseKey(key)
    return sorted(out)


def registry_detect() -> list[dict]:
    """Установки, которых ещё нет в реестре: службы и типовые папки."""
    known = {str(Path(str(i["path"])).resolve()) for i in registry_load()["items"]}
    candidates: set[str] = set(_service_dirs())
    for base in [bypass_root(), Path(r"C:\\"), Path(r"D:\\"), Path(r"E:\\")]:
        try:
            for child in list(base.glob("zapret*"))[:30]:
                if child.is_dir():
                    candidates.add(str(child))
        except OSError:
            continue
    found = []
    for cand in sorted(candidates):
        if cand in known:
            continue
        rep = _scan_install(Path(cand))
        if rep["strategies"]:
            rep["issues"] = [i for i in rep["issues"] if i != "lists"] or rep["issues"]
            found.append(rep)
    return found


def registry_autofill(on_log=None) -> dict:
    """Регистрирует найденные установки, не делая их активными.

    Вызывается при старте до раскладки вшитого пакета: своя установка (её
    служба крутится и так) должна значиться в реестре первой, а вшитый
    пакет - остаться базовым запасным, который подхватится, только когда
    больше ничего нет. Повторные вызовы идемпотентны.
    """
    log = on_log or (lambda level, msg: None)
    before = {i.get("id") for i in registry_load()["items"]}
    added = []
    for report in registry_detect():
        res = registry_add(report["path"], source="local", select=False)
        if res.get("ok") and res["item"].get("id") not in before:
            added.append(res["item"]["path"])
            log("info", f"bypass: найдена установка {res['item']['path']}")
    return {"added": added}


def files_identical(a, b) -> bool:
    """Два файла байт-в-байт одинаковы? (размер, затем sha256)."""
    try:
        if Path(a).stat().st_size != Path(b).stat().st_size:
            return False
    except OSError:
        return False
    left, right = hashlib.sha256(), hashlib.sha256()
    try:
        with open(a, "rb") as first, open(b, "rb") as second:
            while True:
                chunk_a, chunk_b = first.read(1 << 16), second.read(1 << 16)
                if not chunk_a and not chunk_b:
                    break
                left.update(chunk_a)
                right.update(chunk_b)
    except OSError:
        return False
    return left.digest() == right.digest()


def _same_as_archive(zf, info, target: Path) -> bool:
    """Совпадает ли файл на диске байт-в-байт с содержимым архива."""
    try:
        if target.stat().st_size != info.file_size:
            return False
    except OSError:
        return False
    digest = hashlib.sha256()
    try:
        with zf.open(info) as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                digest.update(chunk)
    except OSError:
        return False
    # сравниваем размер уже проверили - хэш только на равных размерах
    other = hashlib.sha256()
    try:
        with open(target, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                other.update(chunk)
    except OSError:
        return False
    return digest.digest() == other.digest()


def _extract_zip(zf, dest: Path) -> tuple:
    """Распаковка: с защитой от zip-slip и с уважением к занятым файлам.

    Проверка путей идёт ДО записи (выход наружу - ValueError, как раньше).
    Дальше каждый файл пишется отдельно: идентичный пропускаем (занятый
    winws.exe не мешает, если это тот же файл - а он и есть), занятый и
    отличающийся собираем в locked. Раньше extractall падал на первом же
    занятом файле, и всё скачивание превращалось в общую ошибку, а установка
    оставалась наполовину перезаписанной.

    Возвращает (сколько записано, список занятых путей).
    """
    base = str(dest.resolve())
    for info in zf.infolist():
        if not info.filename:
            continue
        target = str((dest / info.filename).resolve())
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(f"небезопасный путь в архиве: {info.filename}")
    written, locked = 0, []
    for info in zf.infolist():
        if info.is_dir() or not info.filename:
            continue
        target = dest / info.filename
        if target.exists() and _same_as_archive(zf, info, target):
            continue   # уже такой же - трогать нечего, блокировка не помешает
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written += 1
        except PermissionError:
            locked.append(info.filename)
        except OSError as exc:
            locked.append(f"{info.filename} ({exc})")
    return written, locked


def seed_bundled_bypass(on_log=None) -> dict:
    r"""Раскладывает вшитые пакеты обхода в %LOCALAPPDATA%\Synfronia\Bypass.

    Работает без сети - как шрифты, при первом запуске. Уже существующая
    папка не пересоздаётся, но обязательно попадает в реестр (иначе после
    чистки реестра вшитый обход «исчезнет» из списка). Рядом с архивом
    лежит LICENSE - условие MIT, сам zip лицензии не содержит.

    Возвращает {"added": [...], "skipped": [...], "failed": [...]}.
    """
    report = {"added": [], "skipped": [], "failed": [], "repaired": 0}
    log = on_log or (lambda level, msg: None)
    src = _bundled_dir()
    archives = sorted(src.glob("*.zip")) if src.is_dir() else []
    if not archives:
        log("info", "bypass: вшитых пакетов нет (assets/bypass), пропуск")
        return report
    root = bypass_root()
    select = registry_load()["active"] is None
    for archive in archives:
        try:
            with zipfile.ZipFile(archive) as zf:
                tops = {i.filename.split("/")[0].split("\\")[0]
                        for i in zf.infolist() if i.filename}
                top = next(iter(tops), "")
                install = (root / top) if top else root
                if install.is_dir() and any(install.rglob(WINWS_IMAGE)):
                    report["skipped"].append(install.name)
                    registry_add(install, source="bundled", select=select)
                    select = False
                    # Папка есть, но могла быть вычищена наполовину (чистка
                    # душит только заблокированные файлы, а ACTIVE_*.bin не
                    # заблокированы). Недостающее дописываем из архива.
                    restored = _repair_from_zip(zf, install, top)
                    if restored:
                        report["repaired"] += restored
                        log("info", f"bypass: восстановлено недостающих файлов - {restored}")
                    continue
                _extract_zip(zf, root)
            for license_file in src.glob("LICENSE*"):
                try:
                    shutil.copyfile(license_file, install / license_file.name)
                except OSError:
                    pass
            res = registry_add(install, source="bundled", select=select)
            select = False
            if res.get("ok"):
                report["added"].append(install.name)
                log("info", f"bypass: разложен вшитый пакет {install.name}")
            else:
                report["failed"].append(archive.name)
                log("warning", f"bypass: пакет {archive.name} не прошёл проверку: "
                               f"{','.join(res.get('issues', []))}")
        except Exception as exc:  # noqa: BLE001 - битый архив не должен ронять старт
            report["failed"].append(archive.name)
            log("error", f"bypass: {archive.name} не распаковался ({exc})")
    return report


# Панель настроек модуля: порядок строк = порядок полей, у флажков и полей
# условия видимости относительные (схема превращает их в абсолютные пути).
_WHEN_MODE_BAT = {"key": "mode", "equals": "bat"}
_WHEN_MODE_ARGS = {"key": "mode", "equals": "args"}

SETTINGS = {
    "id": "dpi",
    "label": "sheet.tab.dpi",
    "order": 25,
    "flat_prefix": "dpi_",
    "boxes": {"run": "sheet.dpi.run"},
    "fields": [
        # Плашка состояния - первой строкой: вопрос «включён ли обход
        # вообще» не должен требовать прокрутки до «Проверки и запуска».
        # Текст и точка рисуются из dpi_status() (локально, без сети),
        # кнопка справа - тумблер туда же-обратно. Свой класс строки:
        # плита + кнопка обязаны стоять в одну линию (без переноса).
        {"type": "note", "transient": True, "dom": "dpi-state", "row": 1,
         "row_class": "state-row"},
        {"type": "actions", "transient": True, "row": 1, "buttons": [
            {"dom": "dpi-state-toggle", "label": "sheet.dpi.start"},
        ]},
        {"key": "orch", "type": "choice_buttons", "label": "sheet.dpi.orch",
         "default": "ask",
         "option_hints": {"off": "sheet.dpi.orch.off.hint",
                          "ask": "sheet.dpi.orch.ask.hint",
                          "auto": "sheet.dpi.orch.auto.hint"},
         "options": [["off", "sheet.dpi.orch.off"], ["ask", "sheet.dpi.orch.ask"],
                     ["auto", "sheet.dpi.orch.auto"]]},
        {"key": "after", "type": "choice_buttons", "label": "sheet.dpi.after",
         "default": "restore",
         "option_hints": {"restore": "sheet.dpi.after.restore.hint",
                          "keep": "sheet.dpi.after.keep.hint",
                          "off": "sheet.dpi.after.off.hint"},
         "options": [["restore", "sheet.dpi.after.restore"],
                     ["keep", "sheet.dpi.after.keep"],
                     ["off", "sheet.dpi.after.off"]]},
        {"key": "install", "type": "choice", "label": "sheet.dpi.install",
         "default": "", "dom": "dpi-install", "transient": True,
         # список приходит из get_initial().bypasses (реестр), поэтому
         # options здесь нет - их докрашивает settings.js, как для языков
         "options_source": "bypasses", "value_source": "bypass_active"},
        {"type": "note", "transient": True, "dom": "dpi-install-note"},
        {"type": "actions", "transient": True, "buttons": [
            {"dom": "bypass-choose", "label": "sheet.dpi.choose"},
            {"dom": "bypass-add", "label": "sheet.dpi.add"},
            {"dom": "bypass-detect", "label": "sheet.dpi.detect"},
            {"dom": "bypass-remove", "label": "sheet.dpi.remove"},
        ]},
        {"key": "dir", "type": "text", "label": "sheet.dpi.dir", "default": "",
         # зеркало активной установки: панель его не рисует (его место занял
         # селект выше), но DpiConfig и CLI читают значение отсюда же
         "in_panel": False},
        {"key": "mode", "type": "choice_buttons", "label": "sheet.dpi.mode",
         "default": "bat",
         "option_hints": {"bat": "sheet.dpi.mode.bat.hint",
                          "args": "sheet.dpi.mode.args.hint"},
         "options": [["bat", "sheet.dpi.mode.bat"], ["args", "sheet.dpi.mode.args"]],
         "row": 1},
        {"key": "bat", "type": "choice", "label": "sheet.dpi.bat",
         # список приходит из активной установки (как темы и шрифты), а не
         # задаётся текстом: свободный ввод позволял указать несуществующий
         # файл и узнать об этом лишь при старте
         "default": "general.bat", "options_source": "strategies", "live": True,
         "visible_if": _WHEN_MODE_BAT, "title": "sheet.dpi.bat.hint"},
        # бейдж состояния выбранной стратегии: цвет и когда проверяли.
        # Отдельным полем, а не внутри селекта: нативный select пункты
        # не красит
        {"type": "note", "transient": True, "dom": "dpi-bat-note",
         "hidden": True, "visible_if": _WHEN_MODE_BAT},
        {"key": "args", "type": "text", "label": "sheet.dpi.args", "default": "",
         "placeholder": "--wf-tcp=80,443 --filter-udp=443 ...", "live": True,
         "visible_if": _WHEN_MODE_ARGS, "title": "sheet.dpi.args.hint"},
        {"key": "timeout", "type": "int", "label": "sheet.dpi.timeout",
         "default": 45, "min": 5, "max": 300, "step": 5,
         "box": "run", "row": 1, "title": "sheet.dpi.timeout.hint"},
        {"type": "actions", "transient": True, "box": "run", "row": 2,
         "buttons": [
             {"dom": "dpi-probe", "label": "sheet.dpi.probe"},
             # «Подобрать» разменян на две проверки: выбранную стратегию
             # (цвет для неё) и весь список (цвета для всех + лучшая)
             {"dom": "dpi-test-one", "label": "sheet.dpi.test_one"},
             {"dom": "dpi-test-all", "label": "sheet.dpi.test_all"},
             {"dom": "dpi-start", "label": "sheet.dpi.start"},
             {"dom": "dpi-stop", "label": "sheet.dpi.stop"},
         ]},
        # полоса хода перебора: скрыта, пока проверка не запущена
        {"type": "note", "transient": True, "dom": "dpi-progress", "box": "run",
         "row": 2, "inline": True, "hidden": True},
        {"type": "note", "transient": True, "dom": "dpi-note", "box": "run",
         "row": 2, "inline": True},
    ],
}
