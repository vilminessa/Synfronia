r"""Выгрузка готовых файлов на FTP/FTPS.

Модуль самодостаточный: разбор настроек, безопасные шаблоны имён, подключение
с TLS, создание каталогов, загрузка и (по желанию) удаление локальных файлов.
Сеть проверяется на живых загрузках, поэтому ошибки не поднимаются наружу как
исключения: вызывающий получает отчёт и читает журнал.

Настройки модуля описаны в SETTINGS в конце файла: оттуда берутся и панель
настроек, и значения по умолчанию. Плоские имена в settings.json - те же,
что и раньше: ftp_active, ftp_host, ftp_port, ftp_user, ftp_password,
ftp_tls, ftp_tls_verify, ftp_pasv, ftp_dir, ftp_template, ftp_delete_local,
ftp_timeout, ftp_retries.
"""

import ftplib
import os
import re
import ssl
import time
from datetime import datetime
from pathlib import Path

from i18n import tr
from settings_schema import value as _value

# Что можно подставлять в шаблоны имени файла и каталога.
TEMPLATE_FIELDS = ("title", "ext", "index", "id", "playlist", "date")
DEFAULT_TEMPLATE = "{title}{ext}"
# Windows-переносимые имена: серверы на Windows не примут : * ? " < > | и хвост
# с точкой/пробелом, поэтому чистим и локальное расширение тоже.
_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
_MAX_NAME = 180


class FtpError(Exception):
    """Ошибка выгрузки: сообщение уже записано в журнал вызывающего."""


def _t(lang: str, key: str, **kwargs) -> str:
    """Перевод ключа ftp.* с откатом на русский (как в downloader)."""
    return tr(lang, key, **kwargs)


def _fit(text: str, ext: str = "") -> str:
    """Обрезает по байтам до _MAX_NAME, сохраняя расширение."""
    ext = ext if ext and text.lower().endswith(ext.lower()) else ""
    stem = text[: len(text) - len(ext)] if ext else text
    while stem and len((stem + ext).encode("utf-8")) > _MAX_NAME:
        stem = stem[:-1]
    return (stem.rstrip(" .") or "file") + ext


def clean_name(name: str, fallback: str = "file") -> str:
    """Имя файла/каталога без символов, которые ломают путь или Windows."""
    text = _BAD_CHARS.sub("_", str(name or ""))
    text = text.replace("/", "_").replace("\\", "_").strip().strip(".")
    text = re.sub(r"\s{2,}", " ", text)
    if not text or text in (".", ".."):
        return fallback
    stem = text.split(".")[0].lower()
    if stem in _RESERVED:
        text = "_" + text
    return _fit(text)


def _field(meta: dict, name: str) -> str:
    value = meta.get(name)
    return "" if value is None else str(value)


def render_name(template: str, meta: dict, index: int = 1, fallback: str = "file") -> str:
    """Имя файла по шаблону: «{index:02d} - {title}{ext}» -> «01 - Клип.mp4».

    Неизвестное поле даёт пустую строку, спецификатор формата ({index:02d})
    тоже поддерживается, а в Windows-небезопасные символы заменяются.
    """
    text = str(template or "").strip() or DEFAULT_TEMPLATE
    data = {
        "title": _field(meta, "title"),
        "ext": _field(meta, "ext"),
        "id": _field(meta, "id"),
        "playlist": _field(meta, "playlist"),
        "date": _field(meta, "date") or datetime.now().strftime("%Y-%m-%d"),
        "index": index if index and index > 0 else 0,
    }
    try:
        rendered = text.format(**data)
    except (KeyError, IndexError, ValueError):
        rendered = DEFAULT_TEMPLATE.format(**data)  # битый шаблон -> базовый
    name = clean_name(rendered, fallback)
    ext = data["ext"]
    if ext and not name.lower().endswith(ext.lower()):
        name = _fit(clean_name(name, fallback) + ext, ext)  # «{title}» без расширения
    return name


def render_path(template: str, meta: dict, fallback: str = "") -> str:
    """Путь на сервере: «{playlist}/{date}» -> «Плейлист/2026-09-26».

    Слеши сохраняются, каждый сегмент чистится, «..» и пустые сегменты
    выбрасываются — выше базового каталога уйти нельзя.
    """
    text = str(template or "").strip().replace("\\", "/")
    if not text:
        return ""
    data = {
        "title": _field(meta, "title"),
        "id": _field(meta, "id"),
        "playlist": _field(meta, "playlist"),
        "date": _field(meta, "date") or datetime.now().strftime("%Y-%m-%d"),
    }
    try:
        rendered = text.format(**data)
    except (KeyError, IndexError, ValueError):
        return ""
    parts = [clean_name(part, "") for part in rendered.split("/")]
    return "/".join(p for p in parts if p and p not in (".", ".."))


class FtpConfig:
    """Настройки выгрузки, разобранные из settings.json (тип и умолчания - из схемы)."""

    def __init__(self, settings: dict | None = None, lang: str = "en"):
        data = settings or {}
        self.lang = lang
        self.active = _value(data, "ftp.active")
        self.mode = _value(data, "ftp.mode")
        self.host = _value(data, "ftp.host").strip()
        self.port = _value(data, "ftp.port")
        self.user = _value(data, "ftp.user")
        self.password = _value(data, "ftp.password")
        self.tls = _value(data, "ftp.tls")
        self.tls_verify = _value(data, "ftp.tls_verify")
        self.pasv = _value(data, "ftp.pasv")
        self.dir = _value(data, "ftp.dir")
        self.template = _value(data, "ftp.template").strip()
        self.delete_local = _value(data, "ftp.delete_local")
        self.timeout = _value(data, "ftp.timeout")
        self.retries = _value(data, "ftp.retries")

    @property
    def enabled(self) -> bool:
        """Выгрузка включена и настроена: нужен хотя бы хост."""
        return bool(self.active and self.host)

    @property
    def per_file(self) -> bool:
        return self.mode == "per_file"

    def _t(self, key: str, **kwargs) -> str:
        return _t(self.lang, key, **kwargs)

    def describe(self) -> str:
        scheme = "ftps" if self.tls else "ftp"
        return f"{scheme}://{self.user}@{self.host}:{self.port}"


def _ssl_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class _FtpTls(ftplib.FTP_TLS):
    r"""FTPS с возобновлением TLS-сессии на канале данных.

    Штатный ``FTP_TLS.ntransfercmd`` делает полный хендшейк заново, а FileZilla
    Server с требованием возобновления отвечает «425 TLS session of data
    connection not resumed» (и рвёт соединение раньше - «SSL: SHUTDOWN_WHILE_
    IN_INIT» на обычном NLST). Передача сессии управляющего канала через
    ``session=`` - штатный способ борьбы с этим; в самой библиотеке ftplib
    такой передачи нет, отсюда подкласс.
    """

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host,
                                            session=self.sock.session)
        return conn, size


def connect(cfg: FtpConfig, log=None) -> ftplib.FTP:
    """Подключается и логинится (с PROT для FTPS). Пассивный режим."""
    if not cfg.host:
        raise FtpError(cfg._t("ftp.no_host"))
    if log:
        log("info", cfg._t("ftp.connecting", host=cfg.describe()))
    if cfg.tls:
        ftp = _FtpTls(context=_ssl_context(cfg.tls_verify))
    else:
        ftp = ftplib.FTP()
    ftp.connect(cfg.host, cfg.port, timeout=cfg.timeout)
    ftp.login(cfg.user or "anonymous", cfg.password)
    if cfg.tls:
        ftp.prot_p()
    ftp.set_pasv(bool(cfg.pasv))
    ftp.voidcmd("TYPE I")
    if log:
        log("info", cfg._t("ftp.connected", host=cfg.describe()))
    return ftp


def _dir_exists(ftp: ftplib.FTP, path: str) -> bool:
    """Проверка каталога через CWD: MKD на «уже существует» отвечает 550."""
    try:
        ftp.cwd(path)
    except (ftplib.Error, OSError):
        return False
    return True


def ensure_dir(ftp: ftplib.FTP, path: str, lang: str = "en", log=None, done=None) -> bool:
    """Создаёт каталог на сервере (mkdir -p). False, если не получилось.

    550/553/450 после MKD не считаем успехом, пока CWD не подтвердил, что
    каталог есть: «Permission denied» и «Access denied» выглядят одинаково.
    done — множество уже созданных путей, чтобы не слать повторный MKD.

    Все пути считаются от исходного каталога и на выходе соединение
    возвращается туда же: проверка существования идёт через CWD, поэтому без
    возврата следующий STOR «каталог/файл» ушёл бы внутрь каталога второй
    раз (сервер отвечал 550 No such file or directory).
    """
    parts = [p for p in str(path or "").split("/") if p]
    if not parts:
        return True
    try:
        base = ftp.pwd()
    except (ftplib.Error, OSError):
        base = None   # сервер без PWD: работаем относительно текущего каталога
    prefix = (base or "").rstrip("/")
    try:
        current = ""
        for part in parts:
            current = f"{current}/{part}" if current else part
            if base is None:
                target = current
            else:
                target = f"{prefix}/{current}" if prefix else f"/{current}"
            if done is not None and current in done:
                continue
            try:
                ftp.mkd(target)
            except ftplib.error_perm as exc:
                code = str(exc).split(" ")[0]
                if code not in ("550", "553", "450") or not _dir_exists(ftp, target):
                    if log:
                        log("error", _t(lang, "ftp.dir_failed", path=current, exc=exc))
                    return False
            except (ftplib.Error, OSError) as exc:
                if log:
                    log("error", _t(lang, "ftp.dir_failed", path=current, exc=exc))
                return False
            if done is not None:
                done.add(current)
        return True
    finally:
        if base:
            try:
                ftp.cwd(base)
            except (ftplib.Error, OSError):
                pass   # не смогли вернуться - дальше всё равно абсолютные пути


def _remote_size(ftp: ftplib.FTP, path: str) -> int:
    try:
        return ftp.size(path) or 0
    except (ftplib.Error, OSError):
        return 0


def upload_file(ftp: ftplib.FTP, local, remote: str, cfg: FtpConfig, log=None) -> bool:
    """Загружает один файл (STOR). True, если сервер принял весь файл."""
    src = Path(local)
    size = src.stat().st_size
    if log:
        log("info", cfg._t("ftp.uploading", name=remote, size=_human(size)))
    with src.open("rb") as fh:
        ftp.storbinary(f"STOR {remote}", fh, blocksize=64 * 1024)
    remote_size = _remote_size(ftp, remote)
    if remote_size and remote_size != size:
        if log:
            log("error", cfg._t("ftp.size_mismatch", name=remote, size=_human(remote_size)))
        return False
    if log:
        log("info", cfg._t("ftp.uploaded", name=remote, size=_human(size)))
    return True


def _human(size: int) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def delete_local(path, lang: str = "en", log=None) -> bool:
    """Удаляет локальный файл после успешной загрузки."""
    name = os.path.basename(str(path))
    try:
        os.remove(path)
    except OSError as exc:
        if log:
            log("warning", _t(lang, "ftp.delete_failed", name=name, exc=exc))
        return False
    if log:
        log("info", _t(lang, "ftp.deleted", name=name))
    return True


def _unique(remote: str, taken: set[str]) -> str:
    """Два файла с одинаковым именем не затирают друг друга: stem~2.ext."""
    if remote not in taken:
        return remote
    stem, ext = os.path.splitext(remote)
    num = 2
    while f"{stem}~{num}{ext}" in taken:
        num += 1
    return f"{stem}~{num}{ext}"


def test_connection(cfg: FtpConfig, log=None) -> bool:
    """Проверка настроек: подключается и сразу отключается. False при ошибке."""
    try:
        _close(connect(cfg, log=log))
    except (FtpError, ftplib.Error, OSError, ssl.SSLError) as exc:
        if log:
            log("error", _t(cfg.lang, "ftp.error", exc=exc))
        return False
    if log:
        log("info", _t(cfg.lang, "ftp.test_ok", host=cfg.describe()))
    return True


def _close(ftp) -> None:
    try:
        ftp.quit()
    except (ftplib.Error, OSError):
        try:
            ftp.close()
        except (ftplib.Error, OSError):
            pass


def _meta_from_path(path, meta: dict) -> dict:
    """Достраивает meta по локальному имени файла (ext и title)."""
    data = dict(meta or {})
    src = Path(str(path))
    if not data.get("ext"):
        data["ext"] = src.suffix
    if not data.get("title"):
        data["title"] = src.stem
    return data


def upload_files(cfg: FtpConfig, files, metas=None, log=None, index_from: int = 1) -> dict:
    """Выгружает список файлов одним подключением.

    files — пути или (путь, meta) пары; meta описывает файл для шаблона имени
    (title, ext, id, playlist), а без него имя берётся из локального файла.
    Возвращает отчёт: сколько загружено, сколько нет, список удалённых
    локальных файлов и первые ошибки.
    """
    report = {"uploaded": 0, "failed": 0, "skipped": 0, "deleted": [], "errors": []}
    items = []
    for entry in files or []:
        if isinstance(entry, (tuple, list)):
            path, meta = entry[0], (entry[1] if len(entry) > 1 else {})
        else:
            path, meta = entry, (metas or {}).get(str(entry), {})
        if path and os.path.isfile(str(path)):
            items.append((path, _meta_from_path(path, meta)))
    if not items:
        return report
    if not cfg.enabled:
        report["skipped"] = len(items)
        if log:
            log("info", cfg._t("ftp.disabled"))
        return report
    if log:
        log("info", cfg._t("ftp.batch.start", n=len(items)))

    try:
        ftp = connect(cfg, log=log)
    except (FtpError, ftplib.Error, OSError, ssl.SSLError) as exc:
        report["failed"] = len(items)
        report["errors"].append(str(exc))
        if log and not isinstance(exc, FtpError):
            log("error", cfg._t("ftp.error", exc=exc))
        return report

    made: set[str] = set()
    taken: set[str] = set()

    def reopen() -> "ftplib.FTP | None":
        """Новое соединение после обрыва + восстановление созданных каталогов."""
        _close(ftp)
        try:
            fresh = connect(cfg, log=log)
        except (FtpError, ftplib.Error, OSError, ssl.SSLError) as exc:
            if log:
                log("error", cfg._t("ftp.error", exc=exc))
            return None
        done: set[str] = set()
        for path in sorted(made):  # родитель всегда короче «родитель/потомок»
            if not ensure_dir(fresh, path, cfg.lang, log=log, done=done):
                _close(fresh)
                return None
        return fresh

    try:
        for number, (path, meta) in enumerate(items, start=index_from):
            remote_dir = render_path(cfg.dir, meta)
            if remote_dir and not ensure_dir(ftp, remote_dir, cfg.lang, log=log, done=made):
                report["failed"] += 1
                report["errors"].append(remote_dir)
                continue
            name = render_name(cfg.template, meta, index=number)
            remote = f"{remote_dir}/{name}" if remote_dir else name
            remote = _unique(remote, taken)
            taken.add(remote)
            ok, ftp = _upload_with_retry(ftp, path, remote, cfg, log=log, reopen=reopen)
            if ok:
                report["uploaded"] += 1
                if cfg.delete_local and delete_local(path, cfg.lang, log=log):
                    report["deleted"].append(str(path))
            else:
                report["failed"] += 1
        if log:
            log("info", cfg._t("ftp.batch.done", ok=report["uploaded"], bad=report["failed"]))
    finally:
        _close(ftp)
    return report


def _upload_with_retry(ftp, path, remote: str, cfg: FtpConfig, log=None, reopen=None):
    """STOR с повторами. Возвращает (удалось, соединение).

    Отказ сервера (550 и прочие error_perm) повтором не лечится, а обрыв
    канала на больших файлах — обычное дело, поэтому при reopen() получаем
    свежее соединение и заново создаём каталоги.
    """
    for attempt in range(1, cfg.retries + 1):
        try:
            return upload_file(ftp, path, remote, cfg, log=log), ftp
        except ftplib.error_perm as exc:
            if log:
                log("error", cfg._t("ftp.rejected", name=remote, exc=exc))
            return False, ftp
        except (ftplib.Error, OSError, ssl.SSLError) as exc:
            if log:
                log("warning", cfg._t("ftp.retry", n=attempt, name=remote, exc=exc))
            if attempt >= cfg.retries:
                return False, ftp
            time.sleep(min(2 ** attempt, 10))
            if reopen is not None:
                fresh = reopen()
                if fresh is not None:
                    ftp = fresh
    return False, ftp


# Панель настроек модуля. Порядок полей = порядок строк в панели; поля кроме
# active видны только при включённой выгрузке (visible_if), умолчания, min/max и
# подписи берутся отсюда же - FtpConfig их больше не дублирует. Режим
# выгрузки - choice_buttons: два коротких слова с пояснением в подсказке
# вместо длинных вариантов в выпадающем списке.
_WHEN_ACTIVE = {"key": "active", "equals": True}

SETTINGS = {
    "id": "ftp",
    "label": "sheet.tab.ftp",
    "order": 30,
    "flat_prefix": "ftp_",
    "boxes": {"conn": "sheet.ftp.conn"},
    "fields": [
        {"key": "active", "type": "bool", "label": "sheet.ftp.active",
         "default": False, "check": True, "pixel": True, "no_label": True, "live": True},
        {"key": "mode", "type": "choice_buttons", "label": "sheet.ftp.mode",
         "default": "batch",
         "option_hints": {"batch": "sheet.ftp.mode.batch.hint",
                          "per_file": "sheet.ftp.mode.per_file.hint"},
         "options": [["batch", "sheet.ftp.mode.batch"], ["per_file", "sheet.ftp.mode.per_file"]],
         "row": 1, "visible_if": _WHEN_ACTIVE},
        {"key": "host", "type": "text", "label": "sheet.ftp.host", "default": "",
         "placeholder": "ftp.example.org", "row": 2, "live": True, "visible_if": _WHEN_ACTIVE},
        {"key": "port", "type": "int", "label": "sheet.ftp.port", "default": 21,
         "min": 1, "max": 65535, "step": 1, "row": 3, "visible_if": _WHEN_ACTIVE},
        {"key": "user", "type": "text", "label": "sheet.ftp.user", "default": "anonymous",
         "row": 4, "live": True, "visible_if": _WHEN_ACTIVE},
        {"key": "password", "type": "password", "label": "sheet.ftp.password", "default": "",
         "secret": True, "row": 5, "live": True, "visible_if": _WHEN_ACTIVE},
        {"key": "tls", "type": "bool", "label": "sheet.ftp.tls", "default": False,
         "check": True, "live": True, "visible_if": _WHEN_ACTIVE, "title": "sheet.ftp.tls.hint"},
        {"key": "tls_verify", "type": "bool", "label": "sheet.ftp.tls_verify", "default": True,
         "check": True, "live": True, "visible_if": _WHEN_ACTIVE, "title": "sheet.ftp.tls_verify.hint"},
        {"key": "pasv", "type": "bool", "label": "sheet.ftp.pasv", "default": True,
         "check": True, "live": True, "visible_if": _WHEN_ACTIVE, "title": "sheet.ftp.pasv.hint"},
        {"key": "delete_local", "type": "bool", "label": "sheet.ftp.delete_local",
         "default": False, "check": True, "live": True, "visible_if": _WHEN_ACTIVE},
        {"key": "dir", "type": "text", "label": "sheet.ftp.dir", "default": "",
         "placeholder": "{playlist}/{date}", "live": True, "visible_if": _WHEN_ACTIVE},
        {"type": "note", "transient": True, "dom": "ftp-dir-note",
         "note_source": "ftpDirNote", "visible_if": _WHEN_ACTIVE},
        {"key": "template", "type": "text", "label": "sheet.ftp.template",
         "default": DEFAULT_TEMPLATE, "placeholder": "{index:02d} - {title}{ext}",
         "live": True, "visible_if": _WHEN_ACTIVE},
        {"key": "timeout", "type": "int", "label": "sheet.ftp.timeout", "default": 60,
         "min": 5, "max": 3600, "step": 5, "box": "conn", "row": 1, "visible_if": _WHEN_ACTIVE},
        {"key": "retries", "type": "int", "label": "sheet.ftp.retries", "default": 3,
         "min": 1, "max": 10, "step": 1, "box": "conn", "row": 1, "visible_if": _WHEN_ACTIVE},
        {"type": "actions", "transient": True, "box": "conn", "row": 2,
         "visible_if": _WHEN_ACTIVE, "buttons": [
             {"dom": "ftp-test", "label": "sheet.ftp.test"},
         ]},
        {"type": "note", "transient": True, "dom": "ftp-test-note", "box": "conn", "row": 2,
         "inline": True, "visible_if": _WHEN_ACTIVE},
    ],
}
