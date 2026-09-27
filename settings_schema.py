"""Схема настроек: единственный источник истины для значений, проверок и UI.

Модуль-владелец описывает свои настройки сам и отдаёт словарь ``SETTINGS``:
``ftp.py`` — выгрузку, ``downloader.py`` — загрузчик. Общие настройки
интерфейса (язык, тема, шрифты) живут здесь, в ``CORE_GROUPS``. Схема
собирается лениво, внутри функции: ``settings`` импортируется и ``downloader``,
и ``gui``, поэтому на уровне модулей эти импорты были бы циклом.

Ключ поля — путь внутри группы ("host", "tls_verify"). Плоское имя для
settings.json получается из группы и ключа: у группы есть flat_prefix
("ftp_" у выгрузки, пустой у интерфейса и загрузчика), поэтому плоский формат
остаётся рабочим и не расходится с текущим файлом.

Описание поля
    key          путь внутри группы
    type         bool | int | text | password | choice | actions | note
    label        ключ i18n с подписью
    title        ключ i18n с подсказкой (необязательно)
    note         ключ i18n с пояснением под полем
    note_source  имя JS-функции, которая заполняет пояснение (themeMeta, ...)
    default      значение по умолчанию
    min/max/step ограничения для int
    options      [["значение", "подпись"], ...] для choice; подпись - это ключ
                 i18n, если он есть в языке, иначе сам текст
    options_source  "langs" | "themes" | "fonts" - список из runtime
    options_of   словарь в модуле-владельце: значения опций должны быть в нём
    dynamic      "transcoders" - часть опций может быть недоступна (ffmpeg)
    placeholder  подсказка внутри поля
    dom          id элемента; по умолчанию плоское имя с "_" на "-"
    dom_range    id ползунка, если у поля есть пара "ползунок + число"
    mirror       "range" - у поля есть ползунок
    check        поле рисуется строкой-флажком (текст подписи рядом)
    box          имя блока-секции внутри группы (см. boxes группы)
    row          номер строки внутри блока: поля с одним row в одной строке
    inline       True для пояснения, которое живёт в строке с кнопкой
    visible_if   {"key": ..., "equals": ...} - поле видно только при условии
    live         применить сразу, без перезагрузки страницы
    secret       значение не показывать в подсказках и логах
    transient    поле не сохраняется (кнопки, пояснения, папка загрузки)
    in_panel     False - поле живёт в главном окне, не в панели настроек
"""

TYPES = ("bool", "int", "text", "password", "choice", "actions", "note")

# Общие настройки интерфейса. Порядок вкладок задаётся полем order.
CORE_GROUPS = [
    {
        "id": "ui",
        "label": "sheet.tab.ui",
        "order": 10,
        "fields": [
            {"key": "language", "type": "choice", "label": "sheet.lang.label",
             "default": "en", "options_source": "langs", "dom": "lang", "live": True},
            {"key": "theme", "type": "choice", "label": "sheet.theme.label",
             "default": "scarred_mind", "options_source": "themes", "dom": "theme",
             "live": True, "note_source": "themeMeta"},
            {"type": "actions", "transient": True, "buttons": [
                {"dom": "reload-themes", "icon": "⟳", "label": "sheet.theme.reload"},
                {"dom": "open-themes", "icon": "⤢", "label": "sheet.theme.open"},
            ]},
            # папка загрузки - не настройка: значение приходит из get_initial()
            {"key": "dest", "type": "text", "label": "sheet.dest.label", "dom": "dest",
             "transient": True, "placeholder": ""},
            {"type": "actions", "transient": True, "buttons": [
                {"dom": "browse", "label": "sheet.browse", "browse_dest": True},
            ]},
            {"key": "font_sans", "type": "choice", "label": "sheet.font.sans",
             "default": "", "options_source": "fonts", "dom": "font-sans", "live": True},
            {"key": "font_mono", "type": "choice", "label": "sheet.font.mono",
             "default": "", "options_source": "fonts_mono", "dom": "font-mono", "live": True},
            {"type": "note", "transient": True, "dom": "font-note", "note_source": "fontNote"},
            {"type": "actions", "transient": True, "buttons": [
                {"dom": "reload-fonts", "icon": "⟳", "label": "sheet.font.reload"},
                {"dom": "download-fonts", "icon": "⤓", "label": "sheet.font.download"},
                {"dom": "open-fonts", "icon": "⤢", "label": "sheet.font.open"},
            ]},
            {"type": "note", "transient": True, "dom": "font-dl-note"},
        ],
    },
]

# Модули, отдающие свои настройки: имя модуля -> id группы в нём.
MODULE_GROUPS = (
    ("downloader", "dl"),
    ("ftp", "ftp"),
)

_schema = None
_walked = None
_owner = None


def _import_module(name: str):
    """Ленивый импорт модуля-владельца настроек (обход цикла импортов)."""
    import importlib
    import sys

    if name in sys.modules:
        return sys.modules[name]
    return importlib.import_module(name)


def build_schema() -> dict:
    """Собирает схему из ядра и фрагментов модулей (результат кэшируется)."""
    global _schema
    if _schema is not None:
        return _schema
    groups = list(CORE_GROUPS)
    for module_name, group_id in MODULE_GROUPS:
        module = _import_module(module_name)
        spec = getattr(module, "SETTINGS", None)
        if not spec:
            continue
        specs = spec if isinstance(spec, list) else [spec]
        for item in specs:
            if item.get("id") not in (None, group_id):
                raise ValueError(f"{module_name}: группа {item.get('id')!r} вместо {group_id!r}")
            groups.append(item)
    groups.sort(key=lambda g: g.get("order", 100))
    _schema = {"groups": groups}
    return _schema


def groups() -> list:
    return build_schema()["groups"]


def _walk():
    """Список (группа, поле) по всем группам, включая кнопки и пояснения."""
    global _walked
    if _walked is None:
        _walked = [(g, f) for g in groups() for f in g.get("fields", [])]
    return _walked


def flat_prefix(group_id: str) -> str:
    """Префикс плоских имён группы: у выгрузки 'ftp_', у остальных пусто."""
    for group in groups():
        if group["id"] == group_id:
            return group.get("flat_prefix", "")
    return ""


def flat_name(group_id: str, key: str) -> str:
    """Имя настройки в settings.json: ftp.tls_verify -> ftp_tls_verify,
    dl.socket_timeout -> socket_timeout (у загрузчика префикса нет)."""
    return f"{flat_prefix(group_id)}{key}"


def path_of(group_id: str, key: str) -> str:
    return f"{group_id}.{key}"


def field(key: str):
    """Поле по точечному пути ('ftp.host') или по плоскому имени ('ftp_host')."""
    for group, spec in _walk():
        if not spec.get("key"):
            continue
        if key in (path_of(group["id"], spec["key"]), flat_name(group["id"], spec["key"])):
            return group, spec
    return None, None


def dom_id(key: str) -> str:
    """id элемента поля: ftp.tls_verify -> 'ftp-tls-verify'."""
    group, spec = field(key)
    if spec is None or not spec.get("key"):
        return ""
    return spec.get("dom") or flat_name(group["id"], spec["key"]).replace("_", "-")


def defaults() -> dict:
    """Плоский словарь значений по умолчанию (как сейчас в settings.json)."""
    out = {}
    for group, spec in _walk():
        if not spec.get("key") or spec.get("transient"):
            continue
        out[flat_name(group["id"], spec["key"])] = spec.get("default")
    return out


def has(key: str) -> bool:
    """Известен ли ключ схеме (принимает и 'ftp_host', и 'ftp.host')."""
    _, spec = field(key)
    return spec is not None and not spec.get("transient")


def coerce(key: str, value):
    """Приводит значение к типу поля; битое значение заменяется умолчанием.

    Неизвестный ключ не трогаем: вызывающий код решает сам (save_setting
    отвечает 'unknown key', load_settings - оставляет значение как есть).
    """
    _, spec = field(key)
    if spec is None:
        return value
    kind = spec.get("type")
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes", "да")
        return bool(value)
    if kind == "int":
        low, high = spec.get("min"), spec.get("max")
        try:
            num = int(float(value))
        except (TypeError, ValueError):
            return spec.get("default", 0)
        if low is not None:
            num = max(int(low), num)
        if high is not None:
            num = min(int(high), num)
        return num
    if kind in ("text", "password"):
        return "" if value is None else str(value)
    if kind == "choice":
        # у статических списков (субтитры, качество, кодек, режим FTP) набор
        # значений известен: чужое значение из ручного правки файла -> умолчание.
        # У динамических (язык, тема, шрифты) списка options нет - не проверяем.
        allowed = [opt[0] for opt in spec.get("options", [])]
        if allowed and value not in allowed:
            return spec.get("default")
    return value


def value(data: dict, key: str):
    """Значение настройки из плоского settings-словаря: тип, умолчание, границы.

    Пустой или отсутствующий ключ даёт умолчание из схемы, поэтому потребителям
    (FtpConfig, downloader) не нужно знать ни про типы, ни про min/max.
    """
    group, spec = field(key)
    if spec is None:
        return None
    path = path_of(group["id"], spec["key"])
    flat = flat_name(group["id"], spec["key"])
    if path in data:
        return coerce(path, data[path])
    if flat in data:
        return coerce(flat, data[flat])
    return spec.get("default")


def options_of(key: str):
    """Словарь-владелец опций поля (QUALITY_FORMATS, SUBTITLE_OPTIONS, ...)."""
    global _owner
    if _owner is None:
        _owner = {}
        for module_name, group_id in MODULE_GROUPS:
            _owner[group_id] = module_name
    group, spec = field(key)
    if spec is None or not spec.get("options_of"):
        return None
    module_name = _owner.get(group["id"])
    if not module_name:
        return None
    return getattr(_import_module(module_name), spec["options_of"], None)


def schema_json() -> dict:
    """Схема для страницы: та же структура, но с вычисленными путями и dom."""
    out = {"groups": []}
    for group in groups():
        item = {
            "id": group["id"],
            "label": group.get("label"),
            "boxes": group.get("boxes", {}),
            "fields": [],
        }
        for spec in group.get("fields", []):
            entry = dict(spec)
            if spec.get("key"):
                entry["path"] = path_of(group["id"], spec["key"])
                if not spec.get("transient"):
                    flat = flat_name(group["id"], spec["key"])
                    entry["dom"] = spec.get("dom") or flat.replace("_", "-")
            item["fields"].append(entry)
        out["groups"].append(item)
    return out
