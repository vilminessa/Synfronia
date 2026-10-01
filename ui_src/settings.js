  /* Карточка настроек внутри главного окна (ui_src/settings.js).
     Всё содержимое рисуется из схемы (__SETTINGS_SCHEMA__, settings_schema.py):
     список разделов слева, карточки полей справа. Здесь только то, чего схема
     знать не может - что делает кнопка, как поле применяется и чем наполняется
     пояснение. Текстовые поля сохраняются по событию change (потеря фокуса/
     Enter), чтобы не писать в settings.json на каждый символ.
     Отдельного окна и своего опроса Python больше нет: значения приходят из
     того же poll(), что и у главного окна (app.js -> synfSettingsState), так
     что настройки и интерфейс видят одно и то же состояние. */
  var SETTINGS_SCHEMA = __SETTINGS_SCHEMA__;
  var transAvailability = { ffmpeg: true, avail: [] };
  var uiRev = -1;          // счётчик смен языка/темы/шрифтов со стороны Python
  var fontsRev = -1;       // счётчик пересканирования шрифтов
  var langPainted = "";    // язык, под который сейчас нарисованы подписи
  var extra = {};          // часть get_initial: default_dir, transcoders, ffmpeg
  var activeSection = "";

  var panelFields = {};    // путь настройки -> {spec, nodes, input, range, get, set}
  var panelButtons = {};   // id кнопки -> элемент
  var noteFillers = {};    // note_source -> нужно перерисовывать
  var customSave = {};     // путь настройки -> поле со своим обработчиком
  // обёртки (карточка .field-card, строка .range-row) с полями внутри: если все
  // поля скрыты, пустая рамка и пустая строка тоже убираются, иначе в разделе
  // FTP остаётся рамка «Подключение» с пустым содержимым
  var panelWrappers = [];  // [{el, keys}]

  // SVG-теги создаются в SVG-namespace: document.createElement("svg") даёт
  // HTML-элемент (HTMLUnknownElement), его innerHTML парсится как HTML, фигуры
  // получают box 0x0 и ничего не рисуют - тумблер был «невидим», хотя
  // computed-стили работали. У SVG className read-only, поэтому class -
  // только через setAttribute.
  var SVG_TAGS = {svg: 1, g: 1, rect: 1, path: 1, polyline: 1, circle: 1, line: 1};
  function el(tag, cls, attrs) {
    var isSvg = !!SVG_TAGS[tag];
    var node = isSvg ? document.createElementNS("http://www.w3.org/2000/svg", tag)
                     : document.createElement(tag);
    if (cls) {
      if (isSvg) node.setAttribute("class", cls);
      else node.className = cls;
    }
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
  function caption(key, cls) {
    var node = el("span", cls, {"data-i18n": key});
    node.textContent = t(key);
    return node;
  }
  function labelNode(spec) {
    var node = el("label", null, {for: spec.dom, "data-i18n": spec.label});
    node.textContent = t(spec.label);
    return node;
  }

  // Одно поле схемы -> узлы и, если поле редактируемое, input (+range-зеркало).
  // get/set позволяют работать одинаково и с обычным полем, и с переключателем
  // режима: синхронизация значений не знает, что внутри.
  function renderField(spec) {
    if (spec.type === "actions") {
      var buttons = spec.buttons.map(function(b) {
        return renderButton(b);
      });
      // в строке кнопки не оборачиваем: строку собирает renderWindow
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
      var check = el("div", "check" + (spec.pixel ? " pixel-toggle" : ""));
      var box = el("input", null, {type: "checkbox", id: spec.dom});
      check.appendChild(box);
      // у обычного чекбокса подсказка живёт на подписи
      if (!spec.no_label) {
        var cap = caption(spec.label);
        if (spec.title) {
          cap.setAttribute("data-i18n-tip", spec.title);
          setTip(cap, t(spec.title));
        }
        check.appendChild(cap);
      }
      // пиксельный переключатель без подписи: смысл - в подсказке и в aria.
      // Внутри div, а не <label>, поэтому клик по тумблеру переключает сам
      // (клик по спрятанному чекбоксу и так работает - его не трогаем).
      if (spec.pixel) {
        var px = el("svg", "px", {viewBox: "0 0 40 20", width: "40", height: "20",
                                  "aria-hidden": "true"});
        px.innerHTML = '<rect class="px-track" x="1" y="1" width="38" height="18"></rect>'
          + '<g class="px-knob">'
          + '<rect class="px-knob-fill" x="4" y="4" width="12" height="12"></rect>'
          + '<polyline class="px-check" points="7 10 10 13 14.5 6.5"></polyline></g>';
        check.appendChild(px);
        var onPxClick = function(ev) {
          if (ev.target === box) return;
          box.checked = !box.checked;
          box.dispatchEvent(new Event("change"));
        };
        check.addEventListener("click", onPxClick);
        check.setAttribute("data-i18n-aria", spec.label);
        check.setAttribute("data-i18n-tip", spec.title || spec.label);
        setTip(check, t(spec.title || spec.label));
      }
      // double-click - сброс в дефолт схемы (webaudio-controls идиома):
      // два клика переключателя уже вернули состояние туда-сюда, третий
      // жест возвращает умолчание схемы и сохраняет его
      check.addEventListener("dblclick", function(ev) {
        ev.preventDefault();
        var def = !!spec.default;
        if (box.checked !== def) {
          box.checked = def;
          box.dispatchEvent(new Event("change", {bubbles: true}));
        }
      });
      return {nodes: [check], input: box, get: function() { return box.checked; },
              set: function(v) { box.checked = v !== false && !!v; }};
    }
    var nodes = [labelNode(spec)];
    var input;
    if (spec.type === "choice_buttons") {
      // Переключатель вместо выпадающего списка: короткие подписи рядом, а
      // разница между ними - в подсказке. Короткий список всегда на виду.
      var wrap = el("div", "mode-switch", {id: spec.dom, role: "group",
                                            "aria-label": t(spec.label)});
      (spec.options || []).forEach(function(o) {
        var b = el("button", null, {type: "button", "data-value": o[0], "data-i18n": o[1]});
        b.textContent = t(o[1]);
        // у каждого варианта режима своя подсказка (option_hints в схеме)
        var hintKey = spec.option_hints && spec.option_hints[o[0]];
        if (hintKey) {
          b.setAttribute("data-i18n-tip", hintKey);
          setTip(b, t(hintKey));
        }
        b.addEventListener("click", function() {
          var key = spec.path || spec.dom;
          setModeValue(wrap, this.getAttribute("data-value"));
          saveValue(key, this.getAttribute("data-value"));
        });
        wrap.appendChild(b);
      });
      var readMode = function() {
        var on = wrap.querySelector(".on");
        return on ? on.getAttribute("data-value") : "";
      };
      return {nodes: [labelNode(spec), wrap], input: wrap,
              get: readMode, set: function(v) { setModeValue(wrap, v); }};
    }
    if (spec.type === "knob") {
      // Круговая ручка. Два режима. Позиционный (шрифты): конечная дуга
      // 270° со стартом слева-внизу - «нулевая точка» снизу, упоры на
      // концах, зацикливания нет; магнит - индикатор всегда сидит на
      // позиции щелчка. Числовая (толщина): бесконечная - обороты
      // накапливаются, значение крутится через ноль. Оба режима вращаются
      // плавно: целевой угол догоняется по rAF с МАКСИМУМОМ скорости
      // (1080 град/с) и экспоненциальным замедлением - даже бурст колеса
      // не раскручивает ручку быстрее этого.
      var numeric = spec.min !== undefined && spec.max !== undefined;
      var step = spec.step || 10, lo = spec.min, hi = spec.max;
      var positions = [];              // позиционная: [{value, label}]
      var A0 = 225, SWEEP = 270;       // дуга:225° - слева-внизу (ноль)
      var raw = 0;                     // накопленный угол ввода
      var disp = 0;                    // показываемый угол (анимация)
      var cur = numeric ? spec.default : (spec.default || "");
      var idx = 0;                     // позиционная: индекс выбранной позиции
      var raf = 0, lastT = 0, editT = 0;  // editT - таймер скрытия значения
      function norm(a) { return ((a % 360) + 360) % 360; }
      function nSteps() {
        return numeric ? Math.round((hi - lo) / step) + 1 : positions.length;
      }
      function sa() { return 360 / Math.max(nSteps(), 1); }
      function sweepStep() { return SWEEP / Math.max(positions.length - 1, 1); }
      function clampRaw(a) { return Math.max(A0, Math.min(A0 + SWEEP, a)); }
      function angForIdx(i) { return A0 + i * sweepStep(); }
      function idxAt(a) {
        var n = positions.length;
        if (n <= 1) return 0;
        return Math.max(0, Math.min(n - 1,
          Math.round((clampRaw(a) - A0) / SWEEP * (n - 1))));
      }
      function valueAt(a) {
        return lo + (Math.round(norm(a) / sa()) % nSteps()) * step;
      }
      function angleFor(v) { return (v - lo) / step * sa(); }
      // ближайший к текущему raw путь к желаемому углу (Home/End числа)
      function retarget(desiredNorm) {
        var d = desiredNorm - norm(raw);
        while (d > 180) d -= 360;
        while (d < -180) d += 360;
        raw += d;
      }
      // целевой угол: позиционная - позиция щелчка (магнит), числовая -
      // ближайшая ступень накопленного угла (обороты не сбрасываются)
      function targetAng() {
        return numeric ? Math.round(raw / sa()) * sa() : angForIdx(idx);
      }
      function pct() { return Math.round((cur - lo) / (hi - lo) * 100); }
      var kwrap = el("div", "knob", {
        id: spec.dom, role: "slider", tabindex: "0",
        "aria-label": t(spec.label),
        "aria-valuemin": numeric ? String(lo) : "0",
        "aria-valuemax": numeric ? String(hi) : "0"});
      var ind = el("i", "knob-ind");
      kwrap.appendChild(ind);
      // временное значение на ручке (webaudio-controls идиома): цифра видна
      // только пока идёт ввод (dragging/editing), в покое её нет - подсказка
      // остаётся единственным местом показа (см. .knob-val в settings.css)
      var valNode = el("b", "knob-val");
      kwrap.appendChild(valNode);
      Object.defineProperty(kwrap, "value", {get: function() { return cur; }});
      // риски позиций: активная горит акцентом (детент виден)
      function renderTicks() {
        [].slice.call(kwrap.querySelectorAll(".knob-tick")).forEach(function(n) { n.remove(); });
        if (numeric) return;
        var n = Math.max(positions.length, 1);
        for (var i = 0; i < n; i++) {
          var tk = el("i", "knob-tick" + (i === idx ? " on" : ""));
          tk.style.transform = "rotate(" + angForIdx(i) + "deg) translateY(-14px)";
          tk.setAttribute("data-value", positions[i] ? String(positions[i].value) : "");
          kwrap.appendChild(tk);
        }
      }
      function tipText() {
        if (numeric) return t("sheet.font.weight.tip").replace("{p}", String(pct()));
        return (positions[idx] && positions[idx].label) || String(cur);
      }
      function paint() {
        ind.style.transform = "rotate(" + disp.toFixed(2) + "deg)";
        // значение на ручке: только числовым шкалам (у позиционных подпись
        // длинная - семейство шрифта - и остаётся в подсказке)
        valNode.textContent = numeric ? String(cur) : "";
        var text = tipText();
        setTip(kwrap, text);
        // setTip пишет aria-label узлу без текста - возвращаем подпись поля
        kwrap.setAttribute("aria-label", t(spec.label));
        var fontFam = !numeric && cur ? String(cur) : "";
        if (fontFam) kwrap.setAttribute("data-tip-font", fontFam);
        else kwrap.removeAttribute("data-tip-font");
        if (numeric) {
          kwrap.setAttribute("aria-valuenow", String(cur));
          kwrap.setAttribute("aria-valuetext", String(cur));
        } else {
          kwrap.setAttribute("aria-valuenow", String(idx));
          kwrap.setAttribute("aria-valuetext", text);
        }
        // подсказка живёт при вращении: процент/название меняются на лету
        if (window.TIP && TIP.target === kwrap && TIP.text) {
          TIP.text.textContent = text;
          TIP.node.style.fontFamily = tipFontFamily(kwrap);
        }
      }
      // анимация: к целевому углу - с потолком скорости и затуханием;
      // на месте точное прилипание (магнит к позиции щелчка)
      function tick() {
        raf = 0;
        var now = performance.now();
        var dt = Math.min(0.25, Math.max(0.001, (now - lastT) / 1000));
        lastT = now;
        var d = targetAng() - disp;
        if (Math.abs(d) < 0.15) { disp = targetAng(); paint(); return; }
        var speed = Math.min(1080 * dt, Math.abs(d) * (1 - Math.exp(-dt / 0.09)) + 60 * dt);
        disp += (d > 0 ? 1 : -1) * Math.min(Math.abs(d), speed);
        paint();
        raf = requestAnimationFrame(tick);
      }
      function kick() {
        if (raf) return;
        lastT = performance.now();
        raf = requestAnimationFrame(tick);
      }
      function commit(nv) {
        if (nv !== cur) {
          cur = nv;
          kwrap.dispatchEvent(new Event("change", {bubbles: true}));
        }
      }
      // ввод изменил raw: новое значение + анимация к позиции
      function applyInput() {
        // цифра на ручке появляется при любом вводе и гаснет через 0.8 с
        // покоя (класс снимает и .dragging, и таймер)
        kwrap.classList.add("editing");
        clearTimeout(editT);
        editT = setTimeout(function() { kwrap.classList.remove("editing"); }, 800);
        if (numeric) {
          commit(valueAt(raw));
        } else {
          raw = clampRaw(raw);           // упоры: за дугу270° не выходим
          var ni = idxAt(raw);
          if (ni !== idx) {
            idx = ni;
            cur = positions[idx] ? positions[idx].value : cur;
            renderTicks();
            kwrap.dispatchEvent(new Event("change", {bubbles: true}));
          }
        }
        kick();
        paint();
      }
      kwrap.addEventListener("pointerdown", function(ev) {
        kwrap.focus({preventScroll: true});   // fillSettings не трогает поле в фокусе
        kwrap.setPointerCapture(ev.pointerId);
        kwrap.classList.add("dragging");
        var lx = ev.clientX, ly = ev.clientY;
        var move = function(e2) {
          // драг по ОБЕИМ осям (webaudio-controls): вертикаль - основной
          // жест, горизонтальный оставлен как есть; Shift = точное доводство
          // (вчетверо меньше чувствительность - ступень шкалы меняется реже,
          // значение от этого НЕ становится дробным: квантование шага цело)
          var dx = e2.clientX - lx, dy = e2.clientY - ly;
          lx = e2.clientX; ly = e2.clientY;
          var k = e2.shiftKey ? 0.3 : 1.2;
          raw += (dx + dy) * k;
          applyInput();
        };
        var up = function() {
          kwrap.classList.remove("dragging");
          kwrap.removeEventListener("pointermove", move);
          kwrap.removeEventListener("pointerup", up);
          kwrap.removeEventListener("pointercancel", up);
          if (numeric) raw = Math.round(raw / sa()) * sa();
          applyInput();                    // магнит дожимает к позиции
        };
        kwrap.addEventListener("pointermove", move);
        kwrap.addEventListener("pointerup", up);
        kwrap.addEventListener("pointercancel", up);
      });
      kwrap.addEventListener("wheel", function(ev) {
        ev.preventDefault();
        kwrap.focus({preventScroll: true});   // и колесо под фокусом: poll не откатит
        var s = numeric ? sa() : sweepStep();
        // Shift - точная подстройка: четверть шага; квантование ступени
        // остаётся, поэтому значение всё равно кратно шагу шкалы
        var k = ev.shiftKey ? 0.25 : 1;
        raw += (ev.deltaY < 0 ? s : -s) * k;   // на упоре clampRaw не пустит дальше
        applyInput();
      }, {passive: false});
      // double-click - сброс в дефолт схемы (webaudio-controls идиома):
      // числовая - прямиком к default, позиционная - к позиции со значением
      // default (для шрифтов это системный шрифт "")
      kwrap.addEventListener("dblclick", function(ev) {
        ev.preventDefault();
        if (numeric) {
          retarget(angleFor(spec.default));
        } else {
          var di = 0;
          for (var i = 0; i < positions.length; i++) {
            if (positions[i].value === String(spec.default)) { di = i; break; }
          }
          raw = angForIdx(di);
        }
        applyInput();
        kick();
        paint();
      });
      kwrap.addEventListener("keydown", function(ev) {
        if (ev.key === "Home") {
          ev.preventDefault();
          if (numeric) { retarget(0); }
          else { raw = A0; }
          applyInput();
          return;
        }
        if (ev.key === "End") {
          ev.preventDefault();
          if (numeric) { retarget(angleFor(hi)); }
          else { raw = A0 + SWEEP; }
          applyInput();
          return;
        }
        var d = 0;
        if (ev.key === "ArrowUp" || ev.key === "ArrowRight") d = 1;
        else if (ev.key === "ArrowDown" || ev.key === "ArrowLeft") d = -1;
        if (!d) return;
        ev.preventDefault();
        raw += d * (numeric ? sa() : sweepStep());
        applyInput();
      });
      // позиции приходят снаружи (buildFontOptions): пересобираем риски и
      // возвращаем индекс к текущему значению
      kwrap._knobSet = function(opts) {
        positions = (opts || []).map(function(o) {
          return {value: String(o[0]), label: String(o[1])};
        });
        idx = 0;
        for (var i = 0; i < positions.length; i++) {
          if (positions[i].value === String(cur)) { idx = i; break; }
        }
        kwrap.setAttribute("aria-valuemax", String(Math.max(positions.length - 1, 0)));
        raw = angForIdx(idx);
        renderTicks();
        kick();
        paint();
      };
      var kcell = el("div", "knob-cell");
      kcell.appendChild(labelNode(spec));
      kcell.appendChild(kwrap);
      raw = numeric ? angleFor(cur) : angForIdx(idx);
      disp = raw;
      paint();
      return {nodes: [kcell], input: kwrap,
              get: function() { return cur; },
              set: function(v) {
                if (numeric) {
                  var n = Number(v);
                  if (!isFinite(n)) n = spec.default;
                  n = Math.max(lo, Math.min(hi, Math.round(n / step) * step));
                  retarget(angleFor(n));
                  commit(n);
                } else {
                  cur = v === undefined || v === null ? (spec.default || "") : String(v);
                  idx = 0;
                  for (var i = 0; i < positions.length; i++) {
                    if (positions[i].value === cur) { idx = i; break; }
                  }
                  raw = angForIdx(idx);
                }
                kick();
                paint();
              }};
    }
    if (spec.type === "choice") {
      input = el("select", null, {id: spec.dom});
      // опции из схемы наполняем сразу: иначе у поля без своей функции
      // список остался бы пустым
      fillSelectNode(input, spec.options, true);
    } else if (spec.type === "int") {
      input = el("input", null, {type: "number", id: spec.dom, min: spec.min, max: spec.max, step: spec.step});
    } else {
      input = el("input", null, {type: "text", id: spec.dom});
      input.setAttribute("spellcheck", "false");
      if (spec.type === "password") input.setAttribute("autocomplete", "off");
      if (spec.placeholder) input.placeholder = spec.placeholder;
    }
    // подсказка поля-ввода живёт на самом поле, а не на подписи: наведение на
    // «Перекодировка:» не должно показывать её
    if (spec.title) {
      input.setAttribute("data-i18n-tip", spec.title);
      setTip(input, t(spec.title));
    }
    nodes.push(input);
    var range = null;
    if (spec.mirror === "range" && spec.dom_range) {
      range = el("input", null, {type: "range", id: spec.dom_range, min: spec.min, max: spec.max, step: spec.step});
      nodes.splice(1, 0, range);
    }
    return {nodes: nodes, input: input, range: range,
            get: function() { return spec.type === "bool" ? input.checked : input.value.trim(); },
            set: function(v) { input.value = v || spec.default || ""; }};
  }
  function setModeValue(wrap, value) {
    [].slice.call(wrap.querySelectorAll("button")).forEach(function(b) {
      b.classList.toggle("on", b.getAttribute("data-value") === value);
    });
  }
  // Кнопка действия: с иконкой - только иконка (смысл в подсказке), без иконки
  // - подпись. Текст убираем не всегда: у «Обзор…» и «Проверить подключение»
  // своей иконки нет, и голый значок был бы непонятен. Подсказка есть только у
  // кнопок с иконкой: у текстовых смысл уже виден в подписи.
  function renderButton(b) {
    var svg = b.icon ? iconSvg(b.icon) : "";
    var btn = el("button", svg ? "act-btn ico-" + b.icon : null,
                 {type: "button", id: b.dom});
    if (svg) {
      var ico = el("span", "ico");
      ico.innerHTML = svg;
      btn.appendChild(ico);
      if (b.label) {
        btn.setAttribute("data-i18n-tip", b.label);
        setTip(btn, t(b.label));
      }
    } else {
      btn.appendChild(caption(b.label));
    }
    panelButtons[b.dom] = btn;
    return btn;
  }

  // Разделы карточки: слева кнопки, справа содержимое полей. Внутри раздела
  // карточки и строки собираются теми же правилами, что были у вкладок панели:
  // поля одного блока (box) попадают в одну карточку, поля с одинаковым row -
  // в одну строку. Ответственность разделили: схема -> чистые данные
  // (layoutOf), DOM -> Alpine x-for в settings.html (этап 4). Один узел ведёт
  // только один способ: Alpine рисует структуру, renderField - внутренности
  // поля, switchSection - видимость секций.
  function layoutOf(group) {
    var cards = [], cur = null, curName, row = null, seq = 0;
    function flushRow() {
      if (!row || !cur) { row = null; return; }
      cur.blocks.push({key: "b" + group.id + "-" + (seq++), cls: row.cls,
                       keys: row.keys, fields: row.fields});
      row = null;
    }
    function flushCard() {
      flushRow();
      // блок без полей (все его поля in_panel: false) в раздел не идёт -
      // иначе в разделе висит рамка с заголовком и пустотой внутри
      if (cur && cur.blocks.length) cards.push(cur);
      cur = null;
    }
    function openBlock(name) {
      flushCard();
      cur = {key: name || ("~" + group.id + "-" + seq), title: name ? group.boxes[name] : null,
             blocks: [], keys: []};
      curName = name;
    }
    group.fields.forEach(function(spec) {
      if (spec.in_panel === false) return;
      var name = spec.box || null;
      if (!cur || name !== curName) openBlock(name);
      // у блока кнопок нет ни path, ни dom: в panelFields ему нечего
      // положить, иначе ключом станет "undefined"
      var key = spec.path || spec.dom;
      if (spec.row !== undefined && spec.row !== null) {
        // поля с одинаковым row встают в одну строку (label + input)
        if (row && spec.row !== row.idx) flushRow();
        if (!row) row = {idx: spec.row, cls: spec.row_class || "range-row",
                         fields: [], keys: []};
        row.fields.push(spec);
        if (key) row.keys.push(key);
      } else {
        flushRow();
        cur.blocks.push({key: "b" + group.id + "-" + (seq++), cls: null,
                         keys: key ? [key] : [], fields: [spec]});
      }
      if (key) cur.keys.push(key);
    });
    flushCard();
    return cards;
  }

  // Монтирование блока полей в якорь x-for (директива x-mount-block).
  // Узлы поля рисует renderField как раньше (слушатели вешаются внутри),
  // якорь гасится: в .field-card-body не остаётся лишних обёрток и прямые
  // потомки те же, что при императивной сборке (на них завязан CSS
  // карточки шрифтов). Строка (row_class) - единственный случай, когда
  // обёртка создаётся здесь же, и она сразу попадает в applyVisibility.
  function mountBlockInto(anchor, blk) {
    var row = blk.cls ? el("div", blk.cls) : null;
    var holder = row || document.createDocumentFragment();
    blk.fields.forEach(function(spec) {
      var part = renderField(spec);
      var key = spec.path || spec.dom;
      if (key) {
        panelFields[key] = {spec: spec, nodes: part.nodes, input: part.input,
                            range: part.range, get: part.get, set: part.set};
      }
      part.nodes.forEach(function(n) { holder.appendChild(n); });
    });
    if (row) {
      panelWrappers.push({el: row, keys: blk.keys});
      anchor.parentNode.insertBefore(row, anchor);
    } else {
      anchor.parentNode.insertBefore(holder, anchor);
    }
    anchor.remove();
  }
  // Обёртка-карточка (x-mount-card) участвует в applyVisibility так же, как
  // строка: рамка прячется, когда скрыты все её поля
  function mountCardInto(cardEl, card) {
    panelWrappers.push({el: cardEl, keys: card.keys});
  }

  // Готовность панели. Alpine монтирует её сам при старте движка (x-data в
  // settings.html), сигнал - $nextTick в init() компонента (после полного
  // рендера x-for все поля уже отмонтированы). synfSettingsInit может
  // прийти и раньше, и позже - шаги, требующие полей, копятся в очередь.
  var panelBound = false, afterPanel = [];
  function whenPanelReady(fn) {
    if (panelBound) fn();
    else afterPanel.push(fn);
  }
  function fieldsMounted() {
    if (panelBound) return;
    panelBound = true;
    bindCustom();
    bindSettings();
    var queue = afterPanel;
    afterPanel = [];
    queue.forEach(function(fn) { fn(); });
  }

  // Компонент и директивы регистрируются до старта Alpine: движок шлёт
  // alpine:init перед инициализацией дерева, а settings.js исполняется
  // последним из своих скриптов (порядок common -> motion -> app ->
  // settings -> alpine проверяется чеком).
  document.addEventListener("alpine:init", function() {
    Alpine.data("settingsPanel", function() {
      var groups = SETTINGS_SCHEMA.groups.filter(function(group) {
        return group.in_panel !== false && (group.fields || []).length;
      }).map(function(group) {
        var copy = {};
        Object.keys(group).forEach(function(k) { copy[k] = group[k]; });
        copy.layout = layoutOf(group);   // клон: схема остаётся нетронутой
        return copy;
      });
      return {
        groups: groups,
        // после этого nextTick рендера все x-mount-* отработали
        init: function() { this.$nextTick(fieldsMounted); }
      };
    });
    Alpine.directive("mount-block", function(el, directive, ctx) {
      mountBlockInto(el, ctx.evaluate(directive.expression));
    });
    Alpine.directive("mount-card", function(el, directive, ctx) {
      mountCardInto(el, ctx.evaluate(directive.expression));
    });
  });

  function renderWindow() {
    // структуру рисует Alpine (x-for в settings.html): раньше здесь был
    // полный проход по схеме с innerHTML и чисткой реестров, теперь
    // реестры наполняет mountBlockInto, а пересборки нет вовсе - схема
    // константна, смена языка обходится translateStatic (applySettingsI18n)
    hideTip();
  }


  function switchSection(name) {
    hideTip();
    SETTINGS_SCHEMA.groups.forEach(function(group) {
      var sec = document.getElementById("section-" + group.id);
      var item = document.getElementById("nav-" + group.id);
      if (sec) sec.hidden = group.id !== name;
      if (item) item.classList.toggle("active", group.id === name);
    });
    activeSection = name;
  }

  // -- списки значений полей -------------------------------------------------
  function buildThemeOptions() {
    var sel = document.getElementById("theme");
    if (!sel) return;
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
        // битая тема: подсказка на варианте списка (у <option> нет подсказки
        // нашего компонента - их не трогает initTooltips, только title)
        label += " ⚠";
        opt.title = t("theme.meta.broken") + "\n" + th.warnings.join("\n");
      }
      opt.textContent = label;
      sel.appendChild(opt);
    });
    sel.value = keep;
    if (sel.value === "") {
      var first = sel.querySelector("option");
      sel.value = first ? first.value : "";
    }
  }
  function buildSubsOptions() { fillSelect("subs", fieldOptions("dl.subtitles")); }
  function buildQualOptions() { fillSelect("qual", fieldOptions("dl.quality")); }
  function buildTranscodeOptions() {
    var sel = document.getElementById("transcode");
    if (!sel) return;
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
    if (note) {
      if (!transAvailability.ffmpeg) {
        note.textContent = t("trans.note.noffmpeg");
        note.hidden = false;
      } else if (missing.length) {
        note.textContent = t("trans.note.missing") + missing.join(", ") + ".";
        note.hidden = false;
      } else {
        // всё доступно: пустой контейнер не должен занимать место под списком
        note.textContent = "";
        note.hidden = true;
      }
    }
  }
  function buildLangOptions() {
    fillSelect("lang", LANGS.map(function(k) { return [k, I18N[k]["thisLang"]]; }));
  }

  // Списки шрифтов: "" = системный. Семейства приходят с Python (папка
  // fonts) и наполняют позиции трёх ручек (заголовки, общий, консольный);
  // вес берёт шкалу прямо из схемы и риски не рисует.
  function buildFontOptions() {
    var families = (FONTS && FONTS.families) || [];
    var monoFirst = (FONTS && FONTS.mono) || [];
    var monoAll = monoFirst.concat(families.filter(function(f) {
      return monoFirst.indexOf(f) === -1;
    }));
    var sys = [["", t("sheet.font.system")]];
    [["font-heading", families], ["font-sans", families], ["font-mono", monoAll]]
      .forEach(function(pair) {
        var node = document.getElementById(pair[0]);
        if (node && node._knobSet) {
          node._knobSet(sys.concat(pair[1].map(function(f) { return [f, f]; })));
        }
      });
    updateFontNote();
  }
  // Подсказки ручек зависят от языка (и от значения) - после смены языка
  // перерисовываем их через set(текущее значение)
  function refreshKnobTips() {
    Object.keys(panelFields).forEach(function(key) {
      var f = panelFields[key];
      if (f.spec.type === "knob" && f.get && f.set) f.set(f.get());
    });
  }
  function updateFontNote() {
    var box = document.getElementById("font-note");
    if (!box) return;
    if ((FONTS && FONTS.count) > 0) { box.textContent = ""; box.hidden = true; return; }
    box.textContent = t("sheet.font.hint").replace("{path}", (FONTS && FONTS.folder) || "");
    box.hidden = false;
  }
  // Предпросмотр шрифтов: каждая строка - «{заголовок} - {выбранное
  // семейство}», набранная своими шрифтами (и толщиной - у строки
  // основного текста). Имя системного шрифта переводится, названия
  // семейств - как есть; сам текст не переводится, он показывает глифы.
  function updateFontPreview() {
    var box = document.getElementById("font-preview");
    if (!box) return;
    var sysName = t("sheet.font.system");
    var names = [FONT_PICK.head || sysName, FONT_PICK.sans || sysName,
                 FONT_PICK.mono || sysName];
    function esc(s) {
      return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
    }
    var heads = ["Заголовок", "Основной текст", "Консоль"];
    box.innerHTML = '<div class="fp-head">' + heads[0] + " - " + esc(names[0]) + "</div>"
      + '<div class="fp-text">' + heads[1] + " - " + esc(names[1]) + "</div>"
      + '<div class="fp-mono">' + heads[2] + " - " + esc(names[2]) + "</div>";
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

  // applyI18n живёт в app.js и переводит всё окно целиком, включая карточку:
  // эта функция только её часть, поэтому отдельное имя - иначе одна из двух
  // перезапишет другую (скрипты грузятся в один глобальный scope).
  function applySettingsI18n() {
    translateStatic();
    // списки из схемы переводим первыми, дальше их уточняют сборщики полей
    fillSchemaChoices();
    buildThemeOptions();
    buildSubsOptions();
    buildQualOptions();
    buildTranscodeOptions();
    buildLangOptions();
    buildFontOptions();
    refreshKnobTips();
    refreshNotes();   // предпросмотр зависит от языка (имя системного шрифта)
    var lang = document.getElementById("lang");
    if (lang) lang.value = curLang;
    document.documentElement.lang = curLang;
    langPainted = curLang;
  }

  // -- команды кнопок и наполнение пояснений --------------------------------
  // В схеме у кнопки есть dom и подпись, здесь - только действие.
  var ACTIONS = {
    "reload-themes": function() { reloadThemes(); },
    "download-themes": function() { downloadThemes(); },
    "open-themes": function() { openThemesFolder(); },
    "reload-fonts": function() { reloadFonts(); },
    "download-fonts": function() { downloadFonts(); },
    "open-fonts": function() { openFontsFolder(); },
    "browse": async function() {
      var picked = await pywebview.api.browse_folder();
      if (picked) {
        panelFields["dl.dest"].set(picked);
        pywebview.api.set_dest(picked);
      }
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
  var NOTE_FILLERS = {ftpDirNote: updateFtpDirNote, fontPreview: updateFontPreview};
  function refreshNotes() {
    Object.keys(noteFillers).forEach(function(src) { NOTE_FILLERS[src](); });
  }
  function updateFtpDirNote() {
    var note = document.getElementById("ftp-dir-note");
    var f = panelFields["ftp.dir"];
    if (!note || !f) return;
    var dir = f.get();
    note.textContent = dir ? t("sheet.ftp.dir.ok") : t("sheet.ftp.dir.empty");
  }

  // -- значения и сохранение -------------------------------------------------
  function valueOf(spec) {
    if (spec.value_source) return extra[spec.value_source];
    return (extra.settings || {})[spec.setting];
  }
  // Силы подсказок (common.js, TIP_FORCE) применяются сразу при правке поля,
  // а не с задержкой poll(): fillSettings пропускает поле в фокусе, поэтому
  // пока тянут слайдер, значения едут в общий движок напрямую.
  function syncTipForces() {
    var pull = panelFields["ui.tip_pull"], repel = panelFields["ui.tip_repel"];
    setTipForces(pull && pull.get ? pull.get() : undefined,
                 repel && repel.get ? repel.get() : undefined);
  }
  function saveValue(key, value) {
    var spec = panelFields[key].spec;
    if (spec.setting) pywebview.api.save_setting(spec.setting, value);
    // папка загрузки - не настройка: Python помнит её до конца сеанса
    if (spec.path === "dl.dest") pywebview.api.set_dest(value);
    syncTipForces();
    applyVisibility();
    refreshNotes();
  }
  // Значения приходят и из poll(), поэтому карточка их не только читает, но и
  // показывает: так она останется верной и после ручной правки settings.json
  // или смены языка/темы. Поле, в котором сейчас печатают, не трогаем - иначе
  // poll() (200 мс) затирал бы ввод и сбрасывал курсор.
  function fillSettings() {
    Object.keys(panelFields).forEach(function(key) {
      var f = panelFields[key], spec = f.spec;
      if (!f.get || !f.set) return;
      if (f.input && f.input === document.activeElement) return;
      var value = valueOf(spec);
      if (spec.type === "bool") f.set(value !== false && !!value);
      else f.set(value === undefined || value === null ? (spec.default || "") : String(value));
      if (f.range) f.range.value = f.get();
    });
  }

  function bindSettings() {
    Object.keys(panelFields).forEach(function(key) {
      var f = panelFields[key], spec = f.spec, node = f.input;
      if (!node || customSave[key]) return;
      // переключатель режима сам сохраняет значение по клику (см. renderField)
      if (spec.type === "choice_buttons") return;
      node.addEventListener("change", function() {
        var value = f.get();
        if (f.range) f.range.value = value;
        saveValue(key, value);
      });
      if (f.range) {
        f.range.addEventListener("input", function() {
          node.value = this.value;
          if (spec.setting) pywebview.api.save_setting(spec.setting, this.value);
          // при перетаскивании силы подсказок применяются на лету
          syncTipForces();
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
      var show = !!(src && src.get && src.get()) === !!cond.equals;
      panelFields[key].nodes.forEach(function(node) { node.hidden = !show; });
    });
    // Карточка и строка прячутся, когда скрыты все поля внутри: иначе в
    // разделе FTP остаётся пустая рамка «Подключение», а в строках - пустые
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
  // Поля с собственным поведением помечаются customSave ДО bindSettings(),
  // иначе к теме/языку/шрифтам привяжется ещё и общий обработчик и каждый
  // выбор запишется в settings.json дважды.
  function bindCustom() {
    // тема: часть тем со своим entry собирается в Python (пересборка страницы),
    // остальные применяются на лету
    onChange("ui.theme", function(node, spec) {
      var th = THEMES[node.value] || {};
      if (th.entry) {
        pywebview.api.set_theme(node.value);
        return;
      }
      applyTheme(node.value);
      pywebview.api.save_setting(spec.setting, node.value);
      if (th.font || th.font_mono) loadFontFaces(fontFacesForTheme());
    });
    onChange("ui.language", function(node, spec) {
      curLang = node.value;
      applyI18n();
      applyTheme(themeKey());
      pywebview.api.save_setting(spec.setting, node.value);
    });
    onChange("ui.font_sans", function(node) { setFont("font-sans", node.value); });
    onChange("ui.font_mono", function(node) { setFont("font-mono", node.value); });
    onChange("ui.font_heading", function(node) { setFont("font-heading", node.value); });
    onChange("ui.font_weight", function(node, spec) {
      pywebview.api.save_setting(spec.setting, node.value);
      FONT_PICK.weight = node.value || "";
      setFontVar("--font-weight", FONT_PICK.weight);
      refreshNotes();   // предпросмотр сразу показывает новую толщину
    });
  }

  // -- темы и шрифты ---------------------------------------------------------
  function reloadThemes() {
    var btn = document.getElementById("reload-themes");
    pywebview.api.reload_themes().then(function(newThemes) {
      THEMES = newThemes;
      buildThemeOptions();
      fillSettings();
      flashDone(btn);
    }).catch(function(e) { console.error("reload themes:", e); });
  }
  // Восстановление встроенных тем с диска: сети не нужно, на диск попадает
  // только то, чего ещё нет. Пока Python пишет - кнопка в состоянии busy.
  function downloadThemes() {
    var btn = document.getElementById("download-themes");
    var note = document.getElementById("themes-dl-note");
    btn.classList.add("busy");
    setNote(note, t("theme.dl.start"));
    pywebview.api.download_themes()
      .then(function(res) {
        btn.classList.remove("busy");
        var res2 = res || {};
        if (res2.error) {
          setNote(note, t("theme.dl.fail").replace("{names}", String(res2.error)));
          return;
        }
        if (res2.added && res2.added.length) {
          setNote(note, t("theme.dl.done").replace("{names}", res2.added.join(", ")));
          flashDone(btn);
        } else {
          setNote(note, t("theme.dl.skip"));
        }
      })
      .catch(function(e) {
        btn.classList.remove("busy");
        setNote(note, t("theme.dl.fail").replace("{names}", String(e)));
      });
  }
  function setNote(note, text) {
    if (!note) return;
    note.textContent = text || "";
    note.hidden = !text;
  }
  // Зелёная галочка на кнопке: действие выполнено. Иконка на это время
  // заменяется на неё, потом возвращается.
  function flashDone(btn) {
    if (!btn) return;
    var ico = btn.querySelector(".ico");
    if (!ico) return;
    var svg = ico.innerHTML;
    btn.classList.add("done");
    ico.innerHTML = iconSvg("check");
    setTimeout(function() {
      ico.innerHTML = svg;
      btn.classList.remove("done");
    }, 900);
  }
  function openThemesFolder() {
    pywebview.api.open_themes_folder();
  }
  // Шрифт применяется подменой блока #fonts-style - без перезагрузки страницы
  // и без потери состояния интерфейса. Карточка настроек в том же окне, так
  // что список шрифтов и @font-face обновляются на месте.
  function setFont(id, value) {
    var slot = id === "font-mono" ? "mono" : (id === "font-heading" ? "head" : "sans");
    var key = slot === "mono" ? "font_mono" : (slot === "head" ? "font_heading" : "font_sans");
    pywebview.api.set_font(key, value)
      .then(function(r) {
        if (r && r.error) { console.error("set font:", r.error); return; }
        FONT_PICK[slot] = value || "";
        if (r && r.css !== undefined) applyFontCss(r.css);
        var th = THEMES[themeKey()] || {};
        // тема переопределяет только общий и консольный шрифты - у заголовков
        // своего поля в theme.json нет
        var thFont = slot === "mono" ? th.font_mono : (slot === "head" ? "" : th.font);
        var prop = slot === "mono" ? "--font-mono"
                 : (slot === "head" ? "--font-head" : "--font-sans");
        setFontVar(prop, quoted(thFont || FONT_PICK[slot]));
        refreshNotes();   // предпросмотр показывает новый шрифт сразу
      })
      .catch(function(e) { console.error("set font:", e); });
  }
  function reloadFonts() {
    pywebview.api.reload_fonts()
      .then(function(r) {
        if (r && r.fonts) FONTS = r.fonts;
        if (r && r.css !== undefined) applyFontCss(r.css);
        buildFontOptions();
        fillSettings();
      })
      .catch(function(e) { console.error("reload fonts:", e); });
  }
  // Докачка шрифтов из сети: кнопка busy на всё время, прогресс в note.
  // Список обновится сам, когда Python поднимет fonts_rev (см. synfSettingsState).
  function downloadFonts() {
    var btn = document.getElementById("download-fonts");
    var note = document.getElementById("font-dl-note");
    pywebview.api.download_fonts()
      .then(function(res) {
        if (res === "busy") { setNote(note, t("font.dl.busy")); return; }
        btn.classList.add("busy");
        btn.disabled = true;
        setNote(note, t("font.dl.start"));
      })
      .catch(function(e) {
        btn.classList.remove("busy");
        btn.disabled = false;
        setNote(note, t("font.dl.fail").replace("{names}", String(e)));
      });
  }
  function fontDlState(st) {
    var d = st.fonts_dl;
    if (!d) return;
    var btn = document.getElementById("download-fonts");
    var note = document.getElementById("font-dl-note");
    if (d.downloading) {
      if (btn) { btn.classList.add("busy"); btn.disabled = true; }
      setNote(note, t("font.dl.progress").replace("{pct}", String(Math.round(d.pct || 0))));
    } else if (btn && btn.disabled) {
      btn.classList.remove("busy");
      btn.disabled = false;
      setNote(note, d.error ? t("font.dl.fail").replace("{names}", String(d.error)) : "");
    }
  }
  function openFontsFolder() {
    pywebview.api.open_fonts_folder();
  }

  // -- состояние от главного окна -------------------------------------------
  /* Вызывается из app.js, поэтому здесь нет ни своего get_initial, ни poll():
     окно у приложения одно, и второй опрос того же состояния только путал бы
     счётчики. langPainted нужен, чтобы отличить смену языка (нужна полная
     перерисовка подписей) от обычного обновления значений. */
  function synfSettingsInit(initData) {
    extra = initData || {};
    extra.settings = extra.settings || {};
    uiRev = typeof extra.ui_rev === "number" ? extra.ui_rev : uiRev;
    fontsRev = typeof extra.fonts_rev === "number" ? extra.fonts_rev : fontsRev;
    transAvailability = { ffmpeg: !!extra.ffmpeg, avail: extra.transcoders || [] };
    if (extra.fonts) FONTS = extra.fonts;
    renderWindow();
    // бинды полей делает fieldsMounted (Alpine монтирует панель сам);
    // здесь - то, что требует одновременно данных и полей: при раннем
    // вызове шаги встанут в очередь и отработают сразу после бинда
    whenPanelReady(function() {
      applySettingsI18n();
      fillSettings();
      syncTipForces();
      applyVisibility();
      refreshNotes();
    });
  }

  function synfSettingsState(st) {
    st = st || {};
    if (st.settings) extra.settings = st.settings;
    if (st.lang && st.lang !== curLang) curLang = st.lang;
    if (st.ffmpeg && typeof st.ffmpeg.ok !== "undefined") {
      transAvailability = {ffmpeg: !!st.ffmpeg.ok, avail: transAvailability.avail};
      buildTranscodeOptions();
    }
    if (curLang !== langPainted) {
      // язык сменился: подписи и подсказки обновляет translateStatic
      // (applySettingsI18n) по data-i18n - структуру пересобирать не нужно,
      // узлы те же, а повторный bind задвоил бы слушатели. Проверка на
      // каждый poll() не повторяется: пересборка списков дёргала бы
      // открытый <select> и сбрасывала фокус в поле, где печатают.
      renderWindow();
      whenPanelReady(function() { applySettingsI18n(); });
    }
    fillSettings();
    syncTipForces();
    applyVisibility();
    if (typeof st.ui_rev === "number" && st.ui_rev !== uiRev) {
      uiRev = st.ui_rev;
    }
    if (typeof st.fonts_rev === "number" && st.fonts_rev !== fontsRev) {
      fontsRev = st.fonts_rev;
      reloadFonts();
    }
    fontDlState(st);
  }
