r"""Модульные шрифты: %LOCALAPPDATA%\Synfronia\fonts.

В сборку вшиты три тестовых шрифта (assets/fonts, лицензия OFL 1.1): Inter,
JetBrains Mono и Noto Sans. При первом запуске они раскладываются в папку
шрифтов, поэтому свежая установка работает без сети и список шрифтов не
пустой. Свои файлы пользователь кладёт в ту же папку (или жмёт «Докачать
шрифты»), а Synfronia читает из них семейство, начертание и вес, встраивает
нужные как @font-face с data:URI и подставляет их в CSS через переменные
--font-sans / --font-mono.

• выбор делается в настройках (font_sans / font_mono) или самой темой
  (поля "font" / "font_mono" в theme.json имеют приоритет);
• для TTF/OTF читаются таблицы sfnt: name (семейство/начертание), OS/2
  (вес, жирный/курсив, моноширинность), head (macStyle), fvar (диапазон
  веса у вариативных шрифтов);
• WOFF/WOFF2 разобрать нечем (woff2 вдобавок сжат brotli) — для них
  семейство и начертание берутся из имени файла.
"""

import base64
import os
import re
import shutil
import urllib.request
from pathlib import Path

from paths import _file_log, base_dir

# Расширение -> формат для src: url(...) format(...)
FONT_FORMATS = {
    ".ttf": "truetype",
    ".otf": "opentype",
    ".woff": "woff",
    ".woff2": "woff2",
}
# Файлы больше этого размера не встраиваем: data:URI в HTML станет нечитаемым.
MAX_FONT_BYTES = 8 * 1024 * 1024
# И суммарный лимит на страницу (base64 больше исходника примерно в 1.34 раза).
MAX_TOTAL_BYTES = 8 * 1024 * 1024

# Имя семейства: оставляем буквы (в т.ч. кириллицу/иероглифы), цифры и
# безопасные символы; кавычки, скобки-блоки, `;`, `<`, `>` вырезаем.
_FAMILY_RE = re.compile(r"[^\w .\-()\[\]]+")
_SPACE_RE = re.compile(r"\s{2,}")
# Ключевые слова начертания -> вес (CSS font-weight).
_WEIGHT_WORDS = (
    ("thin", 100), ("hairline", 100), ("extralight", 200), ("ultralight", 200),
    ("light", 300), ("regular", 400), ("normal", 400), ("book", 400),
    ("medium", 500), ("semibold", 600), ("demibold", 600), ("extrabold", 800),
    ("ultrabold", 800), ("black", 900), ("heavy", 900),
)
# Признаки моноширинного семейства в имени (PANOSE заполняют не все шрифты).
_MONO_WORDS = ("mono", "code", "courier", "consol", "menlo", "inconsolata")


def _fonts_root() -> Path:
    r"""Папка шрифтов: %LOCALAPPDATA%\Synfronia\fonts."""
    base = os.environ.get("LOCALAPPDATA") or str(base_dir())
    return Path(base) / "Synfronia" / "fonts"


# -- разбор sfnt (TTF/OTF) ---------------------------------------------------
def _sfnt_table(data: bytes, tag: bytes) -> tuple[int, int] | None:
    """Смещение и длина таблицы sfnt по тегу (None, если её нет)."""
    if len(data) < 12:
        return None
    count = int.from_bytes(data[4:6], "big")
    for i in range(min(count, 64)):
        rec = 12 + i * 16
        if rec + 16 > len(data):
            break
        if data[rec:rec + 4] == tag:
            start = int.from_bytes(data[rec + 8:rec + 12], "big")
            length = int.from_bytes(data[rec + 12:rec + 16], "big")
            if 0 < length and start + length <= len(data):
                return start, length
            return None
    return None


def _decode_name(raw: bytes, platform: int) -> str:
    try:
        if platform in (0, 3):
            return raw.decode("utf-16-be")
        return raw.decode("mac-roman")
    except UnicodeDecodeError:
        return raw.decode("latin-1", "replace")


def _names(data: bytes) -> dict[int, str]:
    """Строковые записи таблицы name: 1 — семейство, 16 — типографское,
    2/17 — начертание. Приоритет: 16/17 > 1/2, Windows > Macintosh."""
    rec = _sfnt_table(data, b"name")
    if rec is None:
        return {}
    start, length = rec
    table = data[start:start + length]
    if len(table) < 6:
        return {}
    count = int.from_bytes(table[2:4], "big")
    storage = int.from_bytes(table[4:6], "big")
    out: dict[int, str] = {}
    ranks: dict[int, tuple[int, int]] = {}
    for i in range(min(count, 512)):
        rec_i = 6 + i * 12
        if rec_i + 12 > len(table):
            break
        platform = int.from_bytes(table[rec_i:rec_i + 2], "big")
        name_id = int.from_bytes(table[rec_i + 6:rec_i + 8], "big")
        str_len = int.from_bytes(table[rec_i + 8:rec_i + 10], "big")
        str_off = int.from_bytes(table[rec_i + 10:rec_i + 12], "big")
        if name_id not in (1, 2, 16, 17) or storage + str_off + str_len > len(table):
            continue
        value = _clean_family(_decode_name(table[storage + str_off:storage + str_off + str_len], platform))
        if not value:
            continue
        rank = (1 if name_id in (16, 17) else 0, 1 if platform in (0, 3) else 0)
        if name_id not in ranks or rank > ranks[name_id]:
            ranks[name_id] = rank
            out[name_id] = value
    return out


def _os2(data: bytes) -> dict:
    """usWeightClass, жирный/курсив и моноширинность из OS/2 + head."""
    info = {"weight": 400, "bold": False, "italic": False, "mono": False}
    rec = _sfnt_table(data, b"OS/2")
    if rec is not None:
        start, length = rec
        table = data[start:start + length]
        if len(table) >= 10:
            weight = int.from_bytes(table[4:6], "big")
            info["weight"] = min(max(weight, 1), 1000)
        if len(table) >= 64:
            flags = int.from_bytes(table[62:64], "big")
            info["bold"] = bool(flags & 0x20)
            info["italic"] = bool(flags & 0x01)
        if len(table) >= 36 and table[32:42].strip(b"\0"):
            info["mono"] = bool(table[32 + 3] & 0x80)  # PANOSE bProportion
    head = _sfnt_table(data, b"head")
    if head is not None:
        start, length = head
        table = data[start:start + length]
        if len(table) >= 46:
            mac = int.from_bytes(table[44:46], "big")
            info["bold"] = info["bold"] or bool(mac & 0x01)
            info["italic"] = info["italic"] or bool(mac & 0x02)
    return info


def _weight_range(data: bytes) -> tuple[int, int] | None:
    """Диапазон оси wght вариативного шрифта (fvar) — для font-weight: min max."""
    rec = _sfnt_table(data, b"fvar")
    if rec is None:
        return None
    start, length = rec
    table = data[start:start + length]
    if len(table) < 16:
        return None
    axes_at = int.from_bytes(table[4:6], "big")
    count = int.from_bytes(table[8:10], "big")
    size = int.from_bytes(table[10:12], "big") or 20
    for i in range(min(count, 32)):
        off = axes_at + i * size
        if off + 20 > len(table):
            break
        if table[off:off + 4] == b"wght":
            lo = int.from_bytes(table[off + 4:off + 8], "big", signed=True) / 65536
            hi = int.from_bytes(table[off + 12:off + 16], "big", signed=True) / 65536
            if 1 <= lo < hi <= 1000:
                return int(lo), int(hi)
    return None


def _clean_family(value) -> str:
    """Имя семейства: без управляющих символов и кавычек (их нельзя в CSS)."""
    text = _FAMILY_RE.sub(" ", str(value or ""))
    return _SPACE_RE.sub(" ", text).strip()[:60]


def _weight_from_subfamily(subfamily: str, fallback: int) -> int:
    low = (subfamily or "").lower()
    for word, weight in _WEIGHT_WORDS:
        if re.search(rf"\b{word}\b", low):
            return weight
    return fallback


def _face_from_name(stem: str) -> tuple[str, int, bool]:
    """Семейство/вес/курсив из имени файла: Inter-BoldItalic.woff2 -> Inter."""
    parts = [p for p in re.split(r"[\s_\-.]+", stem) if p]
    italic = False
    weight = 400
    left: list[str] = []
    for part in parts:
        low = part.lower()
        if low in ("italic", "oblique", "it"):
            italic = True
            continue
        found = None
        for word, w in _WEIGHT_WORDS:
            if low == word:
                found = w
                break
        if found is not None:
            weight = found
            continue
        left.append(part)
    family = _clean_family(" ".join(left)) or _clean_family(stem) or "font"
    return family, weight, italic


# -- вшитые шрифты (assets/fonts) ---------------------------------------------
# Копии лежат в репозитории и попадают в сборку (Synfronia.spec -> datas),
# поэтому первый запуск не требует сети. Кнопка «Докачать шрифты» тянет те же
# файлы из сети — см. TEST_FONTS.
BUNDLED_FONTS = ("Inter.ttf", "JetBrainsMono.ttf", "NotoSans.ttf")
BUNDLED_LICENSES = ("OFL-Inter.txt", "OFL-JetBrainsMono.txt", "OFL-NotoSans.txt")
_RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl"
# Источник каждого файла: имена совпадают с BUNDLED_FONTS, чтобы «докачать»
# можно было ровно те же бинарники, что лежат в сборке.
TEST_FONTS = {
    "Inter.ttf": {
        "url": f"{_RAW}/inter/Inter%5Bopsz%2Cwght%5D.ttf",
        "family": "Inter",
        "bytes": 876576,
    },
    "JetBrainsMono.ttf": {
        "url": f"{_RAW}/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
        "family": "JetBrains Mono",
        "bytes": 187208,
    },
    "NotoSans.ttf": {
        "url": f"{_RAW}/notosans/NotoSans%5Bwdth%2Cwght%5D.ttf",
        "family": "Noto Sans",
        "bytes": 2049096,
    },
}
_FONTS_README = """Synfronia - тестовые шрифты
=========================

{list}
Все три - переменные шрифты под SIL Open Font License 1.1 (полные тексты
лицензий лежат рядом в файлах OFL-*.txt). Приложение положило их сюда при
первом запуске, чтобы список шрифтов не был пустым; файлы можно свободно
удалить и положить свои .ttf/.otf/.woff/.woff2.

Источники (неизменённые файлы upstream):
{urls}

Папка: {folder}
"""


def _bundle_dir() -> Path:
    r"""Папка со вшитыми шрифтами: assets/fonts (рядом с исходниками или в _MEIPASS)."""
    here = Path(__file__).resolve().parent
    for root in (here, base_dir()):
        path = root / "assets" / "fonts"
        if path.is_dir():
            return path
    return here / "assets" / "fonts"


def _check_font(path: Path) -> str:
    """Проверяет файл шрифта и возвращает семейство ('' - файл не годится)."""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size > MAX_FONT_BYTES:
        _file_log("warning", f"font {path.name}: {size} байт - пропущен (слишком большой)")
        return ""
    if path.suffix.lower() not in (".ttf", ".otf"):
        return _clean_family(path.stem)
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    names = _names(data)
    return _clean_family(names.get(16) or names.get(1))


def _font_ok(path: Path, min_bytes: int = 1024) -> bool:
    """Годится ли файл шрифта: читаемый sfnt нужного размера.

    Битый файл в папке шрифтов молча ломает @font-face для всей страницы,
    поэтому проверяем всегда — и перед копированием, и перед скачиванием.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size < min_bytes:
        _file_log("warning", f"font {path.name}: {size} байт - слишком мал, пропущен")
        return False
    if not _check_font(path):
        _file_log("warning", f"font {path.name}: нечитаемый файл, пропущен")
        return False
    return True


def _place_font(src: Path, dest: Path) -> bool:
    """Копирует шрифт на место через временный файл (атомарно)."""
    tmp = dest.with_name(f".part-{dest.name}")
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
    except OSError as exc:
        _file_log("warning", f"font {dest.name}: не удалось сохранить ({exc})")
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True


def seed_bundled_fonts(on_log=None) -> dict:
    """Раскладывает вшитые шрифты в папку шрифтов (чего там ещё нет).

    Работает без сети. Уже существующие файлы не трогаем: папка шрифтов
    принадлежит пользователю, и его шрифты приоритетнее.

    Возвращает {"added": [...], "skipped": [...], "failed": [...]}.
    """
    report = on_log or (lambda level, msg: _file_log(level, msg))
    result = {"added": [], "skipped": [], "failed": []}
    src_dir = _bundle_dir()
    if not src_dir.is_dir():
        result["skipped"] = list(BUNDLED_FONTS)
        report("info", "fonts: вшитые шрифты не найдены (assets/fonts), пропуск")
        return result
    root = _fonts_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        report("warning", f"fonts: не удалось создать папку шрифтов ({exc})")
        result["failed"] = list(BUNDLED_FONTS)
        return result
    for name in BUNDLED_FONTS:
        dest = root / name
        if dest.exists():
            result["skipped"].append(name)
            continue
        src = src_dir / name
        if src.is_file() and _font_ok(src) and _place_font(src, dest):
            result["added"].append(name)
        else:
            result["failed"].append(name)
    for name in BUNDLED_LICENSES:
        src, dest = src_dir / name, root / name
        if src.is_file() and not dest.exists():
            try:
                shutil.copyfile(src, dest)
            except OSError:
                pass
    if result["added"]:
        _write_fonts_readme(root)
        report("info", f"fonts: добавлено тестовых шрифтов - {', '.join(result['added'])}")
    if result["failed"]:
        report("warning", f"fonts: не удалось добавить - {', '.join(result['failed'])}")
    return result


def download_test_fonts(names=None, on_log=None, on_progress=None) -> dict:
    """Докачивает тестовые шрифты из сети (кнопка «Докачать шрифты»).

    Шрифты уже лежат в сборке, поэтому сеть здесь — запасной путь: после
    удаления файлов, обновления версии или для проверки в свежей установке.
    Уже скачанные пропускаем, если не передан force.

    on_progress(done, total) — колбэк после каждого файла; on_log(level, msg).
    Ошибка сети не прерывает цикл: недоступные пишутся в failed.
    """
    report = on_log or (lambda level, msg: _file_log(level, msg))
    wanted = [n for n in (names or TEST_FONTS) if n in TEST_FONTS]
    result = {"added": [], "skipped": [], "failed": []}
    if not wanted:
        return result
    root = _fonts_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        report("error", f"fonts: не удалось создать папку шрифтов ({exc})")
        result["failed"] = list(wanted)
        return result
    total = len(wanted)
    for index, name in enumerate(wanted, 1):
        dest = root / name
        meta = TEST_FONTS[name]
        if dest.is_file():
            result["skipped"].append(name)
            if on_progress:
                on_progress(index, total)
            continue
        report("info", f"fonts: скачиваю {meta['family']} ({index}/{total})…")
        try:
            req = urllib.request.Request(
                meta["url"],
                headers={"User-Agent": "Synfronia (test fonts)"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                size = int(resp.headers.get("Content-Length") or 0)
                if size > MAX_FONT_BYTES:
                    raise ValueError(f"{size} байт - больше лимита")
                tmp = dest.with_name(f".part-{dest.name}")
                with open(tmp, "wb") as fh:
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        fh.write(chunk)
        except Exception as exc:  # noqa: BLE001
            # сеть/прокси/404 — тихо в лог, следующий шрифт не трогаем
            result["failed"].append(name)
            report("error", f"fonts: {meta['family']} не скачан ({exc})")
            _unlink(dest.with_name(f".part-{dest.name}"))
            if on_progress:
                on_progress(index, total)
            continue
        if _font_ok(tmp, min_bytes=meta["bytes"] // 4):
            # файл уже на месте (скачан во временное имя) — только переименование
            try:
                os.replace(tmp, dest)
                result["added"].append(name)
            except OSError as exc:
                result["failed"].append(name)
                report("error", f"fonts: {meta['family']} не сохранён ({exc})")
        else:
            result["failed"].append(name)
            report("error", f"fonts: {meta['family']} — ответ не похож на шрифт, отброшен")
        # при отказе убираем мусор: битый .part-*.ttf иначе попал бы в список шрифтов
        _unlink(tmp)
        if on_progress:
            on_progress(index, total)
    if result["added"]:
        _write_fonts_readme(root)
        load_fonts()  # новые семейства сразу доступны UI
    return result


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _write_fonts_readme(root: Path) -> None:
    """README в папке шрифтов: что внутри и где взято (OFL требует атрибуции)."""
    lines = []
    for name in BUNDLED_FONTS:
        meta = TEST_FONTS.get(name, {})
        lines.append(f"  {name:<18} {meta.get('family', name)}")
        if meta.get("url"):
            lines.append(f"  {'':<18} {meta['url']}")
    text = _FONTS_README.format(list="\n".join(lines) + "\n",
                                urls="  https://github.com/google/fonts",
                                folder=root)
    try:
        (root / "README.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass


# -- загрузка папки ----------------------------------------------------------
_LOADED_FONTS: dict[str, list[dict]] | None = None


def _data_uri(path: Path) -> str:
    mime = FONT_FORMATS[path.suffix.lower()]
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:font/{mime};base64,{payload}"


def _face_for(path: Path) -> dict | None:
    """Описание начертания из файла шрифта (None, если разобрать не удалось)."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > MAX_FONT_BYTES:
        _file_log("warning", f"font {path.name}: {size} байт — пропущен (слишком большой)")
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if path.suffix.lower() in (".ttf", ".otf"):
        names = _names(data)
        family = names.get(16) or names.get(1)
        subfamily = names.get(17) or names.get(2) or ""
        info = _os2(data)
        weight = _weight_from_subfamily(subfamily, info["weight"])
        italic = info["italic"] or "italic" in subfamily.lower() or "oblique" in subfamily.lower()
        mono = info["mono"]
    else:
        family, weight, italic = _face_from_name(path.stem)
        mono = False
    family = _clean_family(family) or _clean_family(path.stem) or "font"
    # PANOSE у моноширинных шрифтов заполнен не везде, поэтому проверяем и имя.
    low = family.lower()
    mono = bool(mono) or any(word in low for word in _MONO_WORDS)
    family = _clean_family(family) or _clean_family(path.stem) or "font"
    return {
        "family": family,
        "weight": int(weight),
        "italic": bool(italic),
        "mono": bool(mono),
        "variable": _weight_range(data) if path.suffix.lower() in (".ttf", ".otf") else None,
        "format": FONT_FORMATS[path.suffix.lower()],
        "file": path.name,
        "uri": _data_uri(path),
    }


def load_fonts() -> dict[str, list[dict]]:
    """Сканирует папку шрифтов: семейство -> список начертаний.

    Возвращает словарь, где для каждого семейства лежат начертания
    (вес + курсив), готовые для @font-face. Нечитаемые файлы пропускаются
    с записью в лог.
    """
    global _LOADED_FONTS
    root = _fonts_root()
    families: dict[str, list[dict]] = {}
    try:
        files = sorted(f for f in root.iterdir()
                       if f.is_file() and not f.name.startswith(".")
                       and f.suffix.lower() in FONT_FORMATS)
    except OSError:
        _LOADED_FONTS = {}
        return _LOADED_FONTS
    for path in files:
        face = _face_for(path)
        if face is None:
            _file_log("warning", f"font {path.name}: не удалось прочитать, пропущен")
            continue
        faces = families.setdefault(face["family"], [])
        if any(f["file"] == face["file"] for f in faces):
            continue
        faces.append(face)
    for faces in families.values():
        faces.sort(key=lambda f: (f["italic"], f["weight"], f["file"]))
    _LOADED_FONTS = families
    return _LOADED_FONTS


def _families() -> dict[str, list[dict]]:
    if _LOADED_FONTS is None:
        load_fonts()
    return _LOADED_FONTS or {}


def families() -> dict[str, list[dict]]:
    """Семейства из последнего сканирования (без нового): None, если не было."""
    return _LOADED_FONTS if _LOADED_FONTS is not None else {}


def fonts_embed() -> dict:
    """Список семейств для выбора в UI (плюс количество файлов и папка).

    mono — семейства, распознанные как моноширинные: их показываем первыми
    в списке моноширинного шрифта.
    """
    fams = _families()
    mono = sorted(k for k, faces in fams.items() if any(f["mono"] for f in faces))
    return {
        "families": sorted(fams),
        "mono": mono,
        "count": sum(len(v) for v in fams.values()),
        "folder": str(_fonts_root()),
    }


def css_family(name: str) -> str:
    """Семейство в виде значения CSS: "Inter SemiBold" (с кавычками)."""
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _faces_for(family: str) -> list[dict]:
    if not family:
        return []
    faces = _families().get(family)
    if faces is not None:
        return faces
    # шрифты ещё не сканировались (или папки нет) — пробуем догрузить
    load_fonts()
    return (_LOADED_FONTS or {}).get(family, [])


def font_css(families) -> str:
    """@font-face блок для перечисленных семейств (без повторов).

    Суммарный размер встраиваемых данных ограничен MAX_TOTAL_BYTES: страница с
    десятком мегабайт base64 внутри грузится заметно дольше, поэтому лишнее
    отбрасываем с записью в лог.
    """
    parts: list[str] = []
    seen: set[tuple] = set()
    total = 0
    for family in families:
        if not family:
            continue
        for face in _faces_for(family):
            key = (face["family"], face["weight"], face["italic"], face["file"])
            if key in seen:
                continue
            seen.add(key)
            if total + len(face["uri"]) > MAX_TOTAL_BYTES:
                _file_log("warning", f"font {face['file']}: не встроен — превышен лимит "
                                     f"{MAX_TOTAL_BYTES // (1024 * 1024)} МБ на страницу")
                continue
            total += len(face["uri"])
            weight = (f"{face['variable'][0]} {face['variable'][1]}"
                      if face.get("variable") else str(face["weight"]))
            parts.append(
                "@font-face{font-family:" + css_family(face["family"])
                + ";font-style:" + ("italic" if face["italic"] else "normal")
                + ";font-weight:" + weight
                + ";font-display:swap;src:url(" + face["uri"] + ") format(\"" + face["format"] + "\");}"
            )
    return "\n".join(parts)


def font_vars(sans: str = "", mono: str = "") -> str:
    """CSS-переменные --font-sans / --font-mono.

    Если шрифт не выбран, переменная не выводится — app.css использует
    системный шрифт через var(--font-sans, "Segoe UI").
    """
    parts = []
    for name, value in (("--font-sans", sans), ("--font-mono", mono)):
        clean = _clean_family(value)
        if clean:
            parts.append(f"{name}: {css_family(clean)}")
    return " ".join(parts)
