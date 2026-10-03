"""Web-интерфейс (pywebview/EdgeChromium) для Synfronia. Модульные темы."""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque

import webview

import dpi
import settings_schema
from core import (
    Downloader,
    FtpConfig,
    available_transcoders,
    base_dir,
    build_page,
    default_download_dir,
    download_ffmpeg,
    download_test_fonts,
    find_ffmpeg,
    font_css,
    fonts_embed,
    is_playlist,
    load_fonts,
    load_languages,
    load_settings,
    load_themes,
    restore_builtin_themes,
    save_settings,
    seed_bundled_fonts,
    test_connection,
    themes_embed,
    tr,
)
from core import _file_log as file_log
from core import _fonts_root as fonts_root
from core import _themes_root as themes_root
from paths import crash_evidence, logs_dir, minidump_fault, newest_crash_dump, \
    webview_child_running

seed_bundled_fonts()   # вшитые шрифты в папку шрифтов: первый запуск работает без сети
load_languages()
load_fonts()   # раньше load_themes: темы проверяют font/font_mono по списку семейств
load_themes()
_settings = load_settings()
HTML = build_page(_settings.get("theme", "scarred_mind"))

# Сколько строк лога держим в памяти для JS. Буфер кольцевой: при переполнении
# самые старые строки вытесняются, а курсор log_cursor сообщает фронтенду, с
# какого места продолжать (см. Api.poll).
LOG_BUFFER = 2000

# Итог загрузки -> строка статуса. «Часть файлов» годится только для плейлиста,
# где что-то скачалось, а что-то нет; обрыв связи на одном видео - это
# «не удалось скачать», а «Готово» после ошибки постобработки - «были ошибки».
_STATUS_KEY = {
    "ok": "p.ready",
    "partial": "p.done_partial",
    "failed": "p.failed",
    "warn": "p.done_warn",
}

# Режим загрузки -> result из poll(), по которому app.js выбирает иконку.
# partial и warn делят знак «!», но подписи у них разные, а полный провал
# получает отдельный знак «✕».
_RESULT_MODE = {
    "ok": "ok",
    "partial": "error",
    "warn": "warn",
    "failed": "failed",
}


def _summary(dl) -> tuple[str, int, int]:
    """Итог загрузки от Downloader; без загрузчика считаем успехом."""
    return getattr(dl, "summary", None) or ("ok", 0, 0)


def _parse_bulk(text: str) -> tuple[list[str], int]:
    """Список ссылок из текста массовой вкладки: (urls, сколько пропущено).

    Правила (идентичны подсчёту на фронте): одна ссылка на строку, trim,
    пустые строки и «#» - комментарии пропускаются, принимается только
    http(s)://, дедуп с сохранением порядка ввода.
    """
    urls: list[str] = []
    seen: set[str] = set()
    skipped = 0
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if not s.lower().startswith(("http://", "https://")):
            skipped += 1
            continue
        if s not in seen:
            seen.add(s)
            urls.append(s)
    return urls, skipped


class Api:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.dl: Downloader | None = None
        self._transcoders: list[str] | None = None
        self._lock = threading.Lock()
        self._logs: deque[str] = deque(maxlen=LOG_BUFFER)
        self._log_total = 0
        self._lang = self.settings.get("language", "en")
        self._status = tr(self._lang, "p.ready")
        self._busy = False
        # итог прошлой загрузки для кнопки: None | "ok" | "error" | "cancelled"
        self._result: str | None = None
        self._cancel = False
        # массовая загрузка: None вне цикла, иначе счётчики для poll()
        self._bulk: dict | None = None
        # упавшие ссылки прошлой массовой загрузки — их подставляет кнопка
        # «Оставить неудавшиеся» (сбрасывается при следующем старте)
        self._bulk_failed: list[str] = []
        # финальные построчные статусы последней массовой — воркер гасит
        # _bulk (уходит в None) вместе с busy, без них окно не покажет итог:
        # строки в ожидании (отмена) не попадают в _bulk_failed и пришлось
        # бы красить их неудачей. Сбрасывается при следующем старте.
        self._bulk_statuses: list[str] = []
        self._progress = {"mode": "determinate", "value": 0.0}
        self._ffmpeg = {"downloading": False, "extracting": False, "pct": 0.0, "ok": False, "error": None}
        self._fonts_dl = {"downloading": False, "pct": 0.0, "error": None}
        self._fonts_rev = 0
        self._page_gen = 0
        # единственное окно приложения: главное, с карточкой настроек поверх
        self._win_main: webview.Window | None = None
        # открыта ли карточка настроек. Состояние живёт во фронтенде, но
        # Python помнит его, чтобы вернуть карточку после пересборки страницы
        # (тема со своим entry перезагружает всю страницу - см. set_theme)
        self._settings_open = False
        # папка загрузки - не настройка (см. settings_schema): помним её на
        # время сеанса, карточка настроек присылает значение через set_dest
        self._dest = ""
        # счётчик, по которому страница узнаёт о смене языка/темы/шрифтов
        self._ui_rev = 0
        # единственная очередь доставки в JS: evaluate_js в pywebview не
        # thread-safe (issue #906), поэтому пинги из любых потоков (лог,
        # воркеры загрузок) копятся в очереди, а исполняет их ровно один
        # диспетчерский поток - запускается в bind_main_window
        self._js_queue: queue.Queue = queue.Queue()
        self._js_thread: threading.Thread | None = None

    # -- окно -----------------------------------------------------------------
    def bind_main_window(self, win) -> None:
        """Запоминает окно главной страницы (его пересобирает set_theme).

        Здесь же стартует единственный диспетчер evaluate_js: раньше окна
        пинги копятся в очереди, первый же вызов доставит их всплеском.
        """
        self._win_main = win
        if not self._js_thread:
            self._js_thread = threading.Thread(
                target=self._js_dispatch, daemon=True, name="js-dispatch")
            self._js_thread.start()

    def synf_settings_state(self, is_open) -> None:
        """Фронтенд сообщает, открыта ли карточка настроек.

        Отдельного вызова "открыть/закрыть" больше нет: карточка - часть
        страницы, поэтому и состояние, и фокус живут в JS. Pythonу нужно
        только это значение, чтобы после пересборки страницы (тема со своим
        entry) вернуть карточку туда же, где она была.
        """
        self._settings_open = bool(is_open)

    def _bump_ui(self) -> None:
        """Отметить, что язык/тема/шрифты изменились: страница это подхватит."""
        with self._lock:
            self._ui_rev += 1
        self._ping()

    # -- push-канал: события + heartbeat -------------------------------------
    # Гибрид (этап 5 дорожной карты): события будят страницу немедленно
    # (вместо ожидания следующего heartbeat), а раз в секунду страница сама
    # тянет полный снапшот через опрос-heartbeat (app.js scheduleTick).
    # Каждое изменение состояния, которое должен увидеть UI, завершается
    # _ping() - уже ПОСЛЕ записи под self._lock, чтобы ответ poll() был
    # свежим. Всплески (бурст лога/прогресса) схлопываются диспетчером в
    # одно пробуждение.
    def _ping(self) -> None:
        """Состояние изменилось: разбудить страницу (см. _js_dispatch)."""
        self._js_queue.put("@ping")

    def _js_dispatch(self) -> None:
        """Единственный поток evaluate_js на всю сессию.

        pywebview не потокобезопасен (issue #906): одновременные вызовы из
        воркеров могут потеряться или упасть. Здесь же гасятся исключения -
        страница могла перезагружаться (set_theme -> load_html): потерянный
        пинг наверстает heartbeat, которому полный снапшот не нужен - новая
        страница сама стартует tick и тянет poll(0) с нуля.
        """
        while True:
            self._js_queue.get()   # ждём первое событие
            # всплеск событий -> одно пробуждение страницы
            while True:
                try:
                    self._js_queue.get_nowait()
                except queue.Empty:
                    break
            try:
                win = self._win_main or (webview.windows[0] if webview.windows else None)
                if win:
                    win.evaluate_js("window.__synfPing && window.__synfPing();")
            except Exception:  # noqa: BLE001 - окно закрыто или страница перезагружается
                pass

    def _ui_state(self) -> dict:
        """Общая часть ответа poll(): что страница должна синхронизировать."""
        return {
            "ui_rev": self._ui_rev,
            "lang": self._lang,
            "theme": self.settings.get("theme", "scarred_mind"),
        }

    # -- подмена страницы ----------------------------------------------------
    def _swap_page(self, html: str, delay: float = 0.35) -> None:
        """Заменяет страницу после того, как значение метода ушло в JS.

        pywebview после каждого вызова API дёргает evaluate_js, чтобы отдать
        результат промису из window.pywebview._returnValuesCallbacks. Если
        перезагрузить страницу до возврата, колбэк не найдётся и pywebview
        напишет в консоль JavascriptException. Поэтому подмену откладываем, а
        поколение гасит устаревшую задержку при быстрых повторных вызовах.
        """
        self._page_gen += 1
        gen = self._page_gen

        def worker() -> None:
            time.sleep(delay)
            if gen != self._page_gen:
                return
            win = self._win_main or (webview.windows[0] if webview.windows else None)
            if win:
                win.load_html(html)

        threading.Thread(target=worker, daemon=True, name="page-swap").start()

    # -- состояние (poll из JS) ----------------------------------------------
    def poll(self, since: int = 0) -> dict:
        with self._lock:
            lines = list(self._logs)
            # Кольцевой буфер: индексы «поехали», поэтому отдаём хвост от
            # max(since, oldest) и всегда сообщаем актуальный курсор.
            oldest = self._log_total - len(lines)
            start = max(since, oldest)
            state = {
                "busy": self._busy,
                "status": self._status,
                "result": self._result,
                "progress": dict(self._progress),
                "logs": lines[start - oldest:],
                "log_cursor": self._log_total,
                "ffmpeg": dict(self._ffmpeg),
                # свежий список кодировщиков (воркер докачки пересчитывает
                # _transcoders): после «Загрузить FFmpeg» карточка раскроет
                # их без перезапуска приложения
                "transcoders": list(self._transcoders) if self._transcoders else None,
                "fonts_dl": dict(self._fonts_dl),
                "fonts_rev": self._fonts_rev,
                # массовая: None вне цикла, иначе {total,index,done,failed}
                "bulk": dict(self._bulk) if self._bulk else None,
                # упавшие ссылки прошлой массовой (для «Оставить неудавшиеся»)
                "bulk_failed": list(self._bulk_failed),
                # финальные построчные статусы последней массовой: воркер уже
                # снёс _bulk (busy=false в том же тике), но окно держит список
                # с отметками ✓/✕ до «К списку ссылок»
                "bulk_statuses": list(self._bulk_statuses),
                # значения для карточки настроек: тот же словарь, что и на
                # диске, поэтому поля не могут разойтись с настройками, по
                # которым идёт загрузка
                "settings": dict(self.settings),
                **self._ui_state(),
            }
        return state

    def get_initial(self) -> dict:
        # стартовая проверка ffmpeg обязана отразиться и в poll: иначе
        # _ffmpeg["ok"] остаётся False до первой докачки и первый же тик
        # затирает верное значение из init - карточка показывала бы
        # «перекодировка недоступна» даже при установленном ffmpeg
        found = bool(find_ffmpeg())
        with self._lock:
            self._ffmpeg["ok"] = found
        if self._transcoders is None:
            self._transcoders = available_transcoders()
        return {
            "settings": dict(self.settings),
            "ffmpeg": found,
            "default_dir": self._dest or str(default_download_dir()),
            "transcoders": list(self._transcoders),
            "fonts": fonts_embed(),
            # карточка открыта? после пересборки страницы её надо вернуть
            "settings_open": self._settings_open,
        }

    # -- автоустановка ffmpeg -------------------------------------------------
    def start_ffmpeg_download(self) -> str:
        with self._lock:
            if self._ffmpeg["downloading"] or self._ffmpeg["extracting"]:
                return "busy"
            if find_ffmpeg():
                self._ffmpeg["ok"] = True
                return "already"
            self._ffmpeg["downloading"] = True
            self._ffmpeg["pct"] = 0.0
            self._ffmpeg["error"] = None
        self._log("info", tr(self._lang, "ffmpeg.download", pct="0"))
        threading.Thread(target=self._ffmpeg_worker, daemon=True, name="ffmpeg-dl").start()
        return "started"

    def _ffmpeg_worker(self) -> None:
        def on_progress(pct: float) -> None:
            with self._lock:
                self._ffmpeg["pct"] = pct
            self._ping()   # процент докачки ffmpeg - в кольцо прогресса

        try:
            path = download_ffmpeg(on_progress=on_progress, on_log=self._log)
        except Exception as exc:  # noqa: BLE001
            path = None
            self._log("error", str(exc))
        if path:
            self._transcoders = available_transcoders()
        with self._lock:
            self._ffmpeg["downloading"] = False
            if path:
                self._ffmpeg["ok"] = True
                self._ffmpeg["extracting"] = False
            else:
                self._ffmpeg["ok"] = False
                self._ffmpeg["error"] = tr(self._lang, "ffmpeg.error", exc="")
        self._ping()   # итог докачки (успех может пройти без строки лога)

    # -- настройки -----------------------------------------------------------
    def save_setting(self, key: str, value) -> str:
        if not settings_schema.has(key):
            return "unknown key"
        self.settings[key] = settings_schema.coerce(key, value)
        if key == "language":
            self._lang = str(self.settings[key])
            if not self._busy:
                self._status = tr(self._lang, "p.ready")
        try:
            save_settings(self.settings)
        except OSError as exc:
            return f"error: {exc}"
        # язык, тема и шрифты видны обоим окнам - сообщаем им обновление
        if key in ("language", "theme", "font_sans", "font_mono"):
            self._bump_ui()
        self._ping()   # настройка изменилась: render-предпочтения не ждут heartbeat
        return "ok"

    def set_dest(self, path: str) -> None:
        """Папка загрузки из карточки настроек (не сохраняется в settings.json)."""
        self._dest = str(path or "").strip()

    # -- темы (модульные) ----------------------------------------------------
    def set_theme(self, theme_id: str) -> str:
        """Сохраняет выбор темы и перезагружает страницу из собранного HTML.

        Используется для полноценных HTML-тем (entry); css-only темы
        переключаются в JS мгновенно через applyTheme() + save_setting.
        Отдельной страницы у настроек больше нет, поэтому пересобирается одна
        страница, а открытость карточки настроек возвращается через
        get_initial -> settings_open.
        """
        if theme_id not in themes_embed():
            return "unknown theme"
        self.settings["theme"] = theme_id
        try:
            save_settings(self.settings)
        except OSError as exc:
            return f"error: {exc}"
        self._bump_ui()
        self._swap_page(build_page(theme_id))
        return "ok"

    def reload_themes(self) -> dict:
        """Пересканирует папку тем и возвращает обновлённый список тем."""
        load_themes()
        self._bump_ui()
        return themes_embed()

    def download_themes(self) -> dict:
        """Дописывает недостающие встроенные темы (кнопка «Докачать темы»).

        Темы вшиты в themes.py, поэтому интернет не нужен: на диск попадают
        только те файлы, которых ещё нет. Перезаписывать нечего - если тему
        правили вручную, она останется как есть. Состав папки меняется, так
        что заодно перечитываем её (load_themes) и поднимаем ui_rev, чтобы
        список тем в карточке обновился.
        """
        result = restore_builtin_themes(on_log=self._log)
        if result["added"]:
            load_themes()
            self._bump_ui()
        return result

    def open_themes_folder(self) -> None:
        """Открывает папку тем в Проводнике."""
        try:
            subprocess.Popen(["explorer", str(themes_root())])
        except OSError:
            pass

    # -- шрифты (модульные, %LOCALAPPDATA%\Synfronia\fonts) --------------------
    def _font_css_now(self) -> str:
        """@font-face для шрифтов, действующих прямо сейчас.

        Тема может переопределить font/font_mono (см. themes.build_page), поэтому
        встраиваем именно её — иначе после смены шрифта интерфейс молча
        откатился бы на системный.
        """
        theme = (themes_embed() or {}).get(self.settings.get("theme", "scarred_mind")) or {}
        # все семейства, а не только выбранные: подсказки опций шрифтов
        # набираются самим шрифтом (см. themes._fill_placeholders)
        return font_css(list(dict.fromkeys(
            [theme.get("font") or self.settings.get("font_sans") or "",
             theme.get("font_mono") or self.settings.get("font_mono") or "",
             self.settings.get("font_heading") or ""]
            + list((load_fonts() or {}).keys()))))

    def font_face_css(self, families) -> str:
        """@font-face для произвольных семейств.

        Нужен, когда @font-face применяется без перезагрузки страницы: JS
        подменяет содержимое <style id="fonts-style">. Лимит на объём
        встраиваемых данных (fonts.MAX_TOTAL_BYTES) действует и здесь.
        """
        if isinstance(families, str):
            families = [families]
        return font_css(list(dict.fromkeys(
            [str(f or "") for f in (families or [])]
            + list((load_fonts() or {}).keys()))))

    def set_font(self, key: str, value: str) -> dict:
        """Сохраняет выбранный шрифт и отдаёт @font-face для активной темы.

        Страница не перезагружается: JS подменяет блок #fonts-style, поэтому
        выбор шрифта не сбрасывает состояние интерфейса.
        """
        if key not in ("font_sans", "font_mono", "font_heading"):
            return {"error": "unknown key"}
        self.settings[key] = str(value or "")
        try:
            save_settings(self.settings)
        except OSError as exc:
            return {"error": f"error: {exc}"}
        self._bump_ui()
        return {"css": self._font_css_now()}

    def reload_fonts(self) -> dict:
        """Пересканивает папку шрифтов: новый список и @font-face для JS."""
        load_fonts()
        return {"fonts": fonts_embed(), "css": self._font_css_now()}

    def download_fonts(self) -> str:
        """Докачивает тестовые шрифты из сети (кнопка «Докачать шрифты»).

        Шрифты вшиты в сборку, поэтому сеть здесь — запасной путь. Возвращает
        "started" / "busy"; итог приходит в лог и подхватывается по fonts_rev.
        """
        with self._lock:
            if self._fonts_dl["downloading"]:
                return "busy"
            self._fonts_dl.update({"downloading": True, "pct": 0.0, "error": None})
        self._ping()   # окно докачки шрифтов открывается сразу
        threading.Thread(target=self._fonts_worker, daemon=True, name="fonts-dl").start()
        return "started"

    def _fonts_worker(self) -> None:
        def on_progress(done: int, total: int) -> None:
            with self._lock:
                self._fonts_dl["pct"] = done / max(total, 1) * 100.0
            self._ping()   # процент докачки шрифтов

        try:
            result = download_test_fonts(on_log=self._log, on_progress=on_progress)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._fonts_dl.update({"downloading": False, "error": str(exc)})
            self._log("error", tr(self._lang, "font.dl.fail", names=str(exc)))
            return
        with self._lock:
            self._fonts_dl.update({"downloading": False, "pct": 100.0})
        self._ping()   # итог без строки лога (ничего не добавилось - тоже ответ)
        if result["added"]:
            self._log("info", tr(self._lang, "font.dl.done", names=", ".join(result["added"])))
            # счётчик растёт — JS сам перерисует списки шрифтов
            with self._lock:
                self._fonts_rev += 1
        elif result["skipped"] and not result["failed"]:
            self._log("info", tr(self._lang, "font.dl.skip"))
        if result["failed"]:
            self._log("error", tr(self._lang, "font.dl.fail", names=", ".join(result["failed"])))

    def open_fonts_folder(self) -> None:
        """Создаёт папку шрифтов при необходимости и открывает её в Проводнике."""
        folder = fonts_root()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        try:
            subprocess.Popen(["explorer", str(folder)])
        except OSError:
            pass

    # -- диалог папки --------------------------------------------------------
    def browse_folder(self):
        """Выбор папки загрузки. Отдельного окна настроек больше нет, поэтому
        диалог открывает то же окно, в котором лежит карточка."""
        win = self._win_main or (webview.windows[0] if webview.windows else None)
        if not win:
            return None
        result = win.create_file_dialog(webview.FOLDER_DIALOG)
        return str(result[0]) if result else None

    # -- загрузка ------------------------------------------------------------
    def start_download(self, cfg: dict) -> dict:
        """Запускает загрузку.

        Из окна приходят только ссылка и режим: папка, субтитры, качество,
        кодек и параметры сети берутся из настроек здесь, поэтому главное окно
        и окно настроек не могут показать разные значения.
        """
        url = (cfg.get("url") or "").strip()
        dest = self._dest or str(default_download_dir())
        if not url:
            return {"error": tr(self._lang, "p.enter_url")}
        playlist = bool(cfg.get("playlist"))
        if not playlist and is_playlist(url):
            self._log("warning", tr(self._lang, "p.playlist_warn"))
        subtitles = str(settings_schema.value(self.settings, "dl.subtitles") or "en")
        quality = str(settings_schema.value(self.settings, "dl.quality") or "lossless")
        transcode = str(settings_schema.value(self.settings, "dl.transcode") or "none")
        with self._lock:
            self._busy = True
            self._result = None
            self._cancel = False
            self._status = tr(self._lang, "p.start")
            self._progress = {"mode": "indeterminate"}
        self._ping()   # busy-переход виден сразу, не через heartbeat
        self.dl = Downloader(on_log=self._log, on_progress=self._on_progress, lang=self._lang)
        ftp = FtpConfig(self.settings, self._lang)
        threading.Thread(
            target=lambda: self._run(url, dest, playlist,
                                     bool(cfg.get("group", True)),
                                     subtitles, quality, transcode, ftp),
            daemon=True,
            name="yt-dlp",
        ).start()
        return {}

    def start_bulk(self, cfg: dict) -> dict:
        """Массовая загрузка: список ссылок, каждая - отдельным запуском.

        Текст из textarea парсится здесь (см. _parse_bulk): фронтенд считает
        счётчик теми же правилами, но источник истины - Python. Каждая ссылка
        идёт своим запуском yt-dlp: упавшая не прерывает остальные, повторы
        и постпроцессоры (включая FTP) работают как в одиночной загрузке.
        """
        urls, skipped = _parse_bulk(cfg.get("urls") or "")
        if skipped:
            self._log("warning", tr(self._lang, "p.bulk_skip", n=skipped))
        if not urls:
            return {"error": tr(self._lang, "status.enter.bulk")}
        dest = self._dest or str(default_download_dir())
        subtitles = str(settings_schema.value(self.settings, "dl.subtitles") or "en")
        quality = str(settings_schema.value(self.settings, "dl.quality") or "lossless")
        transcode = str(settings_schema.value(self.settings, "dl.transcode") or "none")
        with self._lock:
            self._busy = True
            self._result = None
            self._cancel = False
            self._status = tr(self._lang, "p.start")
            self._progress = {"mode": "indeterminate"}
            self._bulk = {"total": len(urls), "index": 0,
                          "done": 0, "failed": 0, "current": "",
                          # построчные состояния для подсветки в окне:
                          # p=endings(ожидают), l= качается, o=ok, f=fail
                          "statuses": ["p"] * len(urls)}
            self._bulk_failed = []
            self._bulk_statuses = []
        self._ping()   # busy-переход виден сразу, не через heartbeat
        self.dl = Downloader(on_log=self._log, on_progress=self._on_progress, lang=self._lang)
        ftp = FtpConfig(self.settings, self._lang)
        threading.Thread(
            target=lambda: self._run_bulk(urls, dest, bool(cfg.get("group", True)),
                                          subtitles, quality, transcode, ftp),
            daemon=True,
            name="yt-dlp-bulk",
        ).start()
        return {}

    def _run(self, url, dest, playlist, group, subtitles, quality, transcode, ftp=None) -> None:
        crashed = False
        bypass = self._bypass_begin()
        try:
            self.dl.download(
                url,
                dest,
                playlist=playlist,
                group=group,
                subtitles=subtitles,
                quality=quality,
                transcode=transcode,
                ftp=ftp,
            )
        except Exception as exc:  # noqa: BLE001
            crashed = True   # сбой не дошёл до Downloader.failed - итог «ошибка»
            self._log("error", str(exc))
        finally:
            # yt-dlp после запроса остановки ещё какое-то время дорабатывает
            # файл, а Downloader чистит _stop в своём finally, поэтому итог
            # отмены берём из флага, выставленного stop_download()
            cancelled = self._cancel or bool(self.dl and self.dl.stopped)
            # Строка статуса отвечает на вопрос «что не так», а не «были ли
            # ошибки»: обрыв связи на одном видео - это «не удалось скачать»,
            # а не «часть файлов не скачалась».
            mode, got, all_got = ("failed", 0, 0) if crashed else _summary(self.dl)
            # Иконке кнопки тоже нужно различать исходы: «!» у «скачано не всё»
            # и у «были ошибки» - разные ситуации, а «✕» означает, что не
            # скачалось ничего. Отдельный result у каждого режима, а не общий
            # error на любое наличие ошибок в логе. Режим «ok» недостижим при
            # ошибках (его ставит ветка «не было ошибок»), так что сверяться
            # с dl.failed здесь не нужно.
            with self._lock:
                self._busy = False
                self._result = "cancelled" if cancelled else _RESULT_MODE.get(mode, "ok")
                if cancelled:
                    self._status = tr(self._lang, "p.cancelled")
                else:
                    key = _STATUS_KEY.get(mode, "p.ready")
                    self._status = tr(self._lang, key, ok=got, total=all_got)
                self._progress = {"mode": "determinate", "value": 100.0}
            # обход гасим сразу после окончания - итоговая строка и подсветка
            # кнопки не должны ждать taskkill
            self._bypass_end(bypass)
        # итог загрузки (busy -> result/status) - будим сразу: кнопка и
        # статус не должны ждать heartbeat
        self._ping()

    def _run_bulk(self, urls, dest, group, subtitles, quality, transcode, ftp=None) -> None:
        """Воркер массовой загрузки: последовательно, по ссылке на запуск.

        Ошибки ссылки не прерывают цикл: итог считается по каждой, детали - в
        журнале (строки «bulk [i/N]»). Остановка (stop_download) гасит цикл на
        текущей ссылке и не берёт остаток очереди.
        """
        total = len(urls)
        done = failed = 0
        cancelled = False
        bypass = self._bypass_begin()
        try:
            for i, url in enumerate(urls, 1):
                with self._lock:
                    if self._cancel:
                        cancelled = True
                        break
                    self._bulk["index"] = i
                    self._bulk["current"] = url
                    self._bulk["statuses"][i - 1] = "l"
                    self._status = f"[{i}/{total}] {url}"
                    self._progress = {"mode": "indeterminate"}
                self._log("info", f"bulk [{i}/{total}] {url}")
                try:
                    self.dl.download(url, dest, playlist=is_playlist(url),
                                     group=group, subtitles=subtitles,
                                     quality=quality, transcode=transcode, ftp=ftp)
                except Exception as exc:  # noqa: BLE001
                    # упавшая ссылка не должна останавливать остальные
                    self._log("error", str(exc))
                if self._cancel or (self.dl and self.dl.stopped):
                    cancelled = True
                    break
                mode, _got, _all = _summary(self.dl)
                if mode == "ok":
                    done += 1
                else:
                    failed += 1
                with self._lock:
                    self._bulk["done"] = done
                    self._bulk["failed"] = failed
                    self._bulk["statuses"][i - 1] = "o" if mode == "ok" else "f"
                self._ping()   # построчные отметки массовой
        finally:
            with self._lock:
                cancelled = cancelled or self._cancel
                self._busy = False
                # упавшие ссылки переживают конец цикла (bulk уходит в None):
                # их подставит кнопка «Оставить неудавшиеся»
                if self._bulk:
                    self._bulk_failed = [u for u, s in
                                         zip(urls, self._bulk["statuses"])
                                         if s == "f"]
                    # итоговый роспись строк тоже переживает гашение bulk:
                    # окно держит список с отметками до «К списку ссылок»
                    self._bulk_statuses = list(self._bulk["statuses"])
                self._bulk = None
                self._progress = {"mode": "determinate", "value": 100.0}
                if cancelled:
                    self._result = "cancelled"
                    self._status = tr(self._lang, "p.cancelled")
                elif failed == 0:
                    self._result = "ok"
                    self._status = tr(self._lang, "p.done.playlist",
                                      n=done, dest=os.path.basename(dest))
                elif done == 0:
                    self._result = _RESULT_MODE.get("failed", "failed")
                    self._status = tr(self._lang, "p.failed")
                else:
                    self._result = _RESULT_MODE.get("partial", "warn")
                    self._status = tr(self._lang, "p.done_partial",
                                      ok=done, total=total)
            self._bypass_end(bypass)
        # итог массовой: busy, result, финальные статусы строк
        self._ping()

    def _bypass_begin(self):
        """Поднимает обход перед загрузкой, если он нужен. Конфиг или None.

        Порядок, как в инструкции: сначала проверяем доступ к YouTube, при
        закрытом маршруте пробуем сохранённую стратегию, а если и она не
        открывает - прогоняем все стратегии и берём ту, где соединение
        лучше (см. dpi.auto). Обход включается только при включённом
        флажке dpi_auto. Любая ошибка здесь не должна ронять загрузку:
        исключения глушим с записью в журнал, дальше идём как есть
        (с закрытым маршрутом yt-dlp сам скажет).
        """
        cfg = dpi.DpiConfig(self.settings, self._lang)
        if not cfg.auto:   # без флажка маршрут даже не проверяем
            return None
        try:
            res = dpi.auto(cfg, log=self._log)
        except Exception as exc:  # noqa: BLE001 - обход не должен ломать загрузку
            self._log("error", str(exc))
            return None
        if not res.get("ok"):
            self._log("error", res.get("error") or tr(self._lang, "sheet.dpi.start_fail"))
            return None
        # started=False - доступ был и без нас: гасить в конце нечего
        return cfg if res.get("started") else None

    def _bypass_end(self, cfg) -> None:
        """Гасит обход, если поднимали сами и настройки об этом просят."""
        if not cfg:
            return
        try:
            dpi.stop(cfg, log=self._log)
        except Exception as exc:  # noqa: BLE001 - итог загрузки не должен упасть
            self._log("warning", str(exc))

    def dpi_probe(self) -> dict:
        """Проверка маршрута по кнопке: YouTube отвечает или нет."""
        return {"ok": True, "reachable": dpi.probe()}

    def dpi_start(self) -> dict:
        """Запуск обхода по кнопке из карточки настроек."""
        cfg = dpi.DpiConfig(self.settings, self._lang)
        return dpi.start(cfg, log=self._log)

    def dpi_scan(self) -> dict:
        """Подбор рабочей стратегии по кнопке: полный перебор, одна UAC."""
        cfg = dpi.DpiConfig(self.settings, self._lang)
        return dpi.scan(cfg, log=self._log)

    def dpi_stop(self) -> dict:
        """Остановка обхода по кнопке из карточки настроек."""
        cfg = dpi.DpiConfig(self.settings, self._lang)
        return dpi.stop(cfg, log=self._log)

    def test_ftp(self) -> dict:
        """Проверка настроек FTP: подключается и сразу отключается."""
        cfg = FtpConfig(self.settings, self._lang)
        if not cfg.host:
            return {"error": tr(self._lang, "ftp.no_host")}
        if test_connection(cfg, log=self._log):
            return {"ok": True, "host": cfg.describe()}
        return {"error": tr(self._lang, "sheet.ftp.test_fail")}

    def stop_download(self) -> None:
        if self.dl:
            self._log("warning", tr(self._lang, "p.stop_req"))
            # итог выставит _run: yt-dlp ещё какое-то время дорабатывает файл
            # после запроса остановки, поэтому "cancelled" рано. Статус
            # меняем сразу - клик «Отмена» обязан быть виден мгновенно,
            # иначе выглядит так, будто его проигнорировали.
            with self._lock:
                self._cancel = True
                self._status = tr(self._lang, "p.stop_req")
            self._ping()   # клик «Отмена» виден мгновенно (лог уже добавил свой)
            self.dl.stop()

    # -- коллбеки от core ----------------------------------------------------
    def _log(self, level: str, msg: str) -> None:
        file_log(level, msg)
        with self._lock:
            self._logs.append(f"[{level}] {msg}")
            self._log_total += 1
        self._ping()

    def _on_progress(self, d: dict) -> None:
        status = d.get("status")
        with self._lock:
            # после «Отмены» статус не перетираем: «Запрошена остановка»
            # должна стоять до самого итога, иначе очередная строка прогресса
            # снова покажет «качается» и клик будет выглядеть проигнорированным
            if self._cancel:
                return
            # во время массовой каждая строка статуса знает свой номер
            prefix = ""
            if self._bulk and self._bulk.get("index"):
                prefix = f"[{self._bulk['index']}/{self._bulk['total']}] "
            if status == "downloading":
                percent = d.get("percent")
                name = d.get("filename") or ""
                if percent is None:
                    self._status = f"{prefix}{name} · {tr(self._lang, 'p.going')}"
                    self._progress = {"mode": "indeterminate"}
                else:
                    self._progress = {"mode": "determinate", "value": percent}
                    bits = f"{percent:.0f}%"
                    spd = f"{d['speed'] / 1024 / 1024:.1f} {tr(self._lang, 'p.mbps')}" if d.get("speed") else ""
                    eta = (f" {tr(self._lang, 'p.eta_prefix')} {int(d['eta'])}{tr(self._lang, 'p.eta_sec')}"
                           if d.get("eta") else "")
                    self._status = f"{prefix}{name} · {bits}{(' | ' + spd) if spd else ''}{eta}"
            elif status == "postprocessing":
                self._status = d.get("msg") or tr(self._lang, "p.post")
                self._progress = {"mode": "indeterminate"}
            elif status == "done":
                self._progress = {"mode": "determinate", "value": 100.0}
        # статус/прогресс записаны - будим страницу (после _cancel-выхода
        # состояние не менялось, пинг там не нужен)
        self._ping()


# -- надзор WebView2 ------------------------------------------------------------
# Окно pywebview создаётся ДО WebView2 и переживает его краш: при мёртвом
# потомке страница не отрисуется, пользователь увидит тёмное окно («зависло»).
# Логика ниже вынесена из main() целиком, чтобы проверка гоняла её без окна
# и без реальных пауз (tools/check_webview_guard.py).

def apply_render_env(settings: dict) -> None:
    r"""--disable-gpu для WebView2 по ручке «Аппаратное ускорение».

    Ручка читается до старта WebView2 (см. панель «Рендеринг»), поэтому
    вступает в силу только со следующего запуска. SYNFRONIA_WEBVIEW_GPU=1 -
    форс-возврат на GPU для одного запуска (отладка). Повторы после краша
    (см. dead_action) флагов не добавляют: эксперимент 01.10.2026 показал,
    что --disable-gpu не спасает от падения в чужом хуке, а картинку лишь
    деградирует.
    """
    if os.environ.get("SYNFRONIA_WEBVIEW_GPU") == "1":
        return
    if not settings_schema.value(settings, "render_gpu"):
        current = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
        if "--disable-gpu" not in current:
            os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = \
                (current + " --disable-gpu").strip()


# Сколько раз подряд перезапускать окно после краша WebView2. Падение
# интермиттирующее (эксперимент 01.10: ~15% запусков при живом RTSS, всегда
# в одной точке чужого хука), поэтому лечится повтором, а не флагами:
# три попытки дают ~0.3% невосстановления при той же вероятности.
MAX_ATTEMPTS = 3


def dead_action(busy: bool, attempt: int, max_attempts: int = MAX_ATTEMPTS) -> str:
    """Решение при пойманном мёртвом WebView2: "restart" либо причина отказа.

    attempt - номер текущей попытки (1 = обычный запуск; берётся из
    SYNFRONIA_WEBVIEW_ATTEMPT, см. _restart_attempt).
    """
    if busy:
        # страница мертва, но фоновая загрузка идёт - не убиваем работу
        return "busy"
    if attempt >= max_attempts:
        # петля из повторов не лечится - честно сообщаем (след уже записан)
        return "give-up"
    return "restart"


# Внедрённые сторонними программами DLL, из-за которых падал WebView2
# (разборы дампов 01.10.2026: все краши - в RTSSHooks64.dll RivaTuner).
_KNOWN_INJECTORS = {
    "RTSSHooks64.dll": "RivaTuner Statistics Server / MSI Afterburner",
    "RTSSHooks.dll": "RivaTuner Statistics Server / MSI Afterburner",
    "nviewh64.dll": "NVIDIA nView",
}


def crash_hint(module) -> str:
    """Подсказка по модулю падения: '' если модуль неизвестен или не наш.

    Если виновата внедрённая чужая DLL - говорим прямо: это сторонний код,
    падение не детерминировано и обычно лечится перезапуском (наш повтор),
    либо закрытием той программы на время работы.
    """
    if not module:
        return ""
    base = str(module).replace("\\", "/").rsplit("/", 1)[-1]
    owner = _KNOWN_INJECTORS.get(base)
    if not owner:
        return ""
    return (f"виноват внедрённый хук {owner} ({base}) - сторонний код, "
            "а не приложение: обычно помогает перезапуск (сторож делает это "
            "сам), либо закрыть эту программу на время работы Synfronia")


def guard_webview(alive, closing, on_dead, *, sleep=time.sleep, tick=0.5,
                  spawn_timeout=20.0, misses_needed=3) -> str:
    r"""Надзор живости WebView2 на всю сессию. Возвращает "dead" или "closed".

    alive()   - есть ли дочерний msedgewebview2 (paths.webview_child_running);
    closing() - окно закрывают: обычный выход, надзор молчит;
    on_dead() - поймали «тёмное окно» (штатно - с причиной: "crashed" или
                "never-spawned").

    Пока потомка ни разу не видели, ждём spawn_timeout - создание процесса
    WebView2 не мгновенно. Как только видели: три промаха подряд = краш. Это
    тот самый дыра старого сторожа, который проверял одного раз и выходил:
    в инциденте 01.10.2026 браузерный процесс упал через 5 с после показа
    окна, и за пределами первой проверки надзора уже не было.
    """
    spawn_left = max(1, int(spawn_timeout / tick))
    seen = False
    misses = 0
    while not closing():
        if alive():
            seen = True
            misses = 0
        elif seen:
            misses += 1
            if misses >= misses_needed:
                on_dead("crashed")
                return "dead"
        else:
            spawn_left -= 1
            if spawn_left <= 0:
                on_dead("never-spawned")
                return "dead"
        sleep(tick)
    return "closed"


def main() -> None:
    apply_render_env(_settings)
    api = Api()
    api.bind_main_window(webview.create_window(
        "Synfronia",
        html=HTML,
        js_api=api,
        width=980,
        height=780,
        min_size=(780, 560),
        background_color="#0c1622",
    ))

    # Сторож старта: WebView2 создаётся без дефолтного таймаута - если loader
    # завис, окно не появится вообще («тёмный экран»), а процесс будет жив.
    # Через 20 с без окна пишем след в gui_diag.log и stderr (в logs\launcher.log,
    # если запуск шёл из debug.py).
    def _report_start_problem(msg: str) -> None:
        line = (f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] сторож: {msg} "
                "(см. python gui.py --diagnose-freeze)")
        print(line, file=sys.stderr, flush=True)
        try:
            with open(base_dir() / "gui_diag.log", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"{msg}\n\nЗакройте окно и запустите приложение заново.",
                "Synfronia",
                0x30,   # MB_ICONWARNING
            )
        except Exception:  # noqa: BLE001
            pass

    def _attempt_no() -> int:
        """Номер текущей попытки старта (1 = обычный запуск)."""
        try:
            return max(1, int(os.environ.get("SYNFRONIA_WEBVIEW_ATTEMPT", "1")))
        except ValueError:
            return 1

    def _webview_dead(reason: str) -> None:
        # след для разбора: дамп Crashpad с модулем падения + GPU-события часа
        evidence = crash_evidence()
        attempt = _attempt_no()
        line = (f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] сторож: WebView2 мёртв "
                f"({reason}), попытка {attempt}/{MAX_ATTEMPTS}, окно показано; "
                f"{evidence}")
        print(line, file=sys.stderr, flush=True)
        try:
            with open(base_dir() / "gui_diag.log", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
        action = dead_action(busy=bool(api._busy), attempt=attempt)
        if action == "restart":
            _restart_attempt(attempt + 1)
        elif action == "busy":
            _report_start_problem(
                "WebView2 упал во время загрузки - дождитесь её окончания "
                "(журнал пишется в logs) и перезапустите приложение")
        else:
            # петля повторов не помогла - называем модуль падения
            fault = minidump_fault(newest_crash_dump()) or {}
            hint = crash_hint(fault.get("module"))
            msg = f"WebView2 упал {MAX_ATTEMPTS} раза подряд - {evidence}"
            if hint:
                msg += f". {hint[0].upper()}{hint[1:]}"
            _report_start_problem(msg)

    def _restart_attempt(next_no: int) -> None:
        """Перезапуск окна с номером попытки next_no (ребёнок получает
        SYNFRONIA_WEBVIEW_ATTEMPT=next_no).

        Окно уже мёртвое (страница не отрисуется), поэтому важнее свежее окно;
        сам процесс уходит сразу - иначе тёмное окно останется поверх нового.
        Сон перед уходом даёт умирающему WebView2 отдать профиль
        (SingletonLock) - иначе ребёнок стартует на горячем профиле.
        """
        env = dict(os.environ)
        env["SYNFRONIA_WEBVIEW_ATTEMPT"] = str(next_no)
        cmd = [sys.executable]
        if not getattr(sys, "frozen", False):
            cmd.append(str(base_dir() / "gui.py"))
        try:
            subprocess.Popen(
                cmd, cwd=str(base_dir()), env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            _report_start_problem(f"перезапустить окно не вышло ({exc})")
            return
        time.sleep(2.0)   # дать умирающему WebView2 освободить профиль
        os._exit(0)

    def _guard() -> None:
        win = webview.windows[-1] if webview.windows else None
        if win is None:
            # окно не создавалось - так бывает в тестах с подменённым webview
            return
        if not win.events.shown.wait(20):
            _report_start_problem("окно не появилось за 20 с - WebView2 завис при старте")
            return
        # Окно показано - и надзор больше не выходит: WebView2 мог упасть в
        # любой момент (в инциденте - через 5 с), а окно переживает краш.
        # Выход пользователя из приложения надзор не трогает (closing()).
        guard_webview(
            alive=lambda: webview_child_running(os.getpid()),
            closing=lambda: (win.events.closing.is_set()
                             or win.events.closed.is_set()),
            on_dead=_webview_dead,
        )

    threading.Thread(target=_guard, daemon=True, name="start-guard").start()
    # storage_path: pywebview по умолчанию (private_mode=True) кладёт WebView2
    # в tempfile.TemporaryDirectory() - после taskkill каталоги копились в
    # %TEMP% (35 штук). Всё содержимое приложения живёт в %LOCALAPPDATA%\Synfronia.
    webview.start(storage_path=str(logs_dir().parent / "webview"))


def diagnose_freeze() -> None:
    import io
    import time
    import traceback

    lines: list[str] = []
    t0 = time.time()

    def step(name: str) -> None:
        lines.append(f"[{time.time() - t0:6.2f}s] {name}")
        with open("gui_diag.log", "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    step(f"start frozen={hasattr(sys, '_MEIPASS')}")
    try:
        import webview.platforms.edgechromium as ec  # noqa: PLC0415

        step("edgechromium import ok")
    except Exception:
        step("edgechromium import FAILED")
        traceback.print_exc(file=sys.stdout)
    try:
        step("before import clr")
        import clr  # noqa: PLC0415

        step("after import clr")
        import clr_loader  # noqa: PLC0415

        step("clr_loader ok")
    except Exception:
        step("clr/clr_loader FAILED")
        traceback.print_exc(file=sys.stdout)
    try:
        step("before AddReference(WebView2.WinForms)")
        clr.AddReference("Microsoft.Web.WebView2.WinForms")
        step("AddReference(WebView2.WinForms) ok")
        from webview.util import interop_dll_path  # noqa: PLC0415

        step(f"interop dll: {interop_dll_path('Microsoft.Web.WebView2.Core.dll')}")
        clr.AddReference(interop_dll_path("Microsoft.Web.WebView2.Core.dll"))
        step("AddReference(Core.dll) ok")
    except Exception:
        step("WebView2 AddReference FAILED")
        traceback.print_exc(file=sys.stdout)
    step("diagnose done")


if __name__ == "__main__":
    if "--diagnose-freeze" in sys.argv:
        diagnose_freeze()
        sys.exit(0)
    if "--selftest" in sys.argv:
        from core import Downloader  # noqa: PLC0415

        dest = sys.argv[2] if len(sys.argv) > 2 else "downloads_selftest"
        url = sys.argv[3] if len(sys.argv) > 3 else "https://youtu.be/GUS0q7gZdNE"
        subtitles = "en"
        quality = "lossless"
        transcode = "none"
        for opt in sys.argv[4:]:
            if opt.startswith("--subtitles="):
                subtitles = opt.split("=", 1)[1]
            elif opt.startswith("--quality="):
                quality = opt.split("=", 1)[1]
            elif opt.startswith("--transcode="):
                transcode = opt.split("=", 1)[1]
            elif opt == "--hevc":
                transcode = "libx265"
        with open(base_dir() / "selftest.log", "w", encoding="utf-8") as f:
            dl = Downloader(on_log=lambda lvl, msg: f.write(f"[{lvl}] {msg}\n"))
            dl.download(url, dest, subtitles=subtitles, quality=quality, transcode=transcode)
        print("selftest done")
        sys.exit(0)

    main()