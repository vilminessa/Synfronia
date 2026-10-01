r"""Проверка надзора WebView2: урок инцидентов «тёмное окно» (01.10.2026).

Пользователь: «заметил, зависло с тёмным экраном». Разбор: браузерный процесс
msedgewebview2 падал с ACCESS_VIOLATION в одном и том же месте - внутри
внедрённого хука RTSSHooks64.dll (RivaTuner/Afterburner, смещение +0x1490af),
и с GPU, и с --disable-gpu. Эксперимент 01.10 (27 прогонов при живом RTSS):
RTSS внедряется в 100% запусков, контроль выжил 0/6 падений, ни один флаг не
побил контроль, вероятность падения ~15% за запуск - то есть лечится не
флагами, а ПОВТОРАМИ (MAX_ATTEMPTS), а диагностика обязана называть модуль.

Здесь проверяется логика, вынесенная из main() (gui.guard_webview,
dead_action, crash_hint, apply_render_env), парсер дампов (paths) и след:

  1. живой потомок + закрытие окна -> обычный выход, следа нет;
  2. потомок так и не появился -> "never-spawned" (как старый сторож);
  3. потомок был, потом умер -> "crashed" ровно после нужного числа промахов;
  4. одиночный промах (моргнул) не срабатывает;
  5. closing важнее краша: выход пользователя не порождает ложный след;
  6. решение о перезапуске: busy -> не убиваем загрузку; попытка 1 и 2 ->
     restart; попытка MAX_ATTEMPTS -> give-up (петля невозможна);
  7. --disable-gpu ставится только по ручке рендеринга, гасится
     SYNFRONIA_WEBVIEW_GPU=1 и не портит чужие аргументы; номер попытки
     никаких флагов не добавляет;
  8. парсер minidump: по синтетическому дампу находит модуль и смещение,
     битый файл -> None, след содержит модуль, подсказка называет RTSS;
  9. в gui.py не вернулся паттерн «проверил и вышел».

    python tools\check_webview_guard.py
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# изолируем настройки, логи и профиль WebView2 до импорта gui
_ISO = Path(tempfile.mkdtemp(prefix="synf-check-guard-"))
os.environ["LOCALAPPDATA"] = str(_ISO)

import gui  # noqa: E402
from paths import crash_evidence, minidump_fault  # noqa: E402


def write_minidump(path, *, base=0x180000000, size=0x267000, off=0x1490af,
                   code=0xC0000005, name="RTSSHooks64.dll") -> None:
    """Синтетический minidump той раскладки, что у Crashpad.

    Заголовок MDMP -> каталог потоков (offset 32): поток 6 - исключение
    (код и адрес), поток 4 - список модулей, имя модуля - MINIDUMP_STRING
    (длина в байтах + UTF-16). Достаточно ровно того, что читает
    paths.minidump_fault; бинарных файлов в репозитории не появляется.
    """
    import struct

    parts = bytearray(460)
    parts[0:4] = b"MDMP"
    struct.pack_into("<I", parts, 8, 2)              # NumberOfStreams
    struct.pack_into("<I", parts, 12, 32)            # StreamDirectoryRva
    struct.pack_into("<III", parts, 32, 6, 160, 56)  # ExceptionStream -> 56
    struct.pack_into("<III", parts, 44, 4, 160, 240)  # ModuleListStream -> 240
    struct.pack_into("<I", parts, 64, code)          # ExceptionCode
    struct.pack_into("<Q", parts, 80, base + off)    # ExceptionAddress
    struct.pack_into("<I", parts, 88, 0)             # NumberParameters
    struct.pack_into("<I", parts, 240, 1)            # NumberOfModules
    struct.pack_into("<Q", parts, 244, base)         # BaseOfImage
    struct.pack_into("<I", parts, 252, size)         # SizeOfImage
    struct.pack_into("<I", parts, 264, 352)          # ModuleNameRva
    encoded = name.encode("utf-16le")
    struct.pack_into("<I", parts, 352, len(encoded))
    parts[356:356 + len(encoded)] = encoded
    Path(path).write_bytes(bytes(parts))

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

    # 6. решение о перезапуске (повторы вместо флагов)
    section("6. решение о перезапуске")
    ok(gui.dead_action(busy=True, attempt=1) == "busy",
       "идёт загрузка -> не убиваем работу")
    ok(gui.dead_action(busy=True, attempt=gui.MAX_ATTEMPTS) == "busy",
       "busy главнее исчерпания попыток (детерминированно)")
    ok(gui.dead_action(busy=False, attempt=1) == "restart",
       "первая попытка -> перезапуск")
    ok(gui.dead_action(busy=False, attempt=2) == "restart",
       "вторая попытка -> перезапуск")
    ok(gui.dead_action(busy=False, attempt=gui.MAX_ATTEMPTS) == "give-up",
       f"попытка {gui.MAX_ATTEMPTS} -> честный отказ, петли нет",
       gui.dead_action(busy=False, attempt=gui.MAX_ATTEMPTS))
    ok(gui.MAX_ATTEMPTS >= 2, "перезапуск вообще предусмотрен", str(gui.MAX_ATTEMPTS))

    # 7. --disable-gpu
    section("7. аргумент --disable-gpu")
    args = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"

    def clear():
        for key in (args, "SYNFRONIA_WEBVIEW_ATTEMPT", "SYNFRONIA_WEBVIEW_GPU"):
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
    os.environ["SYNFRONIA_WEBVIEW_ATTEMPT"] = "3"
    gui.apply_render_env({"render_gpu": True})
    ok(os.environ.get(args) is None,
       "номер попытки не добавляет флагов (повтор = обычный запуск)",
       repr(os.environ.get(args)))
    clear()
    os.environ["SYNFRONIA_WEBVIEW_GPU"] = "1"
    gui.apply_render_env({"render_gpu": False})
    ok(os.environ.get(args) is None,
       "SYNFRONIA_WEBVIEW_GPU=1 возвращает GPU (отладка)", repr(os.environ.get(args)))
    clear()

    # 8. парсер дампа и след разбора
    section("8. парсер minidump и след crash_evidence")
    reports = _ISO / "Synfronia" / "webview" / "EBWebView" / "Crashpad" / "reports"
    reports.mkdir(parents=True)
    text = crash_evidence()
    ok("дамп Crashpad: нет" in text and "LiveKernelEvent" in text,
       "без дампа след честно говорит «нет»", repr(text))
    bad = reports / "bad.dmp"
    bad.write_bytes(b"MZ not a dump")
    ok(minidump_fault(bad) is None, "битый дамп -> None, а не исключение")
    ok(minidump_fault(reports / "нет-такого.dmp") is None,
       "отсутствующий дамп -> None")
    # синтетический дамп той же раскладки, что у Crashpad - и он самый свежий
    # (свежесть управляется mtime явно: разные файлы в одну секунду не различить)
    dump = reports / "fixture.dmp"
    write_minidump(dump)
    now = time.time()
    os.utime(bad, (now - 60, now - 60))
    os.utime(dump, (now, now))
    fault = minidump_fault(dump)
    ok(bool(fault) and fault.get("module") == "RTSSHooks64.dll"
       and fault.get("offset") == 0x1490af and fault.get("code") == 0xC0000005,
       "парсер находит модуль, смещение и код исключения", repr(fault))
    line = crash_evidence()
    ok("fixture.dmp" in line and "модуль: RTSSHooks64.dll (+0x1490af)" in line
       and "ACCESS_VIOLATION" in line,
       "след называет дамп, модуль и исключение", repr(line))
    # подсказка: чужой внедрённый хук - назвать владельца, остальное молчать
    ok("RivaTuner" in gui.crash_hint(
        r"C:\Program Files (x86)\RivaTuner Statistics Server\RTSSHooks64.dll"),
       "чужой хук назван вместе с владельцем")
    ok(gui.crash_hint(r"C:\Windows\System32\foo.dll") == "",
       "неизвестный модуль подсказки не даёт")
    ok(gui.crash_hint(None) == "", "без модуля подсказки нет")

    # 9. паттерн «проверил и вышел» не вернулся
    section("9. надзор не выходит после первого успеха")
    src = (ROOT / "gui.py").read_text(encoding="utf-8")
    ok("guard_webview(" in src, "main() использует guard_webview")
    ok("for _ in range(40)" not in src, "старый цикл «40 проверок и выход» убран")
    ok('env["SYNFRONIA_WEBVIEW_ATTEMPT"] = str(next_no)' in src,
       "перезапуск несёт номер следующей попытки")
    ok("dead_action(busy=bool(api._busy), attempt=attempt)" in src,
       "решение принимается по номеру попытки")
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
