r"""Проверка того, что скрипты в tools/ переживают консоль Windows.

Зачем: консоль Windows сидит в однобайтовой кодовой странице (cp1251 на русской
Windows, cp437/cp850 на английской), где нет ни кириллицы, ни «✕». Проверки
печатают и то, и другое, поэтому при выводе в трубу (`python tools/... | more`)
они падали с UnicodeEncodeError, а на кодовой странице 866 - на любом русском
слове. Ловушка в том, что в окне терминала с UTF-8 всё работает, и поломка
выглядит случайной: у кого-то скрипт проходит, у кого-то нет.

Что проверяем (tools/utf8_console.py -> force_utf8() вызывается всеми скриптами):
  1. каждый скрипт в tools/ зовёт utf8_console.force_utf8() - новый скрипт не забудет;
  2. контроль: БЕЗ переключения на UTF-8 печать «✕» в cp1251 действительно падает,
     иначе проверка ниже ничего бы не проверяла;
  3. force_utf8() печатает и кириллицу, и «✕» в cp1251 и в cp437 без ошибок;
  4. настоящий скрипт проверок (check_download_button.py) на чужой кодовой странице
     доходит до конца и печатает «✕»-строку, а не падает на середине;
  5. build_ui.py --check на cp437 (кириллица в «ui.py: актуален»).

Запуск:  python tools/check_tools_output.py
"""

import os
import subprocess
import sys
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent

_fails: list[str] = []
_checks = 0


def ok(cond: bool, label: str, detail: str = "") -> bool:
    global _checks
    _checks += 1
    if cond:
        print(f"  ok   {label}")
        return True
    print(f"  FAIL {label}{(': ' + detail) if detail else ''}")
    _fails.append(label)
    return False


def section(title: str) -> None:
    print(f"\n{title}")


def child(args: list[str], encoding: str, cwd: Path) -> subprocess.CompletedProcess:
    """Запустить скрипт с чужой кодовой страницей и прочитать вывод как UTF-8.

    Кодировку задаём через PYTHONIOENCODING, а не через chcp: так проверка
    работает в CI и в любом терминале, а decode всегда один и тот же.
    """
    env = {**os.environ, "PYTHONIOENCODING": encoding, "PYTHONUTF8": "0"}
    return subprocess.run([sys.executable, *args], cwd=str(cwd), env=env,
                          capture_output=True, timeout=120)


def calls_force_utf8(text: str) -> bool:
    """Живой вызов, а не упоминание в комментарии.

    Ищем строку, у которой после отступов идёт именно вызов: закомментированный
    `# utf8_console.force_utf8()` не считается, иначе проверка проходила бы после
    отключения.
    """
    return any(line.strip().startswith("utf8_console.force_utf8()")
               for line in text.splitlines())


def tracked_by_git(path: Path) -> bool | None:
    """Не игнорируется ли файл правилами .gitignore.

    Важно: в .gitignore есть `_*` (временные скрипты opencode), и под него
    молча попадал tools/_console.py - в коммите его бы не оказалось, а все
    проверки падали бы с ImportError. None - git недоступен или это не
    репозиторий (например, распакованный архив), тогда не придираемся.
    """
    try:
        res = subprocess.run(["git", "check-ignore", "-q", "--", str(path)],
                             cwd=str(ROOT), capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode not in (0, 1):
        return None  # git есть, но ответ не про ignore (например, не репозиторий)
    return res.returncode == 1


def main() -> int:
    section("каждый скрипт tools/ переключает вывод на UTF-8")
    for path in sorted(TOOLS.glob("*.py")):
        if path.name == "utf8_console.py":
            continue
        text = path.read_text(encoding="utf-8")
        ok(calls_force_utf8(text), f"{path.name} зовёт utf8_console.force_utf8()")

    helper = TOOLS / "utf8_console.py"
    ignored = tracked_by_git(helper)
    if ignored is None:
        print("  --   проверка .gitignore пропущена: git недоступен или это не репозиторий")
    else:
        ok(ignored, "utf8_console.py не попадает под .gitignore",
           "в коммит файл не попадёт, и проверки сломаются на ImportError"
           if not ignored else "")

    section("контроль: без force_utf8() печать «✕» падает (проверка не пустая)")
    # Тот же дочерний процесс, что и ниже, только без переключения кодировки.
    plain = child(["-c", "print('\\u2715 не печатается')"], "cp1251", TOOLS)
    ok(plain.returncode != 0 and "UnicodeEncodeError" in plain.stderr.decode("utf-8", "replace"),
       "cp1251 без force_utf8() даёт UnicodeEncodeError", f"rc={plain.returncode}")
    ok("✕" not in plain.stdout.decode("utf-8", "replace"),
       "и сам «✕» до вывода не доходит")

    section("force_utf8() печатает кириллицу и «✕» на чужой кодовой странице")
    guarded = "import utf8_console; utf8_console.force_utf8(); print('\\u2715 проверка')"
    for encoding in ("cp1251", "cp437", "cp866"):
        res = child(["-c", guarded], encoding, TOOLS)
        text = res.stdout.decode("utf-8", "replace")
        ok(res.returncode == 0 and "✕" in text and "проверка" in text,
           f"{encoding}: «✕» и кириллица печатаются как есть",
           f"rc={res.returncode} out={text.strip()[:40]!r}")

    section("настоящие скрипты доходят до конца на чужой кодовой странице")
    dl = child([str(TOOLS / "check_download_button.py")], "cp1251", ROOT)
    out = dl.stdout.decode("utf-8", "replace")
    ok(dl.returncode == 0 and "UnicodeEncodeError" not in out,
       "check_download_button.py не падает на «✕» в подписях проверок",
       f"rc={dl.returncode}")
    ok("✕" in out, "«✕» в подписи проверки всё-таки напечатан")
    ui = child([str(TOOLS / "build_ui.py"), "--check"], "cp437", ROOT)
    ok(ui.returncode == 0 and "актуален" in ui.stdout.decode("utf-8", "replace"),
       "build_ui.py --check печатает «актуален» на cp437",
       f"rc={ui.returncode}")

    print(f"\nитог: {_checks - len(_fails)}/{_checks} ok")
    if _fails:
        print("провалено: " + ", ".join(_fails))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
