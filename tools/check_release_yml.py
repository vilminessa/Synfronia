"""Линт релизных workflow: ловит ошибки CI до пуша (видно только на раннере).

Две полосы - два файла; общую часть держит вместе парность (последняя секция):
  .github/workflows/release.yml - main: тег v*, обычный релиз, гард на origin/main;
  .github/workflows/beta.yml    - dev:  тег b*, GitHub Pre-release, гард на origin/dev.

Что проверяем:
  * общие файлы проекта: version.py (числовой версия + BUILD_LABEL) и зонд
    ui_fonts_probe (эмуляция no-preference - раннеры Windows отдают reduce
    и гасят CSS-анимации, из-за чего падали проверки кнопки «Скачать»);
  * по каждому из двух файлов (секции 1-6):
    1. YAML валиден, все джобы на месте, триггер по тегам РОВНО свой полосе
       (release: ["v*"], beta: ["b*"]) и workflow_dispatch; формат тега -
       regex только своей полосы ([vb]X.Y.Z[.N], четыре компонента - предел
       Windows VersionInfo);
    2. внешние uses запинены: SHA (40 hex) или версионный тег - ветки (@main)
       запрещены;
    3. permissions джоба generator-generic-ossf-slsa3-publish покрывают
       потребности вложенного SLSA-генератора (id-token: write, contents:
       write, actions: read) - иначе GitHub даёт startup_failure «only
       allowed actions: none» ещё до запуска, и текст виден только в
       веб-интерфейсе Actions;
    4. публикация ограждена if на теге; генератор провенанса ранится и на
       dispatch (if допускает skipped), upload-assets отключён вне тега,
       а проверка подписи привязана к тегу и верифицирует интота-бандл из
       ассетов релиза (bundle + predicate v0.2 + signer-repo);
    5. в шагах python -c только ASCII - консоль CI cp1252, кириллица роняет
       уже собранный артефакт;
    6. полоса: свой гард (v -> origin/main, b -> origin/dev; чужой ветки в
       файле нет вообще), fetch-depth 0 (shallow не видит истории), стамп
       версии до PyInstaller и только на тегах, старое равенство тега и
       version.py убрано, публикация по полосе (--prerelease только в
       beta.yml);
  * парность: всё кроме полосных шагов (формат, гард, текст публикации)
    обязано совпадать побайтово - дублирование общей логики двух файлов
    остаётся под машинным контролем, а не тихим дрейфом.

Запуск:  python tools/check_release_yml.py
"""

import re
import sys
from pathlib import Path

import yaml  # noqa: PyYAML - инструментальная зависимость (requirements.txt)

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
WF_DIR = ROOT / ".github" / "workflows"
PROBE = ROOT / "tools" / "ui_fonts_probe.js"

SLSA_JOB = "generator-generic-ossf-slsa3-publish"
NEEDED_JOBS = ("verify", "build", "python-publish", SLSA_JOB, "verify-attestation")
# что обязан выдать вызывающий джоб вложенному SLSA-генератору (v2.1.0)
SLSA_PERMS = {"id-token": "write", "contents": "write", "actions": "read"}
PIN = re.compile(r"^([0-9a-f]{40}|v\d+(?:\.\d+)*(?:-[0-9A-Za-z.]+)?)$")

# полосы: свой файл, свой тег, свой гард и своя политика публикации
LANES = (
    {"file": "release.yml", "tag": "v*", "prefix": "v", "example": "v1.2.7.5",
     "guard": "origin/main", "alien": "origin/dev", "prerelease": False},
    {"file": "beta.yml", "tag": "b*", "prefix": "b", "example": "b1.2.7.41",
     "guard": "origin/dev", "alien": "origin/main", "prerelease": True},
)
# шаги, которые УМЫШЛЕННО различаются между полосами - парность их исключает
LANE_STEPS = ("Формат тега", "Тег ", "Создать/обновить релиз")

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


def lane_kind(name: object) -> str | None:
    """Префикс полосного шага или None (обычный шаг парность сверяет целиком)."""
    for prefix in LANE_STEPS:
        if str(name).startswith(prefix):
            return prefix
    return None


def normalize(jobs: dict) -> dict:
    """Копия jobs, где полосные шаги заменены на метку - сравниваем остальное."""
    out: dict = {}
    for name, job in jobs.items():
        job2 = dict(job)
        steps = job2.get("steps")
        if isinstance(steps, list):
            job2["steps"] = [
                {"lane": lane_kind(s.get("name", ""))} if lane_kind(s.get("name", "")) else s
                for s in steps
            ]
        out[name] = job2
    return out


def first_diff(a: object, b: object, path: str = "") -> str:
    """Первое расхождение двух структур - для понятного FAIL-отчёта."""
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return f"{path}: разные ключи {sorted(set(a) ^ set(b))}"
        for key in a:
            diff = first_diff(a[key], b[key], f"{path}.{key}")
            if diff:
                return diff
        return ""
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: длина {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            diff = first_diff(x, y, f"{path}[{i}]")
            if diff:
                return diff
        return ""
    return "" if a == b else f"{path}: {a!r} != {b!r}"


def lint_lane(lane: dict) -> dict:
    """Секции 1-6 для одного файла полосы; возвращает jobs ({} - файл не загрузился)."""
    f = lane["file"]
    path = WF_DIR / f

    section(f"{f}: 1. YAML и структура")
    ok(path.is_file(), f"{f} существует")
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        ok(isinstance(data, dict), f"{f}: YAML валиден")
    except yaml.YAMLError as exc:
        ok(False, f"{f}: YAML валиден", str(exc))
        return {}
    jobs = data.get("jobs") or {}
    missing = [j for j in NEEDED_JOBS if j not in jobs]
    ok(not missing, f"{f}: все джобы на месте", str(missing))
    trig = data.get("on", data.get(True))  # YAML 1.1 превращает ключ on в True
    tags = ((trig or {}).get("push") or {}).get("tags") or []
    ok(tags == [lane["tag"]], f"{f}: триггер только по тегам своей полосы ({lane['tag']})",
       str(tags))
    ok("workflow_dispatch" in (trig or {}),
       f"{f}: триггер workflow_dispatch (проба без публикации)")
    steps = jobs.get("verify", {}).get("steps") or []
    fmt = next((s for s in steps if "Формат тега" in str(s.get("name", ""))), None)
    ok(fmt is not None, f"{f}: есть шаг проверки формата тега")
    if fmt is not None:
        ok("refs/tags/" in str(fmt.get("if", "")),
           f"{f}: проверка формата выполняется только на тегах", str(fmt.get("if", "")))
        fmt_run = str(fmt.get("run", ""))
        ok(f"^{lane['prefix']}[" in fmt_run and "{2,3}" in fmt_run,
           f"{f}: regex своей полосы ({lane['prefix']}X.Y.Z[.N], до 4 компонентов)",
           fmt_run[:90])
        ok("[vb]" not in fmt_run, f"{f}: чужой префикс в regex отсутствует", fmt_run[:90])
        ok(lane["example"] in str(fmt.get("name", "")),
           f"{f}: в имени шага пример своего тега ({lane['example']})",
           str(fmt.get("name", "")))

    section(f"{f}: 2. пиннинг внешних экшенов")
    bad: list[str] = []
    for jname, job in jobs.items():
        refs = [step.get("uses", "") for step in job.get("steps", [])]
        if "uses" in job:
            refs.append(job["uses"])
        for uses in refs:
            if not uses or uses.startswith("./") or uses.startswith("docker://"):
                continue
            ref = uses.rsplit("@", 1)[-1] if "@" in uses else ""
            if not PIN.match(ref):
                bad.append(uses)
    ok(not bad, f"{f}: все uses запинены по SHA или версионному тегу (ветки запрещены)",
       str(bad))

    section(f"{f}: 3. permissions вложенного SLSA-генератора")
    gen = jobs.get(SLSA_JOB, {})
    perms = gen.get("permissions") or {}
    lack = {k: v for k, v in SLSA_PERMS.items() if perms.get(k) != v}
    ok(not lack,
       f"{f}: generator: id-token/contents/actions выданы (нет actions: read = startup_failure)",
       f"выдано {perms}, не хватает {lack}")
    ok(str(gen.get("uses", "")).endswith("@v2.1.0"),
       f"{f}: генератор запинен по тегу v2.1.0", str(gen.get("uses", "")))

    section(f"{f}: 4. публикация на теге, провенанс и подпись - на обоих событиях")
    pub_if = str(jobs.get("python-publish", {}).get("if", ""))
    ok("refs/tags/" in pub_if, f"{f}: python-publish ограждён if на тег", pub_if)
    with_ = gen.get("with") or {}
    ua = with_.get("upload-assets")
    ok(ua is True or "startsWith(github.ref" in str(ua),
       f"{f}: upload-assets: на теге true, на dispatch false (без публикации в релиз)",
       str(ua))
    gen_if = str(gen.get("if", ""))
    ok("python-publish.result" in gen_if and "skipped" in gen_if,
       f"{f}: генератор ждёт публикацию, но допускает её пропуск на dispatch", gen_if)
    attest_if = str(jobs.get("verify-attestation", {}).get("if", ""))
    ok("refstags" in attest_if.replace("/", ""),
       f"{f}: проверка подписи на теге (на dispatch ассетов релиза нет)",
       attest_if or "без if")
    attest_steps = jobs.get("verify-attestation", {}).get("steps") or []
    attest_run = " ".join(str(s.get("run", "")) for s in attest_steps)
    ok("gh release download" in attest_run,
       f"{f}: verify качает exe и провенанс из релиза")
    ok("--bundle" in attest_run and "intoto" in attest_run,
       f"{f}: verify верифицирует интота-бандл, а не реестр")
    ok("provenance/v0.2" in attest_run,
       f"{f}: verify фильтрует predicate v0.2 (так подписывает генератор)")
    ok("--signer-repo" in attest_run and "slsa-github-generator" in attest_run,
       f"{f}: verify указывает signer-repo (генератор - reusable workflow)")
    ok("needs.build.outputs.digests" in str(with_.get("base64-subjects", "")),
       f"{f}: subjects берутся из хеша build-джоба")

    section(f"{f}: 5. шаги python -c только ASCII (консоль CI - cp1252)")
    cyr = []
    for jname, job in jobs.items():
        for step in job.get("steps", []):
            run = step.get("run") or ""
            if "python -c" in run and any(ord(ch) > 127 for ch in run):
                cyr.append(f"{jname}/{step.get('name', '?')}")
    ok(not cyr, f"{f}: нет не-ASCII символов в python -c шагах", str(cyr))

    section(f"{f}: 6. полоса {lane['prefix']}: гард, стамп, публикация")
    checkouts = [s for s in steps if "actions/checkout@" in str(s.get("uses", ""))]
    ok(bool(checkouts)
       and (checkouts[0].get("with") or {}).get("fetch-depth") == 0,
       f"{f}: verify: checkout с fetch-depth 0 (иначе merge-base не видит историю)",
       str(checkouts[0].get("with") if checkouts else None))
    guards = [s for s in steps if "merge-base --is-ancestor" in str(s.get("run", ""))]
    ok(len(guards) == 1, f"{f}: ровно один гард своей полосы", f"найдено {len(guards)}")
    guard = guards[0] if guards else {}
    guard_run = str(guard.get("run", ""))
    ok(lane["guard"] in guard_run and lane["alien"] not in guard_run,
       f"{f}: гард смотрит только в {lane['guard']} и не упоминает чужую ветку",
       guard_run[:90])
    ok("refs/tags/" in str(guard.get("if", "")),
       f"{f}: гард только на тегах (dispatch пропускает)", str(guard.get("if", "")))
    ok(str(guard.get("name", "")).startswith(f"Тег {lane['prefix']}"),
       f"{f}: имя гарда про свою полосу (Тег {lane['prefix']}...)",
       str(guard.get("name", "")))
    all_runs = [str(s.get("run", "")) for j in jobs.values()
                for s in j.get("steps", [])]
    ok(not any(lane["alien"] in r for r in all_runs),
       f"{f}: чужой ветки {lane['alien']} нет нигде в шагах")
    ok(not any('test "$ver"' in r for r in all_runs),
       f"{f}: равенство тега и version.py убрано (версию вписывает stamp)")
    build_steps = jobs.get("build", {}).get("steps") or []
    stamp_idx = next((i for i, s in enumerate(build_steps)
                      if "stamp_version.py" in str(s.get("run", ""))), None)
    pyi_idx = next((i for i, s in enumerate(build_steps)
                    if "PyInstaller" in str(s.get("run", ""))), None)
    ok(stamp_idx is not None, f"{f}: в build есть шаг «Версия из тега» (stamp_version.py)")
    ok(stamp_idx is not None and pyi_idx is not None and stamp_idx < pyi_idx,
       f"{f}: стамп идёт ДО PyInstaller (spec читает version.py при сборке)",
       f"stamp={stamp_idx} pyinstaller={pyi_idx}")
    if stamp_idx is not None:
        ok("refs/tags/" in str(build_steps[stamp_idx].get("if", "")),
           f"{f}: стамп только на тегах (dispatch собирается как есть)",
           str(build_steps[stamp_idx].get("if", "")))
    pub_steps = jobs.get("python-publish", {}).get("steps") or []
    pub_run = str((pub_steps[-1] if pub_steps else {}).get("run", ""))
    if lane["prerelease"]:
        ok("--prerelease" in pub_run and "Бета-сборка" in pub_run,
           f"{f}: публикация как Pre-release (пометка «Бета-сборка из dev»)",
           pub_run[:90])
    else:
        ok("--prerelease" not in pub_run and "Бета-сборка" not in pub_run,
           f"{f}: обычный релиз (без --prerelease и бета-пометки)", pub_run[:90])
    return jobs


def main() -> int:
    section("общее: version.py и зонд вёрстки")
    ver_file = ROOT / "version.py"
    ok(ver_file.is_file(), "version.py существует (числовой источник версии)")
    if ver_file.is_file():
        text = ver_file.read_text(encoding="utf-8")
        # версия — X.Y.Z или четырёхкомпонентная X.Y.Z.N (предел VersionInfo)
        m = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?"', text)
        ok(m is not None, "__version__ в формате X.Y.Z[.N]", str(m))
        ok('BUILD_LABEL = ""' in text,
           "BUILD_LABEL есть (его заполняет stamp_version при сборке из тега)")
    ok(PROBE.is_file(), "ui_fonts_probe.js существует")
    if PROBE.is_file():
        probe = PROBE.read_text(encoding="utf-8")
        ok("Emulation.setEmulatedMedia" in probe
           and "prefers-reduced-motion" in probe
           and "no-preference" in probe,
           "ui_fonts_probe эмулирует no-preference (CSS-анимации не погашены)")

    loaded: dict[str, dict] = {}
    for lane in LANES:
        loaded[lane["file"]] = lint_lane(lane)

    section("парность полос: общая логика двух файлов идентична")
    release_jobs = loaded.get("release.yml") or {}
    beta_jobs = loaded.get("beta.yml") or {}
    if release_jobs and beta_jobs:
        ok(list(release_jobs) == list(beta_jobs),
           "джобы и их порядок совпадают",
           f"{list(release_jobs)} != {list(beta_jobs)}")
        diff = first_diff(normalize(release_jobs), normalize(beta_jobs), "jobs")
        ok(not diff,
           "всё кроме полосных шагов (формат, гард, текст публикации) совпадает побайтово",
           diff)
    else:
        ok(False, "оба файла загружены - парность посчитана",
           "release.yml или beta.yml не загружен")

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
