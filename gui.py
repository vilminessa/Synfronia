"""Web-интерфейс (pywebview/EdgeChromium) для Synfronia."""

import json
import sys
import threading

import webview

from core import (
    DEFAULT_SETTINGS,
    I18N,
    Downloader,
    available_transcoders,
    base_dir,
    default_download_dir,
    find_ffmpeg,
    is_playlist,
    load_settings,
    save_settings,
    tr,
)

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
  h1 { font-size: 22px; margin: 0 0 8px; }
  .sub { opacity: .65; font-size: 12px; }
  .clicker-row { text-align: center; margin-top: 10px; }
  .clicker {
    width: 46px; height: 46px; border-radius: 12px;
    background: var(--surface); border: 1px solid var(--widget); color: var(--text);
    font-size: 20px; line-height: 1; cursor: pointer; vertical-align: middle;
    transition: transform .08s, background .15s, border-color .15s;
  }
  .clicker:hover { background: var(--widget); }
  .clicker:active, .clicker.pressed {
    transform: scale(.82);
    background: var(--accent); border-color: var(--accent); color: var(--bg);
  }
  .clicker-count {
    display: inline-block; margin-left: 8px; font-size: 12px; opacity: .7;
    vertical-align: middle; font-variant-numeric: tabular-nums;
  }
  .head { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 14px; }
  .brand { flex: 1; min-width: 0; }
  .icon-btn {
    width: 36px; height: 36px; padding: 0; font-size: 18px; line-height: 1;
    display: flex; align-items: center; justify-content: center; flex: none;
  }
  .logo {
    display: inline-block;
    font-family: "Segoe UI", system-ui, sans-serif; font-size: 22px; font-weight: 700;
    letter-spacing: 0.02em; line-height: 1.15; color: var(--text); white-space: nowrap;
    user-select: none;
    animation: logo-bloom 3.5s ease-in-out infinite;
  }
  @keyframes logo-bloom {
    0%, 100% { text-shadow: 0 0 5px var(--accent), 0 0 12px var(--accent), 0 0 24px var(--accent); opacity: .92; }
    50% { text-shadow: 0 0 8px var(--accent), 0 0 20px var(--accent), 0 0 44px var(--accent); opacity: 1; }
  }
  .tabs { display: flex; gap: 8px; margin-bottom: 14px; }
  .tab {
    padding: 8px 22px; border: 1px solid var(--surface); border-radius: 8px;
    background: var(--surface); color: var(--text); font-size: 14px; cursor: pointer;
  }
  .tab.active { background: var(--accent); color: var(--bg); border-color: var(--accent); }
  .panel { margin-bottom: 4px; }
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
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 50;
  }
  .sheet {
    position: fixed; top: 0; right: 0; bottom: 0; width: 330px; max-width: 92vw;
    background: var(--surface); border-left: 1px solid var(--widget);
    padding: 14px 16px; overflow-y: auto; z-index: 51;
    box-shadow: -8px 0 24px rgba(0,0,0,.45);
  }
  .sheet-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
  .sheet-title { font-size: 16px; font-weight: 600; }
  .sheet-body label { margin-top: 14px; }
  .note { margin-top: 6px; font-size: 12px; opacity: .7; }
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
  <div class="head">
    <div class="brand">
      <h1 class="logo">Synfronia</h1>
      <div class="sub" data-i18n="ui.sub">Скачивание видео и плейлистов YouTube (yt-dlp)</div>
    </div>
    <button type="button" id="settings-btn" class="icon-btn" data-i18n-title="ui.settings" title="Настройки">&#x2699;&#xFE0E;</button>
  </div>

  <div class="tabs">
    <button type="button" id="tab-video" class="tab active" data-i18n="tab.video">Видео</button>
    <button type="button" id="tab-playlist" class="tab" data-i18n="tab.playlist">Плейлист</button>
  </div>

  <div id="panel-video" class="panel">
    <label for="url-video" data-i18n="url.video.label">Ссылка на видео:</label>
    <input type="text" id="url-video" placeholder="https://www.youtube.com/watch?v=…" autofocus>
  </div>

  <div id="panel-playlist" class="panel" hidden>
    <label for="url-playlist" data-i18n="url.playlist.label">Ссылка на плейлист:</label>
    <input type="text" id="url-playlist" placeholder="https://www.youtube.com/playlist?list=…">
    <div class="check"><input type="checkbox" id="group"><span data-i18n="group.label">Сгруппировать: плейлист в подпапку с его названием</span></div>
  </div>

  <div id="warn" data-i18n="warn.ffmpeg">ffmpeg не найден — слияние, субтитры, метаданные и перекодировка будут недоступны.</div>

  <div class="actions">
    <button id="download" data-i18n="btn.download">Скачать</button>
    <button id="stop" disabled data-i18n="btn.stop">Отмена</button>
  </div>

  <div class="pb-wrap"><div id="pb"></div></div>
  <div id="status">Готов.</div>
  <textarea id="log" readonly></textarea>
  <div class="clicker-row">
    <button type="button" id="clicker" class="clicker" data-i18n-title="clicker.title" title="…">&#x25CF;</button>
    <span id="clicker-count" class="clicker-count">0/322</span>
  </div>

  <div id="settings-overlay" class="overlay" hidden></div>
  <div id="settings-sheet" class="sheet" hidden>
    <div class="sheet-head">
      <span class="sheet-title" data-i18n="ui.settings">Настройки</span>
      <button type="button" id="settings-close" class="icon-btn" data-i18n-title="ui.close" title="Закрыть">&#x2715;&#xFE0E;</button>
    </div>
    <div class="sheet-body">
      <label for="lang" data-i18n="sheet.lang.label">Язык:</label>
      <select id="lang"></select>
      <label for="dest" data-i18n="sheet.dest.label">Папка скачивания:</label>
      <div class="row">
        <input type="text" id="dest">
        <button type="button" id="browse" data-i18n="sheet.browse">Обзор…</button>
      </div>
      <label for="theme" data-i18n="sheet.theme.label">Тема:</label>
      <select id="theme"></select>
      <label for="subs" data-i18n="sheet.subs.label">Субтитры:</label>
      <select id="subs"></select>
      <label for="qual" data-i18n="sheet.qual.label">Ограничение качества:</label>
      <select id="qual"></select>
      <label for="transcode" data-i18n="sheet.transcode.label">Перекодировка:</label>
      <select id="transcode"></select>
      <div id="transcode-note" class="note"></div>
    </div>
  </div>

<script>
  var THEMES = {
    scary_forest:   { bg: "#0c1622", surface: "#1f2b29", widget: "#23444b", text: "#dcdedd", accent: "#628d7c" },
    technology_day: { bg: "#00181a", surface: "#00585a", widget: "#003638", text: "#dcdedd", accent: "#00989b" },
    technology_pinks: { bg: "#ffebec", surface: "#ffcbe2", widget: "#ffffff", text: "#5d2547", accent: "#c15f9b" },
    scarred_mind: { bg: "#252b47", surface: "#2f3b65", widget: "#1e2542", text: "#b9c2d6", accent: "#f1b970" },
    audrey_main: { bg: "#fff5f0", surface: "#f9f9f9", widget: "#ededed", text: "#5d5d5d", accent: "#96af9b" },
    night_sky: { bg: "#373051", surface: "#3b2f4d", widget: "#323756", text: "#fffedd", accent: "#fff2c9" }
  };
  var I18N = __I18N__;
  var LANGS = ["ru", "en", "ja", "zh-CN", "es", "de"];
  var TRANS_KEYS = ["none", "libx265", "nvenc", "amf", "qsv"];
  var QUAL_OPTIONS = [
    ["lossless", "qual.lossless"], ["8k", "8K"], ["4k", "4K"], ["2k", "2K (1440p)"],
    ["1080", "1080p"], ["720", "720p"], ["480", "480p"], ["240", "240p"]
  ];
  var SUB_OPTIONS = [["off", "subs.off"], ["ru", "subs.ru"], ["en", "subs.en"], ["all", "subs.all"]];
  var since = 0;
  var busy = false;
  var activeTab = "video";
  var curLang = "ru";
  var clicks = 0;
  var transAvailability = { ffmpeg: true, avail: [] };

  function t(key) {
    var d = I18N[curLang] || I18N.ru;
    if (d && d[key] !== undefined) return d[key];
    if (I18N.ru[key] !== undefined) return I18N.ru[key];
    return key;
  }

  function fillSelect(id, opts, keepValue) {
    var sel = document.getElementById(id);
    if (!keepValue) keepValue = sel.value;
    sel.innerHTML = "";
    opts.forEach(function(o) {
      var opt = document.createElement("option");
      opt.value = o[0];
      opt.textContent = t(o[1]);
      sel.appendChild(opt);
    });
    sel.value = keepValue;
  }

  function buildThemeOptions() { fillSelect("theme", Object.keys(THEMES).map(function(k) { return [k, "theme_" + k]; })); }
  function buildSubsOptions() { fillSelect("subs", SUB_OPTIONS); }
  function buildQualOptions() { fillSelect("qual", QUAL_OPTIONS); }
  function buildTranscodeOptions() {
    var sel = document.getElementById("transcode");
    var prev = sel.value;
    sel.innerHTML = "";
    var missing = [];
    TRANS_KEYS.forEach(function(key) {
      var o = document.createElement("option");
      o.value = key;
      var label = t("trans." + key);
      if (key !== "none" && (!transAvailability.ffmpeg || transAvailability.avail.indexOf(key) === -1)) {
        o.disabled = true;
        missing.push(label);
        o.textContent = label + " " + t("trans.unavailable");
      } else {
        o.textContent = label;
      }
      sel.appendChild(o);
    });
    sel.value = prev;
    var note = document.getElementById("transcode-note");
    if (!transAvailability.ffmpeg) {
      note.textContent = t("trans.note.noffmpeg");
    } else if (missing.length) {
      note.textContent = t("trans.note.missing") + missing.join(", ") + ".";
    }
  }
  function buildLangOptions() { fillSelect("lang", LANGS.map(function(k) { return [k, "lang." + k]; })); }

  function applyI18n() {
    document.querySelectorAll("[data-i18n]").forEach(function(el) {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-title]").forEach(function(el) {
      el.title = t(el.getAttribute("data-i18n-title"));
    });
    buildThemeOptions();
    buildSubsOptions();
    buildQualOptions();
    buildTranscodeOptions();
    buildLangOptions();
    document.getElementById("lang").value = curLang;
    document.documentElement.lang = curLang;
    if (!busy) document.getElementById("status").textContent = t("status.ready");
  }

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
    ["tab-video", "tab-playlist", "url-video", "url-playlist", "settings-btn", "dest", "browse", "group", "theme", "subs", "qual", "transcode", "lang"]
      .forEach(function(id) { document.getElementById(id).disabled = b; });
  }

  function switchTab(name) {
    activeTab = name;
    document.getElementById("tab-video").classList.toggle("active", name === "video");
    document.getElementById("tab-playlist").classList.toggle("active", name === "playlist");
    document.getElementById("panel-video").hidden = name !== "video";
    document.getElementById("panel-playlist").hidden = name !== "playlist";
    if (!busy) document.getElementById(name === "video" ? "url-video" : "url-playlist").focus();
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
      url: document.getElementById(activeTab === "video" ? "url-video" : "url-playlist").value.trim(),
      dest: document.getElementById("dest").value.trim(),
      playlist: activeTab === "playlist",
      group: document.getElementById("group").checked,
      subtitles: document.getElementById("subs").value,
      quality: document.getElementById("qual").value,
      transcode: document.getElementById("transcode").value,
    };
  }

  function init() {
    if (window.__initDone) return;
    window.__initDone = true;
    pywebview.api.get_initial().then(function(initData) {
    curLang = initData.settings.language || "ru";
    if (LANGS.indexOf(curLang) === -1) curLang = "ru";
    transAvailability = { ffmpeg: !!initData.ffmpeg, avail: initData.transcoders || [] };
    buildThemeOptions();
    buildSubsOptions();
    buildQualOptions();
    buildTranscodeOptions();
    applyI18n();
    document.getElementById("theme").value = initData.settings.theme || "scary_forest";
    document.getElementById("subs").value = initData.settings.subtitles || "en";
    document.getElementById("qual").value = initData.settings.quality || "lossless";
    document.getElementById("transcode").value = initData.settings.transcode || "none";
    document.getElementById("lang").value = curLang;
    applyTheme(document.getElementById("theme").value);
    document.getElementById("dest").value = initData.default_dir;
    document.getElementById("group").checked = initData.settings.group_playlist !== false;
    document.getElementById("status").textContent = t("status.ready");
    if (!initData.ffmpeg) document.getElementById("warn").style.display = "block";
    document.getElementById("theme").addEventListener("change", function() {
      applyTheme(this.value); pywebview.api.save_setting("theme", this.value);
    });
    document.getElementById("subs").addEventListener("change", function() {
      pywebview.api.save_setting("subtitles", this.value);
    });
    document.getElementById("qual").addEventListener("change", function() {
      pywebview.api.save_setting("quality", this.value);
    });
    document.getElementById("transcode").addEventListener("change", function() {
      pywebview.api.save_setting("transcode", this.value);
    });
    document.getElementById("group").addEventListener("change", function() {
      pywebview.api.save_setting("group_playlist", this.checked);
    });
    document.getElementById("lang").addEventListener("change", function() {
      curLang = this.value;
      applyI18n();
      applyTheme(document.getElementById("theme").value);
      pywebview.api.save_setting("language", this.value);
    });
    document.getElementById("download").addEventListener("click", async function() {
      var cfg = collect();
      if (!cfg.url) {
        document.getElementById("status").textContent = activeTab === "video"
          ? t("status.enter.video") : t("status.enter.playlist");
        return;
      }
      if (!cfg.playlist && /[?&]list=/.test(cfg.url)) {
        document.getElementById("status").textContent = t("status.playlist.warning");
      }
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
    document.getElementById("clicker").addEventListener("click", function() {
      var btn = document.getElementById("clicker");
      var countEl = document.getElementById("clicker-count");
      clicks++;
      btn.classList.add("pressed");
      setTimeout(function() { btn.classList.remove("pressed"); }, 120);
      countEl.textContent = Math.min(clicks, 322) + "/322";
      if (clicks >= 322) {
        clicks = 0;
        countEl.textContent = "0/322";
        var themeSel = document.getElementById("theme");
        themeSel.value = "night_sky";
        applyTheme("night_sky");
        pywebview.api.save_setting("theme", "night_sky");
        document.getElementById("status").textContent = t("clicker.unlocked");
      }
    });
    function openSettings() {
      document.getElementById("settings-overlay").hidden = false;
      document.getElementById("settings-sheet").hidden = false;
    }
    function closeSettings() {
      document.getElementById("settings-overlay").hidden = true;
      document.getElementById("settings-sheet").hidden = true;
    }
    document.getElementById("settings-btn").addEventListener("click", openSettings);
    document.getElementById("settings-close").addEventListener("click", closeSettings);
    document.getElementById("settings-overlay").addEventListener("click", closeSettings);
    document.addEventListener("keydown", function(ev) {
      if (ev.key === "Escape") closeSettings();
    });
    ["url-video", "url-playlist"].forEach(function(id) {
      document.getElementById(id).addEventListener("keydown", function(ev) {
        if (ev.key === "Enter") document.getElementById("download").click();
      });
    });
    document.getElementById("tab-video").addEventListener("click", function() { switchTab("video"); });
    document.getElementById("tab-playlist").addEventListener("click", function() { switchTab("playlist"); });
    }).catch(function(e) { console.error("init error:", e); });
  }
  if (window.pywebview !== undefined) { init(); }
  else { window.addEventListener("pywebviewready", init); }
  setTimeout(tick, 400);
</script>
</body>
</html>
"""

HTML = HTML.replace("__I18N__", json.dumps(I18N, ensure_ascii=False))


class Api:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.dl: Downloader | None = None
        self._transcoders: list[str] | None = None
        self._lock = threading.Lock()
        self._logs: list[str] = []
        self._lang = self.settings.get("language", "ru")
        self._status = tr(self._lang, "p.ready")
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
        if self._transcoders is None:
            self._transcoders = available_transcoders()
        return {
            "settings": dict(self.settings),
            "ffmpeg": bool(find_ffmpeg()),
            "default_dir": str(default_download_dir()),
            "transcoders": list(self._transcoders),
        }

    # -- настройки -----------------------------------------------------------
    def save_setting(self, key: str, value) -> str:
        if key in DEFAULT_SETTINGS:
            self.settings[key] = value
            if key == "language":
                self._lang = str(value)
                if not self._busy:
                    self._status = tr(self._lang, "p.ready")
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
            return {"error": tr(self._lang, "p.enter_url")}
        playlist = bool(cfg.get("playlist"))
        if not playlist and is_playlist(url):
            self._log("warning", tr(self._lang, "p.playlist_warn"))
        with self._lock:
            self._busy = True
            self._status = tr(self._lang, "p.start")
            self._progress = {"mode": "indeterminate"}
        self.dl = Downloader(on_log=self._log, on_progress=self._on_progress, lang=self._lang)
        threading.Thread(
            target=lambda: self._run(url, dest, playlist,
                                     bool(cfg.get("group", True)),
                                     cfg.get("subtitles", "en"),
                                     cfg.get("quality", "lossless"),
                                     cfg.get("transcode", "none") or "none"),
            daemon=True,
            name="yt-dlp",
        ).start()
        return {}

    def _run(self, url, dest, playlist, group, subtitles, quality, transcode) -> None:
        try:
            self.dl.download(
                url,
                dest,
                playlist=playlist,
                group=group,
                subtitles=subtitles,
                quality=quality,
                transcode=transcode,
            )
        except Exception as exc:  # noqa: BLE001
            self._log("error", str(exc))
        finally:
            with self._lock:
                self._busy = False
                self._status = tr(self._lang, "p.ready")
                self._progress = {"mode": "determinate", "value": 100.0}

    def stop_download(self) -> None:
        if self.dl:
            self._log("warning", tr(self._lang, "p.stop_req"))
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
                    self._status = f"{name} — {tr(self._lang, 'p.going')}"
                    self._progress = {"mode": "indeterminate"}
                else:
                    self._progress = {"mode": "determinate", "value": percent}
                    bits = f"{percent:.0f}%"
                    spd = f"{d['speed'] / 1024 / 1024:.1f} {tr(self._lang, 'p.mbps')}" if d.get("speed") else ""
                    eta = (f" {tr(self._lang, 'p.eta_prefix')} {int(d['eta'])}{tr(self._lang, 'p.eta_sec')}"
                           if d.get("eta") else "")
                    self._status = f"{name} — {bits}{(' | ' + spd) if spd else ''}{eta}"
            elif status == "postprocessing":
                self._status = d.get("msg") or tr(self._lang, "p.post")
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
        subtitles = "en"
        quality = "lossless"
        transcode = "none"
        for opt in sys.argv[4:]:
            if opt.startswith("--subtitles="):
                subtitles = opt.split("=", 1)[1]
            elif opt.startswith("--quality="):
                quality = opt.split("=", 1)[1]
            elif opt.startswith("--transcode="):
                transcode = opt.split("=", 1)[1]
            elif opt == "--hevc":
                transcode = "libx265"
        with open(base_dir() / "selftest.log", "w", encoding="utf-8") as f:
            dl = Downloader(on_log=lambda lvl, msg: f.write(f"[{lvl}] {msg}\n"))
            dl.download(url, dest, subtitles=subtitles, quality=quality, transcode=transcode)
        print("selftest done")
        sys.exit(0)

    main()