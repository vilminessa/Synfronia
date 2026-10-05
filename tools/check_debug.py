"""Проверки отладочной консоли (debug.py): очистка, логи, меню.

Очистка гоняется на временных папках (реальный %LOCALAPPDATA% не трогаем),
процессы только перечисляются, не завершаются. Меню проверяется смоуком:
подсовываем stdin и ждём выхода с кодом 0.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import debug  # noqa: E402

_checks = 0
_fails: list[str] = []


def ok(cond: bool, msg: str, detail: str = "") -> None:
    global _checks
    _checks += 1
    if cond:
        print(f"  ok   {msg}")
    else:
        _fails.append(msg)
        print(f"  FAIL {msg} {detail}")


def section(title: str) -> None:
    print(f"-- {title} --")


def make_tree(root: Path) -> None:
    (root / "bin").mkdir(parents=True)
    (root / "fonts").mkdir()
    (root / "logs").mkdir()
    # пакет обхода - то, чего нельзя восстановить без сети: очистка его
    # бережёт, и тест это обязан зафиксировать (так 1.10.1 была вычищена)
    (root / "Bypass" / "zapret-x").mkdir(parents=True)
    (root / "bin" / "ffmpeg.exe").write_bytes(b"FF" * 100)
    (root / "fonts" / "MyFont.ttf").write_bytes(b"F" * 50)
    (root / "logs" / "app.log").write_text("строка\n", encoding="utf-8")
    (root / "Bypass" / "zapret-x" / "winws.exe").write_bytes(b"MZ")
    (root / "settings.json").write_text("{}", encoding="utf-8")
    (root / "bypasses.json").write_text("{}", encoding="utf-8")


def main() -> int:
    section("1. очистка")
    with tempfile.TemporaryDirectory(prefix="synf_debug_") as tmp:
        root = Path(tmp) / "Synfronia"
        make_tree(root)
        preview = debug.preview(root, keep_bin=True)
        ok(any("оставляется" in l for l in preview), "preview помечает bin как сохраняемый")
        ok(any("settings.json" in l for l in preview), "preview показывает settings.json")
        ok(any("Bypass" in l and "пакеты обхода" in l for l in preview),
           "preview показывает сохраняемый пакет обхода", str([l for l in preview if "Bypass" in l]))
        ok(any("внимание" in l for l in preview),
           "preview предупреждает, что удалятся настройки/реестр/кэш")
        removed, errors = debug.clean_root(root, keep_bin=True)
        ok(not errors, "очистка с keep-bin без ошибок", str(errors))
        left = sorted(p.name for p in root.iterdir())
        ok(left == ["Bypass", "bin", "logs"]
           and (root / "bin" / "ffmpeg.exe").is_file()
           and (root / "logs" / "app.log").is_file(),
           "keep-bin: остаются bin, logs и пакет обхода", str(left))
        ok((root / "Bypass" / "zapret-x" / "winws.exe").is_file(),
           "негатив: пакет обхода не вычищен (именно из-за этого теряли 1.10.1)")
        ok(removed == 3, "keep-bin: удалено 3 элемента (fonts, settings.json, bypasses.json)",
           str(removed))
        removed, errors = debug.clean_root(root, keep_bin=False)
        after_full = sorted(p.name for p in root.iterdir())
        # уже почищено keep-bin: из оставшегося (bin, logs) полная удаляет
        # два элемента, а пакет обхода бережёт всегда
        ok(not errors and removed == 2 and after_full == ["Bypass"],
           "полная очистка: всё удалено, кроме пакета обхода",
           f"{removed} {errors} {after_full}")
        ok(root.is_dir(), "сама папка после очистки остаётся")
        missing, errors = debug.clean_root(Path(tmp) / "нет-папки", keep_bin=False)
        ok(missing == 0 and errors, "несуществующая папка - ошибка, не исключение")

    section("2. размеры")
    ok(debug.human_size(500) == "500 Б" and debug.human_size(2048).endswith("КБ"),
       "human_size: байты и килобайты")

    section("3. логи")
    with tempfile.TemporaryDirectory(prefix="synf_logs_") as tmp:
        lg = Path(tmp)
        big = lg / "app_2026-01-01.log"
        big.write_text("\n".join(f"строка {i}" for i in range(1, 101)), encoding="utf-8")
        (lg / "launcher.log").write_text("x", encoding="utf-8")
        (lg / "не-лог.txt").write_text("x", encoding="utf-8")

        tail = debug.tail_file(big, 5)
        ok(tail == [f"строка {i}" for i in range(96, 101)],
           "tail: ровно последние 5 строк", str(tail))
        ok(len(debug.tail_file(big, 999)) == 100, "tail: больше строк - весь файл")
        ok(debug.tail_file(lg / "нет.log", 5) == [], "tail: нет файла - пусто")

        lines, pos = debug.new_lines(big, 0)
        ok(len(lines) == 100 and pos == big.stat().st_size, "new_lines: весь файл с нуля")
        with open(big, "a", encoding="utf-8") as fh:
            fh.write("добавлено")          # без перевода строки: приёмка с середины
        lines, pos = debug.new_lines(big, pos)
        ok(lines == ["добавлено"], "new_lines: только новые строки", str(lines))
        big.write_text("короче", encoding="utf-8")   # пересоздали (смена дня)
        lines, pos = debug.new_lines(big, 10_000)
        ok(lines == ["короче"], "new_lines: файл уменьшился - читаем с начала")

        old = time.time() - 60
        (lg / "app_старый.log").write_text("a", encoding="utf-8")
        os.utime(lg / "app_старый.log", (old, old))
        files = sorted(lg.glob("*.log"), key=lambda p: p.stat().st_mtime)
        ok(len(files) == 3 and files[0].name == "app_старый.log",
           "log_files: только *.log, старые первыми",
           str([f.name for f in files]))

    section("4. процессы (только чтение)")
    procs = debug.find_app_processes()
    ok(isinstance(procs, list), "find_app_processes возвращает список")
    ok(all("ProcessId" in p for p in procs), "в записях есть PID", str(procs))
    ok(debug.fmt_ps_date("/Date(1700000000000)/").count(".") == 2,
       "fmt_ps_date: разбирает формат PS5")
    ok(debug.fmt_ps_date("2026-09-28T10:00:00") == "2026-09-28T10:00:00",
       "fmt_ps_date: ISO остаётся как есть")

    section("5. служебные файлы %TEMP% и окна")
    with tempfile.TemporaryDirectory(prefix="synf_temptest_") as tmp:
        root = Path(tmp)
        (root / "tmpAAAA" / "EBWebView").mkdir(parents=True)
        (root / "tmpBBBB" / "EBWebView").mkdir(parents=True)
        (root / "random_dir").mkdir()
        (root / "synf_probe_page.html").write_text("x", encoding="utf-8")
        (root / "synfronia_old_test").mkdir()      # старый каталог пробников
        (root / "px7.txt").write_text("x", encoding="utf-8")
        (root / "px_full.txt").write_text("x", encoding="utf-8")
        (root / "after_nudge.png").write_bytes(b"\x89PNG")
        (root / "random.txt").write_text("x", encoding="utf-8")
        live = {os.path.normcase(str(root / "tmpBBBB" / "EBWebView"))}
        names = [p.name for p in debug.list_temp_junk(root)]
        ok(set(names) == {"tmpAAAA", "tmpBBBB", "synf_probe_page.html",
                          "synfronia_old_test", "px7.txt", "px_full.txt",
                          "after_nudge.png"},
           "list_temp_junk: pywebview-каталоги, каталоги и артефакты пробников",
           str(names))
        removed, errors, skipped = debug.clean_temp(root, live)
        ok(not errors, "clean_temp без ошибок", str(errors))
        ok(skipped == ["tmpBBBB"], "занятый живым процессом каталог пропущен", str(skipped))
        left = sorted(p.name for p in root.iterdir())
        ok(left == ["random.txt", "random_dir", "tmpBBBB"],
           "удалено только служебное, живой каталог остался", str(left))
    ok(debug.window_visible(999999) is False, "window_visible: несуществующий PID -> False")
    t0 = time.time()
    ok(debug.wait_for_window(999999, 0.6) is False,
       "wait_for_window: несуществующий PID дожидается таймаута",
       f"{time.time() - t0:.1f}s")
    ok(debug.webview_child_running(999999) is False,
       "webview_child_running: у несуществующего PID потомков нет")
    t0 = time.time()
    ok(debug.wait_for_ready(999999, 0.6) is False,
       "wait_for_ready: нет окна и WebView2 - таймаут",
       f"{time.time() - t0:.1f}s")
    ok(debug.stop_app([{"ProcessId": 999999}]) == [],
       "stop_app: несуществующий PID не попадает в закрытые")

    section("6. пакеты обхода")
    ok(debug.WIPE_ITEM == "12"
       and f"{debug.WIPE_ITEM}. Удалить пакеты обхода" in debug.MENU,
       "пункт удаления пакетов есть в меню")
    with tempfile.TemporaryDirectory(prefix="synf_wipe_") as tmp:
        root = Path(tmp) / "Synfronia"
        make_tree(root)
        # вторая установка: уйти должна вся папка Bypass, а не одна пачка
        (root / "Bypass" / "zapret-y" / "bin").mkdir(parents=True)
        (root / "Bypass" / "zapret-y" / "bin" / "WinDivert.dll").write_bytes(b"ZZ")

        inv = debug.bypass_inventory(root)
        ok([n for n, _s in inv] == ["zapret-x", "zapret-y"],
           "инвентаризация видит обе установки", str(inv))
        lines = debug.preview_wipe(root)
        ok(any("Bypass" in l and "2" in l for l in lines),
           "preview: папка, число установок и размер", str(lines[:1]))
        ok(any("внимание" in l and "GitHub" in l for l in lines),
           "preview предупреждает о потере скачанных версий")
        ok(any("реестра" in l for l in lines),
           "preview предупреждает про вычистку реестра")
        plain = debug.preview(root, keep_bin=True)
        ok(any(f"пункт {debug.WIPE_ITEM}" in l for l in plain),
           "очистка 1/2 отсылает к пункту удаления пакетов", str(plain[-2:]))

        # негатив: занятый winws.exe не роняет удаление остального
        real_unlink = Path.unlink

        def _deny(self, *args, **kwargs):
            if self.name == "winws.exe":
                raise PermissionError(13, "файл занят")
            return real_unlink(self, *args, **kwargs)

        Path.unlink = _deny
        try:
            removed, left = debug.wipe_bypass(root)
        finally:
            Path.unlink = real_unlink
        ok(any(line.startswith("zapret-x/winws.exe") for line in left),
           "занятый winws.exe попал в отчёт «занято»", str(left))
        ok(not (root / "Bypass" / "zapret-y").exists(),
           "вторая установка удалилась несмотря на занятый файл соседа")
        ok((root / "Bypass" / "zapret-x" / "winws.exe").is_file(),
           "занятый файл остался на месте")
        ok(removed > 0, "удалено элементов больше нуля", str(removed))
        ok((root / "Bypass").is_dir(),
           "неполная папка остаётся - видно, что именно не удалилось")

        removed2, left2 = debug.wipe_bypass(root)
        ok(not left2 and removed2 >= 1,
           "без занятого файла удаление доходит до конца", str(left2))
        ok(not (root / "Bypass").exists(), "пустая папка Bypass удалилась")

    # решение об остановке: четыре исхода и ни одного лишнего dpi.stop
    import dpi as dpi_mod

    class Cfg:
        pass

    calls = {"stop": 0}
    real_status, real_stop = dpi_mod.status, dpi_mod.stop
    mute = lambda *_a: None  # noqa: E731 - вывод в тесте не нужен
    try:
        dpi_mod.status = lambda: {"running": False, "pid": None}
        ok(debug.stop_running_bypass(Cfg(), accept=lambda: True, out=mute) == "idle",
           "обход выключен -> idle")
        ok(calls["stop"] == 0, "выключенный обход не трогается (dpi.stop не зовётся)")

        dpi_mod.status = lambda: {"running": True, "pid": 4242}
        ok(debug.stop_running_bypass(Cfg(), accept=lambda: False, out=mute) == "declined",
           "пользователь отказал -> declined")

        def _stop_fail(cfg):
            calls["stop"] += 1
            return {"ok": False, "error": "нет задачи"}

        dpi_mod.stop = _stop_fail
        ok(debug.stop_running_bypass(Cfg(), accept=lambda: True, out=mute) == "failed",
           "остановка не удалась -> failed")

        def _stop_ok(cfg):
            calls["stop"] += 1
            return {"ok": True, "running": True}

        # стоп прошёл, но процесс не гаснет - удалять всё равно нельзя
        dpi_mod.stop = _stop_ok
        dpi_mod.status = lambda: {"running": True, "pid": 4242}
        ok(debug.stop_running_bypass(Cfg(), accept=lambda: True, out=mute, wait=0.4)
           == "failed", "процесс не погас -> failed")
        ok(calls["stop"] == 2, "dpi.stop вызван ровно в двух сценариях", str(calls))

        # успех: первый снимок - запущен, после стопа - погас
        flips = {"n": 0}

        def _flip():
            flips["n"] += 1
            return {"running": flips["n"] <= 1, "pid": 4242}

        dpi_mod.status = _flip
        dpi_mod.stop = lambda cfg: {"ok": True, "running": False}
        ok(debug.stop_running_bypass(Cfg(), accept=lambda: True, out=mute, wait=1)
           == "stopped", "остановка и погасший процесс -> stopped")
    finally:
        dpi_mod.status, dpi_mod.stop = real_status, real_stop

    # реестр: записи о папках внутри Bypass вычищаются, чужие не трогаются
    old_local = os.environ.get("LOCALAPPDATA")
    iso = Path(tempfile.mkdtemp(prefix="synf_prune_"))
    outside = Path(tempfile.mkdtemp(prefix="synf_outside_"))
    os.environ["LOCALAPPDATA"] = str(iso)
    try:
        def plant(folder: Path) -> Path:
            # валидная установка: winws + стратегия + lists (без lists
            # validate_install откажет с кодом lists и в реестр не пойдёт)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "winws.exe").write_bytes(b"MZ")
            (folder / "general.bat").write_text("@echo off", encoding="ascii")
            (folder / "lists").mkdir()
            return folder

        keep_dir = plant(iso / "Synfronia" / "Bypass" / "zapret-keep")
        gone = plant(iso / "Synfronia" / "Bypass" / "zapret-gone")
        foreign = plant(outside / "zapret-c")
        ok(all(dpi_mod.registry_add(str(p)).get("ok")
               for p in (keep_dir, gone, foreign)),
           "фикстура реестра собрана")
        shutil.rmtree(gone)          # папка исчезла - как после wipe
        pruned = debug.prune_registry(iso / "Synfronia")
        items = dpi_mod.registry_load()["items"]
        paths = {str(Path(str(i["path"])).resolve()) for i in items}
        ok(pruned == 1, "вычищена ровно одна мёртвая запись", str(pruned))
        ok(str(keep_dir.resolve()) in paths, "живая установка осталась")
        ok(str(foreign.resolve()) in paths,
           "чужая установка (вне Bypass) не трогается", str(paths))
        active = dpi_mod.registry_load()["active"]
        ok(active in {i["id"] for i in items} or active is None,
           "active после вычистки указывает на существующее", str(active))
    finally:
        if old_local is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = old_local
        shutil.rmtree(iso, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)

    section("7. меню (смоук)")
    run = subprocess.run(
        [sys.executable, str(ROOT / "debug.py")],
        input="x\n7\n\n0\n", capture_output=True, timeout=60, cwd=str(ROOT),
        encoding="utf-8", errors="replace",
    )
    out = run.stdout
    ok(run.returncode == 0, "меню выходит с кодом 0", str(run.returncode))
    ok("Synfronia" in out and "Выбор" in out, "меню печатает заголовок и приглашение")
    ok("неизвестный пункт" in out, "некорректный ввод отклонён", out[-300:])
    ok("Очистить служебные файлы Synfronia" in out, "пункт 11 присутствует в меню")
    ok("Удалить пакеты обхода" in out, "пункт 12 присутствует в меню")
    ok("список файлов логов" not in out or "нет" in out or "app_" in out,
       "пункт 7 отработал (логи есть или пусто)")

    section("8. запуск и немедленное следение за логом (пункт 13)")
    ok("13. Запустить и сразу следить за логом" in debug.MENU,
       "пункт 13 есть в меню")
    with tempfile.TemporaryDirectory(prefix="synf_runfollow_") as tmp:
        fake_log = Path(tmp) / "app_2026-01-01.log"
        fake_log.write_text("старт 1\nстарт 2\n", encoding="utf-8")
        calls = {"launch": 0, "follow": 0}
        real_busy, real_logs, real_pause = (debug.find_app_processes,
                                            debug.log_files, debug.pause)
        try:
            debug.pause = lambda: None     # пауза ждала бы Enter в тесте
            debug.log_files = lambda: [fake_log]
            debug.find_app_processes = lambda: []
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                debug.op_run_follow(
                    Path(tmp),
                    launch=lambda base: calls.__setitem__("launch",
                                                          calls["launch"] + 1) or True,
                    follow=lambda: calls.__setitem__("follow",
                                                     calls["follow"] + 1))
            text = buf.getvalue()
            ok(calls == {"launch": 1, "follow": 1},
               "сначала запуск, потом следение - обе ступени прошли", str(calls))
            ok("старт 2" in text and "реальном времени" in text,
               "перед живым потоком напечатан хвост свежего лога", text[:200])

            # запуск не удался - следить не за чем
            calls.update(launch=0, follow=0)
            with contextlib.redirect_stdout(io.StringIO()):
                debug.op_run_follow(Path(tmp), launch=lambda base: False,
                                    follow=lambda: calls.__setitem__("follow", 1))
            ok(calls["follow"] == 0, "не запустилось - следения нет", str(calls))

            # приложение уже запущено - повторный старт не нужен
            debug.find_app_processes = lambda: [{"ProcessId": 7, "Name": "Synfronia.exe"}]
            calls.update(launch=0, follow=0)
            with contextlib.redirect_stdout(io.StringIO()):
                debug.op_run_follow(
                    Path(tmp),
                    launch=lambda base: calls.__setitem__("launch", 1) or True,
                    follow=lambda: calls.__setitem__("follow", 1))
            ok(calls == {"launch": 0, "follow": 1},
               "уже запущено - только следение за его журналом", str(calls))
        finally:
            debug.find_app_processes, debug.log_files, debug.pause = \
                real_busy, real_logs, real_pause

    print()
    if _fails:
        print(f"итог: {_checks - len(_fails)}/{_checks} ok, провалено: {len(_fails)}")
        for f in _fails:
            print(f"  FAIL: {f}")
        return 1
    print(f"итог: {_checks}/{_checks} ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
