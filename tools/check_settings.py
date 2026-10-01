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
     утекает в главное окно, а оно само не рисует настройки.

Запуск:  python tools/check_settings.py
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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
    "tip-pull", "tip-pull-range", "tip-repel", "tip-repel-range",
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
    ok(ids == ["ui", "dl", "ftp"], "вкладки в порядке ui, dl, ftp", str(ids))
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
    ok(len(flat_names) == 32, "в схеме 32 сохраняемые настройки", str(len(flat_names)))

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
    ok('id: "nav-" + group.id' in settings_js,
       "пункты списка строятся из групп схемы")
    ok('id: "section-" + group.id' in settings_js,
       "разделы строятся из групп схемы")
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

    print(f"\nитог: {_checks - len(_fails)}/{_checks} ok")
    if _fails:
        print("провалено: " + ", ".join(_fails))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
