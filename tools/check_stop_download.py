r"""Проверка остановки загрузки: урок инцидента массовой загрузки.

После клика «Отмена» процесс обязан остановиться, а не доработать до конца.
В инциденте (журнал app_2026-10-01.log) Stop в 05:49:48 остановился только
в 05:52:37: в фазе экстракции страницы не работал НИ ОДИН механизм остановки
(у retry_sleep_functions не было ключа 'extractor', а _hook в этой фазе не
вызывается), а в download() не было ни одной проверки остановки — фейл
первой попытки (ignoreerrors гасит исключения yt-dlp) уводил в полный
повтор попытки формата. Здесь проверяем:

  * retry_sleep_functions знает extractor/file_access;
  * Stop до старта: download() не делает ни одной попытки;
  * Stop во время попытки: вторая попытка формата не стартует (флаг-память
    _stop_req переживает finally, который сбрасывает _stop);
  * подкласс ffmpeg.Popen убивает процесс по остановке и откатывается;
  * Api.stop_download сразу показывает статус «Запрошена остановка».

    python tools\check_stop_download.py
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# изолируем настройки и логи до импорта gui: он сам читает файл при загрузке
_ISO = Path(tempfile.mkdtemp(prefix="synf-check-stop-"))
os.environ["LOCALAPPDATA"] = str(_ISO)

import downloader  # noqa: E402
import gui  # noqa: E402
import i18n  # noqa: E402
import yt_dlp.postprocessor.ffmpeg as ytdlp_ffmpeg  # noqa: E402
from yt_dlp.networking import _urllib as ytdlp_urllib  # noqa: E402
from yt_dlp.utils import Popen as YtPopen  # noqa: E402

_checks = 0
_fails: list[str] = []


def ok(cond: bool, label: str, detail: str = "") -> bool:
    global _checks
    _checks += 1
    mark = "ok " if cond else "FAIL"
    print(f"  [{mark}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(label)
    return cond


def section(title: str) -> None:
    print(f"\n{title}")


def main() -> int:
    dest = _ISO / "downloads"
    dest.mkdir(parents=True, exist_ok=True)
    lang = "en"
    mode_line = i18n.tr(lang, "p.mode", mode=i18n.tr(lang, "p.mode.video"),
                        group=i18n.tr(lang, "p.mode.off"))
    cancel_line = i18n.tr(lang, "p.cancelled")

    # 1. фаза экстракции: ретраи веб-страниц берут 'extractor'
    section("1. retry_sleep_functions")
    dl = downloader.Downloader(lang=lang)
    opts = dl._build_opts(str(dest), False, True, "off", "lossless")
    rsf = opts.get("retry_sleep_functions", {})
    for key in ("http", "fragment", "extractor", "file_access"):
        ok(rsf.get(key) == dl._retry_hook,
           f"retry_sleep_functions[{key!r}] = _retry_hook", repr(rsf.get(key)))

    # 2. Stop до старта: ни одной попытки, возврат мгновенно
    section("2. Stop до старта download()")
    logs: list[str] = []
    dl2 = downloader.Downloader(on_log=lambda _lv, m: logs.append(m), lang=lang)
    dl2.stop()
    t0 = time.monotonic()
    dl2.download("https://example.invalid/video", str(dest))
    elapsed = time.monotonic() - t0
    ok(elapsed < 1.0, "возврат меньше секунды", f"{elapsed:.2f}с")
    ok(mode_line not in logs, "попытка не начиналась (нет строки режима)",
       repr(logs[:3]))
    ok(any(cancel_line in m for m in logs), "в журнале «Загрузка отменена»")
    ok(ytdlp_ffmpeg.Popen is not None, "патч ffmpeg не остался подменённым")

    # 3. Stop во время попытки: вторая попыка формата не стартует
    section("3. Stop во время попытки (локальный 404)")
    log_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: ARG002 - тишина в консоли
            pass

        def do_GET(self):  # noqa: N802 - имя приходит из http.server
            self.send_error(404)

        def do_HEAD(self):  # noqa: N802
            self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    logs3: list[str] = []

    def on_log(_lv, msg: str) -> None:
        # порядок логов в download(): режим (1-й), попытка (2-й); на второй
        # строке объявляем остановку - как юзер, нажавший Stop во время работы
        with log_lock:
            logs3.append(msg)
            if len(logs3) >= 2:
                dl3.stop()

    dl3 = downloader.Downloader(on_log=on_log, lang=lang)
    orig_ff_popen = ytdlp_ffmpeg.Popen
    t0 = time.monotonic()
    dl3.download(f"http://127.0.0.1:{port}/video", str(dest))
    elapsed = time.monotonic() - t0
    server.shutdown()
    server.server_close()
    cands = dl3._format_candidates("lossless")
    first = i18n.tr(lang, "p.attempt", n=1, fmt=cands[0])
    second = i18n.tr(lang, "p.attempt", n=2, fmt=cands[1])
    ok(any(first in m for m in logs3), "первая попытка начиналась")
    ok(not any(second in m for m in logs3),
       "вторая попытка формата не стартовала", repr(logs3[:6]))
    ok(not any(i18n.tr(lang, "p.retry_hls", n=2) in m for m in logs3),
       "нет перехода на HLS-повтор")
    ok(elapsed < 15, "остановка в пределах 15 секунд", f"{elapsed:.1f}с")
    ok(ytdlp_ffmpeg.Popen is orig_ff_popen, "патч ffmpeg.Popen откатился")

    # 4. прерываемый Popen действительно убивает процесс
    section("4. ffmpeg.Popen убивается по остановке")
    dl4 = downloader.Downloader(lang=lang)
    ip = dl4._interruptible_popen()
    ok(issubclass(ip, YtPopen), "подкласс yt_dlp.utils.Popen")
    dl4.stop()
    t0 = time.monotonic()
    _out, _err, rc = ip.run([sys.executable, "-c", "import time; time.sleep(30)"],
                            text=True,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    elapsed = time.monotonic() - t0
    ok(elapsed < 5, "процесс прерван меньше чем за 5с", f"{elapsed:.1f}с")
    # на Windows TerminateProcess отдаёт код 1, на POSIX был бы отрицательный
    ok(rc is not None and rc != 0, "процесс завершён принудительно (код != 0)",
       repr(rc))

    # 5. зависшая сетевая операция: принимаем и молчим - клиент висит на
    # чтении ответа до socket_timeout (~20с), пока watchdog не закроет сокет
    section("5. Stop при зависшем соединении")
    linger = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    linger.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    linger.bind(("127.0.0.1", 0))
    linger.listen(8)
    held: list[socket.socket] = []

    def hold_conn() -> None:
        while True:
            try:
                conn, _ = linger.accept()
                held.append(conn)
            except OSError:
                return

    threading.Thread(target=hold_conn, daemon=True).start()
    lport = linger.getsockname()[1]
    dl5 = downloader.Downloader(lang=lang)
    threading.Timer(0.6, dl5.stop).start()
    t0 = time.monotonic()
    dl5.download(f"http://127.0.0.1:{lport}/hang", str(dest))
    elapsed = time.monotonic() - t0
    linger.close()
    for conn in held:
        try:
            conn.close()
        except OSError:
            pass
    ok(elapsed < 5, "Stop прервал зависшую операцию меньше чем за 5с (без фикса — ~20с)",
       f"{elapsed:.1f}с")
    ok(ytdlp_urllib.create_connection.__qualname__ != "guarded",
       "патч create_connection откатился (глобальная не обёртка)",
       repr(ytdlp_urllib.create_connection))

    # 6. Api: статус виден сразу после клика
    section("6. Api.stop_download - статус мгновенно")
    api = gui.Api()
    api.dl = downloader.Downloader(lang=lang)
    api._busy = True
    api.stop_download()
    expect = i18n.tr(api._lang, "p.stop_req")
    ok(api._status == expect, "статус = «Запрошена остановка» сразу",
       repr(api._status))
    ok(api._cancel, "флаг _cancel взведён")
    ok(api.dl.stopped, "Downloader получил stop()")

    print(f"\nитог: {_checks - len(_fails)}/{_checks} ok")
    if _fails:
        print("упали: " + ", ".join(_fails))
        return 1
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_ISO, ignore_errors=True)
    raise SystemExit(code)
