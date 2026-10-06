"""Линт библиотеки стилей: ui_src/util.css и слои (ловит сдвиги до раннера).

Библиотека (см. DEVELOPING.md «Библиотека стилей»): util.css генерируется из
шкал STYLE в tools/build_ui.py (токены :root + атомарные классы u-*), стили
окон упакованы в слой syn-components, авторский CSS темы themes.py кладёт в
syn-theme, утилиты живут в syn-utilities: компоненты < тема < утилиты.

Что проверяем:
  1. util.css существует и побайтово равен gen_util_css() - правки только через
     шкалы STYLE, ручная правка файла разъезжается с генератором;
  2. в util.css объявлена линия слоёв syn-components, syn-theme, syn-utilities;
  3. app/main/settings css целиком упакованы в @layer syn-components, а
     __UTIL_CSS__ есть в шаблоне и подставляется themes.py;
  4. классы u-* определяются ТОЛЬКО в util.css (никто не пишет атомарные
     классы руками - иначе библиотека расслаивается);
  5. каждый var(--...) в util.css разрешён: задан в его :root либо взят из
     палитры темы (и её радиусов/шрифтов);
  6. themes.py объявляет порядок слоёв и оборачивает CSS темы в syn-theme -
     иначе авторский стиль темы молча проиграл бы компонентам;
  7. @media в util.css используют только BREAKPOINTS-значения.

Запуск:  python tools/check_ui_style.py
"""

import re
import sys
from pathlib import Path

import build_ui  # шкалы и генератор (tools/ в sys.path[0], как у всех чеков)
import utf8_console  # локальный помощник tools/

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ui_src"
UTIL = SRC / "util.css"
THEMES = ROOT / "themes.py"
# переменные темы, на которые могут ссылаться утилиты (помимо своих шкал)
THEME_VARS = {f"--{k}" for k in build_ui.PALETTE} | {
    "--radius-s", "--radius-m", "--radius-l",
    "--font-sans", "--font-mono", "--font-head", "--font-weight", "--opacity",
}
LAYER_DECL = "@layer syn-components, syn-theme, syn-utilities;"

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


def main() -> int:
    section("1. util.css сгенерирован, а не правлен руками")
    want = build_ui.gen_util_css()
    have = (UTIL.read_text(encoding="utf-8").replace("\r\n", "\n")
            if UTIL.is_file() else "")
    ok(have == want,
       "util.css совпадает с генератором build_ui (правки - только в STYLE)",
       f"файл {len(have)} симв. != генератор {len(want)} симв.")

    section("2. порядок слоёв объявлен в util.css")
    ok(LAYER_DECL in have, "строка @layer syn-components, syn-theme, syn-utilities",
       have[:120])

    section("3. компоненты упакованы в слой, плейсхолдер на месте")
    for name in ("app.css", "main.css", "settings.css"):
        text = (SRC / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        wrapped = (text.lstrip().startswith("@layer syn-components {")
                   and text.rstrip().endswith("}"))
        ok(wrapped, f"{name} целиком в @layer syn-components", text[:40])
    template = (SRC / "index.html").read_text(encoding="utf-8")
    ok("__UTIL_CSS__" in template, "__UTIL_CSS__ есть в шаблоне главного окна")
    ok("__UTIL_CSS__" not in (SRC / "settings.html").read_text(encoding="utf-8"),
       "фрагмент карточки не подключает утилиты сам")
    themes_src = THEMES.read_text(encoding="utf-8")
    ok('page.replace("__UTIL_CSS__", _ui.UTIL_CSS)' in themes_src,
       "themes.py подставляет __UTIL_CSS__")

    section("4. классы u-* определяются только в util.css")
    stray: list[str] = []
    pattern = re.compile(r"\.u-[a-z0-9-]+")
    for name in ("app.css", "main.css", "settings.css"):
        stray += [f"{name}:{m.group(0)}" for m in
                  pattern.finditer((SRC / name).read_text(encoding="utf-8"))]
    for name in ("index.html", "settings.html"):
        text = (SRC / name).read_text(encoding="utf-8")
        # определение стиля в разметке: <style>.u-...</style>; class= разрешён
        stray += [f"{name}:{m.group(0)}" for m in
                  pattern.finditer(re.sub(r'class="[^"]*"', "", text))]
    ok(not stray, "ни одного своего .u-* селектора вне util.css", str(stray[:5]))

    section("5. все var(--...) в util.css разрешимы")
    # разбор именно блока :root (первый {...} после :root)
    defs: set[str] = set()
    m_root = re.search(r":root\s*\{([^}]*)\}", have)
    if m_root:
        defs = set(re.findall(r"--[a-z0-9-]+(?=\s*:)", m_root.group(1)))
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", have))
    unresolved = sorted(used - defs - THEME_VARS)
    ok(not unresolved, "каждая переменная из шкал или палитры темы",
       str(unresolved))
    ok("--radius-pill" in defs and "--focus-ring" in defs,
       "таблетка и кольцо фокуса заданы в токенах")

    section("6. тема живёт в слое syn-theme")
    ok(LAYER_DECL in themes_src, "themes.py объявляет порядок слоёв")
    ok("@layer syn-theme {" in themes_src, "CSS темы оборачивается в syn-theme")

    section("7. брейкпоинты только из BREAKPOINTS")
    bp_values = {str(w) for _n, w in build_ui.BREAKPOINTS}
    media = set(re.findall(r"@media \(min-width: (\d+)px\)", have))
    ok(media <= bp_values, "все @media из BREAKPOINTS", str(sorted(media)))

    section("8. селекторы валидны (с точкой) и варианты посчитаны")
    no_dot = re.findall(r"^\s+u-[a-z0-9-]*\s*\{", have, re.M)
    ok(not no_dot, "ни одного селектора u-* без ведущей точки", str(no_dot[:3]))
    ok(".u-block {" in have, "базовая утилита определена как селектор")
    sm_cols = [f".u-{bp}-cols-1 {{" for bp, _w in build_ui.BREAKPOINTS]
    ok(all(c in have for c in sm_cols), "адаптивные варианты cols-1 посчитаны",
       str(sm_cols))

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
