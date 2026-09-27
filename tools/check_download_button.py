r"""Проверка кнопки «Скачать»: контракт result из Api.poll() и разбор итога.

Кнопка показывает SVG по значению result из poll(). Поэтому тут проверяем
две вещи, которые легко разъехаться:

  * Api действительно отдаёт только те итоги, о которых знает app.js
    (ok / error / cancelled), и отмену не выдаёт мгновенно - итог появляется
    только когда yt-dlp действительно закончил;
  * состояние отмены берётся из флага stop_download(), а не из
    Downloader.stopped: загрузчик снимает свой флаг в своём же finally,
    поэтому к моменту выхода _run() он уже всегда пуст.

    python tools\check_download_button.py
"""

import json
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# изолируем настройки и логи до импорта gui: он сам читает файл при загрузке
_ISO = Path(tempfile.mkdtemp(prefix="synf-check-dl-"))
os.environ["LOCALAPPDATA"] = str(_ISO)

import gui  # noqa: E402
import i18n  # noqa: E402
import downloader  # noqa: E402

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


class FakeDownloader:
    """Загрузчик с теми же свойствами, что и настоящий: stop() ставит флаг,
    а download() в своём finally снимает его (как в downloader.py).

    summary - итог последней загрузки в том же виде, что отдаёт Downloader:
    (режим, скачано, всего)."""

    def __init__(self, failed: bool = False, boom: bool = False,
                 mode: str = "ok", ok: int = 0, total: int = 0) -> None:
        self._stop = threading.Event()
        self.failed = failed
        self.boom = boom
        self.summary = (mode, ok, total)
        self.calls: list[dict] = []

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def stop(self) -> None:
        self._stop.set()

    def download(self, url, dest, **kwargs) -> None:
        self.calls.append({"url": url, "dest": dest, **kwargs})
        try:
            if self.boom:
                raise RuntimeError("соединение сброшено")
        finally:
            self._stop.clear()


class FakeThread:
    """Заглушка потока: start_download() не должен ничего качать в тесте."""

    def __init__(self, target=None, **kwargs) -> None:
        self.target = target

    def start(self) -> None:
        return


def run(api, dl) -> None:
    """Прогоняет Api._run с подставленным загрузчиком."""
    api.dl = dl
    api._run("https://youtu.be/x", str(_ISO), False, True, "en", "lossless", "none", None)


def main() -> int:
    gui.threading.Thread = FakeThread          # type: ignore[assignment]
    api = gui.Api()

    # 1. контракт poll()
    section("1. poll() отдаёт result")
    state = api.poll()
    ok("result" in state, "в poll() есть ключ result", str(sorted(state)))
    ok(state["result"] is None, "до загрузки result = None", repr(state["result"]))
    ok(state["busy"] is False and "progress" in state, "busy/progress на месте")

    # 2. разбор итога
    section("2. итог после загрузки")
    gui.Downloader = lambda **kwargs: FakeDownloader()  # type: ignore[assignment]
    api.start_download({"url": "https://youtu.be/x", "dest": str(_ISO)})
    started = api.poll()
    ok(started["result"] is None, "старт сбрасывает прошлый итог", repr(started["result"]))
    ok(started["busy"] is True, "старт ставит busy")
    api.dl = FakeDownloader()
    api.dl.calls = api.dl.calls  # download() вызовется в _run
    api._run("https://youtu.be/x", str(_ISO), False, True, "en", "lossless", "none", None)
    after = api.poll()
    ok(after["result"] == "ok", "обычный успех = ok", repr(after["result"]))
    ok(after["busy"] is False, "после загрузки busy снят")

    run(api, FakeDownloader(failed=True, mode="failed"))
    err = api.poll()
    ok(err["result"] == "error", "ошибки в логе = error", repr(err["result"]))
    ok(err["status"], "при ошибке статус не пуст", repr(err["status"]))

    run(api, FakeDownloader(boom=True))
    boom = api.poll()
    ok(boom["result"] == "error", "исключение = error", repr(boom["result"]))
    ok(boom["busy"] is False, "исключение тоже снимает busy")

    # 3. отмена
    section("3. отмена")
    run(api, FakeDownloader())
    # с прошлой загрузки, как это делает start_download()
    api._result, api._cancel = None, False
    api.dl = FakeDownloader()
    api.stop_download()
    asked = api.poll()
    ok(api._cancel is True, "stop_download() запомнил отмену")
    ok(asked["result"] is None, "отмена не выдаёт итог сразу (иконка ждёт конца)", repr(asked["result"]))
    ok(asked["busy"] is False, "busy не взлетает от stop_download()")
    api.dl.download("https://youtu.be/x", str(_ISO))
    ok(api.dl.stopped is False, "Downloader снял свой флаг - dl.stopped больше не годится")
    api._run("https://youtu.be/x", str(_ISO), False, True, "en", "lossless", "none", None)
    cancelled = api.poll()
    ok(cancelled["result"] == "cancelled", "итог отмены = cancelled", repr(cancelled["result"]))
    ok(cancelled["busy"] is False, "отмена завершает busy")
    ok(cancelled["status"] == i18n.tr(api._lang, "p.cancelled"),
       "при отмене статус говорит про отмену", repr(cancelled["status"]))

    # отмена важнее ошибки: пользователь жал «Отмена», а не «сбой»
    run(api, FakeDownloader(failed=True))
    api.dl = FakeDownloader(failed=True)
    api.stop_download()
    api._run("https://youtu.be/x", str(_ISO), False, True, "en", "lossless", "none", None)
    ok(api.poll()["result"] == "cancelled", "отменённая загрузка с ошибкой = cancelled",
       repr(api.poll()["result"]))

    # 4. фронтенд знает все итоги
    section("4. app.js и i18n знают про эти итоги")
    app_js = (ROOT / "ui_src" / "app.js").read_text(encoding="utf-8")
    match = re.search(r"DL_RESULT\s*=\s*\{([^}]*)\}", app_js)
    ok(bool(match), "в app.js есть таблица DL_RESULT")
    front = set(re.findall(r"""['"]?(\w+)['"]?\s*:""", match.group(1))) if match else set()
    produced = {"ok", "error", "cancelled"}
    ok(front == produced, "app.js ждёт ровно те итоги, что отдаёт Api",
       f"в app.js {sorted(front)}, бэкенд отдаёт {sorted(produced)}")
    ok("st.result" in app_js, "tick() передаёт result из poll() в кнопку")
    ok("dlShown" in app_js, "показанный итог запоминается (иконка не мигает)")

    i18n.load_languages()
    keys = ["btn.downloading", "btn.done", "btn.failed", "btn.cancelled"]
    missing = {lang: [k for k in keys if not i18n.I18N.get(lang, {}).get(k)]
               for lang in i18n.LANGUAGES}
    missing = {lang: v for lang, v in missing.items() if v}
    ok(not missing, "подписи итогов есть во всех языках", str(missing))
    ok(any(i18n.I18N.get("ru", {}).get("btn.done") == "Готово" for _ in (0,)),
       "русская подпись успеха на месте")

    # 5. что именно скачалось: счёт по info
    section("5. _download_counts считает по filepath, а не по записям")
    counts = downloader._download_counts
    cases = [
        ("нет info (сеть отвалилась)", None, (0, 0)),
        ("одно видео скачано", {"filepath": "a.mp4"}, (1, 1)),
        ("одно видео без файла", {"title": "a"}, (0, 1)),
        ("плейлист 3 из 5, двое не извлечены",
         {"_type": "playlist", "entries": [{"filepath": "1.mp4"}, {"filepath": "2.mp4"},
                                           {"filepath": "3.mp4"}, None, None]}, (3, 5)),
        ("плейлист 3 из 5, двое не скачаны",
         {"_type": "playlist", "entries": [{"filepath": "1.mp4"}, {"filepath": "2.mp4"},
                                           {"filepath": "3.mp4"}, {"title": "4"},
                                           {"title": "5"}]}, (3, 5)),
        ("пустой плейлист", {"_type": "playlist", "entries": []}, (0, 0)),
        ("вложенный плейлист",
         {"_type": "playlist", "entries": [
             {"filepath": "1.mp4"},
             {"_type": "playlist", "entries": [{"filepath": "2.mp4"}, None]}]}, (2, 3)),
    ]
    for label, info, want in cases:
        got = counts(info)
        ok(got == want, label, f"получили {got}, ждали {want}")

    # 6. строка статуса по итогу, а не по флагу ошибок
    section("6. статус говорит, что не так, а не «были ли ошибки»")
    api._cancel = False   # как в start_download(): прошлая отмена не должна висеть
    for mode, ok_n, total_n, key, wrong in [
        ("ok", 1, 1, "p.ready", "p.done_partial"),
        ("partial", 3, 5, "p.done_partial", "p.failed"),
        ("failed", 0, 1, "p.failed", "p.done_partial"),
        ("warn", 5, 5, "p.done_warn", "p.done_partial"),
        ("что-то незнакомое", 0, 0, "p.ready", "p.done_partial"),
    ]:
        run(api, FakeDownloader(failed=True, mode=mode, ok=ok_n, total=total_n))
        got = api.poll()["status"]
        want = i18n.tr("en", key, ok=ok_n, total=total_n)
        ok(got == want, f"{mode} -> {key}", f"{got!r} != {want!r}")
        ok(got != i18n.tr("en", wrong, ok=ok_n, total=total_n),
           f"{mode} не показывает {wrong}", repr(got))

    # обрыв связи на одном видео: «часть файлов» тут быть не может
    run(api, FakeDownloader(failed=True, mode="failed"))
    single = api.poll()["status"]
    ok(single == i18n.tr("en", "p.failed"), "обрыв на одном видео -> p.failed", repr(single))
    ok("{ok}" not in i18n.tr("en", "p.failed") and "{ok}" in i18n.tr("en", "p.done_partial"),
       "счётчики только в сообщении про частичный провал")

    run(api, FakeDownloader(boom=True))
    ok(api.poll()["status"] == i18n.tr("en", "p.failed"),
       "исключение в _run -> p.failed, а не «Готов»")
    api._cancel = True    # отмена нажата во время загрузки, итог - частичный
    run(api, FakeDownloader(failed=True, mode="partial", ok=3, total=5))
    cancelled = api.poll()["status"]
    api._cancel = False
    ok(cancelled == i18n.tr("en", "p.cancelled"), "отмена перекрывает «часть файлов»", repr(cancelled))

    # 7. переводы новых итогов
    section("7. итоги переведены во всех языках")
    keys = ["p.failed", "p.done_warn", "p.done_partial"]
    missing = {lang: [k for k in keys if not i18n.I18N.get(lang, {}).get(k)]
               for lang in i18n.LANGUAGES}
    missing = {lang: v for lang, v in missing.items() if v}
    ok(not missing, "p.failed/p.done_warn/p.done_partial есть во всех языках", str(missing))
    no_counts = {lang: k for lang in i18n.LANGUAGES
                 for k in keys if "{ok}" in i18n.I18N.get(lang, {}).get(k, "")
                 and "{total}" not in i18n.I18N.get(lang, {}).get(k, "")}
    ok(not no_counts, "везде, где есть {ok}, есть и {total}", str(no_counts))
    leftovers = {lang: k for lang in i18n.LANGUAGES
                 for k in keys if "{ok}" in i18n.tr(lang, k, ok=1, total=2)}
    ok(not leftovers, "подстановка ok/total не оставляет плейсхолдеров", str(leftovers))

    # 8. старая установка: свой файл перевода не должен вернуть старый текст
    # load_languages() отдаёт файлу приоритет над встроенной таблицей, поэтому
    # менять текст существующего ключа нельзя - на уже настроенной машине он
    # останется старым навсегда. Поэтому все новые итоги - новые ключи.
    section("8. свой файл перевода не возвращает старые формулировки")
    lang_dir = _ISO / "Synfronia" / "language"
    lang_dir.mkdir(parents=True, exist_ok=True)
    (lang_dir / "en.json").write_text(json.dumps({
        "p.done_errors": "Done with errors - some files were not downloaded.",
        "p.ready": "Ready.",
    }, ensure_ascii=False), encoding="utf-8")
    i18n.load_languages()
    ok("p.done_errors" not in i18n.I18N["ru"],
       "старый ключ про «часть файлов» убран из встроенных переводов")
    got = i18n.tr("en", "p.done_partial", ok=3, total=5)
    ok(got == "Done with errors - downloaded 3 of 5.",
       "частичный провал со счётчиками даже со своим файлом перевода", repr(got))
    ok("some files" not in i18n.tr("en", "p.done_partial", ok=3, total=5),
       "старая формулировка про «часть файлов» нигде не всплывает")
    run(api, FakeDownloader(failed=True, mode="partial", ok=3, total=5))
    ok(api.poll()["status"] == "Done with errors - downloaded 3 of 5.",
       "статус со своим файлом перевода показывает счётчики", repr(api.poll()["status"]))

    print(f"\nитог: {_checks - len(_fails)}/{_checks} ok")
    if _fails:
        print("провалено: " + ", ".join(_fails))
        return 1
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_ISO, ignore_errors=True)
    raise SystemExit(code)
