r"""Выгрузка готовых файлов на FTP/FTPS.

Модуль самодостаточный: разбор настроек, безопасные шаблоны имён, подключение
с TLS, создание каталогов, загрузка и (по желанию) удаление локальных файлов.
Сеть проверяется на живых загрузках, поэтому ошибки не поднимаются наружу как
исключения: вызывающий получает отчёт и читает журнал.

Настройки (ключи ftp_* в settings.json, см. settings.DEFAULT_SETTINGS):
  ftp_active      — включена ли выгрузка;
  ftp_mode        — batch (всё одним заходом в конце) / per_file (сразу после
                    каждой успешной загрузки);
  ftp_host, ftp_port, ftp_user, ftp_password, ftp_timeout, ftp_retries;
  ftp_tls         — FTPS (явный TLS), ftp_tls_verify — проверка сертификата;
  ftp_pasv        — пассивный режим (по умолчанию; выключать только если сервер
                    не умеет PASV);
  ftp_dir         — серверный каталог, можно с подстановками {playlist}/{date};
  ftp_template    — имя файла, например «{index:02d} - {title}{ext}»;
  ftp_delete_local — удалять локальный файл после успешной загрузки.
"""

import ftplib
import os
import re
import ssl
import time
from datetime import datetime
from pathlib import Path

from i18n import tr

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
    """Настройки выгрузки, разобранные из settings.json."""

    def __init__(self, settings: dict | None = None, lang: str = "en"):
        data = settings or {}
        self.lang = lang
        self.active = bool(data.get("ftp_active"))
        self.mode = "per_file" if data.get("ftp_mode") == "per_file" else "batch"
        self.host = str(data.get("ftp_host") or "").strip()
        self.port = _as_int(data.get("ftp_port"), 21, 1, 65535)
        self.user = str(data.get("ftp_user") or "anonymous")
        self.password = str(data.get("ftp_password") or "")
        self.tls = bool(data.get("ftp_tls"))
        self.tls_verify = data.get("ftp_tls_verify") is not False
        self.pasv = data.get("ftp_pasv") is not False
        self.dir = str(data.get("ftp_dir") or "")
        self.template = str(data.get("ftp_template") or "").strip() or DEFAULT_TEMPLATE
        self.delete_local = bool(data.get("ftp_delete_local"))
        self.timeout = _as_int(data.get("ftp_timeout"), 60, 5, 3600)
        self.retries = _as_int(data.get("ftp_retries"), 3, 1, 10)

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


def _as_int(value, default: int, low: int, high: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, num))


def _ssl_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def connect(cfg: FtpConfig, log=None) -> ftplib.FTP:
    """Подключается и логинится (с PROT для FTPS). Пассивный режим."""
    if not cfg.host:
        raise FtpError(cfg._t("ftp.no_host"))
    if log:
        log("info", cfg._t("ftp.connecting", host=cfg.describe()))
    if cfg.tls:
        ftp = ftplib.FTP_TLS(context=_ssl_context(cfg.tls_verify))
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
    """
    parts = [p for p in str(path or "").split("/") if p]
    current = ""
    for part in parts:
        current = f"{current}/{part}" if current else part
        if done is not None and current in done:
            continue
        try:
            ftp.mkd(current)
        except ftplib.error_perm as exc:
            code = str(exc).split(" ")[0]
            if code not in ("550", "553", "450") or not _dir_exists(ftp, current):
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
