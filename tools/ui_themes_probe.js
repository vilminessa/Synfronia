// Гоняет headless-пробник по всем темам подряд: палитра у каждой своя, и
// слой карточки/блоков/полей обязан читаться в любой. Каждая тема требует
// своей страницы, поэтому сборка и проверка идут в цикле.
//
//   python tools\build_ui.py
//   node tools\ui_themes_probe.js
//
// Код возврата: 0 - во всех темах всё влезает и контраст выдержан, 1 - нет.
const { execFileSync, spawnSync } = require("child_process");
const path = require("path");

const root = path.join(__dirname, "..");
const themes = execFileSync("python", ["-c",
  "import themes; print(' '.join(themes.load_themes().keys()))"], { cwd: root, encoding: "utf8" })
  .trim().split(/\s+/).filter(Boolean);

let bad = 0;
for (const theme of themes) {
  console.log(`\n=== ${theme} ===`);
  execFileSync("python", [path.join("tools", "ui_probe_page.py"), "--theme", theme], { cwd: root });
  const res = spawnSync("node", [path.join("tools", "ui_fonts_probe.js")], { cwd: root, encoding: "utf8" });
  const out = (res.stdout || "").split(/\r?\n/).filter((l) =>
    /FAIL|контраст|--- /.test(l)).join("\n");
  console.log(out);
  if (res.status !== 0) {
    bad++;
    console.log(`  ${theme}: есть замечания (код ${res.status})`);
  } else {
    console.log(`  ${theme}: ок`);
  }
}
console.log(bad ? `\nFAIL: замечания в ${bad} темах из ${themes.length}` : `\nOK: все ${themes.length} тем`);
process.exit(bad ? 1 : 0);
