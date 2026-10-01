r"""Push-канал событий + heartbeat опроса (этап 5 дорожной карты).

Гибрид: события будят страницу немедленно (Api._ping -> очередь ->
единственный диспетчерский поток -> evaluate_js("__synfPing")), а сам
опрос стал heartbeat - раз в секунду полный снапшот (app.js HEARTBEAT).
Контракт, который здесь держим:

  1. тексты: в gui.py одна точка evaluate_js (диспетчер), в app.js
     heartbeat-константа и приёмник __synfPing, в perf-чеке порог <= 1/с;
  2. пинги идут из всех точек изменения состояния (_log, прогресс,
     busy-переходы, _bump_ui) и всегда ПОСЛЕ записи под lock;
  3. очередь коалесцирует всплеск: 50 пингов до старта диспетчера ->
     ровно одно пробуждение страницы;
  4. диспетчер один на сессию (повторный bind не плодит потоки) и живёт
     после исключения evaluate_js (страница перезагружается).

Запуск:  python tools/check_push_channel.py
"""

import sys
import tempfile
import time
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


class FakeWin:
    """Окно-рекордер: запоминает evaluate_js; можно включить режим «краха»."""

    def __init__(self, boom: bool = False):
        self.calls: list[str] = []
        self.boom = boom

    def evaluate_js(self, code: str):
        if self.boom:
            raise RuntimeError("window is reloading")
        self.calls.append(code)
        return None


def wait_for(cond, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def main() -> int:
    # изолируем файл настроек (как в check_settings)
    import os
    iso = Path(tempfile.mkdtemp(prefix="synf-check-push-"))
    os.environ["LOCALAPPDATA"] = str(iso)

    section("1. тексты: одна точка evaluate_js, heartbeat, приёмник")
    gui_src = (ROOT / "gui.py").read_text(encoding="utf-8")
    app_js = (ROOT / "ui_src" / "app.js").read_text(encoding="utf-8")
    perf_js = (ROOT / "tools" / "ui_perf_probe.js").read_text(encoding="utf-8")
    ok(gui_src.count("win.evaluate_js(") == 1,
       "в gui.py evaluate_js ровно в одном месте (диспетчер)",
       str(gui_src.count("win.evaluate_js(")))
    ok('self._js_queue: queue.Queue = queue.Queue()' in gui_src
       and 'name="js-dispatch"' in gui_src,
       "очередь и единственный диспетчерский поток описаны в Api")
    ok("def _ping(self)" in gui_src and "def _js_dispatch(self)" in gui_src,
       "в Api есть _ping и _js_dispatch")
    ok(gui_src.count("self._ping()") >= 10,
       "пинги стоят во всех точках изменения состояния",
       str(gui_src.count("self._ping()")))
    ok("busy-переход виден сразу" in gui_src and gui_src.count("busy-переход виден сразу") == 2,
       "busy-переходы start/start_bulk будят страницу")
    ok("self._ping()   # клик «Отмена» виден мгновенно" in gui_src
       or "self._ping()   # клик" in gui_src,
       "stop_download будит страницу после записи статуса")
    ok("var HEARTBEAT = 1000" in app_js, "app.js: heartbeat 1 с")
    ok("window.__synfPing" in app_js, "app.js: приёмник события __synfPing")
    ok("scheduleTick(HEARTBEAT)" in app_js, "app.js: следующий тик по heartbeat")
    ok("tickInFlight" in app_js and "pingPending" in app_js,
       "app.js: пинг во время тика не наслаивает конкурентный poll")
    ok("scheduleTick(200)" not in app_js, "app.js: частый опрос 200 мс убран")
    ok("pollRate > 1.5" in perf_js and "6.5" not in perf_js,
       "perf-чек: порог пробуждений включён (<= 1.5/с)")

    section("2. пинги идут после записи состояния")
    import gui
    api = gui.Api()
    # журнал
    api._log("info", "push-test")
    got = []
    while True:
        try:
            got.append(api._js_queue.get_nowait())
        except Exception:
            break
    ok(got == ["@ping"], "_log будит страницу", str(got))
    # прогресс
    api._on_progress({"status": "downloading", "percent": 10.0,
                      "filename": "a.mp4", "speed": 1, "eta": 5})
    ok(api._js_queue.get_nowait() == "@ping", "_on_progress будит страницу")
    # после _cancel изменения нет - и пинга нет
    api._cancel = True
    api._on_progress({"status": "downloading", "percent": 20.0,
                      "filename": "a.mp4", "speed": 1, "eta": 5})
    quiet = True
    try:
        api._js_queue.get_nowait()
        quiet = False
    except Exception:
        pass
    ok(quiet, "после _cancel прогресс не пишется и не будит")
    api._cancel = False
    # смена языка/темы/шрифтов
    api._bump_ui()
    ok(api._js_queue.get_nowait() == "@ping", "_bump_ui будит страницу")
    # из чужого потока (воркеры)
    import threading
    t = threading.Thread(target=api._ping)
    t.start()
    t.join()
    ok(api._js_queue.get_nowait() == "@ping", "_ping работает из чужого потока")

    section("3. диспетчер: всплеск -> одно пробуждение, один поток")
    for _ in range(50):
        api._js_queue.put("@ping")   # окно ещё не привязано
    win = FakeWin()
    api.bind_main_window(win)
    ok(wait_for(lambda: len(win.calls) >= 1), "диспетчер доставил пинг")
    time.sleep(0.25)   # дать всплеску схлопнуться полностью
    ok(len(win.calls) <= 3,
       "всплеск из 50 пингов схлопнулся почти в одно пробуждение",
       str(len(win.calls)))
    ok(all("__synfPing" in c for c in win.calls),
       "доставлен именно __synfPing", str(win.calls[:2]))
    ok(api._js_thread is not None and api._js_thread.is_alive(),
       "диспетчерский поток жив")
    same = api._js_thread
    api.bind_main_window(FakeWin())   # повторный bind (не должен плодить)
    time.sleep(0.1)
    ok(api._js_thread is same, "повторный bind не создаёт второй поток")

    section("4. исключение evaluate_js не убивает диспетчера")
    api._win_main = FakeWin(boom=True)
    api._ping()
    time.sleep(0.25)   # вызов упал внутри - поток обязан выжить
    ok(api._js_thread.is_alive(), "диспетчер пережил крах evaluate_js")
    good = FakeWin()
    api._win_main = good
    api._ping()
    ok(wait_for(lambda: len(good.calls) >= 1), "и продолжает доставлять дальше")

    print(f"\nитог: {_checks - len(_fails)}/{_checks} ok")
    if _fails:
        print("провалено: " + ", ".join(_fails))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
