  var THEMES = __THEMES__;
  var I18N = __I18N__;
  var LANGS = Object.keys(I18N).filter(function(k) { return I18N[k] && I18N[k].thisLang; });
  var TRANS_KEYS = ["none", "libx265", "nvenc", "amf", "qsv"];
  var QUAL_OPTIONS = [
    ["lossless", "qual.lossless"], ["2k", "2K (1440p)"],
    ["1080", "1080p"], ["720", "720p"], ["480", "480p"], ["240", "240p"]
  ];
  var SUB_OPTIONS = [["off", "subs.off"], ["ru", "subs.ru"], ["en", "subs.en"], ["all", "subs.all"]];
  var since = 0;
  var busy = false;
  var activeTab = "video";
  var curLang = "en";
  var clicks = 0;
  var transAvailability = { ffmpeg: true, avail: [] };
  var ffmpegOverlay = document.getElementById("ffmpeg-overlay");
  var ffmpegDlBtn = document.getElementById("ffmpeg-dl");
  var ffmpegRain = document.getElementById("ffmpeg-rain");
  var ffmpegRing = document.getElementById("ffmpeg-ring");
  var ffmpegPercent = document.getElementById("ffmpeg-percent");
  var ffmpegStatus = document.getElementById("ffmpeg-status");
  var ffmpegRetry = document.getElementById("ffmpeg-retry");
  var ffmpegFetching = false;
  var RING_CIRC = 2 * Math.PI * 52;

  /* ---- кнопка-гиперпространство (mephysto/poKNxoY) ---- */
  (function hyperspaceButton() {
    var canvas = ffmpegDlBtn.querySelector("canvas");
    var ctx = canvas.getContext("2d");
    var PARTICLES = [];
    var isGoing = false;
    var W = 0, H = 0, XO = 0, YO = 0;
    var MAX_Z = 2, MAX_R = 2, Z_SPD = 2;

    function Particle() {
      this.x = Math.random() * W;
      this.y = Math.random() * H;
      this.z = Math.random() * MAX_Z;
      this.vel = 0.01 * Z_SPD;
    }
    Particle.prototype.update = function() { this.z -= this.vel; };
    Particle.prototype.render = function() {
      var z = Math.max(this.z, 0.0001);
      var px = (this.x - XO) / z * 6 + XO;
      var py = (this.y - YO) / z * 6 + YO;
      var r = ((MAX_Z - this.z) / MAX_Z) * MAX_R;
      if (px < 0 || px > W || py < 0 || py > H) this.z = MAX_Z;
      this.update();
      ctx.beginPath();
      ctx.arc(px, py, Math.max(r, 0.4), 0, Math.PI * 2);
      ctx.fillStyle = "rgba(255,255,255,0.55)";
      ctx.strokeStyle = "rgba(255,255,255,0.55)";
      ctx.fill();
      ctx.stroke();
    };

    function size() {
      canvas.width = W = ffmpegDlBtn.offsetWidth;
      canvas.height = H = ffmpegDlBtn.offsetHeight;
      XO = W / 2; YO = H / 2;
      if (W < 10 || H < 10) { canvas.width = W = 640; canvas.height = H = 148; XO = W / 2; YO = H / 2; }
    }
    function loop() {
      requestAnimationFrame(loop);
      if (!isGoing) { ctx.clearRect(0, 0, W, H); return; }
      ctx.fillStyle = "rgba(0,0,0,0.28)";
      ctx.fillRect(0, 0, W, H);
      for (var i = 0; i < PARTICLES.length; i++) PARTICLES[i].render();
    }

  function init() {
      size();
      PARTICLES = [];
      var num = 60;
      for (var i = 0; i < num; i++) PARTICLES.push(new Particle());
      loop();
      window.addEventListener("resize", size);
    }
    ffmpegDlBtn.addEventListener("click", function() {
      if (ffmpegFetching) return;
      ffmpegFetching = true;
      isGoing = true;
      ffmpegDlBtn.classList.add("active");
      ffmpegDlBtn.querySelector("span").style.display = "block";
      setFfmpegProgress(0);
      showFfmpegProgress();
      doFfmpegDownload();
    });
    setTimeout(init, 50);
  })();

  /* ---- дождь (по мотивам codepen jh3y/WyNdMG) ---- */
  (function buildRain() {
    var frag = document.createDocumentFragment();
    var drops = 90;
    for (var i = 0; i < drops; i++) {
      var d = document.createElement("i");
      d.style.setProperty("--x", (Math.random() * 100).toFixed(2) + "vw");
      d.style.setProperty("--len", (9 + Math.random() * 16).toFixed(2) + "vh");
      d.style.setProperty("--dur", (0.6 + Math.random() * 1.4).toFixed(2) + "s");
      d.style.setProperty("--delay", (Math.random() * 2.5).toFixed(2) + "s");
      d.style.setProperty("--op", (0.25 + Math.random() * 0.6).toFixed(2));
      frag.appendChild(d);
    }
    ffmpegRain.appendChild(frag);
  })();

  function setFfmpegProgress(pct) {
    var v = Math.max(0, Math.min(100, pct || 0));
    ffmpegRing.classList.remove("ffmpeg-extracting");
    ffmpegRing.querySelector(".ring-fg").style.strokeDashoffset = (RING_CIRC * (1 - v / 100)).toFixed(1);
    ffmpegPercent.textContent = String(Math.round(v)) + "%";
  }
  function setFfmpegExtracting() {
    ffmpegRing.classList.add("ffmpeg-extracting");
    ffmpegPercent.textContent = "\u2026";
  }
  function showFfmpegProgress() {
    ffmpegDlBtn.classList.add("ffmpeg-hidden");
    document.getElementById("ffmpeg-progress").classList.remove("ffmpeg-hidden");
  }
  function updateFfmpegStatus(text) {
    ffmpegStatus.classList.remove("ffmpeg-hidden");
    ffmpegStatus.textContent = text;
  }

  async function doFfmpegDownload() {
    try {
      await pywebview.api.start_ffmpeg_download();
    } catch (e) {}
  }

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

  function buildThemeOptions() {
    var sel = document.getElementById("theme");
    var keep = sel.value;
    sel.innerHTML = "";
    Object.keys(THEMES).forEach(function(k) {
      var th = THEMES[k] || {};
      if (th.hidden === true) return;
      var opt = document.createElement("option");
      opt.value = k;
      var label = (I18N[curLang] || I18N.ru || {})["theme_" + k];
      if (label === undefined && (I18N.ru || {})["theme_" + k] !== undefined) {
        label = I18N.ru["theme_" + k];
      }
      if (label === undefined) label = th.label || k;
      opt.textContent = label;
      sel.appendChild(opt);
    });
    sel.value = keep;
    if (sel.value === "") {
      var _f = sel.querySelector("option");
      sel.value = _f ? _f.value : "";
    }
  }
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
    } else {
      note.textContent = "";
    }
  }
  function buildLangOptions() {
    fillSelect("lang", LANGS.filter(function(k) {
      return I18N[k] && I18N[k]["thisLang"];
    }).map(function(k) {
      return [k, I18N[k]["thisLang"]];
    }));
  }

  function renderClicker() {
    var btn = document.getElementById("clicker");
    btn.textContent = clicks === 0 ? t("clicker.hint") : clicks;
  }
  function clickerMessages() {
    var d = I18N[curLang] || I18N.ru || {};
    var arr = d["clicker.messages"];
    if (!Array.isArray(arr) && I18N.ru) arr = I18N.ru["clicker.messages"];
    return Array.isArray(arr) ? arr : [];
  }
  function flashClickerMsg() {
    var arr = clickerMessages();
    if (!arr.length) return;
    var el = document.getElementById("clicker-msg");
    el.textContent = arr[Math.floor(Math.random() * arr.length)];
    el.classList.add("show");
    setTimeout(function() { el.classList.remove("show"); }, 1400);
  }

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
    renderClicker();
    if (!busy) document.getElementById("status").textContent = t("status.ready");
  }

  function applyTheme(key) {
    var c = THEMES[key] || THEMES.scarred_mind || {};
    function pick(v, d) { return v !== undefined && v !== null ? v : d; }
    var root = document.documentElement.style;
    root.setProperty("--bg", pick(c.bg, "#0c1622"));
    root.setProperty("--surface", pick(c.surface, "#1f2b29"));
    root.setProperty("--widget", pick(c.widget, "#23444b"));
    root.setProperty("--text", pick(c.text, "#dcdedd"));
    root.setProperty("--accent", pick(c.accent, "#628d7c"));
    root.setProperty("--warn", pick(c.warn, "#ffb454"));
    root.setProperty("--radius-s", pick(c.radius_s, 6) + "px");
    root.setProperty("--radius-m", pick(c.radius_m, 8) + "px");
    root.setProperty("--radius-l", pick(c.radius_l, 12) + "px");
    root.setProperty("--opacity", pick(c.opacity, 1));
    var cssEl = document.getElementById("theme-style");
    if (!cssEl) {
      cssEl = document.createElement("style");
      cssEl.id = "theme-style";
      document.head.appendChild(cssEl);
    }
    cssEl.textContent = c.css || "";
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
      if (ffmpegFetching && st.ffmpeg) {
        var fm = st.ffmpeg;
        if (fm.downloading || fm.extracting) {
          showFfmpegProgress();
          if (fm.extracting) {
            setFfmpegExtracting();
            updateFfmpegStatus(t("ffmpeg.extracting"));
          } else {
            setFfmpegProgress(fm.pct || 0);
            updateFfmpegStatus(t("ffmpeg.downloading").replace("{pct}", String(Math.round(fm.pct || 0))));
          }
        } else if (fm.ok) {
          showFfmpegProgress();
          setFfmpegProgress(100);
          updateFfmpegStatus(t("ffmpeg.ready"));
          setTimeout(function() {
            ffmpegOverlay.classList.add("ffmpeg-hidden");
            pywebview.api.get_initial().then(function(id) {
              transAvailability = { ffmpeg: !!id.ffmpeg, avail: id.transcoders || [] };
              buildTranscodeOptions();
            });
            document.getElementById("warn").style.display = "none";
            document.getElementById("status").textContent = t("status.ready");
            ffmpegFetching = false;
          }, 500);
        } else if (fm.error) {
          showFfmpegProgress();
          document.getElementById("ffmpeg-progress").classList.add("ffmpeg-hidden");
          ffmpegDlBtn.classList.remove("ffmpeg-hidden", "active");
          ffmpegDlBtn.querySelector("canvas").getContext("2d").clearRect(0, 0, 2000, 2000);
          updateFfmpegStatus(fm.error);
          ffmpegRetry.style.display = "inline-block";
          ffmpegFetching = false;
        }
      }
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
      retries: parseInt(document.getElementById("retries").value, 10) || 10,
      socket_timeout: parseInt(document.getElementById("socket_timeout").value, 10) || 20,
    };
  }

  
  function reloadThemes() {
    var btn = document.getElementById("reload-themes");
    pywebview.api.reload_themes().then(function(newThemes) {
      THEMES = newThemes;
      buildThemeOptions();
      applyI18n();
      if (btn) {
        var lbl = btn.querySelector("[data-i18n]");
        if (lbl) {
          var txt = lbl.textContent;
          lbl.textContent = "\u2713";
          btn.classList.add("done");
          setTimeout(function() {
            lbl.textContent = txt;
            btn.classList.remove("done");
          }, 900);
        }
      }
    }).catch(function(e) { console.error("reload themes:", e); });
  }
  function openThemesFolder() {
    pywebview.api.open_themes_folder();
  }

  function init() {
    if (window.__initDone) return;
    window.__initDone = true;
    pywebview.api.get_initial().then(function(initData) {
    curLang = initData.settings.language || "en";
    if (LANGS.indexOf(curLang) === -1) curLang = "en";
    transAvailability = { ffmpeg: !!initData.ffmpeg, avail: initData.transcoders || [] };
    buildThemeOptions();
    buildSubsOptions();
    buildQualOptions();
    buildTranscodeOptions();
    applyI18n();
    document.getElementById("theme").value = initData.settings.theme || "scarred_mind";
    document.getElementById("subs").value = initData.settings.subtitles || "en";
    document.getElementById("qual").value = initData.settings.quality || "lossless";
    document.getElementById("transcode").value = initData.settings.transcode || "none";
    document.getElementById("retries").value = initData.settings.retries || 10;
    document.getElementById("retries-range").value = initData.settings.retries || 10;
    document.getElementById("socket_timeout").value = initData.settings.socket_timeout || 20;
    document.getElementById("socket_timeout-range").value = initData.settings.socket_timeout || 20;
    document.getElementById("lang").value = curLang;
    applyTheme(document.getElementById("theme").value);
    document.getElementById("dest").value = initData.default_dir;
    document.getElementById("group").checked = initData.settings.group_playlist !== false;
    document.getElementById("status").textContent = t("status.ready");
    if (!initData.ffmpeg) {
      document.getElementById("warn").style.display = "block";
      ffmpegOverlay.classList.remove("ffmpeg-hidden");
      ffmpegStatus.classList.add("ffmpeg-hidden");
    }
    document.getElementById("theme").addEventListener("change", function() {
      var _t = THEMES[this.value];
      if (_t && _t.entry) {
        pywebview.api.set_theme(this.value);
      } else {
        applyTheme(this.value); pywebview.api.save_setting("theme", this.value);
      }
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
    document.getElementById("retries").addEventListener("change", function() {
      document.getElementById("retries-range").value = this.value;
      pywebview.api.save_setting("retries", this.value);
    });
    document.getElementById("retries-range").addEventListener("input", function() {
      document.getElementById("retries").value = this.value;
      pywebview.api.save_setting("retries", this.value);
    });
    document.getElementById("socket_timeout").addEventListener("change", function() {
      document.getElementById("socket_timeout-range").value = this.value;
      pywebview.api.save_setting("socket_timeout", this.value);
    });
    document.getElementById("socket_timeout-range").addEventListener("input", function() {
      document.getElementById("socket_timeout").value = this.value;
      pywebview.api.save_setting("socket_timeout", this.value);
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
    ffmpegRetry.addEventListener("click", function() {
      ffmpegRetry.style.display = "none";
      ffmpegStatus.classList.add("ffmpeg-hidden");
      ffmpegDlBtn.classList.remove("ffmpeg-hidden");
      ffmpegFetching = true;
      ffmpegDlBtn.classList.add("active");
      setFfmpegProgress(0);
      showFfmpegProgress();
      doFfmpegDownload();
    });
    document.getElementById("clicker").addEventListener("click", function() {
      var btn = document.getElementById("clicker");
      clicks++;
      btn.classList.add("pressed");
      setTimeout(function() { btn.classList.remove("pressed"); }, 120);
      if (clicks % 500 === 0) flashClickerMsg();
      renderClicker();
    });
    function openSettings() {
      document.getElementById("settings-overlay").hidden = false;
      document.getElementById("settings-sheet").hidden = false;
    }
    function closeSettings() {
      document.getElementById("settings-overlay").hidden = true;
      document.getElementById("settings-sheet").hidden = true;
    }
    function switchSettingsTab(tab) {
      var isUi = tab === "ui";
      document.getElementById("panel-ui").hidden = !isUi;
      document.getElementById("panel-dl").hidden = isUi;
      document.getElementById("tab-ui").classList.toggle("active", isUi);
      document.getElementById("tab-dl").classList.toggle("active", !isUi);
    }
    document.getElementById("settings-btn").addEventListener("click", openSettings);
    document.getElementById("settings-close").addEventListener("click", closeSettings);
    document.getElementById("reload-themes").addEventListener("click", function() { reloadThemes(); });
    document.getElementById("open-themes").addEventListener("click", function() { openThemesFolder(); });
    document.getElementById("settings-overlay").addEventListener("click", closeSettings);
    document.getElementById("tab-ui").addEventListener("click", function() { switchSettingsTab("ui"); });
    document.getElementById("tab-dl").addEventListener("click", function() { switchSettingsTab("dl"); });
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