"""Web-интерфейс (pywebview/EdgeChromium) для Synfronia."""

import sys
import threading

import webview

from core import (
    DEFAULT_SETTINGS,
    QUALITY_FORMATS,
    SUBTITLE_OPTIONS,
    Downloader,
    base_dir,
    default_download_dir,
    find_ffmpeg,
    is_playlist,
    load_settings,
    save_settings,
)

THEME_COLORS = {
    "scary_forest": {"bg": "#0c1622", "surface": "#1f2b29", "widget": "#23444b", "text": "#dcdedd", "accent": "#628d7c"},
    "technology_day": {"bg": "#00181a", "surface": "#00585a", "widget": "#003638", "text": "#dcdedd", "accent": "#00989b"},
    "technology_pinks": {"bg": "#ffebec", "surface": "#ffcbe2", "widget": "#ffffff", "text": "#5d2547", "accent": "#c15f9b"},
}

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Synfronia</title>
<style>
  :root {
    --bg: #0c1622; --surface: #1f2b29; --widget: #23444b;
    --text: #dcdedd; --accent: #628d7c; --warn: #ffb454;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px; font-family: "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--text); font-size: 14px;
  }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { opacity: .65; font-size: 12px; margin-bottom: 14px; }
  label { display: block; margin: 10px 0 4px; font-size: 13px; opacity: .9; }
  input[type=text], select {
    width: 100%; padding: 8px 10px; border-radius: 6px; border: 1px solid var(--surface);
    background: var(--widget); color: var(--text); font-size: 14px; outline: none;
  }
  input[type=text]:focus, select:focus { border-color: var(--accent); }
  input:disabled, select:disabled, button:disabled { opacity: .45; }
  .row { display: flex; gap: 8px; align-items: center; }
  .row input[type=text] { flex: 1; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
  .check { display: flex; align-items: center; gap: 6px; margin: 10px 0 4px; font-size: 13px; }
  .check input { width: 15px; height: 15px; accent-color: var(--accent); }
  button {
    padding: 8px 18px; border: none; border-radius: 6px; cursor: pointer;
    background: var(--surface); color: var(--text); font-size: 14px;
  }
  button:hover { background: var(--accent); color: var(--bg); }
  button:disabled:hover { background: var(--surface); color: var(--text); cursor: default; }
  .actions { margin-top: 16px; display: flex; gap: 8px; align-items: center; }
  .pb-wrap { margin-top: 14px; height: 10px; border-radius: 5px; background: var(--surface); overflow: hidden; }
  #pb { height: 100%; width: 0; background: var(--accent); transition: width .2s; }
  #pb.indeterminate { width: 30%; animation: slide 1.2s infinite; }
  @keyframes slide { 0% { margin-left: -30%; } 100% { margin-left: 100%; } }
  #status { margin-top: 6px; font-size: 13px; height: 18px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  #log {
    width: 100%; min-height: 150px; margin-top: 6px; resize: vertical;
    background: var(--widget); color: var(--text); border: 1px solid var(--surface);
    border-radius: 6px; padding: 8px; font-family: Consolas, monospace; font-size: 12px;
  }
  #warn {
    display: none; margin-top: 10px; padding: 8px 12px; border-radius: 6px;
    background: rgba(255, 180, 84, .15); border: 1px solid var(--warn); color: var(--warn); font-size: 13px;
  }
</style>
</head>
<body>
  <h1>Synfronia</h1>
  <div class="sub">Скачивание видео и плейлистов YouTube (yt-dlp)</div>

  <label for="url">Ссылка (видео/плейлист):</label>
  <input type="text" id="url" placeholder="https://www.youtube.com/watch?v=…" autofocus>

  <label for="dest">Папка скачивания:</label>
  <div class="row">
    <input type="text" id="dest">
    <button id="browse">Обзор…</button>
  </div>

  <div class="check"><input type="checkbox" id="playlist"><span>Скачать весь плейлист (иначе только одно видео)</span></div>
  <div class="check"><input type="checkbox" id="group"><span>Сгруппировать: плейлист в подпапку с его названием</span></div>

  <div class="grid">
    <div>
      <label for="theme">Тема:</label>
      <select id="theme"></select>
    </div>
    <div>
      <label for="subs">Субтитры:</label>
      <select id="subs">
        <option value="off">Выкл</option>
        <option value="ru">Русские</option>
        <option value="en">Английские</option>
        <option value="all">Все</option>
      </select>
    </div>
    <div>
      <label for="qual">Качество:</label>
      <select id="qual">
        <option value="lossless">Lossless (максимум)</option>
        <option value="1080">1080p</option>
        <option value="720">720p</option>
        <option value="240">240p</option>
      </select>
    </div>
    <div><div class="check" style="margin-top:22px"><input type="checkbox" id="hevc"><span>Конвертировать в HEVC (H.265)</span></div></div>
  </div>

  <div id="warn">ffmpeg не найден — слияние, субтитры, метаданные и HEVC будут недоступны.</div>

  <div class="actions">
    <button id="download">Скачать</button>
    <button id="stop" disabled>Отмена</button>
  </div>

  <div class="pb-wrap"><div id="pb"></div></div>
  <div id="status">Готов.</div>
  <textarea id="log" readonly></textarea>

<script>
  var THEMES = {
    scary_forest:   { bg: "#0c1622", surface: "#1f2b29", widget: "#23444b", text: "#dcdedd", accent: "#628d7c" },
    technology_day: { bg: "#00181a", surface: "#00585a", widget: "#003638", text: "#dcdedd", accent: "#00989b" },
    technology_pinks: { bg: "#ffebec", surface: "#ffcbe2", widget: "#ffffff", text: "#5d2547", accent: "#c15f9b" }
  };
  var since = 0;
  var busy = false;

  function applyTheme(key) {
    var c = THEMES[key] || THEMES.scary_forest;
    var root = document.documentElement.style;
    root.setProperty("--bg", c.bg); root.setProperty("--surface", c.surface);
    root.setProperty("--widget", c.widget); root.setProperty("--text", c.text);
    root.setProperty("--accent", c.accent);
  }

  function setBusy(b) {
    if (b === busy) return;
    busy = b;
    document.getElementById("download").disabled = b;
    document.getElementById("stop").disabled = !b;
    ["url", "dest", "browse", "playlist", "group", "theme", "subs", "qual", "hevc"]
      .forEach(function(id) { document.getElementById(id).disabled = b; });
  }

  async function tick() {
    if (typeof pywebview === "undefined") { setTimeout(tick, 300); return; }
    try {
      var st = await pywebview.api.poll(since);
      if (st.logs && st.logs.length) {
        var box = document.getElementById("log");
        box.value += st.logs.join("\n") + "\n";
        box.scrollTop = box.scrollHeight;
        since += st.logs.length;
      }
      setBusy(st.busy);
      var p = st.progress || {};
      var bar = document.getElementById("pb");
      if (p.mode === "indeterminate") { bar.classList.add("indeterminate"); bar.style.width = "30%"; }
      else { bar.classList.remove("indeterminate"); bar.style.width = (p.value || 0) + "%"; }
      document.getElementById("status").textContent = st.status || "";
    } catch (e) {}
    setTimeout(tick, 200);
  }

  function collect() {
    return {
      url: document.getElementById("url").value.trim(),
      dest: document.getElementById("dest").value.trim(),
      playlist: document.getElementById("playlist").checked,
      group: document.getElementById("group").checked,
      subtitles: document.getElementById("subs").value,
      quality: document.getElementById("qual").value,
      hevc: document.getElementById("hevc").checked,
    };
  }

  function init() {
    if (window.__initDone) return;
    window.__initDone = true;
    var themeSel = document.getElementById("theme");
    Object.keys(THEMES).forEach(function(k) {
      var o = document.createElement("option");
      o.value = k; o.textContent = k;
      themeSel.appendChild(o);
    });
    pywebview.api.get_initial().then(function(init) {
    document.getElementById("dest").value = init.default_dir;
    document.getElementById("group").checked = init.settings.group_playlist !== false;
    document.getElementById("hevc").checked = !!init.settings.hevc;
    var selects = { subs: ["subtitles", "ru"], qual: ["quality", "lossless"], theme: ["theme", "scary_forest"] };
    var keys = Object.keys(selects);
    var i;
    for (i = 0; i < keys.length; i++) {
      var s = selects[keys[i]];
      document.getElementById(keys[i]).value = init.settings[s[0]] || s[1];
    }
    document.getElementById("theme").value = init.settings.theme || "scary_forest";
    applyTheme(document.getElementById("theme").value);
    if (!init.ffmpeg) document.getElementById("warn").style.display = "block";
    document.getElementById("theme").addEventListener("change", function() {
      applyTheme(this.value); pywebview.api.save_setting("theme", this.value);
    });
    document.getElementById("subs").addEventListener("change", function() {
      pywebview.api.save_setting("subtitles", this.value);
    });
    document.getElementById("qual").addEventListener("change", function() {
      pywebview.api.save_setting("quality", this.value);
    });
    document.getElementById("hevc").addEventListener("change", function() {
      pywebview.api.save_setting("hevc", this.checked);
    });
    document.getElementById("group").addEventListener("change", function() {
      pywebview.api.save_setting("group_playlist", this.checked);
    });
    document.getElementById("download").addEventListener("click", async function() {
      var cfg = collect();
      if (!cfg.url) { document.getElementById("status").textContent = "Введите ссылку на видео или плейлист."; return; }
      var res = await pywebview.api.start_download(cfg);
      if (res && res.error) document.getElementById("status").textContent = res.error;
    });
    document.getElementById("stop").addEventListener("click", function() {
      pywebview.api.stop_download();
    });
    document.getElementById("browse").addEventListener("click", async function() {
      var p = await pywebview.api.browse_folder();
      if (p) document.getElementById("dest").value = p;
    });
    document.getElementById("url").addEventListener("keydown", function(ev) {
      if (ev.key === "Enter") document.getElementById("download").click();
    });
    }).catch(function(e) { console.error("init error:", e); });
  }
  if (window.pywebview !== undefined) { init(); }
  else { window.addEventListener("pywebviewready", init); }
  setTimeout(tick, 400);
</script>
</body>
</html>
"""


class Api:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.dl: Downloader | None = None
        self._lock = threading.Lock()
        self._logs: list[str] = []
        self._status = "Готов."
        self._busy = False
        self._progress = {"mode": "determinate", "value": 0.0}

    # -- состояние (poll из JS) ----------------------------------------------
    def poll(self, since: int = 0) -> dict:
        with self._lock:
            return {
                "busy": self._busy,
                "status": self._status,
                "progress": dict(self._progress),
                "logs": list(self._logs[since:]),
            }

    def get_initial(self) -> dict:
        return {
            "settings": dict(self.settings),
            "ffmpeg": bool(find_ffmpeg()),
            "default_dir": str(default_download_dir()),
        }

    # -- настройки -----------------------------------------------------------
    def save_setting(self, key: str, value) -> str:
        if key in DEFAULT_SETTINGS:
            self.settings[key] = value
            try:
                save_settings(self.settings)
                return "ok"
            except OSError as exc:
                return f"error: {exc}"
        return "unknown key"

    # -- диалог папки --------------------------------------------------------
    def browse_folder(self):
        win = webview.windows[0] if webview.windows else None
        if not win:
            return None
        result = win.create_file_dialog(webview.FOLDER_DIALOG)
        return str(result[0]) if result else None

    # -- загрузка ------------------------------------------------------------
    def start_download(self, cfg: dict) -> dict:
        url = (cfg.get("url") or "").strip()
        dest = (cfg.get("dest") or "").strip() or str(default_download_dir())
        if not url:
            return {"error": "Введите ссылку на видео или плейлист."}
        playlist = bool(cfg.get("playlist"))
        if not playlist and is_playlist(url):
            self._log("warning", "Ссылка на плейлист без флажка — скачается только одно видео.")
        with self._lock:
            self._busy = True
            self._status = "Запуск…"
            self._progress = {"mode": "indeterminate"}
        self.dl = Downloader(on_log=self._log, on_progress=self._on_progress)
        threading.Thread(
            target=lambda: self._run(url, dest, playlist,
                                     bool(cfg.get("group", True)),
                                     cfg.get("subtitles", "ru"),
                                     cfg.get("quality", "lossless"),
                                     bool(cfg.get("hevc", False))),
            daemon=True,
            name="yt-dlp",
        ).start()
        return {}

    def _run(self, url, dest, playlist, group, subtitles, quality, hevc) -> None:
        try:
            self.dl.download(
                url,
                dest,
                playlist=playlist,
                group=group,
                subtitles=subtitles,
                quality=quality,
                hevc=hevc,
            )
        except Exception as exc:  # noqa: BLE001
            self._log("error", str(exc))
        finally:
            with self._lock:
                self._busy = False
                self._status = "Готов."
                self._progress = {"mode": "determinate", "value": 100.0}

    def stop_download(self) -> None:
        if self.dl:
            self._log("warning", "Запрос остановки…")
            self.dl.stop()

    # -- коллбеки от core ----------------------------------------------------
    def _log(self, level: str, msg: str) -> None:
        with self._lock:
            self._logs.append(f"[{level}] {msg}")

    def _on_progress(self, d: dict) -> None:
        status = d.get("status")
        with self._lock:
            if status == "downloading":
                percent = d.get("percent")
                name = d.get("filename") or ""
                if percent is None:
                    self._status = f"{name} — идёт загрузка…"
                    self._progress = {"mode": "indeterminate"}
                else:
                    self._progress = {"mode": "determinate", "value": percent}
                    bits = f"{percent:.0f}%"
                    spd = f"{d['speed'] / 1024 / 1024:.1f} МБ/с" if d.get("speed") else ""
                    eta = f" ETA {int(d['eta'])}с" if d.get("eta") else ""
                    self._status = f"{name} — {bits}{(' | ' + spd) if spd else ''}{eta}"
            elif status == "postprocessing":
                self._status = d.get("msg", "Постобработка…")
                self._progress = {"mode": "indeterminate"}
            elif status == "done":
                self._progress = {"mode": "determinate", "value": 100.0}


def main() -> None:
    webview.create_window(
        "Synfronia",
        html=HTML,
        js_api=Api(),
        width=980,
        height=780,
        min_size=(780, 560),
        background_color="#0c1622",
    )
    webview.start()


def diagnose_freeze() -> None:
    import io
    import time
    import traceback

    lines: list[str] = []
    t0 = time.time()

    def step(name: str) -> None:
        lines.append(f"[{time.time() - t0:6.2f}s] {name}")
        with open("gui_diag.log", "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    step(f"start frozen={hasattr(sys, '_MEIPASS')}")
    try:
        import webview.platforms.edgechromium as ec  # noqa: PLC0415

        step("edgechromium import ok")
    except Exception:
        step("edgechromium import FAILED")
        traceback.print_exc(file=sys.stdout)
    try:
        step("before import clr")
        import clr  # noqa: PLC0415

        step("after import clr")
        import clr_loader  # noqa: PLC0415

        step("clr_loader ok")
    except Exception:
        step("clr/clr_loader FAILED")
        traceback.print_exc(file=sys.stdout)
    try:
        step("before AddReference(WebView2.WinForms)")
        clr.AddReference("Microsoft.Web.WebView2.WinForms")
        step("AddReference(WebView2.WinForms) ok")
        from webview.util import interop_dll_path  # noqa: PLC0415

        step(f"interop dll: {interop_dll_path('Microsoft.Web.WebView2.Core.dll')}")
        clr.AddReference(interop_dll_path("Microsoft.Web.WebView2.Core.dll"))
        step("AddReference(Core.dll) ok")
    except Exception:
        step("WebView2 AddReference FAILED")
        traceback.print_exc(file=sys.stdout)
    step("diagnose done")


if __name__ == "__main__":
    if "--diagnose-freeze" in sys.argv:
        diagnose_freeze()
        sys.exit(0)
    if "--selftest" in sys.argv:
        from core import Downloader  # noqa: PLC0415

        dest = sys.argv[2] if len(sys.argv) > 2 else "downloads_selftest"
        url = sys.argv[3] if len(sys.argv) > 3 else "https://youtu.be/GUS0q7gZdNE"
        subtitles = "ru"
        quality = "lossless"
        hevc = False
        for opt in sys.argv[4:]:
            if opt.startswith("--subtitles="):
                subtitles = opt.split("=", 1)[1]
            elif opt.startswith("--quality="):
                quality = opt.split("=", 1)[1]
            elif opt == "--hevc":
                hevc = True
        with open(base_dir() / "selftest.log", "w", encoding="utf-8") as f:
            dl = Downloader(on_log=lambda lvl, msg: f.write(f"[{lvl}] {msg}\n"))
            dl.download(url, dest, subtitles=subtitles, quality=quality, hevc=hevc)
        print("selftest done")
        sys.exit(0)

    main()