"""Общий для tools/ способ печатать по-русски и с «✕» в любой консоли.

Зачем: Windows-консоль по умолчанию живёт в однобайтовой кодировке (cp1251 на
русской Windows, cp437/cp850 на английской), где нет ни кириллицы, ни «✕».
Скрипты проверок печатают и то, и другое, поэтому при выводе в трубу
(`python tools/... | more`) они падали с UnicodeEncodeError, а под консолью
с кодовой страницей 866 падали на любом русском слове.

force_utf8() переключает уже открытый stdout на UTF-8 с заменой непечатаемых
символов, поэтому вывод остаётся читаемым в cmd/PowerShell без `chcp 65001`.
"""

import sys

__all__ = ["force_utf8"]


def force_utf8() -> None:
    """Перевести stdout/stderr в UTF-8, чтобы печать не падала на кодовой странице.

    errors="replace" — страховка на случай символа, который UTF-8 всё же не
    пропустит: печатаем «?» вместо того, чтобы ронять проверку. Под pythonw
    stdout может быть None, поэтому reconfigure проверяем.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                # поток уже закрыт или перенаправлен не текстом - не наша забота
                pass
