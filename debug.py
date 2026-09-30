r"""Отладочная консоль Synfronia: интерактивное цифровое меню.

    python debug.py

Команды:
  очистка %LOCALAPPDATA%\Synfronia - полностью или оставив только bin\;
  запуск/остановка/состояние приложения;
  логи - хвост, список, показ файла целиком, очистка, следение в реальном
  времени (Ctrl+C возвращает в меню).

Только stdlib и хелперы самого проекта: пути берутся из paths/settings,
кириллица в консоли - через tools/utf8_console. Чистые функции отделены от
меню, их гоняет tools/check_debug.py на временных папках.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import utf8_console  # noqa: E402

utf8_console.force_utf8()

from paths import logs_dir, webview_child_running  # noqa: E402
from settings import settings_path  # noqa: E402

# PowerShell ищет процессы приложения: exe и запуск из исходников (gui.py).
# JSON складывается в файл UTF-8 - конвейер powershell.exe отдаёт байты в
# OEM-кодировке, из-за чего кириллица в путях превращалась бы в кракозябры.
# Файл живёт в %LOCALAPPDATA%\Synfronia\logs (в %TEMP% ничего не пишем).
_PS_FIND = (
    "$p = Get-CimInstance Win32_Process | "
    "Where-Object { $_.Name -eq 'Synfronia.exe' -or $_.CommandLine -match 'gui\\.py' } | "
    "Select-Object ProcessId, Name, CreationDate, CommandLine; "
    "$p | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 '%s'"
)
_PS_TMP = logs_dir() / "debug_ps.json"

MENU = """\
=== Synfronia: отладочная консоль ===
 1. Очистить %LOCALAPPDATA%\\Synfronia полностью
 2. Очистить, оставив только bin\\
 --- приложение ---
 3. Запустить приложение
 4. Завершить приложение
 5. Состояние приложения (PID/время старта)
 --- логи ---
 6. Показать хвост последнего лога (Enter = 50 строк)
 7. Список файлов логов (даты, размеры)
 8. Показать файл лога целиком (выбор по номеру)
 9. Удалить логи
10. Следить за логом в реальном времени (Ctrl+C - назад в меню)
 --- служебное ---
11. Очистить служебные файлы Synfronia в %TEMP%
 0. Выход"""


# -- пути и размеры -----------------------------------------------------------
def app_root() -> Path:
    r"""%LOCALAPPDATA%\Synfronia: там живут настройки, bin, fonts, логи, темы."""
    return settings_path().parent


def human_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} ГБ"


def preview(root: Path, keep_bin: bool) -> list[str]:
    """Строки «что будет удалено»: папки с суммарным размером и файлы."""
    if not root.is_dir():
        return [f"папки нет: {root}"]
    out: list[str] = []
    for child in sorted(root.iterdir()):
        if keep_bin and child.name == "bin":
            out.append(f"  {child.name}\\  -  оставляется (--keep-bin)")
            continue
        if child.is_dir():
            total = sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
            out.append(f"  {child.name}\\  -  {human_size(total)}")
        else:
            out.append(f"  {child.name}  -  {human_size(child.stat().st_size)}")
    return out


def clean_root(root: Path, keep_bin: bool) -> tuple[int, list[str]]:
    """Удалить содержимое root; при keep_bin папка bin сохраняется.

    Возвращает (сколько удалено, список ошибок). Сама папка остаётся:
    её создаёт приложение при старте.
    """
    if not root.is_dir():
        return 0, [f"папки нет: {root}"]
    removed, errors = 0, []
    for child in sorted(root.iterdir()):
        if keep_bin and child.name == "bin":
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1
        except OSError as exc:
            errors.append(f"{child.name}: {exc}")
    return removed, errors


# -- процессы приложения ------------------------------------------------------
def find_app_processes() -> list[dict]:
    """Процессы приложения (Synfronia.exe или python ... gui.py). Только чтение."""
    try:
        _PS_TMP.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return []
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", _PS_FIND % _PS_TMP],
            capture_output=True, timeout=25, check=False,
        )
        if not _PS_TMP.is_file():
            return []
        text = _PS_TMP.read_text(encoding="utf-8-sig").strip()
        _PS_TMP.unlink(missing_ok=True)
        if not text:
            return []
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except (OSError, json.JSONDecodeError):
        return []


def fmt_ps_date(raw: object) -> str:
    """Дата из ConvertTo-Json: PS5 отдаёт /Date(мс)/, PS7 - ISO."""
    s = str(raw or "")
    m = re.match(r"^/Date\((\d+)\)", s)
    if m:
        return time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(int(m.group(1)) / 1000))
    return s or "?"


def run_app(base: Path) -> int:
    """Запуск приложения отдельным процессом. Возвращает PID (0 при ошибке)."""
    exe = base / "Synfronia.exe"
    cmd = [str(exe)] if exe.is_file() else [sys.executable, str(base / "gui.py")]
    log = logs_dir()
    log.mkdir(parents=True, exist_ok=True)
    try:
        fh = open(log / "launcher.log", "ab")
    except OSError as exc:
        print(f"  не открыть лог запуска: {exc}")
        return 0
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(base), stdin=subprocess.DEVNULL,
            stdout=fh, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0x00000008),
        )
        return proc.pid
    except OSError as exc:
        print(f"  не запустить {cmd[0]}: {exc}")
        return 0
    finally:
        fh.close()


def _close_windows(pid: int) -> bool:
    """Отправить WM_CLOSE видимым окнам процесса. True - если отправлено."""
    sent: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        if _user32.IsWindowVisible(hwnd):
            wpid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid:
                _user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                sent.append(hwnd)
        return True

    _user32.EnumWindows(_cb, 0)
    return bool(sent)


def _process_alive(pid: int) -> bool:
    """Проверка через OpenProcess: процесс есть и не завершился."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def stop_app(procs: list[dict]) -> list[int]:
    """Закрыть приложение: сначала мягко (WM_CLOSE - pywebview закрывает
    WebView2 и убирает его каталог, следующий старт стартует со свежего
    профиля), при неудаче - taskkill с деревом. Возвращает закрытые PID."""
    stopped: list[int] = []
    for p in procs:
        pid = int(p.get("ProcessId") or 0)
        if not pid or not _process_alive(pid):
            continue
        if _close_windows(pid):
            for _ in range(10):              # ждём завершения до 5 с
                time.sleep(0.5)
                if not _process_alive(pid):
                    break
        if not _process_alive(pid):
            stopped.append(pid)
            continue
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, timeout=15, check=False)
            if r.returncode == 0:
                stopped.append(pid)
        except OSError:
            pass
    return stopped


# -- окна и служебные файлы в %TEMP% ------------------------------------------
_user32 = ctypes.windll.user32


def window_visible(pid: int) -> bool:
    """Есть ли у процесса видимое окно (user32.EnumWindows)."""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        if _user32.IsWindowVisible(hwnd):
            wpid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid:
                found.append(hwnd)
        return True

    _user32.EnumWindows(_cb, 0)
    return bool(found)


def wait_for_window(pid: int, seconds: float = 15) -> bool:
    """Ждать появления окна процесса (WebView2 может зависнуть при старте)."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if window_visible(pid):
            return True
        time.sleep(0.5)
    return False


def wait_for_ready(pid: int, seconds: float = 15) -> bool:
    """Ждать ЖИВОЕ содержимое: видимое окно И дочерний msedgewebview2.

    Окно появляется раньше и переживает краш WebView2: при умершем
    WebView2 пользователь видит тёмное окно без страницы - одного окна
    как признака запуска недостаточно."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if window_visible(pid) and webview_child_running(pid):
            return True
        time.sleep(0.5)
    return False


def live_webview_dirs() -> set[str]:
    """--user-data-dir живых процессов WebView2: их каталоги трогать нельзя."""
    cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" | "
        "ForEach-Object { $_.CommandLine }"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, timeout=25, check=False)
        text = r.stdout.decode("utf-8", errors="replace")
        return {os.path.normcase(p.rstrip("\\/"))
                for p in re.findall(r'--user-data-dir="?([^"\s]+)"?', text)}
    except OSError:
        return set()


# Артефакты пробников/диагностики и каталоги pywebview (tmp*\EBWebView):
# всё, что раньше копилось в %TEMP% вместо %LOCALAPPDATA%\Synfronia.
_TEMP_JUNK = re.compile(
    r"^(synf|px.*\.txt$|crop_.*\.png$|ring_.*\.png$|red_.*\.png$|"
    r"pair_.*\.png$|after_nudge\.png$|final_state\.png$|sweep_.*\.py$)"
)


def _is_temp_junk(path: Path) -> bool:
    """Каталог pywebview (внутри EBWebView), старый каталог пробников
    или файл-артефакт."""
    if _TEMP_JUNK.match(path.name):
        return True
    return path.is_dir() and (path / "EBWebView").is_dir()


def _held_by_live(path: Path, live: set[str]) -> bool:
    """Каталог занят живым процессом WebView2 (live хранит пути до EBWebView)."""
    prefix = os.path.normcase(str(path) + os.sep)
    return any(d.startswith(prefix) for d in live)


def list_temp_junk(root: Path) -> list[Path]:
    """Служебные файлы Synfronia в %TEMP% (без учёта занятых)."""
    if not root.is_dir():
        return []
    return [c for c in sorted(root.iterdir()) if _is_temp_junk(c)]


def clean_temp(root: Path, live: set[str]) -> tuple[int, list[str], list[str]]:
    """Удалить служебные файлы Synfronia из root; занятые живыми процессами
    пропускаются. Возвращает (удалено, ошибки, пропущено)."""
    removed, errors, skipped = 0, [], []
    for child in list_temp_junk(root):
        if _held_by_live(child, live):
            skipped.append(child.name)
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1
        except OSError as exc:
            errors.append(f"{child.name}: {exc}")
    return removed, errors, skipped


# -- логи ---------------------------------------------------------------------
def log_files() -> list[Path]:
    """Все логи по времени изменения (свежий в конце)."""
    try:
        return sorted(logs_dir().glob("*.log"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return []


def tail_file(path: Path, n: int) -> list[str]:
    """Последние n строк файла (utf-8 с заменой битых байтов)."""
    if not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def new_lines(path: Path, pos: int) -> tuple[list[str], int]:
    """Новые строки файла с позиции pos (для follow): (строки, новая позиция)."""
    try:
        size = path.stat().st_size
        if size < pos:                    # файл пересоздали (смена дня)
            pos = 0
        if size == pos:
            return [], pos
        with open(path, "rb") as fh:
            fh.seek(pos)
            chunk = fh.read()
        text = chunk.decode("utf-8", errors="replace")
        lines = text.splitlines()
        return lines, size
    except OSError:
        return [], pos


# -- диалоги ------------------------------------------------------------------
def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def confirm(question: str) -> bool:
    return ask(f"{question} (y/N): ").lower() in ("y", "yes", "д", "да")


def pause() -> None:
    ask("\nEnter - вернуться в меню...")


def op_clean(root: Path, keep_bin: bool) -> None:
    title = "полная очистка" if not keep_bin else "очистка с сохранением bin\\"
    print(f"\n--- {title}: {root} ---")
    if not root.is_dir():
        print("  папки нет - очищать нечего")
        pause()
        return
    procs = find_app_processes()
    if procs:
        print("  приложение запущено, файлы могут быть заблокированы:")
        for p in procs:
            print(f"    PID {p.get('ProcessId')}  {p.get('Name')}")
        if confirm("  завершить приложение сейчас?"):
            stopped = stop_app(procs)
            print(f"  завершено: {len(stopped)}")
        else:
            print("  отмена: сначала завершите приложение (пункт 4)")
            pause()
            return
    for line in preview(root, keep_bin):
        print(line)
    if not confirm("Удалить перечисленное?"):
        print("  отмена")
        pause()
        return
    removed, errors = clean_root(root, keep_bin)
    print(f"  удалено элементов: {removed}")
    for e in errors:
        print(f"  ошибка: {e}")
    pause()


def op_run(base: Path) -> None:
    busy = find_app_processes()
    if busy:
        print("  приложение уже запущено:")
        for p in busy:
            print(f"    PID {p.get('ProcessId')}  {p.get('Name')}")
        print("  сначала завершите его (пункт 4)")
        pause()
        return
    src = "Synfronia.exe" if (base / "Synfronia.exe").is_file() else "gui.py"
    # Сторож: WebView2 при старте может зависнуть без окна или умереть после
    # показа окна (тёмное окно без страницы) - убиваем и пробуем ещё раз,
    # потом отдаём диагностику.
    for attempt in (1, 2):
        pid = run_app(base)
        if not pid:
            break
        print(f"  запущен {src}, PID {pid} (вывод - logs\\launcher.log); "
              f"жду окно и WebView2 (15 с), попытка {attempt}/2...")
        if wait_for_ready(pid, 15):
            print(f"  окно с содержимым готово - запущен PID {pid}")
            pause()
            return
        state = f"окно={'есть' if window_visible(pid) else 'нет'}, " \
                f"WebView2={'есть' if webview_child_running(pid) else 'нет'}"
        print(f"  не запустилось ({state}) - завершаю и повторяю")
        stop_app([{"ProcessId": pid}])
        time.sleep(1)
    else:
        print("  повтор не помог: запустите python gui.py --diagnose-freeze "
              "и посмотрите gui_diag.log")
    pause()


def op_stop() -> None:
    procs = find_app_processes()
    if not procs:
        print("  приложение не запущено")
    else:
        for p in procs:
            print(f"  PID {p.get('ProcessId')}  {p.get('Name')}")
        stopped = stop_app(procs)
        print(f"  завершено: {len(stopped)} из {len(procs)}")
    pause()


def op_status() -> None:
    procs = find_app_processes()
    if not procs:
        print("  приложение не запущено")
    else:
        for p in procs:
            print(f"  PID {p.get('ProcessId')}  {p.get('Name')}  "
                  f"старт {fmt_ps_date(p.get('CreationDate'))}")
    pause()


def op_tail() -> None:
    files = log_files()
    if not files:
        print("  логов нет")
        pause()
        return
    raw = ask("Сколько строк [50]: ")
    try:
        n = max(1, int(raw)) if raw else 50
    except ValueError:
        n = 50
    print(f"\n--- {files[-1].name} (последние {n}) ---")
    for line in tail_file(files[-1], n):
        print(line)
    pause()


def op_logs_list() -> None:
    files = log_files()
    if not files:
        print("  логов нет")
    else:
        for i, f in enumerate(files, 1):
            when = time.strftime("%d.%m.%Y %H:%M", time.localtime(f.stat().st_mtime))
            print(f"  {i}. {f.name}  {human_size(f.stat().st_size)}  {when}")
    pause()


def op_logs_show() -> None:
    files = log_files()
    if not files:
        print("  логов нет")
        pause()
        return
    for i, f in enumerate(files, 1):
        print(f"  {i}. {f.name}")
    raw = ask("Номер файла [Enter = свежий]: ")
    idx = len(files)
    if raw:
        try:
            idx = int(raw)
        except ValueError:
            idx = len(files)
    if not 1 <= idx <= len(files):
        print("  нет такого номера")
        pause()
        return
    path = files[idx - 1]
    print(f"\n--- {path.name} ---")
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            print(line)
    except OSError as exc:
        print(f"  ошибка: {exc}")
    pause()


def op_logs_clear() -> None:
    files = log_files()
    if not files:
        print("  логов нет")
        pause()
        return
    if not confirm(f"Удалить логи ({len(files)} файлов)?"):
        print("  отмена")
        pause()
        return
    done, errors = 0, []
    for f in files:
        try:
            f.unlink()
            done += 1
        except OSError as exc:
            errors.append(f"{f.name}: {exc}")
    print(f"  удалено: {done}")
    for e in errors:
        print(f"  ошибка: {e}")
    pause()


def op_logs_follow() -> None:
    files = log_files()
    if not files:
        print("  логов нет")
        pause()
        return
    path = files[-1]
    print(f"--- следим за {path.name} (Ctrl+C - назад в меню) ---")
    pos = path.stat().st_size          # с конца: прошлого не печатаем
    try:
        while True:
            lines, pos = new_lines(path, pos)
            for line in lines:
                print(line)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n  прервано")


def op_temp_clean() -> None:
    root = Path(tempfile.gettempdir())
    print(f"\n--- служебные файлы Synfronia в {root} ---")
    junk = list_temp_junk(root)
    if not junk:
        print("  чисто - удалять нечего")
        pause()
        return
    live = live_webview_dirs()
    for c in junk:
        note = " (занят живым процессом - пропускаю)" if _held_by_live(c, live) else ""
        print(f"  {c.name}{note}")
    if not confirm("Удалить перечисленное?"):
        print("  отмена")
        pause()
        return
    removed, errors, skipped = clean_temp(root, live)
    print(f"  удалено: {removed}")
    for s in skipped:
        print(f"  пропущено (занято): {s}")
    for e in errors:
        print(f"  ошибка: {e}")
    pause()


def main() -> int:
    base = Path(__file__).resolve().parent
    root = app_root()
    actions = {
        "1": lambda: op_clean(root, keep_bin=False),
        "2": lambda: op_clean(root, keep_bin=True),
        "3": lambda: op_run(base),
        "4": op_stop,
        "5": op_status,
        "6": op_tail,
        "7": op_logs_list,
        "8": op_logs_show,
        "9": op_logs_clear,
        "10": op_logs_follow,
        "11": op_temp_clean,
    }
    while True:
        print()
        print(MENU)
        choice = ask("Выбор: ")
        if choice in ("0", "", "q", "выход"):
            return 0
        action = actions.get(choice)
        if action is None:
            print("  неизвестный пункт, попробуйте снова")
            continue
        try:
            action()
        except KeyboardInterrupt:
            print("\n  прервано")   # Ctrl+C внутри команды - назад в меню
        except OSError as exc:
            print(f"  ошибка: {exc}")
            pause()


if __name__ == "__main__":
    sys.exit(main())
