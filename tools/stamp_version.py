r"""Вписывает версию из тега в рабочее дерево - коммиты с бампом не нужны.

    python tools/stamp_version.py v1.2.7.5
    python tools/stamp_version.py b1.2.7.41

Что делает: version.py (__version__ + BUILD_LABEL) и based_settings.json
(app_version) получают значения из тега - ОБА разом, иначе проверки
«version.py <-> based_settings» разъезжаются. Подпись идёт байтовой
заменой внутри строки: перевод строк и форматирование файлов не трогаются
(ни одного лишнего диффа, если запустить локально).

Кто зовёт: workflow release в джобе build перед PyInstaller - футер,
VersionInfo exe и данные настроек уезжают в бандл уже с теговой версией;
в git ничего не попадает (рабочее дерево CI одноразовое). Локально - перед
ручной сборкой exe из тега.

Формат тега: [vb]X.Y.Z или [vb]X.Y.Z.N - максимум четыре компонента
(Windows VersionInfo не принимает больше). Префикс v/b сохраняется в
BUILD_LABEL: интерфейс релиза покажет «v1.2.7.5», беты - «b1.2.7.41».
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import utf8_console  # noqa: E402 - локальный помощник tools/

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"^([vb])(\d+\.\d+\.\d+(?:\.\d+)?)$")


def stamp(tag: str) -> tuple[str, str]:
    """(версия, подпись) из тега; ValueError - формат не распознан."""
    clean = (tag or "").strip()
    m = TAG_RE.match(clean)
    if not m:
        raise ValueError(
            f"тег {clean!r} не распознан: ожидается v1.2.7.5 или b1.2.7.41")
    return m.group(2), clean


def _replace(path: Path, pattern: bytes, replacement: bytes) -> bool:
    """Байтовая замена внутри файла: кодировки и переводы строк не трогаем."""
    raw = path.read_bytes()
    updated, count = re.subn(pattern, replacement, raw, count=1)
    if count:
        path.write_bytes(updated)
    return bool(count)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip())
        return 2
    try:
        version, label = stamp(argv[1])
    except ValueError as exc:
        print(f"ошибка: {exc}")
        return 1
    ok_ver = _replace(ROOT / "version.py",
                      rb'__version__\s*=\s*"[^"]*"',
                      f'__version__ = "{version}"'.encode("ascii"))
    ok_label = _replace(ROOT / "version.py",
                        rb'BUILD_LABEL\s*=\s*"[^"]*"',
                        f'BUILD_LABEL = "{label}"'.encode("ascii"))
    ok_cfg = _replace(ROOT / "based_settings.json",
                      rb'"app_version":\s*"[^"]*"',
                      f'"app_version": "{version}"'.encode("ascii"))
    if not (ok_ver and ok_label and ok_cfg):
        print("ошибка: не нашёл поля для записи "
              f"(version={ok_ver}, label={ok_label}, app_version={ok_cfg})")
        return 1
    print(f"version.py: __version__ = {version}, BUILD_LABEL = {label}")
    print(f"based_settings.json: app_version = {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
