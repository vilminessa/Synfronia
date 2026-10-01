r"""Проверка надзора WebView2: урок инцидента «тёмное окно» (01.10.2026).

Пользователь: «заметил, зависло с тёмным экраном». Разбор: браузерный процесс
msedgewebview2 (падение --webview-exe-name=python.exe, дамп Crashpad 9,26 МБ,
0xC0000005 в GPU/ DXGI-пути) упал через 5 с после показа окна, а окно pywebview
пережило краш и осталось тёмным. Оба сторожа (gui._guard и debug.wait_for_ready)
проверяли живость ОДИН раз и выходили, поэтому падение осталось незамеченным:
за пределами первой проверки надзора уже не было.

Здесь проверяется логика, вынесенная из main() (gui.guard_webview,
dead_action, apply_render_env) и след (paths.crash_evidence):

  1. живой потомок + закрытие окна -> обычный выход, следа нет;
  2. потомок так и не появился -> "never-spawned" (как старый сторож);
  3. потомок был, потом умер -> "crashed" ровно после нужного числа промахов;
  4. одиночный промах (моргнул) не срабатывает;
  5. closing важнее краша: выход пользователя не порождает ложный след;
  6. решение о перезапуске: обычная сессия -> restart, busy -> не убиваем
     загрузку, CPU-сессия -> без петли «краш-батут»;
  7. --disable-gpu ставится по ручке рендеринга и по флагу CPU-сессии,
     гасится SYNFRONIA_WEBVIEW_GPU=1 и не портит чужие аргументы;
  8. в gui.py не вернулся паттерн «проверил и вышел».

    python tools\check_webview_guard.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# изолируем настройки, логи и профиль WebView2 до импорта gui
_ISO = Path(tempfile.mkdtemp(prefix="synf-check-guard-"))
os.environ["LOCALAPPDATA"] = str(_ISO)

import gui  # noqa: E402
from paths import crash_evidence  # noqa: E402

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


def close_after(ticks_needed: int):
    """Закрытие окна через N проверок - чтобы симуляция гарантированно кончалась."""
    state = {"n": 0}

    def closing():
        state["n"] += 1
        return state["n"] > ticks_needed

    return closing


def run_guard(alive, closing=lambda: False, *, seen_first=0, **kw):
    """Гонит guard_webview с фиксированным сценарием; возвращает (результат, следы).

    seen_first - сколько первых проверок потомок жив (моргание/старт);
    потом последовательность alive остаётся в живых до конца симуляции.
    """
    calls: list[str] = []
    state = {"n": 0}

    def alive_seq():
        state["n"] += 1
        return state["n"] <= seen_first or alive(state["n"])

    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("tick", 0.5)
    kw.setdefault("spawn_timeout", 5)
    res = gui.guard_webview(alive_seq, closing, calls.append, **kw)
    return res, calls


def main() -> int:
    # 1. нормальный выход
    section("1. живой WebView2 и закрытие окна")
    res, calls = run_guard(lambda n: True, close_after(2))
    ok(res == "closed" and not calls, "надзор замолчал при закрытии окна",
       f"res={res} calls={calls}")

    # 2. потомок не создался вообще (как старый сторож - но с причиной)
    section("2. потомок не появился")
    res, calls = run_guard(lambda n: False)
    ok(res == "dead" and calls == ["never-spawned"], "сработал «никогда не spawn-нулся»",
       f"res={res} calls={calls}")

    # 3. краш после показа - тот самый инцидент
    section("3. краш после показа окна")
    res, calls = run_guard(lambda n: n <= 3, seen_first=0, misses_needed=3)
    ok(res == "dead" and calls == ["crashed"], "падение поймано с причиной crashed",
       f"res={res} calls={calls}")

    # 4. одиночный промах - не приговор
    section("4. одиночный промах живости")
    res, calls = run_guard(lambda n: n != 5, close_after(40), seen_first=10,
                           misses_needed=3)
    ok(res == "closed" and not calls, "моргание не дало ложного срабатывания",
       f"res={res} calls={calls}")

    # 5. выход пользователя важнее краша (ловушка подменённого webview из истории)
    section("5. closing важнее краша")
    res, calls = run_guard(lambda n: False, close_after(7), seen_first=5,
                           misses_needed=3)
    ok(res == "closed" and not calls,
       "закрытие окна прервало накопление промахов без следа",
       f"res={res} calls={calls}")

    # 6. решение о перезапуске
    section("6. решение о перезапуске")
    ok(gui.dead_action(busy=False, cpu_session=False) == "restart",
       "обычная сессия -> перезапуск")
    ok(gui.dead_action(busy=True, cpu_session=False) == "busy",
       "идёт загрузка -> не убиваем работу")
    ok(gui.dead_action(busy=False, cpu_session=True) == "cpu-again",
       "CPU-сессия -> без петли «краш-батут»")
    ok(gui.dead_action(busy=True, cpu_session=True) == "cpu-again",
       "CPU-сессия главнее busy (детерминированно)")

    # 7. --disable-gpu
    section("7. аргумент --disable-gpu")
    args = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"

    def clear():
        for key in (args, "SYNFRONIA_WEBVIEW_CPU", "SYNFRONIA_WEBVIEW_GPU"):
            os.environ.pop(key, None)

    clear()
    gui.apply_render_env({})
    ok(os.environ.get(args) is None, "GPU по умолчанию не трогаем",
       repr(os.environ.get(args)))
    gui.apply_render_env({"render_gpu": False})
    gui.apply_render_env({"render_gpu": False})
    ok(os.environ.get(args) == "--disable-gpu",
       "ручка выключена -> флаг добавлен и не дублируется",
       repr(os.environ.get(args)))
    clear()
    os.environ[args] = "--remote-debugging-port=9222"
    gui.apply_render_env({"render_gpu": False})
    ok(os.environ.get(args) == "--remote-debugging-port=9222 --disable-gpu",
       "чужие аргументы не затираются", repr(os.environ.get(args)))
    clear()
    os.environ["SYNFRONIA_WEBVIEW_CPU"] = "1"
    gui.apply_render_env({"render_gpu": True})
    ok(os.environ.get(args) == "--disable-gpu",
       "CPU-сессия (ребёнок после краша) -> флаг ставится сам",
       repr(os.environ.get(args)))
    clear()
    os.environ["SYNFRONIA_WEBVIEW_GPU"] = "1"
    gui.apply_render_env({"render_gpu": False})
    ok(os.environ.get(args) is None,
       "SYNFRONIA_WEBVIEW_GPU=1 возвращает GPU (отладка)", repr(os.environ.get(args)))
    clear()

    # 8. след разбора
    section("8. след crash_evidence")
    text = crash_evidence()
    ok("дамп Crashpad:" in text and "LiveKernelEvent" in text,
       "строка содержит дамп и LiveKernelEvent", repr(text))
    reports = _ISO / "Synfronia" / "webview" / "EBWebView" / "Crashpad" / "reports"
    reports.mkdir(parents=True)
    (reports / "fake.dmp").write_bytes(b"MZ")
    ok("fake.dmp" in crash_evidence(), "свежий дамп попадает в след",
       repr(crash_evidence()))

    # 9. паттерн «проверил и вышел» не вернулся
    section("9. надзор не выходит после первого успеха")
    src = (ROOT / "gui.py").read_text(encoding="utf-8")
    ok("guard_webview(" in src, "main() использует guard_webview")
    ok("for _ in range(40)" not in src, "старый цикл «40 проверок и выход» убран")
    ok('env["SYNFRONIA_WEBVIEW_CPU"] = "1"' in src,
       "перезапуск ставит SYNFRONIA_WEBVIEW_CPU=1")
    ok("os._exit(0)" in src, "после перезапуска процесс уходит (тёмное окно не висит)")
    ok("closing=lambda:" in src, "надзор слушает закрытие окна")

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
