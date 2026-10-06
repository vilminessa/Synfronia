"""Сборка ui.py из исходников интерфейса в ui_src/.

Запуск (из корня репозитория):
    python tools/build_ui.py            # пересобрать ui.py из ui_src/
    python tools/build_ui.py --check    # ui.py актуален? (код возврата 1, если устарел)
    python tools/build_ui.py --extract  # восстановить ui_src/ из текущего ui.py

Зачем это нужно: ui.py — сгенерированный файл, в котором CSS, JS и HTML-шаблоны
лежат строковыми литералами (UTIL_CSS / APP_CSS / MAIN_CSS / APP_JS / COMMON_JS /
SETTINGS_CSS / SETTINGS_JS / BASE_TEMPLATE / SETTINGS_HTML). Правки удобнее
вносить в обычные текстовые файлы ui_src/, а этот скрипт собирает из них ui.py,
который импортирует core.build_page().

Библиотека стилей: ui_src/util.css тоже генерируется - из шкал STYLE/PALETTE/
BREAKPOINTS ниже (токены :root + атомарные классы u-*). Править util.css
вручную нельзя: и сборка, и --check сверяют его с генератором; новая ступень
шкалы - одна строка в STYLE, новая утилита - пара в gen_util_css().
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
    # утилиты и токены - генерируются, стоят первыми: их объявление @layer
    # должно встретиться в странице раньше упакованных в слой компонентов
    ("UTIL_CSS", "util.css"),
    ("APP_CSS", "app.css"),
    ("MAIN_CSS", "main.css"),
    ("APP_JS", "app.js"),
    ("COMMON_JS", "common.js"),
    ("SETTINGS_CSS", "settings.css"),
    ("SETTINGS_JS", "settings.js"),
    ("BASE_TEMPLATE", "index.html"),
    # карточка настроек (оверлей) - фрагмент главной страницы, не отдельный шаблон
    ("SETTINGS_HTML", "settings.html"),
    # vendor: страница получается строкой (html=HTML в gui.py), внешних загрузок
    # не бывает - библиотеки лежат файлами и вшиваются в неё как литералы.
    # Порядок важен: Motion до app.js, Alpine последним (см. index.html).
    ("MOTION_JS", "vendor/motion.js"),
    ("ALPINE_JS", "vendor/alpine.min.js"),
)

HEADER = (
    "# ui.py — АВТО-ГЕНЕРИРУЕМЫЙ ФАЙЛ, не редактируй его вручную.\n"
    "# Исходники интерфейса: ui_src/{util,app,main,settings}.css, ui_src/{app,common,settings}.js,\n"
    "#                       ui_src/{index,settings}.html, ui_src/vendor/{motion,alpine}.*\n"
    "# Сборка: python tools/build_ui.py   Проверка: python tools/build_ui.py --check"
)

NEWLINE = "\r\n"  # рабочая копия репозитория в CRLF (core.autocrlf=true)

# ---- библиотека стилей: шкалы -> ui_src/util.css (генерация в gen_util_css) ----
STYLE = {
    "space": (2, 4, 6, 8, 12, 16, 24, 32),            # отступы: имя токена = px
    "fs": {"xs": 11, "sm": 12, "base": 13, "md": 14, "lg": 16, "xl": 20,
           "2xl": 24, "display": 44},                 # кегли
    "fw": {"regular": 400, "semibold": 600, "bold": 700},   # насыщенность
    "dur": {"press": "90ms", "ui": "150ms", "enter": "200ms", "slow": "300ms"},
    "ease": {"standard": "cubic-bezier(.4, 0, .2, 1)", "out": "ease-out",
             "spring": "cubic-bezier(.2, .9, .25, 1.28)"},
    "height": {"sm": "26px", "md": "34px", "lg": "42px"},   # контролы
    "op": {"half": ".5", "dim": ".75", "quiet": ".9"},      # прозрачности
    "lead": {"tight": "1.2", "snug": "1.35", "normal": "1.5"},
}
# палитра темы (живёт в :root шаблона/темы, не здесь) - утилиты цвета на неё ссылаются
PALETTE = ("bg", "surface", "widget", "text", "accent", "warn", "ok", "err")
# адаптив: min-width, как в Tailwind (срабатывает на шире). @media var() не
# умеет, поэтому числа живут здесь же - единственное место, где bp числами
BREAKPOINTS = (("sm", 640), ("md", 900))
# какие утилиты получают sm/md-варианты: сетка, зазор, отступы, ширина
RESPONSIVE = ("u-cols-", "u-gap-", "u-gap-x-", "u-gap-y-", "u-p-", "u-px-",
              "u-py-", "u-pt-", "u-pb-", "u-pl-", "u-pr-", "u-m-", "u-mx-",
              "u-my-", "u-mt-", "u-mb-", "u-ml-", "u-mr-", "u-w-")


def gen_util_css() -> str:
    """Собирает ui_src/util.css: токены шкал в :root + атомарные классы u-*.

    Порядок слоёв: syn-components (окна) < syn-theme (авторский CSS темы) <
    syn-utilities (u-*): авторская тема главнее компонентов, но уступает
    явным параметрам элемента. Палитра темы - вне слоёв, её приоритет выше всех.
    """
    sp = STYLE["space"]
    groups: list[tuple[str, list[tuple[str, str]]]] = []

    def grp(title: str, items: list[tuple[str, str]]) -> None:
        groups.append((title, items))

    grp("дисплей и позиционирование", [
        ("u-block", "display: block"),
        ("u-inline-block", "display: inline-block"),
        ("u-inline-flex", "display: inline-flex"),
        ("u-flex", "display: flex"),
        ("u-grid", "display: grid"),
        ("u-hidden", "display: none"),
        ("u-relative", "position: relative"),
        ("u-absolute", "position: absolute"),
        ("u-fixed", "position: fixed"),
        ("u-overflow-hidden", "overflow: hidden"),
        ("u-overflow-auto", "overflow: auto"),
        ("u-pointer-none", "pointer-events: none"),
        ("u-select-none", "user-select: none"),
        ("u-cursor-pointer", "cursor: pointer"),
    ])
    grp("флекс", [
        ("u-flex-1", "flex: 1 1 0%"),
        ("u-flex-none", "flex: none"),
        ("u-items-center", "align-items: center"),
        ("u-items-start", "align-items: flex-start"),
        ("u-items-end", "align-items: flex-end"),
        ("u-justify-between", "justify-content: space-between"),
        ("u-justify-center", "justify-content: center"),
        ("u-justify-end", "justify-content: flex-end"),
        ("u-wrap", "flex-wrap: wrap"),
        ("u-nowrap", "flex-wrap: nowrap"),
    ])
    grp("сетка", [
        ("u-cols-1", "grid-template-columns: minmax(0, 1fr)"),
        ("u-cols-2", "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)"),
        ("u-cols-3", "grid-template-columns: repeat(3, minmax(0, 1fr))"),
    ])
    grp("зазор", [(f"u-gap-{n}", f"gap: var(--sp-{n})") for n in sp]
        + [(f"u-gap-x-{n}", f"column-gap: var(--sp-{n})") for n in sp]
        + [(f"u-gap-y-{n}", f"row-gap: var(--sp-{n})") for n in sp])
    grp("размеры", [
        ("u-w-full", "width: 100%"),
        ("u-w-auto", "width: auto"),
        ("u-h-full", "height: 100%"),
        ("u-min-w-0", "min-width: 0"),
    ])
    pad: list[tuple[str, str]] = []
    mar: list[tuple[str, str]] = []
    for n in sp:
        pad += [
            (f"u-p-{n}", f"padding: var(--sp-{n})"),
            (f"u-px-{n}", f"padding-left: var(--sp-{n}); padding-right: var(--sp-{n})"),
            (f"u-py-{n}", f"padding-top: var(--sp-{n}); padding-bottom: var(--sp-{n})"),
            (f"u-pt-{n}", f"padding-top: var(--sp-{n})"),
            (f"u-pb-{n}", f"padding-bottom: var(--sp-{n})"),
            (f"u-pl-{n}", f"padding-left: var(--sp-{n})"),
            (f"u-pr-{n}", f"padding-right: var(--sp-{n})"),
        ]
        mar += [
            (f"u-m-{n}", f"margin: var(--sp-{n})"),
            (f"u-mx-{n}", f"margin-left: var(--sp-{n}); margin-right: var(--sp-{n})"),
            (f"u-my-{n}", f"margin-top: var(--sp-{n}); margin-bottom: var(--sp-{n})"),
            (f"u-mt-{n}", f"margin-top: var(--sp-{n})"),
            (f"u-mb-{n}", f"margin-bottom: var(--sp-{n})"),
            (f"u-ml-{n}", f"margin-left: var(--sp-{n})"),
            (f"u-mr-{n}", f"margin-right: var(--sp-{n})"),
        ]
    grp("внутренние отступы", pad)
    grp("внешние отступы", mar + [("u-ml-auto", "margin-left: auto")])
    grp("типографика", [
        *((f"u-fs-{k}", f"font-size: var(--fs-{k})") for k in STYLE["fs"]),
        *((f"u-fw-{k}", f"font-weight: var(--fw-{k})") for k in STYLE["fw"]),
        *((f"u-lead-{k}", f"line-height: var(--lead-{k})") for k in STYLE["lead"]),
        ("u-text-left", "text-align: left"),
        ("u-text-center", "text-align: center"),
        ("u-text-right", "text-align: right"),
        ("u-uppercase", "text-transform: uppercase"),
        ("u-truncate", "overflow: hidden; text-overflow: ellipsis; white-space: nowrap"),
        ("u-nowrap", "white-space: nowrap"),
        ("u-tabular", "font-variant-numeric: tabular-nums"),
    ])
    grp("цвета темы", [
        *((f"u-bg-{k}", f"background-color: var(--{k})") for k in PALETTE),
        *((f"u-text-{k}", f"color: var(--{k})") for k in PALETTE),
        *((f"u-border-{k}", f"border-color: var(--{k})") for k in PALETTE),
        ("u-border", "border-width: 1px; border-style: solid; border-color: var(--widget)"),
    ])
    grp("скругления", [
        ("u-rounded-s", "border-radius: var(--radius-s)"),
        ("u-rounded-m", "border-radius: var(--radius-m)"),
        ("u-rounded-l", "border-radius: var(--radius-l)"),
        ("u-rounded-pill", "border-radius: var(--radius-pill)"),
    ])
    grp("прозрачность", [(f"u-op-{k}", f"opacity: var(--op-{k})")
                         for k in STYLE["op"]])
    grp("переходы", [
        ("u-transition",
         "transition-property: background-color, border-color, color, opacity, "
         "box-shadow, transform; transition-duration: var(--dur-ui); "
         "transition-timing-function: var(--ease-standard)"),
        *((f"u-dur-{k}", f"transition-duration: var(--dur-{k})")
          for k in STYLE["dur"]),
        *((f"u-ease-{k}", f"transition-timing-function: var(--ease-{k})")
          for k in STYLE["ease"]),
    ])
    grp("фокус и выделение", [
        ("u-focus-ring:focus-visible", "outline: var(--focus-ring); outline-offset: 2px"),
    ])

    lines = [
        "/* ui_src/util.css — АВТО-ГЕНЕРИРУЕМЫЙ ФАЙЛ, не редактируй вручную.",
        "   Шкалы и набор утилит — STYLE / PALETTE / BREAKPOINTS в tools/build_ui.py.",
        "   Пересборка: python tools/build_ui.py   Проверка: python tools/build_ui.py --check",
        "   Слои: компоненты < авторский стиль темы < утилиты; палитра темы живёт",
        "   в :root вне слоёв. */",
        "",
        "@layer syn-components, syn-theme, syn-utilities;",
        "",
        ":root {",
        f"  /* отступы: имя = px ({', '.join(str(n) for n in sp)}) */",
        "  " + "; ".join(f"--sp-{n}: {n}px" for n in sp) + ";",
        "  /* кегли */",
        "  " + "; ".join(f"--fs-{k}: {v}px" for k, v in STYLE["fs"].items()) + ";",
        "  /* насыщенность шрифта */",
        "  " + "; ".join(f"--fw-{k}: {v}" for k, v in STYLE["fw"].items()) + ";",
        "  /* длительности */",
        "  " + "; ".join(f"--dur-{k}: {v}" for k, v in STYLE["dur"].items()) + ";",
        "  /* сглаживания */",
        "  " + "; ".join(f"--ease-{k}: {v}" for k, v in STYLE["ease"].items()) + ";",
        "  /* высоты контролов */",
        "  " + "; ".join(f"--h-{k}: {v}" for k, v in STYLE["height"].items()) + ";",
        "  /* прозрачности */",
        "  " + "; ".join(f"--op-{k}: {v}" for k, v in STYLE["op"].items()) + ";",
        "  /* интерлиньяж */",
        "  " + "; ".join(f"--lead-{k}: {v}" for k, v in STYLE["lead"].items()) + ";",
        "  /* таблетка и кольцо фокуса — общие, не зависят от темы */",
        "  --radius-pill: 999px;",
        "  --focus-ring: 2px solid var(--accent);",
        "}",
        "",
        "@layer syn-utilities {",
    ]
    for title, items in groups:
        lines.append(f"  /* {title} */")
        for sel, body in items:
            lines.append(f"  .{sel} {{ {body}; }}")
    for bp, width in BREAKPOINTS:
        matched = [item for _title, items in groups for item in items
                   if item[0].startswith(RESPONSIVE)]
        if not matched:
            continue
        lines.append("")
        lines.append(f"  /* {bp} и шире ({width}px) */")
        lines.append(f"  @media (min-width: {width}px) {{")
        for sel, body in matched:
            # "u-cols-1" -> ".u-sm-cols-1" (bp вставляем после ведущего u-)
            lines.append(f"    .u-{bp}-{sel[2:]} {{ {body}; }}")
        lines.append("  }")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _read(path: Path) -> str:
    """Читает исходник как текст с LF-переводами строк (в строках ui.py только LF)."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _write(path: Path, text: str) -> None:
    """Пишет файл в CRLF, кодировка UTF-8 без BOM."""
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", NEWLINE).encode("utf-8"))


def _sync_util() -> bool:
    """Перегенерировать util.css; True — файл менялся."""
    want = gen_util_css()
    have = _read(SRC / "util.css") if (SRC / "util.css").is_file() else ""
    if have == want:
        return False
    _write(SRC / "util.css", want)
    print(f"util.css: перегенерирован из шкал STYLE ({len(want)} символов)")
    return True


def _literals() -> dict[str, str]:
    """Достаёт строковые литералы (APP_CSS / APP_JS / BASE_TEMPLATE и др.) из ui.py."""
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
    _sync_util()
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
    want = gen_util_css()
    have = _read(SRC / "util.css") if (SRC / "util.css").is_file() else ""
    if have != want:
        print("util.css: УСТАРЕЛ — запусти python tools/build_ui.py (шкалы в build_ui.py)")
        return 1
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
