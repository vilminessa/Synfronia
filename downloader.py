"""Загрузка через yt-dlp: опции, прогресс, остановка, постпроцессоры."""

import os
import re
import shutil
import subprocess
import threading
import urllib.request
import zipfile
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.embedthumbnail import EmbedThumbnailPP
from yt_dlp.postprocessor.ffmpeg import (
    FFmpegEmbedSubtitlePP,
    FFmpegMetadataPP,
    FFmpegPostProcessor,
    FFmpegPostProcessorError,
)

from i18n import I18N, LANGUAGES, tr
from paths import ffmpeg_local_dir
from settings import load_settings


_PLAYLIST_RE = re.compile(r"[?&]list=")


SUBTITLE_OPTIONS = {
    "off": None,
    "ru": ["ru"],
    "en": ["en"],
    "all": ["all"],
}

QUALITY_FORMATS = {
    "lossless": "bv*+ba/b",
    "2k": "bv*[height<=1440]+ba/b[height<=1440]",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]",
    "720": "bv*[height<=720]+ba/b[height<=720]",
    "480": "bv*[height<=480]+ba/b[height<=480]",
    "240": "bv*[height<=240]+ba/b[height<=240]",
}

QUALITY_LIMITS = {
    "2k": 1440,
    "1080": 1080,
    "720": 720,
    "480": 480,
    "240": 240,
}

TRANSCODERS = {
    "libx265": {
        "label": "HEVC (x265, программный)",
        "vcodec": "libx265",
        "tag": "hvc1",
        "args": ["-preset", "medium", "-crf", "23"],
    },
    "nvenc": {
        "label": "NVIDIA NVENC (H.265)",
        "vcodec": "hevc_nvenc",
        "tag": "hvc1",
        "args": ["-preset", "p5", "-cq", "23"],
    },
    "amf": {
        "label": "AMD AMF (H.265)",
        "vcodec": "hevc_amf",
        "tag": "hvc1",
        "args": ["-quality", "quality", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"],
    },
    "qsv": {
        "label": "Intel Quick Sync (QSV) (H.265)",
        "vcodec": "hevc_qsv",
        "tag": "hvc1",
        "args": ["-preset", "medium", "-global_quality", "23"],
    },
}

ENCODER_NAMES = {
    "libx265": "libx265",
    "nvenc": "hevc_nvenc",
    "amf": "hevc_amf",
    "qsv": "hevc_qsv",
}


FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def download_ffmpeg(on_progress=None, on_log=None) -> str | None:
    """Скачивает ffmpeg-release-essentials.zip и распаковывает ffmpeg.exe/ffprobe.exe
    в ffmpeg_local_dir(). Возвращает путь к ffmpeg.exe или None при ошибке.
    on_progress(percent: float) вызывается по мере скачивания (0..100)."""
    dest = ffmpeg_local_dir()
    exe_path = dest / "ffmpeg.exe"
    if exe_path.is_file():
        return str(exe_path)

    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "ffmpeg.zip"
    try:
        if on_log:
            on_log("info", "Скачиваю ffmpeg…")
        req = urllib.request.Request(
            FFMPEG_DOWNLOAD_URL,
            headers={"User-Agent": "Synfronia/1.3 (auto-installer)"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            received = 0
            with open(zip_path, "wb") as fh:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
                    received += len(chunk)
                    if on_progress and total:
                        on_progress(received / total * 100.0)

        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                base = Path(name).name
                if base in ("ffmpeg.exe", "ffprobe.exe"):
                    target = dest / base
                    with zf.open(name) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)

        zip_path.unlink(missing_ok=True)
        return str(exe_path) if exe_path.is_file() else None
    except Exception as exc:  # noqa: BLE001
        if on_log:
            on_log("error", f"ffmpeg download failed: {exc}")
        zip_path.unlink(missing_ok=True)
        return None


def find_ffmpeg() -> str | None:
    """Ищет ffmpeg в локальной папке (LocaAppData), PATH и типовых местах (winget)."""
    local = ffmpeg_local_dir() / "ffmpeg.exe"
    if local.is_file():
        return str(local)
    found = shutil.which("ffmpeg")
    if found:
        return found
    candidates = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/ffmpeg.exe",
        Path(os.environ.get("ProgramFiles", "")) / "ffmpeg/bin/ffmpeg.exe",
    )
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def available_transcoders(ffmpeg: str | None = None) -> list[str]:
    """Ключи перекодировщиков, доступных в текущей сборке ffmpeg."""
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        return list(ENCODER_NAMES)
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-encoders"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return list(ENCODER_NAMES)
    output = proc.stdout or ""
    return [name for name, enc in ENCODER_NAMES.items() if re.search(rf"\b{re.escape(enc)}\b", output)]


def is_playlist(url: str) -> bool:
    """Простая эвристика: признак ссылки на плейлист по ?list=."""
    return bool(_PLAYLIST_RE.search(url or ""))


class _StopDownload(Exception):
    pass


class TranscodePP(FFmpegPostProcessor):
    """Перекодирует видео выбранным кодировщиком (x265/NVENC/AMF/QSV)
    в отдельный файл с суффиксом «HEVC», удаляя оригинал — чтобы в папке
    оставался только перекодированный файл."""

    def __init__(self, downloader=None, encoder: str = "libx265", lang: str = "en",
                 copy_subtitles: bool = False):
        super().__init__(downloader)
        self._config = TRANSCODERS.get(encoder) or TRANSCODERS["libx265"]
        self._lang = lang
        self._copy_subtitles = copy_subtitles

    def _output_name(self, filename: str) -> str:
        """Формирует имя выходного файла: base [HEVC].mp4"""
        stem = os.path.splitext(filename)[0]
        return f"{stem} [HEVC].mp4"

    @FFmpegPostProcessor._restrict_to(images=False)
    def run(self, info):
        filename = info.get("filepath")
        if not filename or info.get("ext", "").lower() != "mp4":
            self.to_screen(tr(self._lang, "p.skip_not_mp4"))
            return [], info
        cfg = self._config
        out_path = self._output_name(filename)
        if os.path.abspath(out_path) == os.path.abspath(filename):
            self.to_screen(tr(self._lang, "p.skip_not_mp4"))
            return [], info
        temp = f"{out_path}.tmp.mp4"

        # Список кодеров для попыток: сначала выбранный (NVENC/AMF/QSV),
        # при недоступном GPU-кодеке падаем на CPU libx265.
        candidates = [cfg["vcodec"].split("_")[0] if cfg["vcodec"] in ("hevc_nvenc", "hevc_amf", "hevc_qsv") else "libx265"]
        if cfg["vcodec"] != "libx265":
            candidates = ["nvenc" if cfg["vcodec"] == "hevc_nvenc" else ("amf" if cfg["vcodec"] == "hevc_amf" else ("qsv" if cfg["vcodec"] == "hevc_qsv" else "libx265"))]
            candidates.append("libx265")

        last_err = None
        for enc in candidates:
            enc_cfg = TRANSCODERS.get(enc) or TRANSCODERS["libx265"]
            if enc_cfg["vcodec"] == "libx265" and last_err is not None:
                self.to_screen(tr(self._lang, "p.transcode_fallback", vcodec="libx265"))
            self.to_screen(tr(self._lang, "p.transcode_run", vcodec=enc_cfg["vcodec"]))
            try:
                self.run_ffmpeg(
                    filename,
                    temp,
                    ["-map", "0:v:0", "-map", "0:a?"]
                    + ([ "-map", "0:s?", "-c:s", "copy" ] if self._copy_subtitles else [])
                    + ["-c:v", enc_cfg["vcodec"], "-tag:v", enc_cfg["tag"]]
                    + enc_cfg["args"]
                    + ["-c:a", "copy"],
                )
                if os.path.exists(temp):
                    os.replace(temp, out_path)
                    # Оригинал больше не нужен: в папке остаётся только
                    # перекодированный файл, иначе было бы два видео.
                    try:
                        os.remove(filename)
                    except OSError:
                        pass
                last_err = None
                break
            except FFmpegPostProcessorError as e:
                last_err = e
                self.to_screen(tr(self._lang, "p.transcode_failed", detail=str(e)[:120]))
                if os.path.exists(temp):
                    os.remove(temp)
                continue
            finally:
                if os.path.exists(temp):
                    os.remove(temp)
        if last_err is not None:
            self.to_screen(tr(self._lang, "p.transcode_all_failed"))
            return [], info
        info["filepath"] = out_path
        info["_filename"] = out_path
        return [], info


def _quality_suffix_name(filename: str, limit: int) -> str:
    """Добавляет к имени файла суффикс лимита качества ([<limit>p]),
    объединяя его с уже имеющимся суффиксом [HEVC], если такой есть."""
    stem, ext = os.path.splitext(filename)
    m = re.search(r" \[\d+(?:\.\d+)?p(?: HEVC)?\]$", stem)
    if m:
        tag = m.group(0)
        if " HEVC" in tag:
            stem = stem[: m.start()] + f" [{limit}p HEVC]"
        else:
            stem = stem[: m.start()] + f" [{limit}p]"
    elif stem.endswith(" [HEVC]"):
        stem = stem[: -len(" [HEVC]")] + f" [{limit}p HEVC]"
    else:
        stem = f"{stem} [{limit}p]"
    return stem + ext


class QualitySuffixPP(FFmpegPostProcessor):
    """Добавляет суффикс лимита качества (например [240p]) к готовому файлу,
    если исходное разрешение видео выше установленного ограничения."""

    def __init__(self, downloader=None, quality: str = "lossless", lang: str = "en"):
        super().__init__(downloader)
        self._limit = QUALITY_LIMITS.get(quality)
        self._lang = lang

    def _source_height(self, info: dict) -> int | None:
        best = None
        for fmt in info.get("formats") or []:
            h = fmt.get("height")
            if h:
                best = max(best or 0, int(h))
        return best

    @FFmpegPostProcessor._restrict_to(images=False)
    def run(self, info):
        filename = info.get("filepath")
        if not filename or not self._limit:
            return [], info
        source = self._source_height(info)
        if not source or source <= self._limit:
            return [], info
        target = _quality_suffix_name(filename, self._limit)
        if os.path.abspath(target) == os.path.abspath(filename):
            return [], info
        try:
            os.replace(filename, target)
        except OSError:
            return [], info
        info["filepath"] = target
        info["_filename"] = target
        return [], info


class Downloader:
    """Запускает yt-dlp в рабочем потоке и стучится в UI через колбэки."""

    def __init__(self, on_log=None, on_progress=None, lang: str = "en"):
        self._on_log = on_log or (lambda *_: None)
        self._on_progress = on_progress or (lambda *_: None)
        self._lang = lang if lang in LANGUAGES else "en"
        self._stop = threading.Event()
        self._wd_done = threading.Event()
        self._errors = False
        self._finished = []

    def _t(self, key: str, **kwargs) -> str:
        return tr(self._lang, key, **kwargs)

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @property
    def failed(self) -> bool:
        return self._errors

    # -- колбэки в yt-dlp -----------------------------------------------------
    def _log(self, level: str, msg: str) -> None:
        self._on_log(level, msg)

    def _retry_hook(self, n: int = 0) -> float:
        """Вызывается yt-dlp перед каждой ретраей (http/fragment).
        Если запрошена остановка — бросает _StopDownload, мгновенно обрывая цикл."""
        if self._stop.is_set():
            raise _StopDownload()
        return 0.0

    def _watchdog(self, ydl) -> None:
        """Фоновый сторож: при запросе остановки закрывает все активные
        HTTP-соединения yt-dlp, чтобы прервать блокирующий read и retry-цикл."""
        while not self._stop.wait(0.05):
            if self._wd_done.is_set():
                return
        try:
            director = ydl._request_director
            director.close()
        except Exception:  # noqa: BLE001
            pass

    class _Logger:
        def __init__(self, owner: "Downloader"):
            self._owner = owner

        def debug(self, msg): self._owner._log("debug", msg)
        def info(self, msg): self._owner._log("info", msg)
        def warning(self, msg): self._owner._log("warning", msg)
        def error(self, msg):
            self._owner._errors = True
            self._owner._log("error", msg)

    def _hook(self, d: dict) -> None:
        if self._stop.is_set():
            raise _StopDownload()
        status = d.get("status")
        if status == "finished" and d.get("filename"):
            self._finished.append(os.path.abspath(d["filename"]))
        if status in ("downloading", "finished"):
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            recvd = d.get("downloaded_bytes") or 0
            percent = (recvd / total * 100) if total else None
            self._on_progress(
                {
                    "status": status,
                    "filename": os.path.basename(d.get("filename") or ""),
                    "downloaded": recvd,
                    "total": total,
                    "percent": percent,
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                }
            )
        elif status == "postprocessing":
            self._on_progress(
                {
                    "status": "postprocessing",
                    "filename": "",
                    "percent": None,
                    "msg": self._t("p.postprocess"),
                }
            )

    def _cleanup_orphans(self) -> None:
        bases = set()
        for path in map(os.path.abspath, self._finished):
            parent, name = os.path.split(path)
            m = re.search(r"(?i)\.f\d+\.", name)
            bases.add(os.path.join(parent, name[: m.start()]) if m else path)
        for base in bases:
            parent, name = os.path.split(base)
            if not os.path.isdir(parent):
                continue
            try:
                entries = os.listdir(parent)
            except OSError:
                continue
            for entry in entries:
                if not entry.startswith(name + "."):
                    continue
                rest = entry[len(name):]
                if rest.startswith(".f") or rest in (".part", ".webp", ".jpg", ".jpeg", ".png"):
                    try:
                        os.remove(os.path.join(parent, entry))
                    except OSError:
                        pass

    # -- опции yt-dlp ---------------------------------------------------------
    def _build_opts(
        self,
        dest: str,
        playlist: bool,
        group: bool,
        subtitles: str,
        quality: str,
    ) -> dict:
        if playlist and group:
            outtmpl = os.path.join(dest, "%(playlist_title)s", "%(title)s.%(ext)s")
        else:
            outtmpl = os.path.join(dest, "%(title)s.%(ext)s")

        subs_langs = SUBTITLE_OPTIONS.get(subtitles)
        _retries = int(load_settings().get("retries", 10))
        _timeout = int(load_settings().get("socket_timeout", 20))
        opts = {
            "outtmpl": outtmpl,
            "format": QUALITY_FORMATS.get(quality, QUALITY_FORMATS["lossless"]),
            "merge_output_format": "mp4",
            "restrictfilenames": True,
            "noplaylist": not playlist,
            "overwrites": True,
            "noprogress": True,
            "writethumbnail": True,
            "logger": self._Logger(self),
            "progress_hooks": [self._hook],
            "ignoreerrors": True,
            "retries": _retries,
            "fragment_retries": _retries,
            "socket_timeout": _timeout,
            "js_runtimes": {"node": {}},
            "retry_sleep_functions": {"http": self._retry_hook, "fragment": self._retry_hook},
        }
        if subs_langs:
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = True
            opts["subtitleslangs"] = subs_langs
        return opts

    def _add_ffmpeg(self, opts: dict) -> dict:
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        else:
            opts["hls_use_mpegts"] = True
            self._log("warning", self._t("p.ffmpeg_missing"))
        return opts

    def _register_pps(self, ydl: YoutubeDL, subs_on: bool, transcode: str, quality: str) -> None:
        if transcode and transcode != "none":
            ydl.add_post_processor(TranscodePP(ydl, transcode, self._lang, subs_on))
        if subs_on:
            ydl.add_post_processor(FFmpegEmbedSubtitlePP(ydl))
        ydl.add_post_processor(FFmpegMetadataPP(ydl))
        ydl.add_post_processor(EmbedThumbnailPP(ydl))
        ydl.add_post_processor(QualitySuffixPP(ydl, quality, self._lang))

    def _format_candidates(self, quality: str) -> list:
        base = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["lossless"])
        limit = QUALITY_LIMITS.get(quality)
        if limit:
            hls = (
                f"bv*[height<={limit}][protocol^=m3u8]+ba/"
                f"bv*[height<={limit}]+ba/b[height<={limit}]"
            )
        else:
            hls = "bv*[protocol^=m3u8]+ba/bv*+ba/b"
        return [base, hls] if hls != base else [base]

    # -- запуск ---------------------------------------------------------------
    def download(
        self,
        url: str,
        dest: str,
        playlist: bool = False,
        group: bool = True,
        subtitles: str = "en",
        quality: str = "lossless",
        transcode: str = "none",
    ) -> None:
        os.makedirs(dest, exist_ok=True)
        self._errors = False
        self._finished = []
        opts = self._build_opts(dest, playlist, group, subtitles, quality)
        subs_on = bool(SUBTITLE_OPTIONS.get(subtitles))
        mode = self._t("p.mode.playlist" if playlist else "p.mode.video")
        grouping = self._t("p.mode.on") if playlist and group else self._t("p.mode.off")
        self._log("info", self._t("p.mode", mode=mode, group=grouping))
        if transcode and transcode != "none":
            encoder = TRANSCODERS.get(transcode)
            label = self._t("trans." + transcode) if "trans." + transcode in I18N["ru"] else (encoder["label"] if encoder else transcode)
            self._log("info", self._t("p.transcoding", label=label))
        candidates = self._format_candidates(quality)
        for i, fmt in enumerate(candidates):
            self._errors = False
            self._finished = []
            if i:
                self._log("warning", self._t("p.retry_hls", n=i + 1))
            opts = self._build_opts(dest, playlist, group, subtitles, quality)
            opts["format"] = fmt
            self._log("debug", self._t("p.attempt", n=i + 1, fmt=opts["format"]))
            info = None
            short = None
            try:
                self._wd_done.clear()
                with YoutubeDL(self._add_ffmpeg(opts)) as ydl:
                    threading.Thread(
                        target=self._watchdog, args=(ydl,), daemon=True, name="synfronia-watchdog"
                    ).start()
                    self._register_pps(ydl, subs_on, transcode, quality)
                    info = ydl.extract_info(url, download=True)
                    if info and info.get("_type") == "playlist":
                        done = [e for e in info.get("entries", []) if e]
                        short = self._t("p.done.playlist", n=len(done), dest=os.path.basename(dest))
                    elif info:
                        short = self._t("p.done.single", title=info.get("title", "?"))
            except _StopDownload:
                self._log("warning", self._t("p.cancelled"))
                return
            except Exception as exc:  # noqa: BLE001
                self._log("error", self._t("p.error", exc=exc))
                break
            finally:
                self._wd_done.set()
                self._stop.clear()
                self._on_progress({"status": "done"})
            if not self._errors:
                if short:
                    self._log("info", short)
                return
            self._cleanup_orphans()
            if info and info.get("_type") == "playlist":
                break
        if not self._errors:
            return
        self._log("warning", self._t("p.done_errors"))
        if short and info and info.get("_type") == "playlist":
            self._log("info", short)
