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
  var LOG_LINES = 2000; // сколько строк лога держим в textarea
  var LOG_CHARS = 120000; // порог (~2000 строк) для обрезки без split на каждом poll
  var pollTimer = 0;
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
  var FONTS = { families: [], count: 0, folder: "" };
  var fontsRev = -1;   // счётчик пересканирования шрифтов со стороны Python
  // Выбор шрифтов из настроек (без кавычек) — нужен, чтобы при переключении
  // темы вернуть шрифт, если у темы нет своих font/font_mono, и чтобы запросить
  // @font-face именно для этих семейств.
  var FONT_PICK = { sans: "", mono: "" };

  function quoted(family) {
    return family ? '"' + String(family).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"' : "";
  }
  function setFontVar(prop, value) {
    var root = document.documentElement.style;
    if (value) root.setProperty(prop, value);
    else root.removeProperty(prop);
  }
  // @font-face лежат в <style id="fonts-style"> (подставляет themes.build_page).
  // Подменяем содержимое целиком — дубликаты не копятся, страница не грузится
  // заново, поэтому состояние интерфейса (вкладки, поля, лог) сохраняется.
  function applyFontCss(css) {
    var el = document.getElementById("fonts-style");
    if (!el) {
      el = document.createElement("style");
      el.id = "fonts-style";
      document.head.appendChild(el);
    }
    el.textContent = css || "";
  }
  function loadFontFaces(families) {
    var list = (families || []).filter(Boolean).filter(function(f, i, arr) {
      return arr.indexOf(f) === i;
    });
    if (!list.length) { applyFontCss(""); return Promise.resolve(); }
    return pywebview.api.font_face_css(list)
      .then(function(css) { applyFontCss(css); })
      .catch(function(e) { console.error("font faces:", e); });
  }

  /* ---- кнопка-гиперпространство (mephysto/poKNxoY) ---- */
  var hyperspace = (function hyperspaceButton() {
    var canvas = ffmpegDlBtn.querySelector("canvas");
    var ctx = canvas.getContext("2d");
    var PARTICLES = [];
    var isGoing = false;
    var rafId = 0;
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

    // requestAnimationFrame крутится только пока анимация идёт: в простое
    // это пустой 60 fps впустую (батарея/CPU), поэтому кадр сам себя
    // останавливает, а play()/resume() снова его запускают.
    function frame() {
      ctx.fillStyle = "rgba(0,0,0,0.28)";
      ctx.fillRect(0, 0, W, H);
      for (var i = 0; i < PARTICLES.length; i++) PARTICLES[i].render();
      rafId = isGoing ? requestAnimationFrame(frame) : 0;
    }

    function play() {
      isGoing = true;
      if (!rafId) rafId = requestAnimationFrame(frame);
    }

    function stop() {
      isGoing = false;
      if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      ctx.clearRect(0, 0, W, H);
    }

    function pause() { if (rafId) { cancelAnimationFrame(rafId); rafId = 0; } }
    function resume() { if (isGoing) play(); }

    function init() {
      size();
      PARTICLES = [];
      var num = 60;
      for (var i = 0; i < num; i++) PARTICLES.push(new Particle());
      window.addEventListener("resize", function() { size(); if (isGoing) play(); });
    }
    ffmpegDlBtn.addEventListener("click", function() {
      if (ffmpegFetching) return;
      ffmpegFetching = true;
      play();
      ffmpegDlBtn.classList.add("active");
      ffmpegDlBtn.querySelector("span").style.display = "block";
      setFfmpegProgress(0);
      showFfmpegProgress();
      doFfmpegDownload();
    });
    setTimeout(init, 50);
    return { play: play, stop: stop, pause: pause, resume: resume };
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
      if (th.warnings && th.warnings.length) {
        label += " \u26A0";
        opt.title = t("theme.meta.broken") + "\n" + th.warnings.join("\n");
      }
      opt.textContent = label;
      sel.appendChild(opt);
    });
    sel.value = keep;
    if (sel.value === "") {
      var _f = sel.querySelector("option");
      sel.value = _f ? _f.value : "";
    }
    updateThemeMeta();
  }

  // Метаданные темы (автор/версия) и предупреждения валидации theme.json.
  function updateThemeMeta() {
    var box = document.getElementById("theme-meta");
    if (!box) return;
    var sel = document.getElementById("theme");
    var th = THEMES[sel.value] || {};
    var parts = [];
    if (th.label) parts.push(th.label);
    if (th.author) parts.push(t("theme.meta.author").replace("{name}", th.author));
    if (th.version) parts.push(t("theme.meta.version").replace("{v}", th.version));
    box.textContent = parts.join(" · ");
    box.hidden = parts.length === 0;
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

  // Списки шрифтов: "" = системный. Семейства приходят с Python (папка fonts).
  function buildFontOptions() {
    var families = (FONTS && FONTS.families) || [];
    var monoFirst = (FONTS && FONTS.mono) || [];
    var monoAll = monoFirst.concat(families.filter(function(f) {
      return monoFirst.indexOf(f) === -1;
    }));
    [["font-sans", families], ["font-mono", monoAll]].forEach(function(pair) {
      var sel = document.getElementById(pair[0]);
      if (!sel) return;
      var keep = sel.value;
      sel.innerHTML = "";
      var sys = document.createElement("option");
      sys.value = "";
      sys.textContent = t("sheet.font.system");
      sel.appendChild(sys);
      pair[1].forEach(function(f) {
        var o = document.createElement("option");
        o.value = f;
        o.textContent = f;
        sel.appendChild(o);
      });
      sel.value = keep;
    });
    updateFontNote();
  }
  function updateFontNote() {
    var box = document.getElementById("font-note");
    if (!box) return;
    if ((FONTS && FONTS.count) > 0) { box.textContent = ""; box.hidden = true; return; }
    box.textContent = t("sheet.font.hint").replace("{path}", (FONTS && FONTS.folder) || "");
    box.hidden = false;
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
    buildFontOptions();
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
    setFontVar("--font-sans", c.font ? quoted(c.font) : quoted(FONT_PICK.sans));
    setFontVar("--font-mono", c.font_mono ? quoted(c.font_mono) : quoted(FONT_PICK.mono));
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
    ["tab-video", "tab-playlist", "url-video", "url-playlist", "settings-btn", "dest", "browse", "group", "theme", "subs", "qual", "transcode", "lang", "font-sans", "font-mono"]
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

  function scheduleTick(delay) {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = document.hidden ? 0 : setTimeout(tick, delay);
  }

  async function tick() {
    pollTimer = 0;
    if (typeof pywebview === "undefined") { scheduleTick(300); return; }
    try {
      var st = await pywebview.api.poll(since);
      if (typeof st.log_cursor === "number") since = st.log_cursor;
      if (st.logs && st.logs.length) {
        var box = document.getElementById("log");
        box.value += st.logs.join("\n") + "\n";
        if (box.value.length > LOG_CHARS) {
          var all = box.value.split("\n");
          box.value = all.slice(all.length - LOG_LINES).join("\n");
        }
        box.scrollTop = box.scrollHeight;
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
            hyperspace.stop();
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
          hyperspace.stop();
          document.getElementById("ffmpeg-progress").classList.add("ffmpeg-hidden");
          ffmpegDlBtn.classList.remove("ffmpeg-hidden", "active");
          updateFfmpegStatus(fm.error);
          ffmpegRetry.style.display = "inline-block";
          ffmpegFetching = false;
        }
      }
      fontDlState(st);
      // Шрифты докачались на стороне Python: перерисовываем списки и @font-face.
      if (typeof st.fonts_rev === "number" && st.fonts_rev !== fontsRev) {
        fontsRev = st.fonts_rev;
        reloadFonts();
      }
    } catch (e) {}
    scheduleTick(200);
  }

  // -- вкладка FTP -----------------------------------------------------------
  // Поля FTP сохраняются по событию change (потеря фокуса/Enter), чтобы не
  // писать в settings.json на каждый символ. Пароль хранится как есть.
  var FTP_DEFAULTS = { ftp_port: 21, ftp_timeout: 60, ftp_retries: 3 };
  var FTP_FIELDS = [
    ["ftp-active", "ftp_active", "bool"],
    ["ftp-mode", "ftp_mode", "text"],
    ["ftp-host", "ftp_host", "text"],
    ["ftp-port", "ftp_port", "int"],
    ["ftp-user", "ftp_user", "text"],
    ["ftp-password", "ftp_password", "text"],
    ["ftp-tls", "ftp_tls", "bool"],
    ["ftp-tls-verify", "ftp_tls_verify", "bool"],
    ["ftp-pasv", "ftp_pasv", "bool"],
    ["ftp-delete-local", "ftp_delete_local", "bool"],
    ["ftp-dir", "ftp_dir", "text"],
    ["ftp-template", "ftp_template", "text"],
    ["ftp-timeout", "ftp_timeout", "int"],
    ["ftp-retries", "ftp_retries", "int"],
  ];

  function updateFtpVisibility() {
    var on = document.getElementById("ftp-active").checked;
    document.getElementById("ftp-fields").hidden = !on;
  }

  function updateFtpDirNote() {
    var dir = document.getElementById("ftp-dir").value.trim();
    document.getElementById("ftp-dir-note").textContent = dir
      ? t("sheet.ftp.dir.ok")
      : t("sheet.ftp.dir.empty");
  }

  function initFtp(settings) {
    FTP_FIELDS.forEach(function(spec) {
      var el = document.getElementById(spec[0]);
      var value = settings[spec[1]];
      if (spec[2] === "bool") el.checked = value !== false && !!value;
      else if (spec[2] === "int") el.value = value || FTP_DEFAULTS[spec[1]] || "";
      else el.value = value || el.placeholder || "";
    });
    updateFtpVisibility();
    updateFtpDirNote();
    FTP_FIELDS.forEach(function(spec) {
      var el = document.getElementById(spec[0]);
      var event = (spec[2] === "bool" || spec[2] === "int") ? "change" : "change";
      el.addEventListener(event, function() {
        var value = spec[2] === "bool" ? this.checked
                  : spec[2] === "int" ? parseInt(this.value, 10) || 0
                  : this.value.trim();
        if (spec[1] === "ftp_active") updateFtpVisibility();
        if (spec[1] === "ftp_dir") updateFtpDirNote();
        pywebview.api.save_setting(spec[1], value);
      });
    });
    document.getElementById("ftp-test").addEventListener("click", async function() {
      var note = document.getElementById("ftp-test-note");
      note.className = "note";
      note.textContent = t("sheet.ftp.testing");
      var res = await pywebview.api.test_ftp();
      if (res && res.ok) {
        note.className = "note ok";
        note.textContent = t("sheet.ftp.test_ok").replace("{host}", res.host);
      } else {
        note.className = "note bad";
        note.textContent = (res && res.error) || t("sheet.ftp.test_fail");
      }
    });
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
  // @font-face встраиваются на стороне Python, но применяются подменой блока
  // #fonts-style — без перезагрузки страницы и без потери состояния UI.
  function setFont(id, value) {
    var slot = id === "font-mono" ? "mono" : "sans";
    pywebview.api.set_font(id === "font-mono" ? "font_mono" : "font_sans", value)
      .then(function(r) {
        if (r && r.error) { console.error("set font:", r.error); return; }
        FONT_PICK[slot] = value || "";
        if (r && r.css !== undefined) applyFontCss(r.css);
        var th = THEMES[document.getElementById("theme").value] || {};
        var thFont = slot === "mono" ? th.font_mono : th.font;
        setFontVar(slot === "mono" ? "--font-mono" : "--font-sans",
                   quoted(thFont || FONT_PICK[slot]));
      })
      .catch(function(e) { console.error("set font:", e); });
  }
  function reloadFonts() {
    pywebview.api.reload_fonts()
      .then(function(r) {
        if (r && r.fonts) FONTS = r.fonts;
        if (r && r.css !== undefined) applyFontCss(r.css);
        buildFontOptions();
        applyI18n();
      })
      .catch(function(e) { console.error("reload fonts:", e); });
  }
  // Докачка шрифтов из сети: кнопка busy на всё время, прогресс в note.
  // Список обновится сам, когда Python поднимет fonts_rev (см. tick).
  function downloadFonts() {
    var btn = document.getElementById("download-fonts");
    var note = document.getElementById("font-dl-note");
    pywebview.api.download_fonts()
      .then(function(res) {
        if (res === "busy") { setFontDlNote(t("font.dl.busy")); return; }
        btn.classList.add("busy");
        btn.disabled = true;
        setFontDlNote(t("font.dl.start"));
      })
      .catch(function(e) {
        btn.classList.remove("busy");
        btn.disabled = false;
        setFontDlNote(t("font.dl.fail").replace("{names}", String(e)));
      });
  }
  function setFontDlNote(text) {
    var note = document.getElementById("font-dl-note");
    if (!note) return;
    note.textContent = text || "";
    note.hidden = !text;
  }
  function fontDlState(st) {
    var d = st.fonts_dl;
    if (!d) return;
    var btn = document.getElementById("download-fonts");
    if (d.downloading) {
      if (btn) { btn.classList.add("busy"); btn.disabled = true; }
      setFontDlNote(t("font.dl.progress").replace("{pct}", String(Math.round(d.pct || 0))));
    } else if (btn && btn.disabled) {
      btn.classList.remove("busy");
      btn.disabled = false;
      setFontDlNote(d.error ? t("font.dl.fail").replace("{names}", String(d.error)) : "");
    }
  }
  function openFontsFolder() {
    pywebview.api.open_fonts_folder();
  }

  function init() {
    if (window.__initDone) return;
    window.__initDone = true;
    pywebview.api.get_initial().then(function(initData) {
    curLang = initData.settings.language || "en";
    if (LANGS.indexOf(curLang) === -1) curLang = "en";
    transAvailability = { ffmpeg: !!initData.ffmpeg, avail: initData.transcoders || [] };
    FONTS = initData.fonts || FONTS;
    FONT_PICK.sans = initData.settings.font_sans || "";
    FONT_PICK.mono = initData.settings.font_mono || "";
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
    document.getElementById("font-sans").value = initData.settings.font_sans || "";
    document.getElementById("font-mono").value = initData.settings.font_mono || "";
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
      updateThemeMeta();
      var _t = THEMES[this.value] || {};
      // Темы со своим entry собираются в Python: там нужен полный rebuild
      // страницы (свой HTML). Остальные применяются на лету, @font-face темы
      // догружаем отдельным запросом.
      if (_t.entry) {
        pywebview.api.set_theme(this.value);
        return;
      }
      applyTheme(this.value);
      pywebview.api.save_setting("theme", this.value);
      if (_t.font || _t.font_mono) {
        loadFontFaces([_t.font, _t.font_mono, FONT_PICK.sans, FONT_PICK.mono]);
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
    ["font-sans", "font-mono"].forEach(function(id) {
      document.getElementById(id).addEventListener("change", function() { setFont(id, this.value); });
    });
    document.getElementById("lang").addEventListener("change", function() {
      curLang = this.value;
      applyI18n();
      buildFontOptions();   // подпись «системный» в списках шрифтов тоже переводится
      applyTheme(document.getElementById("theme").value);
      updateThemeMeta();
      pywebview.api.save_setting("language", this.value);
    });
    initFtp(initData.settings);
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
      ["ui", "dl", "ftp"].forEach(function(name) {
        document.getElementById("panel-" + name).hidden = name !== tab;
        document.getElementById("tab-" + name).classList.toggle("active", name === tab);
      });
    }
    document.getElementById("settings-btn").addEventListener("click", openSettings);
    document.getElementById("settings-close").addEventListener("click", closeSettings);
    document.getElementById("reload-themes").addEventListener("click", function() { reloadThemes(); });
    document.getElementById("open-themes").addEventListener("click", function() { openThemesFolder(); });
    document.getElementById("reload-fonts").addEventListener("click", function() { reloadFonts(); });
    document.getElementById("download-fonts").addEventListener("click", function() { downloadFonts(); });
    document.getElementById("open-fonts").addEventListener("click", function() { openFontsFolder(); });
    document.getElementById("settings-overlay").addEventListener("click", closeSettings);
    document.getElementById("tab-ui").addEventListener("click", function() { switchSettingsTab("ui"); });
    document.getElementById("tab-dl").addEventListener("click", function() { switchSettingsTab("dl"); });
    document.getElementById("tab-ftp").addEventListener("click", function() { switchSettingsTab("ftp"); });
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
  // Пока вкладка/окно скрыты, не опрашиваем Python и не крутим анимацию.
  document.addEventListener("visibilitychange", function() {
    if (document.hidden) {
      if (pollTimer) { clearTimeout(pollTimer); pollTimer = 0; }
      hyperspace.pause();
    } else {
      hyperspace.resume();
      scheduleTick(50);
    }
  });
  scheduleTick(400);