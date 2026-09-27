  /* Главное окно (ui_src/app.js). Настройки живут в отдельном окне
     (ui_src/settings.js), здесь только загрузка, прогресс и журнал.
     Общие переводы, палитра темы и шрифты - в ui_src/common.js. */
  var since = 0;
  var LOG_LINES = 2000; // сколько строк лога держим в textarea
  var LOG_CHARS = 120000; // порог (~2000 строк) для обрезки без split на каждом poll
  var pollTimer = 0;
  var busy = false;
  var activeTab = "video";
  var clicks = 0;
  var uiRev = -1;    // счётчик смен языка/темы/шрифтов в окне настроек
  var blocked = false;  // открыто ли окно настроек (главное окно приглушено)
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
    ffmpegPercent.textContent = "…";
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

  function applyI18n() {
    translateStatic();
    renderClicker();
    updateDownloadTitle();
    if (!busy) document.getElementById("status").textContent = t("status.ready");
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
    ok: '<svg viewBox="0 0 24 24"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg>',
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
    var text = state !== "busy" ? "" : (dlBest > 0 ? Math.round(dlBest) + "%" : "…");
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
    ["tab-video", "tab-playlist", "url-video", "url-playlist", "settings-btn", "group"]
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

  /* ---- окно настроек ------------------------------------------------------
     Настройки живут в отдельном окне, а пока оно открыто, главное окно не должно
     принимать клики - поэтому Python вызывает synfSetBlocked(true/false).
     Настоящей модальности у WebView2 нет: alt-tab и горячие клавиши ОС
     по-прежнему переключают окна, поэтому оверлей глушим и активный элемент
     снимаем с фокуса. */
  function setBlocked(value) {
    blocked = !!value;
    var veil = document.getElementById("settings-block");
    if (veil) veil.hidden = !blocked;
    // Модальность без второго окна: оверлей ловит клики, а inert - клавиатуру
    // (иначе Tab и Enter уходят в поля под оверлеем). На старых WebView2, где
    // inert нет, гасим те же элементы через disabled.
    var kids = [].slice.call(document.body.children).filter(function(n) { return n !== veil; });
    if ("inert" in HTMLElement.prototype) {
      kids.forEach(function(node) { node.inert = blocked; });
    } else {
      kids.forEach(function(node) {
        [].slice.call(node.querySelectorAll("input, select, textarea, button, a[href]"))
          .forEach(function(el) { el.disabled = blocked; });
      });
    }
    if (blocked && document.activeElement && document.activeElement.blur) {
      document.activeElement.blur();
    }
  }
  function openSettings() {
    pywebview.api.open_settings().then(function() { setBlocked(true); });
  }
  // Python сообщает, что окно настроек закрыто (в том числе крестиком ОС)
  function settingsClosed() {
    setBlocked(false);
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
      if (st.settings_open !== undefined && st.settings_open !== blocked) {
        if (st.settings_open) setBlocked(true); else settingsClosed();
      }
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
      // Язык, тема или шрифты сменились в окне настроек: главное окно догоняет
      // их по тому же счётчику ui_rev, без перезагрузки страницы.
      if (typeof st.ui_rev === "number" && st.ui_rev !== uiRev) {
        uiRev = st.ui_rev;
        if (st.lang && st.lang !== curLang) {
          curLang = st.lang;
          applyI18n();
        }
        if (st.theme) applyTheme(st.theme);
        loadFontFaces(fontFacesForTheme());
      }
    } catch (e) {}
    scheduleTick(200);
  }

  function init() {
    if (window.__initDone) return;
    window.__initDone = true;
    pywebview.api.get_initial().then(function(initData) {
      curLang = initData.settings.language || "en";
      if (LANGS.indexOf(curLang) === -1) curLang = "en";
      FONT_PICK.sans = initData.settings.font_sans || "";
      FONT_PICK.mono = initData.settings.font_mono || "";
      applyTheme(initData.settings.theme || "");
      setDownloadState("idle", 0, false);
      applyI18n();
      document.getElementById("group").checked = initData.settings.group_playlist !== false;
      document.getElementById("status").textContent = t("status.ready");
      if (!initData.ffmpeg) {
        document.getElementById("warn").style.display = "block";
        ffmpegOverlay.classList.remove("ffmpeg-hidden");
        ffmpegStatus.classList.add("ffmpeg-hidden");
      }
      document.getElementById("group").addEventListener("change", function() {
        pywebview.api.save_setting("group_playlist", this.checked);
      });
      // В конфиге загрузки только то, что выбирается в этом окне: папка,
      // субтитры, качество, кодек и сеть живут в настройках, и Python берёт
      // их сам - значения в обоих окнах не могут разойтись.
      document.getElementById("download").addEventListener("click", async function() {
        var url = document.getElementById(activeTab === "video" ? "url-video" : "url-playlist").value.trim();
        if (!url) {
          document.getElementById("status").textContent = activeTab === "video"
            ? t("status.enter.video") : t("status.enter.playlist");
          return;
        }
        var cfg = {
          url: url,
          playlist: activeTab === "playlist",
          group: document.getElementById("group").checked,
        };
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
      document.getElementById("settings-btn").addEventListener("click", openSettings);
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
