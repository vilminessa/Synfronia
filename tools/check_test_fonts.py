r"""Проверка вшитых/скачиваемых шрифтов без сети.

Что проверяем (fonts.seed_bundled_fonts / fonts.download_test_fonts):
  1. раскладка вшитых шрифтов: три семейства, лицензии и README на месте;
  2. повторный запуск ничего не перезаписывает (пользовательские файлы целы);
  3. докачка с сети (подменённый urlopen): файл валиден, семейство появилось;
  4. повторная докачка не качает заново (existing skip);
  5. битый ответ отбрасывается, .part-* не остаётся, лишних семейств нет;
  6. обрыв сети не роняет вызов и не мешает следующим шрифтам;
  7. файлы в assets/fonts совпадают с разложенными по байтам (сборка не режет).

Запуск:  python tools/check_test_fonts.py
Сеть:    set SYNFONIA_FONTS_NETWORK=1 — дополнительно качает Inter по-настоящему.
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ASSETS = ROOT / "assets" / "fonts"
FAMILIES = {"Inter", "JetBrains Mono", "Noto Sans"}

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


class _Resp(io.BytesIO):
    """Заглушка urlopen: отдаёт заранее заданные байты + Content-Length."""

    def __init__(self, data: bytes, length: int | None = None):
        super().__init__(data)
        self.headers = {"Content-Length": str(length if length is not None else len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(payload: dict[str, bytes]):
    """Возвращает подмену urlopen, раздающую payload по имени файла."""
    calls: list[str] = []

    def opener(req, timeout=None):
        url = getattr(req, "full_url", str(req))
        calls.append(url)
        for name, data in payload.items():
            if name in url:
                return _Resp(data)
        raise OSError(f"404 {url}")

    opener.calls = calls  # type: ignore[attr-defined]
    return opener


def section(title: str) -> None:
    print(f"\n{title}")


def main() -> int:
    if not ASSETS.is_dir():
        print(f"FAIL нет папки {ASSETS}")
        return 1
    iso = Path(tempfile.mkdtemp(prefix="synf-check-fonts-"))
    os.environ["LOCALAPPDATA"] = str(iso)
    for mod in ("fonts",):
        sys.modules.pop(mod, None)
    import fonts  # после подмены LOCALAPPDATA: путь считается на импорте

    root = fonts._fonts_root()
    print(f"изолированный LOCALAPPDATA: {iso}")

    # 1. раскладка вшитых шрифтов
    section("1. раскладка вшитых шрифтов")
    report = fonts.seed_bundled_fonts()
    ok(sorted(report["added"]) == sorted(fonts.BUNDLED_FONTS), "все три шрифта разложены",
       str(report))
    ok(not report["failed"], "без ошибок", str(report["failed"]))
    for name in fonts.BUNDLED_FONTS:
        ok((root / name).is_file() and (root / name).stat().st_size > 1024, f"{name} на месте")
    for name in fonts.BUNDLED_LICENSES:
        ok((root / name).is_file(), f"{name} (лицензия) скопирован")
    ok((root / "README.txt").is_file(), "README.txt написан")
    fams = fonts.load_fonts()
    ok(set(fams) == FAMILIES, "распознаны Inter, JetBrains Mono, Noto Sans", str(sorted(fams)))
    ok(fonts.fonts_embed()["mono"] == ["JetBrains Mono"], "JetBrains Mono помечен моно",
       str(fonts.fonts_embed()["mono"]))
    ok(all(f["variable"] for f in fams.get("Inter", [])), "Inter распознан как вариативный")
    css = fonts.font_css(sorted(FAMILIES))
    ok(0 < len(css) < fonts.MAX_TOTAL_BYTES, "@font-face уложился в лимит страницы",
       f"{len(css)} байт")

    # 2. идемпотентность + приоритет пользовательских файлов
    section("2. повторный запуск не трогает файлы")
    (root / "Inter.ttf").write_bytes((ASSETS / "JetBrainsMono.ttf").read_bytes())
    again = fonts.seed_bundled_fonts()
    ok(again["added"] == [] and sorted(again["skipped"]) == sorted(fonts.BUNDLED_FONTS),
       "второй запуск ничего не добавил", str(again))
    ok((root / "Inter.ttf").read_bytes() == (ASSETS / "JetBrainsMono.ttf").read_bytes(),
       "пользовательский файл не перезаписан")
    shutil.copyfile(ASSETS / "Inter.ttf", root / "Inter.ttf")

    # 3-4. докачка с сети
    section("3. докачка из сети (urlopen подменён)")
    saved_urlopen = fonts.urllib.request.urlopen
    inter = (ASSETS / "Inter.ttf").read_bytes()
    opener = _fake_urlopen({"Inter%5Bopsz%2Cwght%5D.ttf": inter})
    fonts.urllib.request.urlopen = opener
    try:
        (root / "Inter.ttf").unlink()
        res = fonts.download_test_fonts(["Inter.ttf"], on_log=lambda *_: None)
        ok(res["added"] == ["Inter.ttf"], "Inter скачан", str(res))
        ok((root / "Inter.ttf").stat().st_size == len(inter), "размер совпадает с источником")
        ok("Inter" in fonts.load_fonts(), "семейство появилось после докачки")
        res2 = fonts.download_test_fonts(["Inter.ttf"], on_log=lambda *_: None)
        ok(res2["skipped"] == ["Inter.ttf"] and not res2["added"], "повтор не качает заново", str(res2))
        ok(len(opener.calls) == 1, "urlopen вызван один раз", str(len(opener.calls)))

        # 5. битый ответ
        section("5. битый ответ отбрасывается")
        (root / "NotoSans.ttf").unlink()
        fonts.urllib.request.urlopen = _fake_urlopen({"NotoSans": b"definitely not a font" * 500})
        res3 = fonts.download_test_fonts(["NotoSans.ttf"], on_log=lambda *_: None)
        ok(res3["failed"] == ["NotoSans.ttf"], "битый файл в failed", str(res3))
        ok(not (root / "NotoSans.ttf").exists(), "битый файл не попал в папку")
        ok(not list(root.glob(".part-*")), "временных .part-* не осталось")
        ok("Noto Sans" not in fonts.load_fonts(), "лишнего семейства в списке нет")

        # 6. сеть недоступна
        section("6. обрыв сети не ломает вызов")
        def boom(req, timeout=None):
            raise OSError("connection reset by peer")
        fonts.urllib.request.urlopen = boom
        (root / "JetBrainsMono.ttf").unlink()
        res4 = fonts.download_test_fonts(["JetBrainsMono.ttf"], on_log=lambda *_: None)
        ok(res4["failed"] == ["JetBrainsMono.ttf"], "ошибка сети в failed", str(res4))
        ok(not (root / "JetBrainsMono.ttf").exists(), "файл не создан")
        ok(not list(root.glob(".part-*")), "временных файлов не осталось")
    finally:
        fonts.urllib.request.urlopen = saved_urlopen

    # 7. вшитые файлы совпадают с assets (иначе сборка обрежет бинарники)
    section("7. целостность вшитых файлов")
    # после неудачных скачиваний папка неполна — раскладываем заново
    reseed = fonts.seed_bundled_fonts()
    ok(not reseed["failed"], "повторная раскладка без ошибок", str(reseed))
    ok(all((root / n).is_file() for n in fonts.BUNDLED_FONTS),
       "повторная раскладка восстанавливает недостающее", str(reseed["added"]))
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "assets/fonts"],
        capture_output=True, text=True, check=False,
    ).stdout.split()
    ok(len(tracked) >= len(fonts.BUNDLED_FONTS) + len(fonts.BUNDLED_LICENSES),
       "файлы assets/fonts под git", str(tracked))
    ok(all((ROOT / p).is_file() for p in tracked), "все файлы из git на месте")
    for name in fonts.BUNDLED_FONTS:
        ok((ASSETS / name).stat().st_size == (root / name).stat().st_size,
           f"{name}: размер в сборке = в папке шрифтов")
        ok((ASSETS / name).read_bytes() == (root / name).read_bytes(),
           f"{name}: байты совпадают с assets/fonts")

    # опционально: настоящая сеть
    if os.environ.get("SYNFONIA_FONTS_NETWORK") == "1":
        section("8. сетевой smoke-тест (SYNFONIA_FONTS_NETWORK=1)")
        net = Path(tempfile.mkdtemp(prefix="synf-check-fonts-net-"))
        os.environ["LOCALAPPDATA"] = str(net)
        sys.modules.pop("fonts", None)
        import fonts as fonts2
        res = fonts2.download_test_fonts(on_log=lambda lvl, msg: print(f"    [{lvl}] {msg}"))
        ok(len(res["added"]) == len(fonts2.BUNDLED_FONTS), "все шрифты скачались по сети", str(res))
        ok(set(fonts2.load_fonts()) == FAMILIES, "семейства на месте после сети")
        shutil.rmtree(net, ignore_errors=True)

    shutil.rmtree(iso, ignore_errors=True)
    print(f"\nитог: {_checks - len(_fails)}/{_checks} ok")
    if _fails:
        print("провалено: " + ", ".join(_fails))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
