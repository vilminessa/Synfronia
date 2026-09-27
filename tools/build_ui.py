"""Сборка ui.py из исходников интерфейса в ui_src/.

Запуск (из корня репозитория):
    python tools/build_ui.py            # пересобрать ui.py из ui_src/
    python tools/build_ui.py --check    # ui.py актуален? (код возврата 1, если устарел)
    python tools/build_ui.py --extract  # восстановить ui_src/ из текущего ui.py

Зачем это нужно: ui.py — сгенерированный файл, в котором CSS, JS и HTML-шаблон
лежат тремя большими строковыми литералами (APP_CSS / APP_JS / BASE_TEMPLATE).
Правки удобнее вносить в обычные текстовые файлы ui_src/, а этот скрипт
собирает из них ui.py, который импортирует core.build_page().
"""

import ast
import sys
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ui_src"
OUT = ROOT / "ui.py"

# (имя в ui.py, файл исходника в ui_src/)
PARTS = (
    ("APP_CSS", "app.css"),
    ("APP_JS", "app.js"),
    ("BASE_TEMPLATE", "index.html"),
)

HEADER = (
    "# ui.py — АВТО-ГЕНЕРИРУЕМЫЙ ФАЙЛ, не редактируй его вручную.\n"
    "# Исходники интерфейса: ui_src/app.css, ui_src/app.js, ui_src/index.html\n"
    "# Сборка: python tools/build_ui.py   Проверка: python tools/build_ui.py --check"
)

NEWLINE = "\r\n"  # рабочая копия репозитория в CRLF (core.autocrlf=true)


def _read(path: Path) -> str:
    """Читает исходник как текст с LF-переводами строк (в строках ui.py только LF)."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _write(path: Path, text: str) -> None:
    """Пишет файл в CRLF, кодировка UTF-8 без BOM."""
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", NEWLINE).encode("utf-8"))


def _literals() -> dict[str, str]:
    """Достаёт строковые литералы (APP_CSS / APP_JS / BASE_TEMPLATE) из ui.py."""
    out: dict[str, str] = {}
    for line in _read(OUT).split("\n"):
        for name, _ in PARTS:
            if line.startswith(name + " = "):
                out[name] = ast.literal_eval(line.split(" = ", 1)[1])
    missing = [name for name, _ in PARTS if name not in out]
    if missing:
        raise SystemExit(f"{OUT.name}: не найдены литералы: {', '.join(missing)}")
    return out


def render(sources: dict[str, str]) -> str:
    """Собирает текст ui.py из значений литералов (repr даёт однострочные литералы)."""
    lines = [*HEADER.split("\n"), ""]
    for index, (name, _file) in enumerate(PARTS):
        if index:
            lines.append("")
        lines.append(f"{name} = {sources[name]!r}")
    return "\n".join(lines) + "\n"


def build() -> int:
    sources = {name: _read(SRC / file) for name, file in PARTS}
    text = render(sources)
    current = _read(OUT) if OUT.is_file() else ""
    if current == text:
        print(f"{OUT.name}: актуален, пересборка не требуется")
        return 0
    _write(OUT, text)
    print(f"{OUT.name}: пересобран из {SRC.relative_to(ROOT)}")
    return 0


def check() -> int:
    sources = {name: _read(SRC / file) for name, file in PARTS}
    if not OUT.is_file() or _read(OUT) != render(sources):
        print(f"{OUT.name}: УСТАРЕЛ — запусти python tools/build_ui.py")
        return 1
    print(f"{OUT.name}: актуален")
    return 0


def extract() -> int:
    literals = _literals()
    for name, file in PARTS:
        _write(SRC / file, literals[name])
        print(f"{file}: {len(literals[name])} символов")
    return 0


def main(argv: list[str]) -> int:
    SRC.mkdir(parents=True, exist_ok=True)
    if "--check" in argv:
        return check()
    if "--extract" in argv:
        return extract()
    return build()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
