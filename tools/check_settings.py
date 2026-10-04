r"""Проверка схемы настроек без запуска приложения.

Что проверяем (settings_schema, settings, фрагменты ftp.py / downloader.py):
  1. схема собирается из ядра и фрагментов модулей, вкладки в нужном порядке;
  2. у полей есть тип, подпись, умолчание; плоские имена и dom-id уникальны;
  3. ключи и умолчания совпадают с текущим based_settings.json - плоский формат
     не поехал, старый settings.json читается как раньше;
  4. dom-id полей совпадают с теми, что рисует settings.js и ждёт пробник
     (ни одного нового, ни одного потерянного);
  5. coerce: границы, битые значения, строки вместо чисел, незнакомые опции;
  6. все подписи схемы есть во всех 6 языках;
  7. значения опций есть в словарях модулей (QUALITY_FORMATS, TRANSCODERS, ...);
  8. visible_if ссылается на существующий ключ своей группы;
  9. файл настроек: чужие ключи не пишутся, hevc переносится, значения чинятся,
     а обычное чтение файл не трогает;
 10. окно настроек: свой шаблон и стиль, общий JS в обоих окнах, схема не
     утекает в главное окно, а оно само не рисует настройки;
 11. обход блокировок (dpi.py): решалка «нужен ли обход», отказы без
     запуска и без прав администратора, список стратегий и кэш, невидимость
     работы (проверка обновлений zapret, окна, имя задачи);
 12. выгрузка на FTP: возобновление TLS-сессии на канале данных, рендер
     пути на сервере и ensure_dir на фейковом сервере (абсолютные пути и
     возврат CWD);
 13. реестр установок обхода: вшитый пакет раскладывается без сети,
     битые папки не регистрируются, оба layout-а опознаются, архив с
     zip-slip не распаковывается.

Запуск:  python tools/check_settings.py
"""

import inspect
import ftplib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dpi  # noqa: E402
import ftp as ftp_mod  # noqa: E402
import i18n  # noqa: E402
import settings  # noqa: E402
import settings_schema  # noqa: E402
import version  # noqa: E402
from ftp import FtpConfig  # noqa: E402

# id, которые рисует окно настроек и на которые завязан settings.js.
# Схема обязана выдавать ровно этот набор: пока он не сгенерирован, список
# служит контрактом для следующих этапов (генерация панели).
LEGACY_DOM = {
    # раздел «Интерфейс»
    "lang", "theme", "reload-themes", "download-themes", "themes-dl-note",
    "open-themes",
    "font-heading", "font-sans", "font-mono", "font-weight", "font-preview",
    "font-note", "font-dl-note",
    "reload-fonts", "download-fonts", "open-fonts",
    # силы подсказок: ручки + сцена-предпросмотр, зеркальных ползунков
    # (tip-pull-range/tip-repel-range) больше нет
    "tip-pull", "tip-repel", "tip-preview",
    "render-gpu", "render-anim", "render-blur",
    "app-version",
    # раздел «Загрузчик»
    "subs", "qual", "transcode", "transcode-note", "dest", "browse",
    "retries", "retries-range", "socket_timeout", "socket_timeout-range",
    # раздел «FTP»
    "ftp-active", "ftp-mode", "ftp-host", "ftp-port", "ftp-user", "ftp-password",
    "ftp-tls", "ftp-tls-verify", "ftp-pasv", "ftp-delete-local", "ftp-dir",
    "ftp-dir-note", "ftp-template", "ftp-timeout", "ftp-retries",
    "ftp-test", "ftp-test-note",
    # раздел «Обход»
    "dpi-orch", "dpi-after", "dpi-install", "dpi-install-note", "dpi-dir",
    "dpi-mode", "dpi-bat", "dpi-args", "dpi-timeout", "dpi-probe", "dpi-scan",
    "dpi-start", "dpi-stop", "dpi-note",
    "bypass-choose", "bypass-add", "bypass-detect", "bypass-remove",
    # вне панели
    "group",
}

# (ключ, значение на входе, ожидание после coerce)
COERCE_CASES = [
    ("ftp_port", "99999", 65535),
    ("ftp_port", "0", 1),
    ("ftp_port", "abc", 21),
    ("ftp_port", None, 21),
    ("ftp_port", 2121.0, 2121),
    ("ftp_timeout", 1, 5),
    ("ftp_timeout", "3600", 3600),
    ("socket_timeout", 999, 120),
    ("retries", 7.9, 7),
    ("retries", -3, 1),
    ("ftp_retries", "2", 2),
    ("ftp_tls", "true", True),
    ("ftp_tls", "0", False),
    ("ftp_active", 1, True),
    ("ftp_tls_verify", "", False),
    ("ftp_pasv", "нет", False),
    ("quality", "huge", "lossless"),
    ("quality", "1080", "1080"),
    ("font_weight", "555", 560),     # knob: квантование по step10
    ("font_weight", "95", 100),      # knob: нижняя граница
    ("font_weight", "нет", 400),     # knob: битое значение -> умолчание
    ("font_sans", "JetBrains Mono", "JetBrains Mono"),  # ручка шрифта: pass-through
    ("font_sans", None, ""),                       # ручка шрифта: None -> умолчание
    ("ftp_mode", "nope", "batch"),
    ("transcode", "av1", "none"),
    ("theme", "моя тема", "моя тема"),   # список опций динамический - не проверяем
    ("language", "xx", "xx"),
    ("ftp_host", None, ""),
    ("ftp_user", 42, "42"),
    ("ftp_password", None, ""),
    ("dpi_timeout", 1, 5),
    ("dpi_timeout", "300", 300),
    ("dpi_mode", "nope", "bat"),
    ("dpi_orch", "nope", "ask"),
    ("dpi_orch", "auto", "auto"),
    ("dpi_after", "nope", "restore"),
    ("dpi_after", "keep", "keep"),
    ("dpi_dir", None, ""),
    ("some_garbage", "x", "x"),         # чужой ключ не трогаем
]

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


def _doms() -> list:
    """Все id, которые должны появиться в DOM: у полей - вычисленные, у кнопок
    и пояснений - из фрагмента."""
    out = []
    for group, spec in settings_schema._walk():
        path = settings_schema.path_of(group["id"], spec["key"]) if spec.get("key") else None
        dom = settings_schema.dom_id(path) if path else spec.get("dom")
        if dom:
            out.append(dom)
        if spec.get("dom_range"):
            out.append(spec["dom_range"])
        for button in spec.get("buttons", []):
            if button.get("dom"):
                out.append(button["dom"])
    return out


def _i18n_keys() -> set:
    """Все ключи i18n, на которые ссылается схема (подписи, блоки, группы)."""
    keys = set()
    for group in settings_schema.groups():
        if group.get("label"):
            keys.add(group["label"])
        keys.update(group.get("boxes", {}).values())
        for spec in group.get("fields", []):
            for name in ("label", "title", "note"):
                if spec.get(name):
                    keys.add(spec[name])
            for hint in (spec.get("option_hints") or {}).values():
                if hint:
                    keys.add(hint)
            for value, caption in spec.get("options", []):
                if caption in i18n.I18N.get("ru", {}):  # подпись-ключ, а не текст
                    keys.add(caption)
            for button in spec.get("buttons", []):
                if button.get("label"):
                    keys.add(button["label"])
    return keys


def main() -> int:
    # 1. сборка схемы
    section("1. схема собирается")
    groups = settings_schema.groups()
    ids = [g["id"] for g in groups]
    ok(ids == ["ui", "dl", "dpi", "ftp"], "вкладки в порядке ui, dl, dpi, ftp", str(ids))
    ok(all(g.get("label") for g in groups), "у вкладок есть подписи")
    ok(settings_schema.flat_prefix("ftp") == "ftp_", "у выгрузки префикс ftp_")
    ok(settings_schema.flat_prefix("dl") == "", "у загрузчика префикса нет (совместимость)")
    for module_name, group_id in settings_schema.MODULE_GROUPS:
        module = settings_schema._import_module(module_name)
        ok(bool(getattr(module, "SETTINGS", None)), f"{module_name}.SETTINGS на месте")
    ok(settings_schema.field("ftp.tls_verify")[1] is not None, "поле находится по пути")
    ok(settings_schema.field("ftp_tls_verify")[1] is not None, "то же - по плоскому имени")

    # 2. описание полей
    section("2. описание полей")
    bad = []
    for group, spec in settings_schema._walk():
        tag = spec.get("path") or f"{group['id']}.<{spec.get('type')}>"
        if spec.get("type") not in settings_schema.TYPES:
            bad.append(f"{tag}: тип {spec.get('type')!r}")
        if not spec.get("label") and spec.get("type") not in ("actions", "note"):
            bad.append(f"{tag}: нет подписи")
        if not spec.get("key") and not spec.get("transient"):
            bad.append(f"{tag}: нет ключа")
        if spec.get("key") and not spec.get("transient") and "default" not in spec:
            bad.append(f"{tag}: нет умолчания")
        if spec.get("type") == "int" and not (spec.get("min") is not None and spec.get("max")):
            bad.append(f"{tag}: int без границ")
        if spec.get("type") == "choice" and not (spec.get("options") or spec.get("options_source")):
            bad.append(f"{tag}: choice без списка опций")
        if spec.get("type") == "actions" and not spec.get("buttons"):
            bad.append(f"{tag}: actions без кнопок")
    ok(not bad, "у всех полей есть тип, подпись, умолчание и границы", "; ".join(bad))

    flat_names, paths = [], []
    for group, spec in settings_schema._walk():
        if spec.get("key") and not spec.get("transient"):
            flat_names.append(settings_schema.flat_name(group["id"], spec["key"]))
            paths.append(settings_schema.path_of(group["id"], spec["key"]))
    ok(len(set(flat_names)) == len(flat_names), "плоские имена уникальны",
       str([n for n in flat_names if flat_names.count(n) > 1]))
    ok(len(set(paths)) == len(paths), "пути уникальны", str([p for p in paths if paths.count(p) > 1]))
    doms = _doms()
    ok(len(doms) == len(set(doms)), "dom-id уникальны",
       str([d for d in doms if doms.count(d) > 1]))
    ok(len(flat_names) == 39, "в схеме 39 сохраняемых настроек", str(len(flat_names)))

    # 3. совместимость с текущим файлом
    section("3. плоский формат не поехал")
    defaults = settings_schema.defaults()
    based = json.loads((ROOT / "based_settings.json").read_text(encoding="utf-8"))
    ok(set(based) == set(defaults), "ключи совпадают с based_settings.json",
       f"нет: {sorted(set(based) - set(defaults))}, лишние: {sorted(set(defaults) - set(based))}")
    diffs = {k: (based[k], defaults[k]) for k in defaults if based.get(k) != defaults[k]}
    ok(not diffs, "умолчания совпадают", str(diffs))

    # 4. dom-id полей
    section("4. dom-id полей не изменились")
    ok(set(doms) == LEGACY_DOM, "набор id совпадает с контрактом settings.js",
       f"нет: {sorted(LEGACY_DOM - set(doms))}, лишние: {sorted(set(doms) - LEGACY_DOM)}")

    # 4b. что страница получает из schema_json (рисует по нему settings.js)
    section("4b. schema_json для страницы")
    page = settings_schema.schema_json()
    fields = [f for g in page["groups"] for f in g["fields"]]
    stored = [f for f in fields if "setting" in f]
    ok(len(stored) == len(defaults),
       f"у {len(stored)} полей есть плоское имя для save_setting",
       f"сохраняемых настроек в схеме {len(defaults)}")
    ok(all(settings_schema.has(f["setting"]) for f in stored),
       "плоские имена известны схеме (save_setting их примет)",
       str([f["setting"] for f in stored if not settings_schema.has(f["setting"])]))
    pairs = {f["path"]: f["setting"] for f in stored}
    ok(all(settings_schema.flat_name(*p.split(".", 1)) == s for p, s in pairs.items()),
       "плоское имя выводится из пути (как в flat_name)")
    conds = [f["visible_if"] for f in fields if f.get("visible_if")]
    ok(conds and all("." in c["key"] for c in conds),
       "visible_if.key абсолютный (как в settings.js)", str(conds[:2]))
    ok(all(f["dom"] for f in stored), "у каждого сохраняемого поля есть dom")
    transients = [f for f in fields if "setting" not in f]
    ok(all(f.get("type") in ("actions", "note") or f.get("value_source") for f in transients),
       "у нес сохраняемых полей есть type или value_source",
       str([f.get("key") for f in transients]))
    ok(any(f.get("type") == "actions" and f.get("buttons") for f in fields),
       "кнопки описаны в схеме, а не в разметке")
    ok(all(len(f["visible_if"]) == 2 for f in fields if f.get("visible_if")),
       "в visible_if только key и equals")


    # 5. coerce
    section("5. приведение значений")
    for key, raw, expected in COERCE_CASES:
        got = settings_schema.coerce(key, raw)
        ok(got == expected and type(got) is type(expected),
           f"coerce({key!r}, {raw!r}) = {expected!r}", f"получилось {got!r}")
    ok(settings_schema.has("ftp_host") and settings_schema.has("ftp.host"),
       "has() принимает оба имени")
    ok(not settings_schema.has("some_garbage"), "has() отвергает чужой ключ")
    cfg = FtpConfig({"ftp_port": "99999", "ftp_host": "  ftp.example.org  "})
    ok(cfg.port == 65535 and cfg.host == "ftp.example.org", "FtpConfig берёт границы из схемы",
       f"{cfg.port} {cfg.host!r}")
    empty = FtpConfig({})
    ok((empty.port, empty.user, empty.tls_verify, empty.pasv, empty.template, empty.timeout,
        empty.retries, empty.mode) == (21, "anonymous", True, True, "{title}{ext}", 60, 3, "batch"),
       "FtpConfig без файла = умолчания схемы")
    ok(settings_schema.value({"ftp_dir": "{date}"}, "ftp.dir") == "{date}", "value() читает ключ")
    ok(settings_schema.value({"ftp_dir": 5}, "ftp.dir") == "5", "value() приводит тип")
    ok(settings_schema.value({}, "ftp.mode") == "batch", "value() отдаёт умолчание")

    # 6. i18n
    section("6. подписи во всех 6 языках")
    i18n.load_languages()
    keys = _i18n_keys()
    ok(len(keys) >= 30, f"схема ссылается на {len(keys)} ключей i18n")
    missing = {lang: [k for k in sorted(keys) if k not in i18n.I18N.get(lang, {})]
               for lang in i18n.LANGUAGES}
    missing = {lang: keys_list for lang, keys_list in missing.items() if keys_list}
    ok(not missing, "во всех языках есть все ключи", str(missing))
    empty = [lang for lang in i18n.LANGUAGES if not i18n.I18N.get(lang)]
    ok(not empty, "все языки загрузились", str(empty))
    # надпись элемента в сцене подсказок: ключ вне схемы (рисует settings.js),
    # поэтому _i18n_keys его не видит - проверяем отдельно
    ok(all("sheet.ui.tip_demo_el" in i18n.I18N.get(lang, {})
           for lang in i18n.LANGUAGES),
       "надпись элемента сцены переведена во всех языках")

    # 7. опции против словарей модулей
    section("7. опции совпадают со словарями модулей")
    for key in ("dl.subtitles", "dl.quality", "dl.transcode"):
        _, spec = settings_schema.field(key)
        owner = settings_schema.options_of(key)
        values = [value for value, _ in spec["options"]]
        # "none" в перекодировке - сентинел "не перекодировать", в словаре
        # кодировщиков его нет by design
        values = [v for v in values if v != spec["default"]]
        ok(bool(owner), f"{spec['options_of']} найден")
        ok(all(v in owner for v in values),
           f"значения {key} есть в {spec['options_of']}",
           str([v for v in values if v not in owner]))
        ok(spec["default"] in owner or spec["default"] == "none",
           f"умолчание {key} = {spec['default']!r} допустимо")
    ok(settings_schema.options_of("ftp.mode") is None, "у ftp.mode своего словаря нет")

    # 8. visible_if
    section("8. условия видимости")
    bad = []
    ftp = next(g for g in groups if g["id"] == "ftp")
    keys_in_group = {s.get("key") for s in ftp["fields"] if s.get("key")}
    for spec in ftp["fields"]:
        cond = spec.get("visible_if")
        if not cond:
            if spec.get("key") != "active":
                bad.append(f"{spec['path']}: нет условия")
            continue
        if cond.get("key") not in keys_in_group:
            bad.append(f"{spec['path']}: ссылка на {cond.get('key')!r}")
    ok(not bad, "у всех полей выгрузки условие по флажку active", "; ".join(bad))
    _, active = settings_schema.field("ftp.active")
    ok(active["type"] == "bool" and active["default"] is False, "active - выключенный флажок")

    # 9. файл настроек
    section("9. файл настроек (изолированный LOCALAPPDATA)")
    iso = Path(tempfile.mkdtemp(prefix="synf-check-settings-"))
    os.environ["LOCALAPPDATA"] = str(iso)
    try:
        path = settings.settings_path()
        first = settings.load_settings()
        ok(path.is_file(), "файл создан при первом запуске")
        ok(set(first) == set(defaults), "в файле ровно ключи схемы")

        first["мусор"] = 1
        first["ftp_port"] = "2121"
        settings.save_settings(first)
        stored = json.loads(path.read_text(encoding="utf-8"))
        ok("мусор" not in stored, "чужие ключи не пишутся")
        ok(stored["ftp_port"] == 2121, "значения приводятся к типу при записи")

        path.write_text(json.dumps({"hevc": True, "ftp_dir": "{date}"}), encoding="utf-8")
        migrated = settings.load_settings()
        ok(migrated["transcode"] == "libx265", "hevc=True переносится в transcode")
        ok(migrated["ftp_dir"] == "{date}", "остальные ключи не теряются")
        stored = json.loads(path.read_text(encoding="utf-8"))
        ok(set(stored) == set(defaults) and "hevc" not in stored,
           "файл дополнен и почищен")

        path.write_text(json.dumps({"retries": 999, "quality": "huge"}), encoding="utf-8")
        fixed = settings.load_settings()
        ok(fixed["retries"] == 50 and fixed["quality"] == "lossless",
           "битые значения чинятся при чтении", f"{fixed['retries']} {fixed['quality']}")
        stored = json.loads(path.read_text(encoding="utf-8"))
        ok(stored["retries"] == 50 and stored["quality"] == "lossless",
           "и сразу записываются в файл")

        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["app_version"] = "1.2.6.4"
        path.write_text(json.dumps(stored), encoding="utf-8")
        upgraded = settings.load_settings()
        ok(upgraded["app_version"] == version.__version__,
           "файл прошлой версии поднимается до текущей")
        stored = json.loads(path.read_text(encoding="utf-8"))
        ok(stored["app_version"] == version.__version__,
           "и новая версия записывается в файл")

        os.utime(path, (1_000_000, 1_000_000))
        stamp = path.stat().st_mtime_ns
        again = settings.load_settings()
        ok(path.stat().st_mtime_ns == stamp, "чистое чтение файл не трогает")
        ok(again == fixed, "повторное чтение даёт те же значения")

        path.write_text("{ не json", encoding="utf-8")
        ok(settings.load_settings() == defaults, "битый файл откатывается к умолчаниям")
    finally:
        shutil.rmtree(iso, ignore_errors=True)

    # 10. карточка настроек внутри главного окна: схему рисует settings.js,
    #    разметка - свой фрагмент, общее состояние - из poll() главного окна
    section("10. карточка настроек")
    src = ROOT / "ui_src"
    settings_js = (src / "settings.js").read_text(encoding="utf-8")
    app_js = (src / "app.js").read_text(encoding="utf-8")
    common_js = (src / "common.js").read_text(encoding="utf-8")
    card_html = (src / "settings.html").read_text(encoding="utf-8")
    main_html = (src / "index.html").read_text(encoding="utf-8")

    ok('var SETTINGS_SCHEMA = __SETTINGS_SCHEMA__' in settings_js,
       "settings.js получает схему из плейсхолдера")
    ok("SLOT:settings" not in main_html,
       "главная страница больше не содержит панели настроек")
    ok('<html' not in card_html and "__COMMONJS__" not in card_html,
       "фрагмент карточки - кусок страницы, а не отдельное окно")
    ok('id="settings-nav"' in card_html and 'id="settings-sections"' in card_html,
       "в карточке есть список разделов и область полей")
    ok('id="settings-close"' in card_html, "в карточке есть кнопка закрытия")
    ok('id="settings-overlay"' in card_html, "карточка лежит в оверлее")
    for ph in ("__SETTINGS_HTML__", "__SETTINGS_CSS__", "__SETTINGS_JS__"):
        ok(ph in main_html, f"главная страница вставляет {ph}")
    for ph in ("__COMMONJS__", "__APPJS__", "__MOTION__", "__ALPINE__"):
        ok(ph in main_html, f"главная страница подключает {ph}")
    ok("__SETTINGS_JS__" in main_html and "__APPJS__" in main_html
       and main_html.index("__APPJS__") < main_html.index("__SETTINGS_JS__"),
       "settings.js подключается после app.js (иначе он затрёт его applyI18n)")
    # порядок vendor критичен: Motion до app.js (глобал Motion нужен коду),
    # Alpine последним - все alpine:init-обработчики должны быть
    # зарегистрированы до старта движка (собственный старт на DOMContentLoaded)
    ok(main_html.index("__COMMONJS__") < main_html.index("__MOTION__")
       and main_html.index("__MOTION__") < main_html.index("__APPJS__")
       and main_html.index("__SETTINGS_JS__") < main_html.index("__ALPINE__"),
       "порядок скриптов: common -> motion -> app -> settings -> alpine")
    for ident in ("renderWindow", "applyVisibility", "fillSettings", "bindSettings", "bindCustom",
                  "synfSettingsInit", "synfSettingsState", "set_dest", "save_setting",
                  "set_theme", "set_font", "reload_fonts", "download_fonts", "download_themes"):
        ok(ident in settings_js, f"settings.js использует {ident}")
    for gone in ("poll_settings", "close_settings", "pywebviewready"):
        ok(gone not in settings_js,
           f"у карточки нет своего запроса состояния ({gone})")
    # разделы и пункты списка строит Alpine (x-for по схеме): проверяем
    # шаблон settings.html - там :id из групп схемы, а не разметка в JS
    ok(':id="\'nav-\' + group.id"' in card_html,
       "пункты списка строятся из групп схемы")
    ok(':id="\'section-\' + group.id"' in card_html,
       "разделы строятся из групп схемы")
    ok('x-data="settingsPanel()"' in card_html and 'x-mount-block' in card_html
       and 'x-mount-card' in card_html,
       "панель собрана x-for с монтированием полей (settingsPanel)")
    ok("layoutOf" in settings_js and "mountBlockInto" in settings_js
       and "fieldsMounted" in settings_js and "whenPanelReady" in settings_js,
       "settings.js: схема -> layout, монтирование полей, очередь готовности")
    ok("Alpine.data(\"settingsPanel\"" in settings_js and "$nextTick(fieldsMounted)" in settings_js,
       "компонент Alpine регистрируется в alpine:init и биндит после рендера")
    ok("collect(" not in app_js and "SETTINGS_SCHEMA" not in app_js,
       "главное окно не рисует и не собирает настройки")
    for ident in ("openSettings", "setSettingsOpen", "synfSettingsState", "poll"):
        ok(ident in app_js, f"app.js использует {ident}")
    for gone in ("open_settings", "setBlocked", "settingsClosed"):
        ok(gone not in app_js, f"у окна больше нет {gone}")
    ok("synfSettingsState(st)" in app_js and "synfSettingsState(st.settings" not in app_js,
       "в карточку уходит весь poll(), а не только настройки")
    ok("ui_rev" in app_js and "ui_rev" in settings_js,
       "главное окно и карточка следят за ui_rev")
    ok("var curTheme" in common_js and "curTheme ||" in common_js,
       "активная тема хранится в общем коде, а не берётся из селекта окна")
    ok("dl.dest" in settings_js and "set_dest" in settings_js,
       "папка загрузки уходит в Python через set_dest")
    for ph in ("__THEME_ROOT__", "__THEME_CSS__", "__FONTS_CSS__", "__APP_CSS__"):
        ok(ph in main_html, f"{ph} подставляется в шаблон")
        ok(ph not in card_html, f"фрагмент карточки не подставляет {ph}")
    for ph in ("__I18N__", "__THEMES__"):
        ok(ph in common_js, f"{ph} подставляется в общий JS")
    ok("__SETTINGS_SCHEMA__" in settings_js,
       "схема настроек подставляется в settings.js")
    ok("__MAIN_CSS__" in main_html, "в главное окно подключается его стиль")
    ok("__SETTINGS_SCHEMA__" not in main_html,
       "схема настроек не утекает в главное окно")
    ok('id="settings-block"' not in main_html and 'class="overlay"' not in main_html,
       "старый блок настроек из главной страницы убран")

    # 11. обход блокировок (dpi.py): решалка, отказы без запуска, переводы
    section("11. обход блокировок")
    ok(ids.index("dl") < ids.index("dpi") < ids.index("ftp"),
       "вкладка обхода между загрузчиком и выгрузкой", str(ids))
    ok(settings_schema.flat_prefix("dpi") == "dpi_", "у обхода префикс dpi_")
    d = dpi.DpiConfig({})
    got = (d.orch, d.after, d.dir, d.mode, d.bat, d.args, d.timeout)
    ok(got == ("ask", "restore", "", "bat", "general.bat", "", 45),
       "DpiConfig без файла = умолчания схемы", str(got))
    # решалка: обход включается только при включённой оркестрации И закрытом
    # маршруте - отрицательные ветки не дают поднять zapret «просто так»
    for orch, reachable, expected in (("off", False, "skip"), ("off", True, "skip"),
                                      ("ask", False, "start"), ("auto", False, "start"),
                                      ("auto", True, "skip")):
        got = dpi.resolve({"dpi_orch": orch}, reachable)
        ok(got == expected, f"resolve(orch={orch!r}, reachable={reachable}) = {expected!r}",
           f"получилось {got!r}")
    # что делать после загрузки: три режима и защита от битого значения
    for after, expected in (("restore", "restore"), ("keep", "keep"),
                            ("off", "off"), ("лишнее", "restore")):
        ok(dpi.after_action(dpi.DpiConfig({"dpi_after": after})) == expected,
           f"after_action({after!r}) = {expected!r}",
           dpi.after_action(dpi.DpiConfig({"dpi_after": after})))
    # негатив: непригодная папка - отказ текстом, без запуска и без UAC
    for label, bad_dir in (("пустой папки", ""),
                           ("несуществующей папки",
                            os.path.join(tempfile.gettempdir(), "synf-no-such-dir"))):
        try:
            dpi.command(dpi.DpiConfig({"dpi_dir": bad_dir}))
            ok(False, f"command при {label} поднимает ValueError")
        except ValueError as exc:
            ok(bool(str(exc).strip()), f"command при {label} поднимает ValueError с текстом",
               str(exc))
    # негатив: закрытый порт -> False, и ни один процесс не появляется
    st_before = dpi.status()
    ok(dpi.probe(host="127.0.0.1", port=1, timeout=0.3) is False,
       "probe по закрытому порту = False")
    # обе цели: на закрытом маршруте обе молчат, и молчат быстро (без сети)
    both = dpi.probe_all(timeout=0.001)
    ok(both == {"ok": False, "web": False, "media": False},
       "probe_all: закрытый маршрут даёт обе цели False", str(both))
    ok(dpi.probe_media(timeout=0.001) is False,
       "проба googlevideo по недоступному адресу = False")
    ok(dpi.status() == st_before, "probe не трогает процессы", str(dpi.status()))
    # старт при непригодной папке не доходит до запроса прав администратора
    res = dpi.start(dpi.DpiConfig({"dpi_dir": ""}))
    if st_before["running"]:
        ok(res.get("ok") is True and res.get("already") is True,
           "start при запущенном winws = already", str(res))
    else:
        ok(res.get("ok") is False and bool(res.get("error")),
           "start без папки -> отказ с текстом", str(res))
    ok(dpi.status() == st_before, "start при отказе не трогает процессы",
       str(dpi.status()))
    # все ключи, которые модуль спрашивает у i18n, есть во всех 6 языках
    dpi_src = (ROOT / "dpi.py").read_text(encoding="utf-8")
    used = sorted(set(re.findall(r'"(sheet\.dpi\.[\w.]+)"', dpi_src)))
    ok(len(used) >= 10, f"в dpi.py {len(used)} ключей i18n", str(used))
    missing = {lang: [k for k in used if k not in i18n.I18N.get(lang, {})]
               for lang in i18n.LANGUAGES}
    missing = {lang: ks for lang, ks in missing.items() if ks}
    ok(not missing, "ключи обхода переведены во всех языках", str(missing))
    # подбор рабочей стратегии: список, кэш и отказы без UAC и без сети
    tmpdir = Path(tempfile.mkdtemp(prefix="synf-dpi-strategies-"))
    try:
        empty = dpi.DpiConfig({"dpi_dir": str(tmpdir)})
        ok(dpi.strategies(empty) == [], "без файлов стратегий - пустой список",
           str(dpi.strategies(empty)))
        # папка обязана быть установкой (есть winws.exe), иначе разбор
        # установки честно откажет - см. раздел 13
        (tmpdir / "winws.exe").write_bytes(b"MZ")
        for name in ("general (ALT10).bat", "general (ALT2).bat", "general.bat"):
            (tmpdir / name).write_text("", encoding="ascii")
        ok(dpi.strategies(empty) == ["general (ALT2).bat", "general (ALT10).bat",
                                     "general.bat"],
           "стратегии идут в натуральном порядке (ALT2 раньше ALT10)",
           str(dpi.strategies(empty)))
        # негатив: непригодная папка - отказ до запроса прав администратора
        missing = dpi.DpiConfig({"dpi_dir": str(tmpdir / "no-such-dir")})
        res = dpi.scan(missing)
        ok(res.get("ok") is False and bool(res.get("error")),
           "scan при непригодной папке -> отказ с текстом", str(res))
        # негатив: оркестрация выключена - auto не ходит в сеть и ничего не запускает
        off = dpi.auto(dpi.DpiConfig({"dpi_orch": "off", "dpi_dir": ""}))
        ok(off == {"ok": True, "started": False},
           "auto при выключенной оркестрации = ничего не делает", str(off))
        # негатив: «спрашивать» без явного выбора тоже не трогает систему -
        # решение принимает диалог в главном окне, а не воркер
        ask = dpi.auto(dpi.DpiConfig({"dpi_orch": "ask", "dpi_dir": ""}))
        ok(ask == {"ok": True, "started": False},
           "auto в режиме «спрашивать» = ничего не делает", str(ask))
        # кэш: записал - прочитал; битый файл не роняет чтение
        dpi.write_cache("general (ALT).bat")
        ok(dpi.read_cache() == "general (ALT).bat", "кэш стратегии пишется и читается",
           str(dpi.read_cache()))
        cache_file = dpi._probe_dir() / "strategy.json"
        cache_file.write_text("{ не json", encoding="utf-8")
        ok(dpi.read_cache() is None, "битый кэш -> None, без исключения")
        try:
            cache_file.unlink()
        except OSError:
            pass
        # кэш стратегий раздельный по установкам: выигравшая стратегия одной
        # папки не обязана работать в другой (1.9.x и 1.10.x набирают по-своему)
        other = tmpdir / "other-install"
        other.mkdir(exist_ok=True)
        dpi.write_cache("general (ALT9).bat", install=str(tmpdir), ms=613)
        ok(dpi.read_cache(install=str(tmpdir)) == "general (ALT9).bat",
           "кэш читается для своей установки", str(dpi.read_cache(install=str(tmpdir))))
        ok(dpi.read_cache(install=str(other)) is None,
           "кэш чужой установки не подхватывается",
           str(dpi.read_cache(install=str(other))))

        # негатив: стратегия ссылается на несуществующий файл-фейк - установка
        # негодна, хотя winws.exe и папка lists на месте. Именно так обход и
        # умирал после чистки: winws не находил ACTIVE_*.bin и выходил сразу
        pay = tmpdir / "payload-install"
        (pay / "bin").mkdir(parents=True)
        (pay / "lists").mkdir()
        (pay / "bin" / "winws.exe").write_bytes(b"MZ")
        (pay / "general (ALT9).bat").write_text(
            'start "" /min "%BIN%winws.exe" --fake="%BIN%ACTIVE_DISCORD_UDP.bin"\n',
            encoding="ascii")
        rep = dpi.validate_install(str(pay))
        ok(rep["ok"] is False and "payload" in rep["issues"],
           "стратегия с отсутствующим файлом-фейком -> отказ payload",
           str(rep["issues"]))
        ok(rep.get("payload") == ["BIN/ACTIVE_DISCORD_UDP.bin"],
           "в отчёте перечислен недостающий файл", str(rep.get("payload")))
        (pay / "bin" / "ACTIVE_DISCORD_UDP.bin").write_bytes(b"\x00")
        ok(dpi.validate_install(str(pay))["ok"] is True,
           "файл появился - установка снова годна")

        # починка из вшитого архива: только недостающее, без перезаписи
        # и без выхода наружу (zip-slip)
        zpath = tmpdir / "bundle.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("top/bin/winws.exe", b"MZ")
            zf.writestr("top/bin/ACTIVE_DISCORD_UDP.bin", b"FAKE")
            zf.writestr("top/lists/list-google.txt", b"x")
            zf.writestr("../evil.txt", b"x")
            zf.writestr("top/../evil2.txt", b"x")
        target = tmpdir / "install"
        (target / "bin").mkdir(parents=True)
        (target / "bin" / "winws.exe").write_bytes(b"EXISTING")
        with zipfile.ZipFile(zpath) as zf:
            restored = dpi._repair_from_zip(zf, target, "top")
        ok(restored == 2, "починка дописала два недостающих файла", str(restored))
        ok((target / "bin" / "ACTIVE_DISCORD_UDP.bin").read_bytes() == b"FAKE",
           "недостающий файл-фейк восстановлен")
        ok((target / "bin" / "winws.exe").read_bytes() == b"EXISTING",
           "существующий файл не перезаписан")
        ok(not (tmpdir / "evil.txt").exists() and not (tmpdir / "evil2.txt").exists(),
           "zip-slip не записал наружу")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    # невидимость работы: помощник глушит проверку обновлений zapret (иначе
    # каждый старт стратегии открывает страницу релизов в браузере) и прячет
    # окна стратегий; имя задачи - простое, оно уходит в schtasks
    ok("NO_UPDATE_CHECK" in dpi._RUNNER_SOURCE,
       "помощник глушит проверку обновлений zapret (нет вкладок браузера)")
    ok("ShowWindow" in dpi._RUNNER_SOURCE, "помощник прячет окна стратегий")
    ok("WindowStyle Hidden" in dpi._RUNNER_SOURCE,
       "помощник и его команды стартуют без окон")
    ok(dpi.TASK_NAME.isascii() and " " not in dpi.TASK_NAME,
       "имя задачи планировщика простое (ASCII, без пробелов)", dpi.TASK_NAME)
    # негатив: проверка наличия задачи работает без прав и не путает имена
    ok(dpi._task_exists("SynfroniaNoSuchTask") is False,
       "несуществующая задача не выдаётся за существующую")
    ok("_run_action" in (ROOT / "dpi.py").read_text(encoding="utf-8"),
       "все операции с правами идут через единый _run_action")
    # оркестрация: помощник умеет снимать исходное состояние и возвращать его
    for token in ('"suspend"', '"restore"', '"state"', "Stop-Service",
                  "Start-Service", "orchestrator.json", "Get-CimInstance Win32_Service"):
        ok(token in dpi._RUNNER_SOURCE, f"помощник знает про {token}")
    # подбор обязан мерить обе цели: веб открывается раньше потока, и стратегия
    # «веб есть, видео нет» не должна считаться рабочей
    ok("function Test-Targets" in dpi._RUNNER_SOURCE,
       "помощник проверяет и youtube, и googlevideo")
    ok("$req.media" in dpi._RUNNER_SOURCE and "$MediaTarget" in dpi._RUNNER_SOURCE,
       "цель медиапотока приходит из запроса")
    ok('"media": PROBE_MEDIA' in dpi_src,
       "run_action кладёт цель медиапотока в запрос помощнику")
    # политика задачи читается из её же XML: маркер-файл обнуляла любая
    # чистка probe/, после чего каждый запуск требовал прав администратора
    ok("MultipleInstancesPolicy" in dpi_src,
       "политика задачи читается из её XML, а не из файла-маркера")
    ok("task.policy" not in dpi_src, "хрупкий маркер политики убран")
    ok("def finish(" in dpi_src, "завершение оркестрации - единая dpi.finish")
    # переносы старых ключей: выбор пользователя не теряется при обновлении
    migrations = {old: (new, mapper) for old, new, mapper in settings.MIGRATIONS}
    ok(migrations.get("dpi_auto", ("", None))[0] == "dpi_orch"
       and migrations["dpi_auto"][1](True) == "auto"
       and migrations["dpi_auto"][1](False) == "off",
       "dpi_auto переносится в dpi_orch (auto/off)")
    ok(migrations.get("dpi_stop_after", ("", None))[0] == "dpi_after"
       and migrations["dpi_stop_after"][1](True) == "restore"
       and migrations["dpi_stop_after"][1](False) == "keep",
       "dpi_stop_after переносится в dpi_after (restore/keep)")
    # хвост прерванной загрузки: без записи восстанавливать нечего
    orch_file = dpi.orchestrator_path()
    try:
        dpi.forget()
        ok(dpi.pending_restore() is False, "без записи хвоста восстанавливать нечего")
        orch_file.write_text('{"kind": "none"}', encoding="utf-8")
        ok(dpi.pending_restore() is True, "запись на месте - хвост виден")
        dpi.forget()
        ok(dpi.pending_restore() is False, "forget убирает хвост")
    finally:
        dpi.forget()
    # диалог «обход нужен» живёт в главном окне и продолжает тот же запуск
    ok('id="bypass-overlay"' in main_html, "диалог обхода есть в главном окне")
    for key in ("sheet.dpi.prompt.title", "sheet.dpi.prompt.text",
                "sheet.dpi.prompt.on", "sheet.dpi.prompt.off"):
        ok(f'data-i18n="{key}"' in main_html, f"диалог использует {key}")
        ok(all(key in i18n.I18N.get(lang, {}) for lang in i18n.LANGUAGES),
           f"{key} переведён")
    ok("need_bypass" in app_js and "startJob" in app_js,
       "app.js после ответа продолжает тот же запуск")
    gui_src = (ROOT / "gui.py").read_text(encoding="utf-8")
    ok("need_bypass" in gui_src and "_need_bypass_dialog" in gui_src,
       "gui отдаёт need_bypass вместо старта в режиме «спрашивать»")
    ok("pending_restore" in gui_src, "старт возвращает хвост прерванной загрузки")
    # выбор обхода: селект вместо текстового пути, модал и загрузка версий
    _, dir_spec = settings_schema.field("dpi.dir")
    ok(dir_spec.get("in_panel") is False,
       "dpi_dir убран из панели (его место занял селект), но остаётся настройкой")
    _, install_spec = settings_schema.field("dpi.install")
    ok(install_spec.get("transient") and install_spec.get("value_source"),
       "выбор установки транзиентен и берёт значение из get_initial")
    settings_html = (ROOT / "ui_src" / "settings.html").read_text(encoding="utf-8")
    ok('id="bypass-dialog"' in settings_html, "модал «Выберите обход» есть в карточке")
    for dom in ("bypass-install-list", "bypass-release-list", "bypass-repo-row",
                "bypass-download-note", "bypass-dialog-close", "bypass-dialog-done",
                "bypass-dialog-add", "bypass-dialog-detect", "bypass-dialog-remove"):
        ok(f'id="{dom}"' in settings_html, f"в модале есть {dom}")
    for dom in ("bypass-install-list", "bypass-release-list", "bypass-repo-row",
                "bypass-download-note", "bypass-dialog-close", "bypass-dialog-done"):
        ok(dom in settings_js, f"settings.js знает про {dom}")
    for name in ("bypass_repos", "bypass_releases", "bypass_download"):
        ok(f"def {name}(" in gui_src, f"Api.{name} существует")
    # список репозиториев замкнут: наружу уходят только два разрешённых
    found = re.search(r"GH_REPOS = \(([^)]*)\)", gui_src)
    repos = re.findall(r'"([^"]+)"', found.group(1)) if found else []
    ok(repos == ["Flowseal/zapret-discord-youtube", "bol-van/zapret-win-bundle"],
       "разрешены ровно два репозитория", str(repos))
    # все ключи, которых касаются наши исходники, переведены во всех языках
    used = set()
    for rel in ("dpi.py", "gui.py", "download.py", "ui_src/settings.js",
                "ui_src/app.js", "ui_src/index.html", "ui_src/settings.html"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        used |= set(re.findall(r'["\'](sheet\.dpi\.[\w.]+)["\']', src))
        used |= set(re.findall(r'data-i18n="(sheet\.dpi\.[\w.]+)"', src))
    missing = {lang: sorted(k for k in used if k not in i18n.I18N.get(lang, {}))
               for lang in i18n.LANGUAGES}
    missing = {lang: ks for lang, ks in missing.items() if ks}
    ok(not missing, f"все {len(used)} ключей обхода переведены во всех языках",
       str(missing))
    # кнопки и общее пояснение обхода обязаны жить в actions settings.js
    for ident in ('"dpi-probe":', '"dpi-scan":', '"dpi-start":', '"dpi-stop":',
                  'getElementById("dpi-note")'):
        ok(ident in settings_js, f"settings.js использует {ident}")

    # 12. выгрузка на FTP: канал данных с возобновлением TLS-сессии
    section("12. выгрузка на FTP")
    ok(issubclass(ftp_mod._FtpTls, ftplib.FTP_TLS), "_FtpTls наследует FTP_TLS")
    ntc = inspect.getsource(ftp_mod._FtpTls.ntransfercmd)
    ok("session=self.sock.session" in ntc,
       "канал данных получает сессию управляющего (иначе 425 у FileZilla)")
    ok("ftplib.FTP.ntransfercmd(self" in ntc,
       "ntransfercmd вызывает базовый FTP, а не FTP_TLS (без зацикливания)")
    src_connect = inspect.getsource(ftp_mod.connect)
    ok("_FtpTls(" in src_connect and "ftplib.FTP_TLS(" not in src_connect,
       "connect() в режиме FTPS берёт подкласс, а не штатный FTP_TLS")
    # путь на сервере: {playlist} без плейлиста схлопывается в корень шаблона,
    # ".." и пустые сегменты выкидываются - выше базового каталога не уйти
    ok(ftp_mod.render_path("media/{playlist}", {"playlist": ""}) == "media",
       "{playlist} без плейлиста -> сегмент пропал, папка осталась",
       ftp_mod.render_path("media/{playlist}", {"playlist": ""}))
    ok(ftp_mod.render_path("media/{playlist}", {"playlist": "Мой плейлист"})
       == "media/Мой плейлист", "{playlist} с названием -> подпапка")
    ok(ftp_mod.render_path("../{playlist}", {"playlist": "x"}) == "x",
       ".. из пути выбрасывается", ftp_mod.render_path("../{playlist}", {"playlist": "x"}))

    # ensure_dir на фейковом сервере: абсолютные пути и возврат CWD - именно
    # из-за отсутствия возврата STOR «media/файл» уходил в /media/media/файл
    class _FakeFtp:
        def __init__(self, existing=(), denied=(), where="/"):
            self.existing = set(existing) | {"/"}   # корень есть всегда
            self.denied = set(denied)
            self.where = where
            self.cmds = []

        def pwd(self):
            return self.where

        def mkd(self, path):
            self.cmds.append(("MKD", path))
            if path in self.existing:
                raise ftplib.error_perm("550 Permission denied")   # уже есть
            if path in self.denied:
                raise ftplib.error_perm("550 Permission denied")
            self.existing.add(path)

        def cwd(self, path):
            self.cmds.append(("CWD", path))
            target = path if path.startswith("/") else f"{self.where.rstrip('/')}/{path}"
            if target not in self.existing:
                raise ftplib.error_perm("550 Failed to change directory.")
            self.where = target

    fake = _FakeFtp(existing={"/media"})
    ok(ftp_mod.ensure_dir(fake, "media/Мой плейлист") is True,
       "ensure_dir создаёт недостающие сегменты", str(fake.cmds))
    ok(("MKD", "/media") in fake.cmds and ("MKD", "/media/Мой плейлист") in fake.cmds,
       "MKD идёт абсолютными путями от исходного каталога", str(fake.cmds))
    ok(fake.where == "/", "CWD возвращён в исходный каталог (иначе media/media)",
       f"остались в {fake.where}")
    again = _FakeFtp(existing={"/media"})
    ok(ftp_mod.ensure_dir(again, "") is True and not again.cmds,
       "пустой путь - ни одной команды")
    denied = _FakeFtp(existing={"/media"}, denied={"/media/x"})
    ok(ftp_mod.ensure_dir(denied, "media/x") is False,
       "отказ сервера на втором сегменте -> False, без исключения")

    # 13. реестр установок обхода и вшитый пакет (работа без сети)
    section("13. реестр установок и вшитый обход")
    bundled = dpi._bundled_dir()
    archives = sorted(bundled.glob("*.zip")) if bundled.is_dir() else []
    ok(bool(archives), "в assets/bypass лежит вшитый пакет", str(bundled))
    license_file = bundled / "LICENSE-flowseal.txt"
    ok(license_file.is_file(),
       "рядом лежит MIT-лицензия (условие распространения пакета)",
       str(license_file))

    iso = Path(tempfile.mkdtemp(prefix="synf-bypass-"))
    old_local = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = str(iso)
    try:
        rep = dpi.seed_bundled_bypass()
        ok(not rep["failed"] and bool(rep["added"]),
           "вшитый пакет разложен в Synfronia\\Bypass", str(rep))
        reg = dpi.registry_load()
        ok(bool(reg["items"]) and reg["active"] in {i.get("id") for i in reg["items"]},
           "после распаковки установка зарегистрирована и активна", str(reg["active"]))
        installed = Path(reg["items"][0]["path"])
        ok(str(installed).startswith(str(iso)),
           "попали в изолированную Bypass, а не в рабочую", str(installed))
        scan = dpi.validate_install(installed)
        ok(scan["ok"] and scan["layout"] == dpi.LAYOUT_FLOWSEAL,
           "распакованная установка валидна (layout flowseal)", str(scan["issues"]))
        ok(len(scan["strategies"]) >= 20,
           f"найдено стратегий: {len(scan['strategies'])}", str(scan["strategies"][:3]))
        ok((installed / "LICENSE-flowseal.txt").is_file(),
           "лицензия скопирована внутрь установки")
        again = dpi.seed_bundled_bypass()
        ok(not again["added"], "повторный запуск ничего не дублирует", str(again))
        # автозаполнение: находит свои установки, но не отбирает активную
        fake_local = dpi.bypass_root() / "zapret-local"
        (fake_local / "bin").mkdir(parents=True, exist_ok=True)
        (fake_local / "bin" / "winws.exe").write_bytes(b"MZ")
        (fake_local / "general.bat").write_text("@echo off", encoding="ascii")
        auto = dpi.registry_autofill()
        ok(len(auto["added"]) >= 1, "автозаполнение находит чужую установку", str(auto))
        ok(dpi.registry_load()["active"] == reg["active"],
           "автозаполнение не отбирает активную установку", str(dpi.registry_load()["active"]))
        ok(dpi.registry_autofill()["added"] == [],
           "повторное автозаполнение идемпотентно")
        ok(settings.load_settings().get("dpi_dir") == str(installed),
           "dpi_dir зеркалит активную установку",
           str(settings.load_settings().get("dpi_dir")))

        # негативы: битую папку в реестр не берём
        empty_dir = iso / "not-a-bypass"
        empty_dir.mkdir()
        bad = dpi.registry_add(str(empty_dir))
        ok(bad.get("ok") is False and "winws" in bad.get("issues", []),
           "папка без winws.exe отклоняется с кодом issues", str(bad.get("issues")))
        ok(dpi.validate_install(str(iso / "no-such-dir"))["issues"] == ["folder"],
           "несуществующая папка -> код folder")
        ok(str(empty_dir) not in [i["path"] for i in dpi.registry_load()["items"]],
           "отклонённая папка не попала в реестр")

        # layout-б от другого автора: winws и preset-стратегии во вложенной папке
        bundle = iso / "zapret-win-bundle-master"
        (bundle / "zapret-winws").mkdir(parents=True)
        (bundle / "zapret-winws" / "winws.exe").write_bytes(b"MZ")
        (bundle / "zapret-winws" / "preset1.cmd").write_text("@echo off", encoding="ascii")
        (bundle / "zapret-winws" / "preset2.cmd").write_text("@echo off", encoding="ascii")
        b = dpi.validate_install(str(bundle))
        ok(b["ok"] and b["layout"] == dpi.LAYOUT_WINWS,
           "zapret-win-bundle опознан как layout winws", str(b))
        ok(b["strategies"] == ["zapret-winws/preset1.cmd", "zapret-winws/preset2.cmd"],
           "preset-стратегии идут относительными путями", str(b["strategies"]))
        ok(b["issues"] == [], "для layout winws папка lists не обязательна", str(b["issues"]))

        # zip-slip: архив, который лезет наружу, распаковывать нельзя
        evil = iso / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../evil.txt", "x")
            zf.writestr("ok/file.txt", "y")
        try:
            with zipfile.ZipFile(evil) as zf:
                dpi._extract_zip(zf, iso / "out")
            ok(False, "zip-slip отклонён")
        except ValueError:
            ok(True, "zip-slip отклонён (путь за пределы назначения)")

        # реестр: снятие активной установки переносит выбор, чужой id - отказ
        active = dpi.registry_load()["active"]
        ok(dpi.registry_remove(active).get("ok") is True, "активная установка снимается")
        after = dpi.registry_load()
        ok(after["active"] is None or after["active"] in {i.get("id") for i in after["items"]},
           "после снятия active всегда указывает на существующее", str(after["active"]))
        ok(dpi.registry_remove("no-such-id").get("ok") is False,
           "чужой id -> отказ, а не тихий успех")
        ok(dpi.registry_select("no-such-id").get("ok") is False,
           "выбор несуществующей установки -> отказ")
    finally:
        if old_local is not None:
            os.environ["LOCALAPPDATA"] = old_local
        shutil.rmtree(iso, ignore_errors=True)

    # ключи отказов переведены и используются из gui
    for code in ("folder", "winws", "strategies", "lists", "payload"):
        key = f"sheet.dpi.issue.{code}"
        ok(all(key in i18n.I18N.get(lang, {}) for lang in i18n.LANGUAGES),
           f"{key} есть во всех языках")
    gui_src = (ROOT / "gui.py").read_text(encoding="utf-8")
    ok("sheet.dpi.issue." in gui_src, "gui переводит коды отказов")
    for name in ("bypass_list", "bypass_validate", "bypass_detect", "bypass_add",
                 "bypass_select", "bypass_remove"):
        ok(f"def {name}(" in gui_src, f"Api.{name} существует")
    spec_src = (ROOT / "Synfronia.spec").read_text(encoding="utf-8")
    ok('"assets/bypass"' in spec_src, "пакет попадает в сборку (spec datas)")
    ok("registry_autofill" in gui_src, "старт ищет свои установки")
    ok("seed_bundled_bypass" in gui_src, "старт раскладывает вшитый пакет")

    print(f"\nитог: {_checks - len(_fails)}/{_checks} ok")
    if _fails:
        print("провалено: " + ", ".join(_fails))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
