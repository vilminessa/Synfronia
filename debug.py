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

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import utf8_console  # noqa: E402

utf8_console.force_utf8()

from paths import logs_dir  # noqa: E402
from settings import settings_path  # noqa: E402

# PowerShell ищет процессы приложения: exe и запуск из исходников (gui.py).
# JSON складывается в файл UTF-8 - конвейер powershell.exe отдаёт байты в
# OEM-кодировке, из-за чего кириллица в путях превращалась бы в кракозябры.
_PS_FIND = (
    "$p = Get-CimInstance Win32_Process | "
    "Where-Object { $_.Name -eq 'Synfronia.exe' -or $_.CommandLine -match 'gui\\.py' } | "
    "Select-Object ProcessId, Name, CreationDate, CommandLine; "
    "$p | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 '%s'"
)
_PS_TMP = Path(os.environ.get("TEMP", ".")) / "synf_debug_ps.json"

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
    if not _PS_TMP.parent.is_dir():
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


def stop_app(procs: list[dict]) -> list[int]:
    """Завершить найденные процессы (taskkill с деревом). Возвращает закрытые PID."""
    stopped: list[int] = []
    for p in procs:
        pid = int(p.get("ProcessId") or 0)
        if not pid:
            continue
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, timeout=15, check=False)
            if r.returncode == 0:
                stopped.append(pid)
        except OSError:
            pass
    return stopped


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
    pid = run_app(base)
    if pid:
        src = "Synfronia.exe" if (base / "Synfronia.exe").is_file() else "gui.py"
        print(f"  запущен {src}, PID {pid} (вывод - logs\\launcher.log)")
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
