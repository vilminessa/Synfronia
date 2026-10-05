"""Линт release.yml: ловит ошибки CI до пуша (их видно только на раннере).

Что проверяем (.github/workflows/release.yml):
  1. YAML валиден, есть все джобы и все триггера (теги v* и b*, dispatch),
     а сам тег обязан быть [vb]X.Y.Z[.N] (четыре компонента - предел
     Windows VersionInfo);
  2. внешние uses запинены: SHA (40 hex) или версионный тег - ветки (@main)
     запрещены;
  3. permissions джоба generator-generic-ossf-slsa3-publish покрывают
     потребности вложенного SLSA-генератора (id-token: write, contents: write,
     actions: read) - иначе GitHub даёт startup_failure «only allowed
     actions: none» ещё до запуска, и текст виден только в веб-интерфейсе
     Actions;
  4. публикация ограждена if на теге; генератор провенанса ранится и на
     dispatch (if допускает skipped), upload-assets отключён вне тега,
     а проверка подписи привязана к тегу и верифицирует интота-бандл из
     ассетов релиза (bundle + predicate v0.2 + signer-repo);
  5. в шагах python -c только ASCII - консоль CI cp1252, кириллица роняет
     уже собранный артефакт;
  6. зонд ui_fonts_probe эмулирует prefers-reduced-motion: no-preference -
     раннеры Windows отдают reduce и гасят CSS-анимации, из-за чего падали
     проверки кнопки «Скачать» и хвоста подсказки;
  7. две полосы: v-тег обязан входить в main, b-тег - в dev (merge-base на
     полной истории), версия вписывается в рабочее дерево CI
     tools/stamp_version.py до PyInstaller (коммитов с бампом не нужно),
     b-релизы публикуются как Pre-release.

Запуск:  python tools/check_release_yml.py
"""

import re
import sys
from pathlib import Path

import yaml  # noqa: PyYAML - инструментальная зависимость (requirements.txt)

import utf8_console  # локальный помощник tools/, доступен по sys.path[0] скрипта

utf8_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows" / "release.yml"
PROBE = ROOT / "tools" / "ui_fonts_probe.js"

SLSA_JOB = "generator-generic-ossf-slsa3-publish"
NEEDED_JOBS = ("verify", "build", "python-publish", SLSA_JOB, "verify-attestation")
# что обязан выдать вызывающий джоб вложенному SLSA-генератору (v2.1.0)
SLSA_PERMS = {"id-token": "write", "contents": "write", "actions": "read"}
PIN = re.compile(r"^([0-9a-f]{40}|v\d+(?:\.\d+)*(?:-[0-9A-Za-z.]+)?)$")

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


def main() -> int:
    section("1. YAML и структура")
    ok(WF.is_file(), "release.yml существует")
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or {}
    missing = [j for j in NEEDED_JOBS if j not in jobs]
    ok(not missing, "все джобы на месте", str(missing))
    trig = data.get("on", data.get(True))  # YAML 1.1 превращает ключ on в True
    tags = ((trig or {}).get("push") or {}).get("tags") or []
    ok("v*" in tags and "b*" in tags, "триггеры по тегам v* и b*", str(tags))
    ok("workflow_dispatch" in (trig or {}), "триггер workflow_dispatch (проба без публикации)")

    ver_file = ROOT / "version.py"
    ok(ver_file.is_file(), "version.py существует (числовой источник версии)")
    if ver_file.is_file():
        # версия — X.Y.Z или четырёхкомпонентная X.Y.Z.N (предел VersionInfo)
        m = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?"',
                      ver_file.read_text(encoding="utf-8"))
        ok(m is not None, "__version__ в формате X.Y.Z[.N]", str(m))
        ok('BUILD_LABEL = ""' in ver_file.read_text(encoding="utf-8"),
           "BUILD_LABEL есть (его заполняет stamp_version при сборке из тега)")
    steps = jobs.get("verify", {}).get("steps") or []
    vsteps = [s for s in steps if "Формат тега" in str(s.get("name", ""))]
    ok(bool(vsteps), "в verify есть шаг проверки формата тега")
    if vsteps:
        ok("refs/tags/" in str(vsteps[0].get("if", "")),
           "проверка формата выполняется только на тегах", str(vsteps[0].get("if", "")))
        vrun = str(vsteps[0].get("run", ""))
        ok("[vb]" in vrun and "{2,3}" in vrun,
           "формат: префикс v или b и до четырёх компонентов", vrun[:100])

    section("2. пиннинг внешних экшенов")
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
    ok(not bad, "все uses запинены по SHA или версионному тегу (ветки запрещены)", str(bad))

    section("3. permissions вложенного SLSA-генератора")
    gen = jobs.get(SLSA_JOB, {})
    perms = gen.get("permissions") or {}
    lack = {k: v for k, v in SLSA_PERMS.items() if perms.get(k) != v}
    ok(not lack,
       "generator: id-token/contents/actions выданы (нет actions: read = startup_failure)",
       f"выдано {perms}, не хватает {lack}")
    ok(str(gen.get("uses", "")).endswith("@v2.1.0"),
       "генератор запинен по тегу v2.1.0", str(gen.get("uses", "")))

    section("4. публикация на теге, провенанс и подпись - на обоих событиях")
    pub_if = str(jobs.get("python-publish", {}).get("if", ""))
    ok("refs/tags/" in pub_if, "python-publish ограждён if на тег", pub_if)
    with_ = gen.get("with") or {}
    ua = with_.get("upload-assets")
    ok(ua is True or "startsWith(github.ref" in str(ua),
       "upload-assets: на теге true, на dispatch false (без публикации в релиз)", str(ua))
    gen_if = str(gen.get("if", ""))
    ok("python-publish.result" in gen_if and "skipped" in gen_if,
       "генератор ждёт публикацию, но допускает её пропуск на dispatch", gen_if)
    attest_if = str(jobs.get("verify-attestation", {}).get("if", ""))
    ok("refstags" in attest_if.replace("/", ""),
       "проверка подписи на теге (на dispatch ассетов релиза нет)", attest_if or "без if")
    attest_steps = jobs.get("verify-attestation", {}).get("steps") or []
    attest_run = " ".join(str(s.get("run", "")) for s in attest_steps)
    ok("gh release download" in attest_run,
       "verify качает exe и провенанс из релиза")
    ok("--bundle" in attest_run and "intoto" in attest_run,
       "verify верифицирует интота-бандл, а не реестр")
    ok("provenance/v0.2" in attest_run,
       "verify фильтрует predicate v0.2 (так подписывает генератор)")
    ok("--signer-repo" in attest_run and "slsa-github-generator" in attest_run,
       "verify указывает signer-repo (генератор - reusable workflow)")
    ok("needs.build.outputs.digests" in str(with_.get("base64-subjects", "")),
       "subjects берутся из хеша build-джоба")

    section("5. шаги python -c только ASCII (консоль CI - cp1252)")
    cyr = []
    for jname, job in jobs.items():
        for step in job.get("steps", []):
            run = step.get("run") or ""
            if "python -c" in run and any(ord(ch) > 127 for ch in run):
                cyr.append(f"{jname}/{step.get('name', '?')}")
    ok(not cyr, "нет не-ASCII символов в python -c шагах", str(cyr))

    section("6. зонд против prefers-reduced-motion на раннерах")
    probe = PROBE.read_text(encoding="utf-8")
    ok("Emulation.setEmulatedMedia" in probe
       and "prefers-reduced-motion" in probe
       and "no-preference" in probe,
       "ui_fonts_probe эмулирует no-preference (CSS-анимации не погашены)")

    section("7. полосы: v->main, b->dev, версия из тега без коммитов")
    checkouts = [s for s in steps if "actions/checkout@" in str(s.get("uses", ""))]
    ok(bool(checkouts)
       and (checkouts[0].get("with") or {}).get("fetch-depth") == 0,
       "verify: checkout с fetch-depth 0 (иначе merge-base не видит историю)",
       str(checkouts[0].get("with") if checkouts else None))
    main_step = next((s for s in steps if "origin/main" in str(s.get("run", ""))), None)
    dev_step = next((s for s in steps if "origin/dev" in str(s.get("run", ""))), None)
    ok(main_step is not None and dev_step is not None,
       "оба гарда на месте: тег v -> main, тег b -> dev")
    if main_step is not None:
        ok("refs/tags/v" in str(main_step.get("if", ""))
           and "origin/dev" not in str(main_step.get("run", "")),
           "v-гард смотрит только в main", str(main_step.get("if", "")))
    if dev_step is not None:
        ok("refs/tags/b" in str(dev_step.get("if", ""))
           and "origin/main" not in str(dev_step.get("run", "")),
           "b-гард смотрит только в dev", str(dev_step.get("if", "")))
    ok("merge-base --is-ancestor" in str(main_step.get("run", ""))
       and "merge-base --is-ancestor" in str(dev_step.get("run", "")),
       "гарды используют merge-base --is-ancestor")

    all_runs = [str(s.get("run", "")) for j in jobs.values()
                for s in j.get("steps", [])]
    ok(not any('test "$ver"' in r for r in all_runs),
       "равенство тега и version.py убрано (версию вписывает stamp)")
    build_steps = jobs.get("build", {}).get("steps") or []
    stamp_idx = next((i for i, s in enumerate(build_steps)
                      if "stamp_version.py" in str(s.get("run", ""))), None)
    pyi_idx = next((i for i, s in enumerate(build_steps)
                    if "PyInstaller" in str(s.get("run", ""))), None)
    ok(stamp_idx is not None, "в build есть шаг «Версия из тега» (stamp_version.py)")
    ok(stamp_idx is not None and pyi_idx is not None and stamp_idx < pyi_idx,
       "стамп идёт ДО PyInstaller (spec читает version.py при сборке)",
       f"stamp={stamp_idx} pyinstaller={pyi_idx}")
    if stamp_idx is not None:
        ok("refs/tags/" in str(build_steps[stamp_idx].get("if", "")),
           "стамп только на тегах (dispatch собирается как есть)",
           str(build_steps[stamp_idx].get("if", "")))
    pub_steps = jobs.get("python-publish", {}).get("steps") or []
    pub_run = str((pub_steps[-1] if pub_steps else {}).get("run", ""))
    ok('[[ "$GITHUB_REF_NAME" == b* ]]' in pub_run
       and "extra+=(--prerelease)" in pub_run,
       "b-теги публикуются как Pre-release, v-теги - обычным релизом")

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
