"""Линт release.yml: ловит ошибки CI до пуша (их видно только на раннере).

Что проверяем (.github/workflows/release.yml):
  1. YAML валиден, есть все джобы и оба триггера (теги v* и dispatch);
  2. внешние uses запинены: SHA (40 hex) или версионный тег - ветки (@main)
     запрещены;
  3. permissions джоба generator-generic-ossf-slsa3-publish покрывают
     потребности вложенного SLSA-генератора (id-token: write, contents: write,
     actions: read) - иначе GitHub даёт startup_failure «only allowed
     actions: none» ещё до запуска, и текст виден только в веб-интерфейсе
     Actions;
  4. публикация ограждена if на теге; генератор провенанса ранится и на
     dispatch (if допускает skipped), upload-assets отключён вне тега,
     а проверка подписи не привязана к тегу - проба конвейера до выпуска;
  5. в шагах python -c только ASCII - консоль CI cp1252, кириллица роняет
     уже собранный артефакт;
  6. зонд ui_fonts_probe эмулирует prefers-reduced-motion: no-preference -
     раннеры Windows отдают reduce и гасят CSS-анимации, из-за чего падали
     проверки кнопки «Скачать» и хвоста подсказки.

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
    ok("v*" in tags, "триггер по тегам v*", str(tags))
    ok("workflow_dispatch" in (trig or {}), "триггер workflow_dispatch (проба без публикации)")

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
    ok("refstags" not in attest_if,
       "проверка подписи ранится и на dispatch (проба до тега)",
       attest_if or "без if")
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
