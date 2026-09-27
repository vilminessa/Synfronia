  var THEMES = __THEMES__;
  var I18N = __I18N__;
  var LANGS = Object.keys(I18N).filter(function(k) { return I18N[k] && I18N[k].thisLang; });
  // Схема настроек (settings_schema.py): из неё рисуется панель настроек и берутся
  // подписи списков - свои копии option-значений в app.js не нужны.
  var SETTINGS_SCHEMA = __SETTINGS_SCHEMA__;
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
      window.addEventListener("resize", function() {
  size(); if (isGoing) play();
  /* окно могло стать уже панели: подрезаем явную ширину, иначе подтягиваем ручку */
  var sheet = document.getElementById("settings-sheet");
  if (sheet && sheet.style.width) applySheetW(sheet.getBoundingClientRect().width);
  else syncSheetEdge();
});
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

  // Наполнение <select>: opts = [["value", "i18n.key"], ...]. keepValue=true
  // сохраняет выбор - список пересобирается при смене языка и при первой
  // отрисовке, когда значения из настроек ещё нет. Если прежнего значения в
  // списке не оказалось, берём первый вариант, чтобы поле не осталось пустым
  // (так же поступает buildThemeOptions).
  function fillSelectNode(sel, opts, keepValue) {
    if (!sel || !opts || !opts.length) return;
    if (!keepValue) keepValue = sel.value;
    sel.innerHTML = "";
    opts.forEach(function(o) {
      var opt = document.createElement("option");
      opt.value = o[0];
      opt.textContent = t(o[1]);
      sel.appendChild(opt);
    });
    sel.value = keepValue;
    if (sel.value === "") {
      var first = sel.querySelector("option");
      sel.value = first ? first.value : "";
    }
  }
  function fillSelect(id, opts, keepValue) {
    fillSelectNode(document.getElementById(id), opts, keepValue);
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
  function buildSubsOptions() { fillSelect("subs", fieldOptions("dl.subtitles")); }
  function buildQualOptions() { fillSelect("qual", fieldOptions("dl.quality")); }
  function buildTranscodeOptions() {
    var sel = document.getElementById("transcode");
    var prev = sel.value;
    sel.innerHTML = "";
    var missing = [];
    fieldOptions("dl.transcode").forEach(function(pair) {
      var o = document.createElement("option");
      o.value = pair[0];
      var label = t(pair[1]);
      if (pair[0] !== "none" && (!transAvailability.ffmpeg || transAvailability.avail.indexOf(pair[0]) === -1)) {
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
    // списки из схемы переводим первыми, дальше их уточняют сборщики полей
    fillSchemaChoices();
    buildThemeOptions();
    buildSubsOptions();
    buildQualOptions();
    buildTranscodeOptions();
    buildLangOptions();
    buildFontOptions();
    document.getElementById("lang").value = curLang;
    document.documentElement.lang = curLang;
    renderClicker();
    updateDownloadTitle();
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
    /* тема могла задать свою ширину панели (Liquid Glass — 340px): ручка обязана совпасть */
    syncSheetEdge();
  }

  /* ---- растягиваемая панель настроек ----
     Панель прижата к правому краю, тянем за левую кромку. Геометрию всегда держит JS:
     --sheet-w и --sheet-left задают и .sheet, и ручку, иначе кромка разъезжается
     (тема может отступовать панель от края окна, как Liquid Glass). */
  var SHEET_MIN = 260, SHEET_DEFAULT = 330, RESIZE_STEP = 16;
  function sheetMax() {
    return Math.max(SHEET_MIN, Math.round(window.innerWidth * 0.92));
  }
  function applySheetW(w) {
    w = Math.min(sheetMax(), Math.max(SHEET_MIN, Math.round(w)));
    document.getElementById("settings-sheet").style.width = w + "px";
    syncSheetEdge();
    return w;
  }
  /* Привязать ручку к левой кромке панели. Когда панель скрыта, размер и отступ
     берём из вычисленных стилей — иначе ручка прыгнет в угол при открытии. */
  function syncSheetEdge() {
    var sheet = document.getElementById("settings-sheet");
    if (!sheet) return;
    var r = sheet.getBoundingClientRect();
    var w = r.width;
    if (w <= 0) {
      var cs = window.getComputedStyle(sheet);
      w = parseFloat(cs.width) || SHEET_DEFAULT;
      var right = parseFloat(cs.right);
      if (isNaN(right)) right = 0;
      r = {width: w, left: window.innerWidth - right - w};
    }
    var root = document.documentElement.style;
    root.setProperty("--sheet-w", Math.round(w) + "px");
    root.setProperty("--sheet-left", Math.round(r.left) + "px");
  }
  function stopSheetResize() {
    if (!window.__sheetResizing) return;
    window.__sheetResizing = false;
    document.body.classList.remove("resizing");
    var handle = document.getElementById("sheet-resize");
    if (handle) handle.classList.remove("active");
  }
  function initSheetResize() {
    var handle = document.getElementById("sheet-resize");
    if (!handle) return;
    handle.addEventListener("pointerdown", function(ev) {
      if (ev.button !== 0) return;
      ev.preventDefault();
      window.__sheetResizing = true;
      document.body.classList.add("resizing");
      handle.classList.add("active");
      try { handle.setPointerCapture(ev.pointerId); } catch (e) { /* без захвата */ }
    });
    handle.addEventListener("pointermove", function(ev) {
      if (!window.__sheetResizing) return;
      ev.preventDefault();
      applySheetW(window.innerWidth - ev.clientX);
    });
    ["pointerup", "pointercancel"].forEach(function(type) {
      handle.addEventListener(type, stopSheetResize);
    });
    /* двойной клик — вернуть ширину по умолчанию */
    handle.addEventListener("dblclick", function() { applySheetW(SHEET_DEFAULT); });
    /* клавиатура: стрелки — шаг, Home/End — края, Enter — сброс */
    handle.addEventListener("keydown", function(ev) {
      var sheet = document.getElementById("settings-sheet");
      var w = sheet.getBoundingClientRect().width;
      var keys = {
        ArrowLeft: w + RESIZE_STEP, ArrowRight: w - RESIZE_STEP,
        Home: sheetMax(), End: SHEET_MIN, Enter: SHEET_DEFAULT
      };
      if (!(ev.key in keys)) return;
      ev.preventDefault();
      applySheetW(keys[ev.key]);
    });
  }

  /* ---- кнопка «Скачать»: прогресс внутри кнопки и SVG-результат ----
     Состояния: idle -> busy (determinate/indeterminate) -> ok|err|cancel -> idle.
     Итог держим 2 секунды, потом возвращаем «Скачать». Размеры задаёт .dl-label
     (она в потоке), проценты и иконка накладываются поверх.
     Процент - рекорд за текущую загрузку: yt-dlp считает его от размера
     ТЕКУЩЕГО файла, так что в плейлисте значение возвращалось к началу, а на
     постобработке и вовсе пропадало. dlBest не даёт заливке откатиться, а в
     неопределённом режиме мы не меняем ни заливку, ни число - только гоним
     блик, поэтому кнопка не мигает. */
  var DL_STATES = ["idle", "busy", "ok", "err", "warn", "fail", "cancel"];
  var DL_ICON = {
    ok: '<svg viewBox="0 0 24 24"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg>',
    err: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><path d="M12 16.2h.01"/></svg>',
    // полный провал: голый крест без круга - заметно отличается от «!» и
    // крупнее, потому что анимация dl-bulge выталкивает его за края кнопки
    fail: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12"/><path d="M18 6 6 18"/></svg>',
    cancel: '<svg viewBox="0 0 24 24"><path d="M8 3h8l5 5v8l-5 5H8l-5-5V8z"/><path d="M8.5 12h7"/></svg>'
  };
  DL_ICON.warn = DL_ICON.err;   // тот же «!», но подпись btn.warn
  var DL_TITLE = {idle: "btn.download", busy: "btn.downloading", ok: "btn.done",
                  err: "btn.partial", warn: "btn.warn", fail: "btn.failed",
                  cancel: "btn.cancelled"};
  var DL_RESULT = {ok: "ok", error: "err", warn: "warn", failed: "fail", cancelled: "cancel"};
  var DL_RESET_MS = 2000;
  var dlState = "idle";
  var dlBest = 0;         // рекорд процента за загрузку
  var dlIndeterminate = false;
  var dlShown = null;     // какой result уже показан, чтобы не мигать после сброса
  var dlTimer = 0;

  function updateDownloadTitle() {
    var btn = document.getElementById("download");
    var key = DL_TITLE[dlState] || "btn.download";
    btn.title = t(key);
    btn.setAttribute("aria-label", t(key));
  }
  function setDownloadState(state, pct, indeterminate) {
    if (DL_STATES.indexOf(state) === -1) state = "idle";
    var btn = document.getElementById("download");
    if (state !== dlState) {
      if (state === "busy") dlBest = 0;          // новая загрузка - новый рекорд
      clearTimeout(dlTimer);
      dlTimer = 0;
      DL_STATES.forEach(function(s) { btn.classList.remove("dl-" + s); });
      btn.classList.add("dl-" + state);
      btn.querySelector(".dl-icon").innerHTML = DL_ICON[state] || "";
      dlState = state;
      if (state === "ok" || state === "err" || state === "warn" ||
          state === "fail" || state === "cancel") {
        dlTimer = setTimeout(function() {
          dlTimer = 0;
          setDownloadState("idle", 0, false);
        }, DL_RESET_MS);
      }
    }
    // рекорд только растёт; в неопределённом режиме значение не трогаем
    if (state === "busy" && !indeterminate) dlBest = Math.max(dlBest, Math.min(100, pct || 0));
    dlIndeterminate = !!indeterminate;
    btn.classList.toggle("dl-indeterminate", state === "busy" && dlIndeterminate);
    // многоточие - только пока процент ещё ни разу не пришёл
    var text = state !== "busy" ? "" : (dlBest > 0 ? Math.round(dlBest) + "%" : "\u2026");
    var pctNode = btn.querySelector(".dl-pct");
    if (pctNode.textContent !== text) pctNode.textContent = text;
    btn.style.setProperty("--dl-pct", state !== "busy" || dlBest <= 0 ? "0%" : dlBest + "%");
    updateDownloadTitle();
  }
  function setDownloadResult(result) {
    var state = DL_RESULT[result];
    if (!state || result === dlShown) return;
    dlShown = result;
    setDownloadState(state, 0, false);
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
      if (st.busy) {
        dlShown = null;
        setDownloadState("busy", p.mode === "indeterminate" ? 0 : (p.value || 0), p.mode === "indeterminate");
      } else {
        setDownloadResult(st.result);
      }
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

  // -- панель настроек -------------------------------------------------------
  // Панель целиком рисуется из схемы (__SETTINGS_SCHEMA__): вкладки, поля,
  // кнопки, блоки и пояснения. Здесь только то, чего схема знать не может:
  // что делает кнопка, как поле применяется и чем наполняется пояснение.
  // Текстовые поля сохраняются по событию change (потеря фокуса/Enter),
  // чтобы не писать в settings.json на каждый символ.
  var panelFields = {};   // путь настройки -> {spec, nodes, input, range}
  var panelButtons = {};  // id кнопки -> элемент
  var noteFillers = {};   // note_source -> нужно перерисовывать
  var customSave = {};    // путь настройки -> поле со своим обработчиком
  // обёртки (блок .settings-box, строка .range-row) с полями внутри: если все
  // поля скрыты, пустая рамка и пустая строка тоже убираются, иначе на вкладке
  // FTP остаётся рамка «Подключение» с пустым содержимым
  var panelWrappers = []; // [{el, keys}]

  function el(tag, cls, attrs) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (Array.isArray(attrs)) {
      attrs.forEach(function(n) { node.appendChild(n); });
    } else if (attrs) {
      Object.keys(attrs).forEach(function(k) {
        if (attrs[k] !== undefined && attrs[k] !== null) node.setAttribute(k, attrs[k]);
      });
    }
    return node;
  }
  function fieldSpec(path) {
    var groups = SETTINGS_SCHEMA.groups;
    for (var i = 0; i < groups.length; i++) {
      var fields = groups[i].fields;
      for (var j = 0; j < fields.length; j++) {
        if (fields[j].path === path) return fields[j];
      }
    }
    return null;
  }
  function fieldOptions(path) {
    var spec = fieldSpec(path);
    return (spec && spec.options) || [];
  }
  // Пересборка списков, опции которых пришли прямо из схемы (ftp.mode и т.п.).
  // Поля со своей логикой (dl.transcode с недоступными кодировщиками) дальше
  // переопределяются своими сборщиками.
  function fillSchemaChoices() {
    Object.keys(panelFields).forEach(function(key) {
      var f = panelFields[key], spec = f.spec;
      if (spec.type !== "choice" || !spec.options) return;
      fillSelectNode(f.input, spec.options, true);
    });
  }
  function caption(key, cls) {
    var node = el("span", cls, {"data-i18n": key});
    node.textContent = t(key);
    return node;
  }
  function labelNode(spec) {
    var node = el("label", null, {for: spec.dom, "data-i18n": spec.label});
    node.textContent = t(spec.label);
    if (spec.title) {
      node.setAttribute("data-i18n-title", spec.title);
      node.title = t(spec.title);
    }
    return node;
  }

  // Одно поле схемы -> узлы и, если поле редактируемое, input (+range-зеркало).
  function renderField(spec) {
    if (spec.type === "actions") {
      var buttons = spec.buttons.map(function(b) {
        var btn = el("button", null, {type: "button", id: b.dom});
        if (b.icon) {
          var ico = el("span", "ta-ico");
          ico.textContent = b.icon;
          btn.appendChild(ico);
        }
        btn.appendChild(caption(b.label));
        panelButtons[b.dom] = btn;
        return btn;
      });
      // в строке кнопки не оборачиваем: строку собирает renderSettingsPanel
      if (spec.row !== undefined && spec.row !== null) return {nodes: buttons};
      return {nodes: [el("div", spec.row_class || (spec.browse_dest ? "row" : "theme-actions"), buttons)]};
    }
    if (spec.type === "note") {
      var note = el(spec.inline ? "span" : "div", "note", {id: spec.dom});
      if (spec.hidden) note.hidden = true;
      // перерисовываем при правке настроек только те пояснения, чьё содержимое
      // зависит от значения поля (остальные наполняют свои команды)
      if (NOTE_FILLERS[spec.note_source]) noteFillers[spec.note_source] = true;
      return {nodes: [note]};
    }
    if (spec.type === "bool" && spec.check) {
      var check = el("div", "check");
      var box = el("input", null, {type: "checkbox", id: spec.dom});
      check.appendChild(box);
      check.appendChild(caption(spec.label));
      return {nodes: [check], input: box};
    }
    var nodes = [labelNode(spec)];
    var input;
    if (spec.type === "choice") {
      input = el("select", null, {id: spec.dom});
      // опции из схемы наполняем сразу: иначе у поля без своей функции
      // (например ftp.mode) список остался бы пустым
      fillSelectNode(input, spec.options, true);
    } else if (spec.type === "int") {
      input = el("input", null, {type: "number", id: spec.dom, min: spec.min, max: spec.max, step: spec.step});
    } else {
      input = el("input", null, {type: "text", id: spec.dom});
      input.setAttribute("spellcheck", "false");
      if (spec.type === "password") input.setAttribute("autocomplete", "off");
      if (spec.placeholder) input.placeholder = spec.placeholder;
    }
    nodes.push(input);
    var range = null;
    if (spec.mirror === "range" && spec.dom_range) {
      range = el("input", null, {type: "range", id: spec.dom_range, min: spec.min, max: spec.max, step: spec.step});
      nodes.splice(1, 0, range);
    }
    return {nodes: nodes, input: input, range: range};
  }

  function renderSettingsPanel() {
    var tabs = document.getElementById("settings-tabs");
    var panels = document.getElementById("settings-panels");
    tabs.innerHTML = "";
    panels.innerHTML = "";
    panelWrappers = [];
    SETTINGS_SCHEMA.groups.forEach(function(group, gi) {
      var tab = el("button", gi ? "tab" : "tab active", {type: "button", id: "tab-" + group.id});
      tab.appendChild(caption(group.label));
      tab.addEventListener("click", function() { switchSettingsTab(group.id); });
      tabs.appendChild(tab);

      var panel = el("div", null, {id: "panel-" + group.id});
      if (gi) panel.hidden = true;
      var out = [];         // узлы панели
      var boxNodes = null;  // узлы текущего блока
      var boxKeys = null;   // пути полей блока
      var rowNodes = null;  // узлы текущей строки
      var rowKeys = null;   // пути полей строки
      var rowIdx = null;
      var rowCls = null;
      var boxName = null;
      function wrap(host, node, keys) {
        host.push(node);
        panelWrappers.push({el: node, keys: keys});
      }
      function flushRow() {
        if (rowNodes) {
          wrap(boxNodes || out, el("div", rowCls, rowNodes), rowKeys);
          rowNodes = rowKeys = null; rowIdx = rowCls = null;
        }
      }
      function flushBox() {
        flushRow();
        if (boxNodes) {
          wrap(out, el("div", "settings-box", boxNodes), boxKeys);
          boxNodes = boxKeys = null;
        }
      }
      group.fields.forEach(function(spec) {
        if (spec.in_panel === false) return;
        if ((spec.box || null) !== boxName) {
          flushBox();
          boxName = spec.box || null;
          if (boxName) { boxNodes = [caption(group.boxes[boxName], "settings-box-title")]; boxKeys = []; }
        }
        var part = renderField(spec);
        var key = spec.path || spec.dom;
        if (boxKeys) boxKeys.push(key);
        if (spec.row !== undefined && spec.row !== null) {
          // поля с одинаковым row встают в одну строку (label + input)
          if (rowNodes && spec.row !== rowIdx) flushRow();
          if (!rowNodes) { rowNodes = []; rowKeys = []; rowIdx = spec.row; rowCls = spec.row_class || "range-row"; }
          rowKeys.push(key);
          part.nodes.forEach(function(n) { rowNodes.push(n); });
        } else {
          flushRow();
          var host = boxNodes || out;
          part.nodes.forEach(function(n) { host.push(n); });
        }
        panelFields[key] = {spec: spec, nodes: part.nodes, input: part.input, range: part.range};
      });
      flushBox();
      out.forEach(function(n) { panel.appendChild(n); });
      panels.appendChild(panel);
    });
  }

  function switchSettingsTab(name) {
    SETTINGS_SCHEMA.groups.forEach(function(group) {
      document.getElementById("panel-" + group.id).hidden = group.id !== name;
      document.getElementById("tab-" + group.id).classList.toggle("active", group.id === name);
    });
  }

  // Кнопки панели: в схеме у кнопки есть dom и подпись, здесь - только действие.
  var ACTIONS = {
    "reload-themes": function() { reloadThemes(); },
    "open-themes": function() { openThemesFolder(); },
    "reload-fonts": function() { reloadFonts(); },
    "download-fonts": function() { downloadFonts(); },
    "open-fonts": function() { openFontsFolder(); },
    "browse": async function() {
      var picked = await pywebview.api.browse_folder();
      if (picked) panelFields["ui.dest"].input.value = picked;
    },
    "ftp-test": async function() {
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
    }
  };
  var NOTE_FILLERS = {ftpDirNote: updateFtpDirNote};
  function refreshNotes() {
    Object.keys(noteFillers).forEach(function(src) { NOTE_FILLERS[src](); });
  }

  function fillSettings(settings, initData) {
    Object.keys(panelFields).forEach(function(key) {
      var f = panelFields[key], spec = f.spec, node = f.input;
      if (!node) return;
      var value = spec.value_source ? initData[spec.value_source] : settings[spec.setting];
      if (spec.type === "bool") node.checked = value !== false && !!value;
      else if (spec.type === "text" || spec.type === "password") node.value = value || node.placeholder || "";
      else node.value = value || spec.default;
      if (f.range) f.range.value = node.value;
    });
  }

  function bindSettings() {
    Object.keys(panelFields).forEach(function(key) {
      var f = panelFields[key], spec = f.spec, node = f.input;
      if (!node || customSave[key]) return;
      node.addEventListener("change", function() {
        var value = spec.type === "bool" ? node.checked : node.value.trim();
        if (f.range) f.range.value = value;
        if (spec.setting) pywebview.api.save_setting(spec.setting, value);
        applyVisibility();
        refreshNotes();
      });
      if (f.range) {
        f.range.addEventListener("input", function() {
          node.value = this.value;
          if (spec.setting) pywebview.api.save_setting(spec.setting, this.value);
        });
      }
    });
    Object.keys(ACTIONS).forEach(function(dom) {
      if (panelButtons[dom]) panelButtons[dom].addEventListener("click", function() { ACTIONS[dom](); });
    });
  }

  // Условия видимости описаны в схеме (visible_if) - здесь только их применение.
  function applyVisibility() {
    Object.keys(panelFields).forEach(function(key) {
      var cond = panelFields[key].spec.visible_if;
      if (!cond) return;
      var src = panelFields[cond.key];
      var show = !!(src && src.input && src.input.checked) === !!cond.equals;
      panelFields[key].nodes.forEach(function(node) { node.hidden = !show; });
    });
    // Рамка блока и строка прячутся, когда скрыты все поля внутри: иначе на
    // вкладке FTP остаётся пустая рамка «Подключение», а в строках - пустые
    // отступы от margin.
    panelWrappers.forEach(function(box) {
      var any = box.keys.some(function(key) {
        var f = panelFields[key];
        return f && f.nodes.some(function(node) { return !node.hidden; });
      });
      box.el.hidden = !any;
    });
  }

  // Поля с собственным поведением: тема, язык, шрифты.
  function onChange(path, fn) {
    var f = panelFields[path];
    if (!f || !f.input) return;
    customSave[path] = true;
    f.input.addEventListener("change", function() { fn(f.input, f.spec); });
  }

  function updateFtpDirNote() {
    var dir = panelFields["ftp.dir"].input.value.trim();
    var note = document.getElementById("ftp-dir-note");
    note.textContent = dir ? t("sheet.ftp.dir.ok") : t("sheet.ftp.dir.empty");
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
    setDownloadState("idle", 0, false);
    renderSettingsPanel();
    buildThemeOptions();
    buildSubsOptions();
    buildQualOptions();
    buildTranscodeOptions();
    applyI18n();
    fillSettings(initData.settings, initData);
    applyTheme(panelFields["ui.theme"].input.value);
    document.getElementById("group").checked = initData.settings.group_playlist !== false;
    document.getElementById("status").textContent = t("status.ready");
    if (!initData.ffmpeg) {
      document.getElementById("warn").style.display = "block";
      ffmpegOverlay.classList.remove("ffmpeg-hidden");
      ffmpegStatus.classList.add("ffmpeg-hidden");
    }
    // тема: часть тем со своим entry собирается в Python (полный rebuild
    // страницы), остальные применяются на лету, @font-face догружаем отдельно
    onChange("ui.theme", function(node, spec) {
      updateThemeMeta();
      var th = THEMES[node.value] || {};
      if (th.entry) {
        pywebview.api.set_theme(node.value);
        return;
      }
      applyTheme(node.value);
      pywebview.api.save_setting(spec.setting, node.value);
      if (th.font || th.font_mono) {
        loadFontFaces([th.font, th.font_mono, FONT_PICK.sans, FONT_PICK.mono]);
      }
    });
    onChange("ui.language", function(node, spec) {
      curLang = node.value;
      applyI18n();
      buildFontOptions();   // подпись «системный» в списках шрифтов тоже переводится
      applyTheme(panelFields["ui.theme"].input.value);
      updateThemeMeta();
      pywebview.api.save_setting(spec.setting, node.value);
    });
    onChange("ui.font_sans", function(node) { setFont("font-sans", node.value); });
    onChange("ui.font_mono", function(node) { setFont("font-mono", node.value); });
    bindSettings();
    applyVisibility();
    refreshNotes();
    document.getElementById("group").addEventListener("change", function() {
      pywebview.api.save_setting("group_playlist", this.checked);
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
      // yt-dlp ещё дорабатывает файл после запроса остановки, поэтому кнопку
      // блокируем до реального завершения: итог придёт в poll()
      this.disabled = true;
      pywebview.api.stop_download();
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
      document.getElementById("sheet-resize").hidden = false;
      syncSheetEdge();
    }
    function closeSettings() {
      document.getElementById("settings-overlay").hidden = true;
      document.getElementById("settings-sheet").hidden = true;
      document.getElementById("sheet-resize").hidden = true;
      stopSheetResize();
    }
    document.getElementById("settings-btn").addEventListener("click", openSettings);
    document.getElementById("settings-close").addEventListener("click", closeSettings);
    document.getElementById("settings-overlay").addEventListener("click", closeSettings);
    initSheetResize();
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