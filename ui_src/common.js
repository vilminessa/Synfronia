  /* Общая часть интерфейса (ui_src/common.js): переводы, палитра темы,
     шрифты, иконки кнопок и подсказки. Подключается один раз - главной
     страницей, - поэтому язык, тему и шрифты достаточно поменять в одном
     месте: и поля настроек, и остальной интерфейс видят одно и то же. */
  var THEMES = __THEMES__;
  var I18N = __I18N__;
  var LANGS = Object.keys(I18N).filter(function(k) { return I18N[k] && I18N[k].thisLang; });
  var curLang = "en";
  // Активная тема. В настройках она есть в селекте #theme, в остальном
  // интерфейсе селекта нет - тема приходит из poll(), поэтому держим её
  // здесь: и applyTheme, и fontFacesForTheme должны знать её одинаково.
  var curTheme = "";
  var FONTS = { families: [], count: 0, folder: "" };
  // Выбор шрифтов из настроек (без кавычек) — нужен, чтобы при переключении
  // темы вернуть шрифт, если у темы нет своих font/font_mono, и чтобы запросить
  // @font-face именно для этих семейств.
  var FONT_PICK = { sans: "", mono: "" };

  function t(key) {
    var d = I18N[curLang] || I18N.ru;
    if (d && d[key] !== undefined) return d[key];
    if (I18N.ru[key] !== undefined) return I18N.ru[key];
    return key;
  }

  // Переводы разметки, помеченной data-i18n / data-i18n-tip. Списки и
  // подписи полей настроек дополняют её своими сборщиками.
  // Подсказки живут в data-tip, а не в title: нативную всплывашку рисует
  // браузер, её нельзя оформить и она появляется второй раз поверх нашей.
  function translateStatic() {
    document.querySelectorAll("[data-i18n]").forEach(function(el) {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-tip]").forEach(function(el) {
      setTip(el, t(el.getAttribute("data-i18n-tip")));
    });
  }
  // Подсказка элемента: текст + доступное имя, если на кнопке нет подписи.
  function setTip(el, text) {
    el.setAttribute("data-tip", text || "");
    if (!el.textContent.trim()) el.setAttribute("aria-label", text || "");
  }

  // ---- иконки кнопок -------------------------------------------------------
  // Тонкие линии currentColor, 24x24 - одинаково смотрятся в любой теме.
  // Кнопка с иконкой не показывает текст: смысл живёт в подсказке (data-tip).
  var ICON_ATTRS = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
                 + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
  var ICONS = {
    reload: '<path d="M20.5 12a8.5 8.5 0 1 1-2.5-6"/><path d="M20.5 4v5h-5"/>',
    download: '<path d="M12 3v11"/><path d="m8 11 4 4 4-4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    folder: '<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.5h7A1.5 1.5 0 0 1 19 10v.5"/><path d="M3.4 10h17.2l-2 8.2a1.5 1.5 0 0 1-1.45 1.1H6.2a1.5 1.5 0 0 1-1.45-1.1Z"/>',
    check: '<path d="m4.5 12.5 5 5 10-11"/>',
  };
  function iconSvg(name) {
    var body = ICONS[name];
    return body ? "<svg " + ICON_ATTRS + ">" + body + "</svg>" : "";
  }
  function iconNode(name) {
    var span = document.createElement("span");
    span.className = "ico";
    span.innerHTML = iconSvg(name);
    return span;
  }

  // ---- подсказки -----------------------------------------------------------
  // Один элемент на страницу. Появляется с задержкой, догоняет курсор
  // (инерция), стрелка идёт от края подсказки к краю того элемента, к
  // которому подсказка относится.
  var TIP = {node: null, text: null, arrow: null, target: null, shown: false,
             x: 0, y: 0, tx: 0, ty: 0, raf: 0, timer: 0};
  var TIP_GAP = 10;      // отступ подсказки от элемента
  var TIP_MARGIN = 8;    // минимальный отступ от края окна
  var TIP_DELAY = 220;   // задержка появления, чтобы не мигало при проносе
  var TIP_K = 0.18;      // коэффициент инерции: меньше - длиннее «хвост»

  function tipParts() {
    if (TIP.node) return;
    var node = document.createElement("div");
    node.id = "tip";
    node.className = "tip";
    node.hidden = true;
    node.setAttribute("role", "tooltip");
    var arrow = document.createElement("i");
    arrow.className = "tip-arrow";
    var text = document.createElement("span");
    text.className = "tip-text";
    node.appendChild(arrow);
    node.appendChild(text);
    document.body.appendChild(node);
    TIP.node = node;
    TIP.arrow = arrow;
    TIP.text = text;
  }

  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function tipAnchor(el) {
    if (!el) return null;
    return el.closest("[data-tip]");
  }

  function showTip(el) {
    var text = (el.getAttribute("data-tip") || "").trim();
    if (!text) return;
    if (el.id === "tip") return;
    tipParts();
    TIP.target = el;
    TIP.text.textContent = text;
    el.setAttribute("aria-describedby", "tip");
    TIP.node.hidden = false;
    TIP.node.classList.add("tip-on");
    placeTip(true);
    if (reducedMotion()) {
      TIP.x = TIP.tx;
      TIP.y = TIP.ty;
      tipFrame();
    } else {
      TIP.raf = requestAnimationFrame(tipFrame);
    }
  }

  function hideTip() {
    clearTimeout(TIP.timer);
    if (TIP.raf) { cancelAnimationFrame(TIP.raf); TIP.raf = 0; }
    if (TIP.target) {
      TIP.target.removeAttribute("aria-describedby");
      TIP.target = null;
    }
    if (!TIP.node || TIP.node.hidden) return;
    TIP.node.classList.remove("tip-on");
    TIP.node.hidden = true;
    TIP.shown = false;
  }

  // Куда поставить подсказку: над элементом, если есть место, иначе под ним.
  // Горизонталь - по центру элемента с прижимкой к краям окна.
  function placeTip(first) {
    var el = TIP.target;
    if (!el || !el.isConnected) return;
    var r = el.getBoundingClientRect();
    if (!r.width && !r.height) return;
    var w = TIP.node.offsetWidth;
    var h = TIP.node.offsetHeight;
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var below = r.top - h - TIP_GAP < TIP_MARGIN;
    var y = below ? r.bottom + TIP_GAP : r.top - h - TIP_GAP;
    if (y + h > vh - TIP_MARGIN) y = Math.max(TIP_MARGIN, vh - h - TIP_MARGIN);
    if (y < TIP_MARGIN) y = TIP_MARGIN;
    var x = r.left + r.width / 2 - w / 2;
    x = Math.max(TIP_MARGIN, Math.min(x, vw - w - TIP_MARGIN));
    TIP.tx = x;
    TIP.ty = y;
    // сторона, на которой стоит подсказка, задаёт вид стрелки
    TIP.node.classList.toggle("tip-below", below);
    // стрелка у края подсказки, направленного к элементу, но не ближе угла;
    // сторону (низ/верх) задаёт CSS, сюда - только положение по горизонтали
    var cx = r.left + r.width / 2;
    var ax = Math.max(14, Math.min(cx - x, w - 14));
    TIP.arrow.style.left = ax + "px";
    if (first) {
      // стартовая точка инерции: подсказка «догоняет» нужное место
      TIP.x = x;
      TIP.y = below ? y - 10 : y + 10;
    }
  }

  function tipFrame() {
    TIP.raf = 0;
    if (!TIP.target) return;
    TIP.x += (TIP.tx - TIP.x) * TIP_K;
    TIP.y += (TIP.ty - TIP.y) * TIP_K;
    TIP.node.style.left = TIP.x.toFixed(1) + "px";
    TIP.node.style.top = TIP.y.toFixed(1) + "px";
    if (Math.abs(TIP.tx - TIP.x) > 0.4 || Math.abs(TIP.ty - TIP.y) > 0.4) {
      TIP.raf = requestAnimationFrame(tipFrame);
    } else {
      TIP.x = TIP.tx;
      TIP.y = TIP.ty;
      TIP.node.style.left = TIP.x + "px";
      TIP.node.style.top = TIP.y + "px";
      TIP.shown = true;
    }
  }

  function initTooltips() {
    tipParts();
    function over(ev) {
      var el = tipAnchor(ev.target);
      if (el === TIP.target) return;
      if (TIP.target) hideTip();
      if (!el) return;
      clearTimeout(TIP.timer);
      TIP.timer = setTimeout(function() { if (!TIP.target) showTip(el); }, TIP_DELAY);
    }
    function out(ev) {
      if (ev.relatedTarget && tipAnchor(ev.relatedTarget) === TIP.target) return;
      hideTip();
    }
    document.addEventListener("pointerover", over, true);
    document.addEventListener("pointerout", out, true);
    document.addEventListener("focusin", function(ev) {
      var el = tipAnchor(ev.target);
      if (el) { if (TIP.target) hideTip(); showTip(el); }
    });
    document.addEventListener("focusout", hideTip);
    document.addEventListener("keydown", function(ev) {
      if (ev.key === "Escape") hideTip();
    });
    window.addEventListener("resize", function() { if (TIP.target) placeTip(false); });
    document.addEventListener("scroll", function() { if (TIP.target) placeTip(false); }, true);
  }

  function applyTheme(key) {
    if (THEMES[key]) curTheme = key;
    var c = THEMES[curTheme] || THEMES.scarred_mind || {};
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

  // @font-face для действующей темы и выбранных шрифтов.
  function fontFacesForTheme() {
    var th = THEMES[themeKey()] || {};
    return [th.font, th.font_mono, FONT_PICK.sans, FONT_PICK.mono];
  }
  function themeKey() {
    var sel = document.getElementById("theme");
    return (sel && sel.value) || curTheme || "";
  }
