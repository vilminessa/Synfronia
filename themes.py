r"""Модульные темы и сборка страницы.

Каждая тема — подпапка в %LOCALAPPDATA%\Synfronia\themes:
theme.json (палитра/мета/extends/entry), custom.css, slots/*.html,
ресурсы (url(...) и {{asset:rel}} -> data:URI). Из этого собирается
итоговый HTML: build_page() наполняет __THEME_ROOT__/__THEME_CSS__/
__APP_CSS__/__APPJS__/__I18N__/__THEMES__ в ui.BASE_TEMPLATE.
"""

import base64
import json
import os
import re
from pathlib import Path

import ui as _ui

from i18n import I18N
from paths import base_dir


# -- темы --------------------------------------------------------------------
# Поля темы: label (название), цвета палитры bg/surface/widget/text/accent/warn,
# opacity (общая прозрачность интерфейса 0..1), радиусы скругления
# radius_s / radius_m / radius_l (px), hidden (скрыть из списка).
# Значения — дефолты; пользователь правит копии в
# %LOCALAPPDATA%\Synfronia\themes\{имя_темы}\theme.json.
_THEME_DEFAULTS = {
    "warn": "#ffb454",
    "opacity": 1.0,
    "radius_s": 6,
    "radius_m": 8,
    "radius_l": 12,
}
THEMES = {
    "scary_forest": {
        "label": "Scary Forest",
        "bg": "#0c1622",
        "surface": "#1f2b29",
        "widget": "#23444b",
        "text": "#dcdedd",
        "accent": "#628d7c",
        **_THEME_DEFAULTS,
    },
    "technology_day": {
        "label": "Technology day",
        "bg": "#00181a",
        "surface": "#00585a",
        "widget": "#003638",
        "text": "#dcdedd",
        "accent": "#00989b",
        **_THEME_DEFAULTS,
    },
    "technology_pinks": {
        "label": "Technology Pinks",
        "bg": "#ffebec",
        "surface": "#ffcbe2",
        "widget": "#ffffff",
        "text": "#5d2547",
        "accent": "#c15f9b",
        **_THEME_DEFAULTS,
    },
    "scarred_mind": {
        "label": "Scarred Mind",
        "bg": "#252b47",
        "surface": "#2f3b65",
        "widget": "#1e2542",
        "text": "#b9c2d6",
        "accent": "#f1b970",
        **_THEME_DEFAULTS,
    },
    "audrey_main": {
        "label": "Audrey Main Colours",
        "bg": "#fff5f0",
        "surface": "#f9f9f9",
        "widget": "#ededed",
        "text": "#5d5d5d",
        "accent": "#96af9b",
        **_THEME_DEFAULTS,
    },
    "night_sky": {
        "label": "Basic Night Sky",
        "bg": "#373051",
        "surface": "#3b2f4d",
        "widget": "#323756",
        "text": "#fffedd",
        "accent": "#fff2c9",
        **_THEME_DEFAULTS,
    },
    "vilmy": {
        "label": "Vilmy~",
        "bg": "#F5F0E6",
        "surface": "#EFE9DC",
        "widget": "#EDE5D3",
        "text": "#1F3A2E",
        "accent": "#B89968",
        **_THEME_DEFAULTS,
    },
}


# -- внешние темы (папки в %LOCALAPPDATA%\Synfronia\themes) ------------------
# Каждая тема — отдельная подпапка {theme_id}/ с файлами:
#   theme.json   — палитра/прозрачность/скругление (поля см. THEMES выше);
#   custom.css   — дополнительный CSS темы (можно менять фон элементов,
#                  подставлять картинки: url("bg.png"), url("anim.gif") и т.д.);
#   любые файлы  — ресурсы темы, на них ссылаются относительными url(...).
# Имя файла CSS можно переопределить полем "css" в theme.json.
_THEME_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")

_THEME_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}

_BASE_CSS = (
    "/* Дополнительный CSS темы. Ресурсы темы кладите рядом и подключайте "
    "относительно: url(\"bg.png\"), url(\"anim.gif\"). */\n"
)

_URLEX = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)"'\s][^)"']*))\s*\)""")

# Ассеты в шаблоне HTML темы: {{asset:relpath}} -> data:URI.
_ASSET_RE = re.compile(r"\{\{asset:([^}]*)\}\}")
# Секции базового шаблона: <!-- SLOT:name --> ... <!-- /SLOT:name -->
_SLOT_RE = re.compile(r"<!-- SLOT:([a-z0-9_-]+) -->(.*?)<!-- /SLOT:\1 -->", re.S)
_PALETTE_FIELDS = (
    "bg", "surface", "widget", "text", "accent", "warn",
    "opacity", "radius_s", "radius_m", "radius_l",
)
_THEME_META_FIELDS = (
    "label", "extends", "entry", "css", "author", "version", "hidden",
)


def _themes_root() -> Path:
    r"""Папка тем: %LOCALAPPDATA%\Synfronia\themes."""
    base = os.environ.get("LOCALAPPDATA") or str(base_dir())
    return Path(base) / "Synfronia" / "themes"


_LOADED_THEMES: dict[str, dict] | None = None


def _asset_data_uri(path: Path) -> str | None:
    """Превращает локальный файл темы (png/gif/jpg/…) в data:URI."""
    mime = _THEME_MIME.get(path.suffix.lower())
    if mime is None:
        return None
    try:
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def _process_theme_css(css: str, folder: Path) -> str:
    """Подставляет локальные файлы темы в url(...) как data:URI.

    Относительные url(имя.расширение) резолвятся внутри папки темы и
    встраиваются в CSS; абсолютные (http/https/data://, пути с диском)
    остаются как есть.
    """
    folder = folder.resolve()

    def repl(m):
        rel = m.group(1) or m.group(2) or m.group(3)
        if not rel:
            return m.group(0)
        low = rel.lower()
        if (low.startswith("data:") or low.startswith("http://")
                or low.startswith("https://") or low.startswith("//")
                or low.startswith("file:") or low.startswith("/")
                or re.match(r"^[A-Za-z]:[\\/]", low) or low.startswith("\\\\")):
            return m.group(0)
        candidate = (folder / rel).resolve()
        if not candidate.is_relative_to(folder):
            return m.group(0)
        uri = _asset_data_uri(candidate)
        return f"url(\"{uri}\")" if uri else m.group(0)

    return _URLEX.sub(repl, css)


def _seed_theme(root: Path, key: str, payload: dict) -> None:
    """Раскладывает встроенную тему в папку (theme.json + custom.css),
    только если их ещё нет — правки пользователя сохраняются."""
    folder = root / key
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    meta = folder / "theme.json"
    if not meta.exists():
        try:
            meta.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8-sig",
            )
        except OSError:
            pass
    css = folder / "custom.css"
    if not css.exists():
        try:
            css.write_text(_BASE_CSS, encoding="utf-8-sig")
        except OSError:
            pass


_THEME_README = """\
Synfronia — модульные темы
==========================
Каждая тема — отдельная подпапка в themes\\. Список тем строится по файлам
theme.json внутри подпапок.

СТРУКТУРА ТЕМЫ
--------------
  {id}\\theme.json    — описание темы (палитра, extends, entry, css, мета)
  {id}\\custom.css    — CSS темы (по умолчанию; можно задать поле "css")
  {id}\\index.html    — (необязательно) СВОЙ полный HTML-шаблон страницы
  {id}\\slots\\*.html — (необязательно) отдельные секции интерфейса
  {id}\\*.png/.gif/...— ресурсы: url("bg.png") в CSS, {{asset:bg.png}} в HTML

theme.json
----------
Палитра (наследуется родителями): bg, surface, widget, text, accent, warn,
opacity, radius_s, radius_m, radius_l.

  {
    "extends": "scarred_mind",     // унаследовать палитру/CSS другой темы (можно опустить)
    "entry": "index.html",         // свой полный HTML (плейсхолдеры ниже)
    "css": ["custom.css"],          // файлы CSS (или строка с одним файлом)
    "author": "Имя автора",
    "version": "1.0",
    "bg": "#123456"                // переопределение цвета
  }

CSS
---
Ресурсы подключайте относительно папки темы: url("bg.png"), url("anim.gif").
При сборке страницы они автоматически встраиваются в CSS как data:URI.
CSS наследуется по цепочке extends: файлы родителя идут раньше файлов темы.

ПОЛНЫЙ HTML (entry)
------------------
Если в теме есть index.html, весь интерфейс собирается из него. Место для
плейсхолдеров (подставляются при сборке, без логики на месте):

  __THEME_ROOT__    палитра темы (:root CSS-переменные)
  __THEME_CSS__     собранный CSS темы (с data:URI внутри)
  __APP_CSS__       базовые стили приложения
  __APPJS__         логика приложения (обязателен в полном HTML-шаблоне)
  __I18N__          переводы (JSON)
  __THEMES__        список тем (JSON)
  {{asset:rel}}     локальный файл темы -> data:URI

Пример минимального index.html:
  <style>:root{__THEME_ROOT__}</style>
  <style id="theme-style">__THEME_CSS__</style>
  <link rel="stylesheet" href="__APP_CSS__">   <!-- или просто <style>__APP_CSS__</style> -->
  ...ваша разметка (элементы сохраняют id, которые использует __APPJS__)...
  <script>__APPJS__</script>

СЕКЦИИ (slots)
--------------
Эти секции базового шаблона можно переопределить файлами slots\\<имя>.html:
  head, tabs, panel-video, panel-playlist, warn, ffmpeg-overlay, actions,
  progress, clicker, settings.
Маркеры в шаблоне: <!-- SLOT:<имя> --> ... <!-- /SLOT:<имя> -->.
Слоты ищутся по цепочке extends: сначала в теме, затем у родителей.
"""


def _seed_theme_readme(root: Path) -> None:
    """Раскладывает README справочник по темам в корень папки тем."""
    try:
        readme = root / "README.txt"
        if not readme.exists():
            readme.write_text(_THEME_README, encoding="utf-8-sig")
    except OSError:
        pass


def _migrate_flat(root: Path) -> None:
    """Переносит старые плоские «{theme}.json» (наследие предыдущей версии)
    в папку темы как theme.json; плоский файл после переноса удаляется."""
    for f in sorted(root.glob("*.json")):
        key = f.stem
        if not key or not _THEME_ID_RE.fullmatch(key):
            continue
        if (root / key / "theme.json").exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            (root / key).mkdir(parents=True, exist_ok=True)
            (root / key / "theme.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8-sig",
            )
            f.unlink()
        except OSError:
            pass


def load_themes() -> dict[str, dict]:
    """Сканирует папку тем: каждая подпапка = тема (theme.json + custom.css).

    • при первом запуске (папка пуста/нет файлов) раскладывает базовые темы
      по папкам — файлы можно править, добавлять CSS и картинки;
    • при каждом запуске читается каждая «*/theme.json»: имя папки = id темы,
      содержимое = словарь полей палитры/прозрачности/скругления; рядом
      custom.css с ресурсами темы. Новая тема (новая подпапка) автоматически
      попадает в возвращаемый словарь (базовые идут первыми, затем новые).
    • theme.json может содержать:
        "extends": "<id>"          — унаследовать палитру/CSS от другой темы;
        "entry": "index.html"      — свой полный HTML-шаблон страницы;
        "css": ["custom.css", ...] — файлы CSS (по умолчанию ["custom.css"]);
        "author", "version"        — метаданные (необязательно).
    """
    global _LOADED_THEMES
    root = _themes_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return dict(THEMES)
    _migrate_flat(root)
    _seed_theme_readme(root)
    # 1) базовые темы — раскладываем по папкам, только если их ещё нет
    for key, payload in THEMES.items():
        _seed_theme(root, key, payload)
    # 2) сканируем папку: каждая подпапка с theme.json — тема.
    #    Пока только собираем «сырые» спецификации (без CSS и разрешения extends).
    raw = {key: dict(payload) | {"_folder": None} for key, payload in THEMES.items()}
    order = list(THEMES)
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not _THEME_ID_RE.fullmatch(folder.name):
            continue
        key = folder.name
        meta = folder / "theme.json"
        if not meta.exists():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        spec = dict(raw.get(key, {}))
        spec.update(data)
        spec.setdefault("label", key)
        spec["_folder"] = folder
        raw[key] = spec
        if key not in order:
            order.append(key)
    # 3) разрешаем цепочки наследования (base-first) -> эффективные темы
    merged: dict[str, dict] = {}
    for key in order:
        merged[key] = _resolve_theme(key, raw)
    _LOADED_THEMES = {k: merged[k] for k in order}
    return _LOADED_THEMES


def _theme_chain(key: str, raw: dict[str, dict]) -> list[dict]:
    """Возвращает цепочку extends для темы key (base-first), без циклов."""
    chain: list[dict] = []
    seen: set[str] = set()
    cur: str | None = key
    while cur and cur not in seen:
        seen.add(cur)
        spec = raw.get(cur)
        if not spec:
            break
        chain.insert(0, spec)
        cur = spec.get("extends")
    return chain


def _css_files_for(spec: dict) -> list[str]:
    """CSS-файлы темы из её theme.json («css» может быть строкой или списком)."""
    raw_files = spec.get("css") or ["custom.css"]
    if isinstance(raw_files, str):
        raw_files = [raw_files]
    return [str(f) for f in raw_files]


def _resolve_theme(key: str, raw: dict[str, dict]) -> dict:
    """Собирает эффективную тему по цепочке extends:
    • палитра — потомок переопределяет родителя;
    • css — конкатенация файлов всей цепочки (родитель -> ребёнок), data:URI
      встраивается;
    • entry — самый глубокий в цепочке владелец index.html;
    • слоты и ассеты ищутся по всем папкам цепочки (глубина -> корень).
    """
    chain = _theme_chain(key, raw)
    if not chain:
        chain = [dict(raw.get(key, dict(THEMES.get(key, {}))))]
    out: dict = {}
    css_parts: list[str] = []
    entry = None
    entry_folder: Path | None = None
    for spec in chain:
        for f in _PALETTE_FIELDS:
            if f in spec and spec[f] is not None:
                out[f] = spec[f]
        for f in _THEME_META_FIELDS:
            if f in spec and f != "extends" and spec[f] is not None:
                out[f] = spec[f]
        folder = spec.get("_folder")
        for fname in _css_files_for(spec):
            if not folder:
                continue
            path = folder / fname
            if not path.is_file():
                continue
            try:
                css_parts.append(_process_theme_css(path.read_text(encoding="utf-8-sig"), folder))
            except (OSError, UnicodeDecodeError):
                pass
        ent = spec.get("entry")
        if ent and folder:
            entry = str(ent)
            entry_folder = folder
    out.setdefault("label", key)
    out["css"] = "\n".join(p for p in css_parts if p.strip())
    if entry and entry_folder is not None:
        out["entry"] = entry
        out["_entry_folder"] = entry_folder
        offset = len(out["_entry_folder"].parts)
        out["_slots"] = out["_entry_folder"]
    # Папки для поиска слотов и ассетов: глубина -> корень.
    slot_folders = [spec.get("_folder") for spec in reversed(chain) if spec.get("_folder")]
    out["_slot_folders"] = slot_folders
    return out


def _palette_root_vars(theme: dict) -> str:
    """CSS-переменные палитры темы как строка для :root{...}."""
    parts = []
    for f in _PALETTE_FIELDS:
        if f in theme and theme[f] is not None:
            v = theme[f]
            if f.startswith("radius"):
                parts.append(f"--{f}: {v}px")
            elif f == "opacity":
                parts.append(f"--opacity: {v}")
            else:
                parts.append(f"--{f}: {v}")
    return " ".join(parts)


def _asset_uri_for_page(rel: str, folders: list[Path]) -> str | None:
    """Находит файл rel в одной из папок цепочки тем и возвращает data:URI."""
    for folder in folders or []:
        candidate = (folder / rel).resolve()
        if not candidate.is_relative_to(folder.resolve()):
            continue
        if candidate.is_file():
            uri = _asset_data_uri(candidate)
            if uri:
                return uri
    return None


def _apply_slots(template: str, folders: list[Path]) -> str:
    """Заменяет секции <!-- SLOT:name -->...<!-- /SLOT:name --> базового
    шаблона содержимым файлов slots\\<name>.html (ищет по всей цепочке)."""

    def repl(m: re.Match) -> str:
        name = m.group(1)
        for folder in folders or []:
            slot = folder / "slots" / f"{name}.html"
            if slot.is_file():
                try:
                    return slot.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeDecodeError):
                    return m.group(0)
        return m.group(0)

    return _SLOT_RE.sub(repl, template)


def _apply_assets(html: str, folders: list[Path]) -> str:
    """Заменяет {{asset:rel}} на data:URI локального файла темы."""
    if not folders:
        return html

    def repl(m: re.Match) -> str:
        uri = _asset_uri_for_page(m.group(1).strip(), folders)
        return uri if uri else m.group(0)

    return _ASSET_RE.sub(repl, html)


def build_page(theme_key: str, lang: str | None = None) -> str:
    """Собирает итоговый HTML страницы для темы theme_key.

    • если у темы есть entry (index.html в папке) — сборка из него;
    • иначе — из встроенного базового шаблона (ui.BASE_TEMPLATE), причём
      секции SLOT:... можно переопределить файлами slots/<имя>.html;
    • ассеты {{asset:rel}} и url(...) в CSS встраиваются как data:URI;
    • плейсхолдеры (__THEME_ROOT__, __THEME_CSS__, __APP_CSS__, __APPJS__,
      __I18N__, __THEMES__) подставляются простой заменой.
    """
    if theme_key not in _LOADED_THEMES:
        theme_key = "scarred_mind"
    theme = _LOADED_THEMES[theme_key] or dict(THEMES.get(theme_key, {}))
    folders = theme.get("_slot_folders") or []

    # 1) выбор шаблона: свой index.html либо базовый
    entry = theme.get("entry")
    if entry and theme.get("_entry_folder"):
        try:
            template = (theme["_entry_folder"] / entry).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            template = _ui.BASE_TEMPLATE
    else:
        template = _ui.BASE_TEMPLATE
    template = _apply_slots(template, folders)

    # 2) ассеты в разметке -> data:URI
    template = _apply_assets(template, folders)

    # 3) плейсхолдеры
    page = template.replace("__THEME_ROOT__", _palette_root_vars(theme))
    page = page.replace("__THEME_CSS__", theme.get("css") or "")
    page = page.replace("__APP_CSS__", _ui.APP_CSS)
    page = page.replace("__APPJS__", _ui.APP_JS)
    page = page.replace("__I18N__", json.dumps(I18N, ensure_ascii=False))
    page = page.replace("__THEMES__", json.dumps(themes_embed(), ensure_ascii=False))
    return page


def themes_embed() -> dict:
    """Спецификации тем для встраивания в JS (__THEMES__) без служебных полей."""
    embed: dict = {}
    for k, spec in (_LOADED_THEMES or {}).items():
        item = {f: spec[f] for f in _PALETTE_FIELDS + _THEME_META_FIELDS if f in spec}
        item["label"] = spec.get("label", k)
        item["css"] = spec.get("css", "")
        item["hidden"] = bool(spec.get("hidden", False))
        if spec.get("entry"):
            item["entry"] = spec["entry"]
        embed[k] = item
    return embed
