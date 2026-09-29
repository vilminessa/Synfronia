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
    document.querySelectorAll("[data-i18n-aria]").forEach(function(el) {
      el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria")));
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
  // Один элемент на страницу (см. initTooltips). В режиме hover подсказка
  // «крутится» вокруг элемента: сторона выбирается по направлению от центра
  // элемента к курсору, вдоль грани - за координатой курсора, - поэтому нить
  // упирается в грань, а не в угол, и подсказка не накрывает элемент. Между
  // краем подсказки и краем элемента рисуется «нить» (SVG) с наконечником-
  // стрелкой у элемента. В режиме focus (клавиатура) курсора нет - сторона
  // выбирается по простору: сверху, иначе снизу, затем по бокам. Скрывается,
  // как только элемент пропал из-под курсора, узел отсоединён или курсор
  // ушёл из окна, - потому что pointerout после перерисовки карточки
  // настроек не приходит.
  var TIP = {node: null, text: null, thread: null, line: null, head: null,
             target: null, pending: null, mode: "hover", side: null,
             cx: 0, cy: 0, x: 0, y: 0, tx: 0, ty: 0,
             raf: 0, timer: 0, shown: false, lastT: 0};
  var SVG_NS = "http://www.w3.org/2000/svg";
  var TIP_GAP = 10;      // минимальный зазор до элемента
  var TIP_MARGIN = 8;    // минимальный отступ от края окна
  var TIP_DELAY = 220;   // задержка появления, чтобы не мигало при проносе
  var TIP_TAU = 70;      // постоянная времени инерции (мс): меньше - короче хвост
  var TIP_HEAD_LEN = 7;  // длина наконечника-стрелки
  var TIP_HEAD_W = 3.5;  // половина ширины наконечника
  // «Магнитные» силы подсказки - две настройки 0..100 (карточка «Подсказки»).
  // Дефолты повторяют прежнее поведение: pull 50 - прежняя инерция,
  // repel 100 - выталкивание из рамки элемента сразу и целиком.
  var TIP_FORCE = {pull: 50, repel: 100};
  function setTipForces(pull, repel) {
    var p = Number(pull), r = Number(repel);
    if (isFinite(p)) TIP_FORCE.pull = Math.max(0, Math.min(100, p));
    if (isFinite(r)) TIP_FORCE.repel = Math.max(0, Math.min(100, r));
    // подсказка может стоять «на месте» (кадры остановлены после схождения) -
    // без толчка новая сила применится только при следующем движении мыши
    if (TIP.target && TIP.raf === 0 && !reducedMotion()) {
      TIP.raf = requestAnimationFrame(tipFrame);
    }
  }

  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function tipAnchor(el) {
    if (!el || !el.closest) return null;
    return el.closest("[data-tip]");
  }

  function tipParts() {
    if (TIP.node) return;
    var node = document.createElement("div");
    node.id = "tip";
    node.className = "tip";
    node.hidden = true;
    node.setAttribute("role", "tooltip");
    var text = document.createElement("span");
    text.className = "tip-text";
    node.appendChild(text);
    document.body.appendChild(node);
    TIP.node = node;
    TIP.text = text;
  }

  function threadParts() {
    if (TIP.thread) return;
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.id = "tip-thread";
    var line = document.createElementNS(SVG_NS, "path");
    line.setAttribute("class", "tip-thread-line");
    var head = document.createElementNS(SVG_NS, "path");
    head.setAttribute("class", "tip-thread-head");
    svg.appendChild(line);
    svg.appendChild(head);
    document.body.appendChild(svg);
    TIP.thread = svg;
    TIP.line = line;
    TIP.head = head;
  }

  // Куда поставить подсказку. hover - орбита: сторона берётся по направлению
  // от центра элемента к курсору (нормировано на полуполе, чтобы сторона не
  // дрожала на диагонали; прежняя сторона держится, пока новая не выигрывает
  // с заметным перевесом), вдоль грани подсказка идёт за координатой курсора.
  // Так нить упирается в грань, а не в угол, а при обводе курсором подсказка
  // плавно переходит вокруг элемента на другие грани. Снаружи, с зазором
  // силы repel; при 0 зазор минимален и подсказка может лечь на элемент
  // вполовину (onto). focus: сверху, если есть место, иначе снизу, затем
  // по бокам с большим простором.
  function tipTarget() {
    var el = TIP.target;
    var w = TIP.node.offsetWidth;
    var h = TIP.node.offsetHeight;
    var r = el.getBoundingClientRect();
    var gap = 2 + 0.16 * TIP_FORCE.repel;
    var onto = (1 - TIP_FORCE.repel / 100) * Math.min(w, h) / 2;
    var dx, dy;
    if (TIP.mode === "focus") {
      var sp = {top: r.top - TIP_MARGIN,
                bottom: window.innerHeight - r.bottom - TIP_MARGIN,
                left: r.left - TIP_MARGIN,
                right: window.innerWidth - r.right - TIP_MARGIN};
      var need = {top: h, bottom: h, left: w, right: w};
      var fside = null, bestS = null, bestV = -Infinity;
      ["top", "bottom", "right", "left"].forEach(function(s) {
        var free = sp[s] - need[s];
        if (fside === null && free >= TIP_GAP) fside = s;
        if (free > bestV) { bestV = free; bestS = s; }
      });
      fside = fside || bestS;
      if (fside === "top" || fside === "bottom") {
        dx = r.left + r.width / 2 - w / 2;
        dy = fside === "top" ? r.top - TIP_GAP - h : r.bottom + TIP_GAP;
      } else {
        dy = r.top + r.height / 2 - h / 2;
        dx = fside === "right" ? r.right + TIP_GAP : r.left - TIP_GAP - w;
      }
    } else {
      var hw = Math.max(r.width / 2, 1), hh = Math.max(r.height / 2, 1);
      var vx = TIP.cx - (r.left + r.width / 2);
      var vy = TIP.cy - (r.top + r.height / 2);
      var sc = {bottom: vy / hh, right: vx / hw, top: -vy / hh, left: -vx / hw};
      // помещается ли подсказка снаружи этой грани (с зазором и отступом окна)
      function fits(s) {
        if (s === "top") return r.top - TIP_MARGIN - gap >= h;
        if (s === "bottom") return window.innerHeight - r.bottom - TIP_MARGIN - gap >= h;
        if (s === "left") return r.left - TIP_MARGIN - gap >= w;
        return window.innerWidth - r.right - TIP_MARGIN - gap >= w;
      }
      var order = Object.keys(sc).sort(function(a, b) { return sc[b] - sc[a]; });
      var side = null;
      // прежняя сторона держится, пока новая не выигрывает с заметным перевесом
      if (TIP.side && sc[order[0]] <= sc[TIP.side] + 0.25 && fits(TIP.side)) side = TIP.side;
      if (!side) for (var i = 0; i < order.length; i++) if (fits(order[i])) { side = order[i]; break; }
      if (!side) side = TIP.side || order[0];   // негде поместиться - clamp спасёт
      TIP.side = side;
      if (side === "top" || side === "bottom") {
        dx = (w < r.width
              ? Math.max(r.left + w / 2, Math.min(TIP.cx, r.right - w / 2))
              : r.left + r.width / 2) - w / 2;
        dy = side === "bottom" ? r.bottom + gap - onto : r.top - gap + onto - h;
      } else {
        dy = (h < r.height
              ? Math.max(r.top + h / 2, Math.min(TIP.cy, r.bottom - h / 2))
              : r.top + r.height / 2) - h / 2;
        dx = side === "right" ? r.right + gap - onto : r.left - gap + onto - w;
      }
    }
    dx = Math.max(TIP_MARGIN, Math.min(dx, window.innerWidth - w - TIP_MARGIN));
    dy = Math.max(TIP_MARGIN, Math.min(dy, window.innerHeight - h - TIP_MARGIN));
    return {x: dx, y: dy};
  }

  function showTip(el, mode) {
    if (el.id === "tip") return;
    TIP.mode = mode === "focus" ? "focus" : "hover";
    var text = (el.getAttribute("data-tip") || "").trim();
    if (!text) return;
    tipParts();
    threadParts();
    TIP.target = el;
    TIP.pending = null;
    TIP.shown = false;
    TIP.side = null;
    TIP.text.textContent = text;
    el.setAttribute("aria-describedby", "tip");
    TIP.node.hidden = false;
    TIP.node.classList.add("tip-on");
    TIP.thread.classList.add("tip-on");
    var t0 = tipTarget();
    TIP.tx = t0.x;
    TIP.ty = t0.y;
    TIP.x = TIP.tx;
    TIP.y = TIP.ty;
    TIP.lastT = 0;
    if (reducedMotion()) {
      paintTip();
    } else if (!TIP.raf) {
      TIP.raf = requestAnimationFrame(tipFrame);
    }
  }

  function hideTip() {
    clearTimeout(TIP.timer);
    TIP.pending = null;
    if (TIP.raf) { cancelAnimationFrame(TIP.raf); TIP.raf = 0; }
    if (TIP.target) {
      TIP.target.removeAttribute("aria-describedby");
      TIP.target = null;
    }
    if (!TIP.node || TIP.node.hidden) return;
    TIP.node.classList.remove("tip-on");
    TIP.node.hidden = true;
    if (TIP.thread) {
      TIP.thread.classList.remove("tip-on");
      TIP.line.setAttribute("d", "");
      TIP.head.setAttribute("d", "");
    }
    TIP.shown = false;
  }

  function tipFrame(now) {
    TIP.raf = 0;
    if (!TIP.target || !TIP.target.isConnected) { hideTip(); return; }
    if (TIP.mode === "hover" && !TIP.target.matches(":hover")) { hideTip(); return; }
    var t = tipTarget();
    TIP.tx = t.x;
    TIP.ty = t.y;
    if (!TIP.lastT) TIP.lastT = now;
    var dt = Math.min(50, Math.max(1, now - TIP.lastT));
    TIP.lastT = now;
    // притяжение к курсору: множитель к инерции (pull 50 = прежний темп)
    var k = (1 - Math.exp(-dt / TIP_TAU)) * (0.5 + TIP_FORCE.pull / 100);
    TIP.x += (TIP.tx - TIP.x) * k;
    TIP.y += (TIP.ty - TIP.y) * k;
    var settled = Math.abs(TIP.tx - TIP.x) < 0.5 && Math.abs(TIP.ty - TIP.y) < 0.5;
    if (settled) { TIP.x = TIP.tx; TIP.y = TIP.ty; }
    paintTip();
    if (!settled) TIP.raf = requestAnimationFrame(tipFrame);
    else TIP.shown = true;
  }

  function paintTip() {
    TIP.node.style.left = TIP.x.toFixed(1) + "px";
    TIP.node.style.top = TIP.y.toFixed(1) + "px";
    paintThread();
  }

  // Нить: линия от края подсказки до ближайшей точки бордюра элемента плюс
  // наконечник-стрелка, носик которой упирается в сам элемент.
  function paintThread() {
    var el = TIP.target;
    if (!el) return;
    var r = el.getBoundingClientRect();
    if (!r.width && !r.height) return;
    var w = TIP.node.offsetWidth;
    var h = TIP.node.offsetHeight;
    var cx = TIP.x + w / 2;
    var cy = TIP.y + h / 2;
    // ближайшая к центру подсказки точка рамки элемента
    var px = Math.max(r.left, Math.min(cx, r.right));
    var py = Math.max(r.top, Math.min(cy, r.bottom));
    if (px > r.left && px < r.right && py > r.top && py < r.bottom) {
      var dl = cx - r.left, dr = r.right - cx, dt = cy - r.top, db = r.bottom - cy;
      var m = Math.min(dl, dr, dt, db);
      if (m === dl) px = r.left; else if (m === dr) px = r.right;
      else if (m === dt) py = r.top; else py = r.bottom;
    }
    var dx = px - cx, dy = py - cy;
    var len = Math.hypot(dx, dy);
    if (len < 1) {
      TIP.line.setAttribute("d", "");
      TIP.head.setAttribute("d", "");
      return;
    }
    // выход луча из рамки подсказки (старт нити)
    var sx, sy;
    if (dx === 0) { sx = cx; sy = cy + (dy < 0 ? -h / 2 : h / 2); }
    else if (dy === 0) { sx = cx + (dx < 0 ? -w / 2 : w / 2); sy = cy; }
    else {
      var tx0 = (w / 2) / Math.abs(dx), ty0 = (h / 2) / Math.abs(dy);
      var t0 = Math.min(tx0, ty0);
      sx = cx + dx * t0;
      sy = cy + dy * t0;
    }
    TIP.line.setAttribute("d", "M " + sx.toFixed(1) + " " + sy.toFixed(1)
      + " L " + px.toFixed(1) + " " + py.toFixed(1));
    var nx = -dy / len, ny = dx / len;
    var bx = px - dx / len * TIP_HEAD_LEN;
    var by = py - dy / len * TIP_HEAD_LEN;
    TIP.head.setAttribute("d", "M " + (bx + nx * TIP_HEAD_W).toFixed(1) + " " + (by + ny * TIP_HEAD_W).toFixed(1)
      + " L " + px.toFixed(1) + " " + py.toFixed(1)
      + " L " + (bx - nx * TIP_HEAD_W).toFixed(1) + " " + (by - ny * TIP_HEAD_W).toFixed(1) + " Z");
  }

  function snapTip() {
    var t = tipTarget();
    TIP.tx = t.x;
    TIP.ty = t.y;
    TIP.x = TIP.tx;
    TIP.y = TIP.ty;
    paintTip();
  }

  function initTooltips() {
    tipParts();
    document.addEventListener("pointerover", function(ev) {
      var el = tipAnchor(ev.target);
      if (!el) return;
      if (el === TIP.target) return;
      if (TIP.target) hideTip();
      if (TIP.pending === el) return;
      TIP.pending = el;
      clearTimeout(TIP.timer);
      TIP.timer = setTimeout(function() {
        if (TIP.pending === el && !TIP.target) showTip(el, "hover");
      }, TIP_DELAY);
    }, true);
    document.addEventListener("pointerout", function(ev) {
      if (ev.relatedTarget && (tipAnchor(ev.relatedTarget) === TIP.target ||
                               tipAnchor(ev.relatedTarget) === TIP.pending)) return;
      TIP.pending = null;
      clearTimeout(TIP.timer);
      hideTip();
    }, true);
    // Живость: элемент перерисовали или убрали (карточка настроек, смена
    // темы) - pointerout не придёт, а подсказка обязана исчезнуть. Заодно
    // помним курсор, за которым подсказка тянется с инерцией.
    document.addEventListener("pointermove", function(ev) {
      TIP.cx = ev.clientX;
      TIP.cy = ev.clientY;
      if (!TIP.target || TIP.mode !== "hover") return;
      if (!TIP.target.isConnected || !TIP.target.matches(":hover")) { hideTip(); return; }
      if (reducedMotion()) {
        if (!TIP.raf) snapTip();
      } else if (!TIP.raf) {
        TIP.raf = requestAnimationFrame(tipFrame);
      }
    }, true);
    document.documentElement.addEventListener("pointerleave", function() {
      hideTip();
    });
    document.addEventListener("focusin", function(ev) {
      var el = tipAnchor(ev.target);
      if (el) { if (TIP.target) hideTip(); showTip(el, "focus"); }
    });
    document.addEventListener("focusout", function(ev) {
      if (ev.relatedTarget && (tipAnchor(ev.relatedTarget) === TIP.target ||
                               tipAnchor(ev.relatedTarget) === TIP.pending)) return;
      hideTip();
    });
    document.addEventListener("keydown", function(ev) {
      if (ev.key === "Escape") hideTip();
    });
    var relayout = function() {
      if (!TIP.target || !TIP.target.isConnected) return;
      if (reducedMotion()) snapTip();
      else if (!TIP.raf) TIP.raf = requestAnimationFrame(tipFrame);
    };
    window.addEventListener("resize", relayout);
    document.addEventListener("scroll", function() {
      if (TIP.target && !TIP.target.isConnected) { hideTip(); return; }
      relayout();
    }, true);
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
