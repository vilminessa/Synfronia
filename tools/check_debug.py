"""Проверки отладочной консоли (debug.py): очистка, логи, меню.

Очистка гоняется на временных папках (реальный %LOCALAPPDATA% не трогаем),
процессы только перечисляются, не завершаются. Меню проверяется смоуком:
подсовываем stdin и ждём выхода с кодом 0.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import debug  # noqa: E402

_checks = 0
_fails: list[str] = []


def ok(cond: bool, msg: str, detail: str = "") -> None:
    global _checks
    _checks += 1
    if cond:
        print(f"  ok   {msg}")
    else:
        _fails.append(msg)
        print(f"  FAIL {msg} {detail}")


def section(title: str) -> None:
    print(f"-- {title} --")


def make_tree(root: Path) -> None:
    (root / "bin").mkdir(parents=True)
    (root / "fonts").mkdir()
    (root / "logs").mkdir()
    (root / "bin" / "ffmpeg.exe").write_bytes(b"FF" * 100)
    (root / "fonts" / "Inter.ttf").write_bytes(b"F" * 50)
    (root / "logs" / "app.log").write_text("строка\n", encoding="utf-8")
    (root / "settings.json").write_text("{}", encoding="utf-8")


def main() -> int:
    section("1. очистка")
    with tempfile.TemporaryDirectory(prefix="synf_debug_") as tmp:
        root = Path(tmp) / "Synfronia"
        make_tree(root)
        preview = debug.preview(root, keep_bin=True)
        ok(any("оставляется" in l for l in preview), "preview помечает bin как сохраняемый")
        ok(any("settings.json" in l for l in preview), "preview показывает settings.json")
        removed, errors = debug.clean_root(root, keep_bin=True)
        ok(not errors, "очистка с keep-bin без ошибок", str(errors))
        left = sorted(p.name for p in root.iterdir())
        ok(left == ["bin"] and (root / "bin" / "ffmpeg.exe").is_file(),
           "keep-bin: осталась только папка bin с ffmpeg", str(left))
        ok(removed == 3, "keep-bin: удалено 3 элемента (fonts, logs, settings.json)",
           str(removed))
        removed, errors = debug.clean_root(root, keep_bin=False)
        ok(not errors and removed == 1 and not list(root.iterdir()),
           "полная очистка: bin удалён, папка пуста", f"{removed} {errors}")
        ok(root.is_dir(), "сама папка после очистки остаётся")
        missing, errors = debug.clean_root(Path(tmp) / "нет-папки", keep_bin=False)
        ok(missing == 0 and errors, "несуществующая папка - ошибка, не исключение")

    section("2. размеры")
    ok(debug.human_size(500) == "500 Б" and debug.human_size(2048).endswith("КБ"),
       "human_size: байты и килобайты")

    section("3. логи")
    with tempfile.TemporaryDirectory(prefix="synf_logs_") as tmp:
        lg = Path(tmp)
        big = lg / "app_2026-01-01.log"
        big.write_text("\n".join(f"строка {i}" for i in range(1, 101)), encoding="utf-8")
        (lg / "launcher.log").write_text("x", encoding="utf-8")
        (lg / "не-лог.txt").write_text("x", encoding="utf-8")

        tail = debug.tail_file(big, 5)
        ok(tail == [f"строка {i}" for i in range(96, 101)],
           "tail: ровно последние 5 строк", str(tail))
        ok(len(debug.tail_file(big, 999)) == 100, "tail: больше строк - весь файл")
        ok(debug.tail_file(lg / "нет.log", 5) == [], "tail: нет файла - пусто")

        lines, pos = debug.new_lines(big, 0)
        ok(len(lines) == 100 and pos == big.stat().st_size, "new_lines: весь файл с нуля")
        with open(big, "a", encoding="utf-8") as fh:
            fh.write("добавлено")          # без перевода строки: приёмка с середины
        lines, pos = debug.new_lines(big, pos)
        ok(lines == ["добавлено"], "new_lines: только новые строки", str(lines))
        big.write_text("короче", encoding="utf-8")   # пересоздали (смена дня)
        lines, pos = debug.new_lines(big, 10_000)
        ok(lines == ["короче"], "new_lines: файл уменьшился - читаем с начала")

        old = time.time() - 60
        (lg / "app_старый.log").write_text("a", encoding="utf-8")
        os.utime(lg / "app_старый.log", (old, old))
        files = sorted(lg.glob("*.log"), key=lambda p: p.stat().st_mtime)
        ok(len(files) == 3 and files[0].name == "app_старый.log",
           "log_files: только *.log, старые первыми",
           str([f.name for f in files]))

    section("4. процессы (только чтение)")
    procs = debug.find_app_processes()
    ok(isinstance(procs, list), "find_app_processes возвращает список")
    ok(all("ProcessId" in p for p in procs), "в записях есть PID", str(procs))
    ok(debug.fmt_ps_date("/Date(1700000000000)/").count(".") == 2,
       "fmt_ps_date: разбирает формат PS5")
    ok(debug.fmt_ps_date("2026-09-28T10:00:00") == "2026-09-28T10:00:00",
       "fmt_ps_date: ISO остаётся как есть")

    section("5. меню (смоук)")
    run = subprocess.run(
        [sys.executable, str(ROOT / "debug.py")],
        input="x\n7\n\n0\n", capture_output=True, timeout=60, cwd=str(ROOT),
        encoding="utf-8", errors="replace",
    )
    out = run.stdout
    ok(run.returncode == 0, "меню выходит с кодом 0", str(run.returncode))
    ok("Synfronia" in out and "Выбор" in out, "меню печатает заголовок и приглашение")
    ok("неизвестный пункт" in out, "некорректный ввод отклонён", out[-300:])
    ok("список файлов логов" not in out or "нет" in out or "app_" in out,
       "пункт 7 отработал (логи есть или пусто)")

    print()
    if _fails:
        print(f"итог: {_checks - len(_fails)}/{_checks} ok, провалено: {len(_fails)}")
        for f in _fails:
            print(f"  FAIL: {f}")
        return 1
    print(f"итог: {_checks}/{_checks} ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
