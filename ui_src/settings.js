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
    // у режима выгрузки подсказка живёт на кнопках-переключателях, иначе она
    // продублировалась бы на подписи и на самих кнопках
    if (spec.title && spec.type !== "choice_buttons") {
      node.setAttribute("data-i18n-tip", spec.title);
      setTip(node, t(spec.title));
    }
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
      var check = el("div", "check");
      var box = el("input", null, {type: "checkbox", id: spec.dom});
      check.appendChild(box);
      check.appendChild(caption(spec.label));
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
        if (spec.title) {
          b.setAttribute("data-i18n-tip", spec.title);
          setTip(b, t(spec.title));
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
  // своей иконки нет, и голый значок был бы непонятен.
  function renderButton(b) {
    var svg = b.icon ? iconSvg(b.icon) : "";
    var btn = el("button", svg ? "act-btn ico-" + b.icon : null,
                 {type: "button", id: b.dom, "data-i18n-tip": b.label});
    if (svg) {
      var ico = el("span", "ico");
      ico.innerHTML = svg;
      btn.appendChild(ico);
      setTip(btn, t(b.label));
    } else {
      btn.appendChild(caption(b.label));
    }
    panelButtons[b.dom] = btn;
    return btn;
  }

  // Разделы карточки: слева кнопки, справа содержимое полей. Внутри раздела
  // карточки и строки собираются теми же правилами, что были у вкладок панели:
  // поля одного блока (box) попадают в одну карточку, поля с одинаковым row -
  // в одну строку.
  function renderWindow() {
    hideTip();
    var nav = document.getElementById("settings-nav");
    var host = document.getElementById("settings-sections");
    if (!nav || !host) return;
    nav.innerHTML = "";
    host.innerHTML = "";
    panelFields = {};
    panelButtons = {};
    panelWrappers = [];
    customSave = {};
    var groups = SETTINGS_SCHEMA.groups.filter(function(group) {
      return group.in_panel !== false && (group.fields || []).length;
    });
    groups.forEach(function(group, gi) {
      var item = el("button", gi ? "nav-item" : "nav-item active", {type: "button", id: "nav-" + group.id});
      item.appendChild(caption(group.label));
      item.setAttribute("data-i18n-tip", group.label);
      setTip(item, t(group.label));
      item.addEventListener("click", function() { switchSection(group.id); });
      nav.appendChild(item);

      var section = el("div", null, {id: "section-" + group.id, role: "tabpanel"});
      if (gi) section.hidden = true;
      var out = [];        // карточки раздела: то, что уходит в section
      var cardEls = {};    // имя блока -> карточка (одна на блок, не на поле)
      var cur = null;      // текущий блок: с названием (body) или без него
      var rowNodes = null; // узлы текущей строки
      var rowKeys = null;  // пути полей строки
      var rowIdx = null;
      var rowCls = null;
      function wrap(list, node, keys) {
        list.push(node);
        panelWrappers.push({el: node, keys: keys});
      }
      // Смена блока: закрываем предыдущий и открываем новый. Поля копятся в
      // cur.nodes, а в раздел попадают при flush() - иначе пришлось бы держать
      // два разных «списка» (массив без названия и <div> тела карточки).
      function openBlock(name) {
        flush();
        if (!name) { cur = {name: null, nodes: [], keys: []}; return; }
        if (!cardEls[name]) {
          var body = el("div", "field-card-body");
          var box = el("div", "field-card", [caption(group.boxes[name], "field-card-title"), body]);
          cardEls[name] = {name: name, el: box, body: body, keys: [], nodes: []};
          wrap(out, box, cardEls[name].keys);
        }
        cardEls[name].nodes = [];
        cur = cardEls[name];
      }
      function flushRow() {
        if (!rowNodes || !cur) return;
        var row = el("div", rowCls, rowNodes);
        cur.nodes.push(row);
        panelWrappers.push({el: row, keys: rowKeys});
        rowNodes = rowKeys = null;
        rowIdx = rowCls = null;
      }
      function flush() {
        flushRow();
        if (!cur) return;
        if (cur.body) {
          // блок без полей (все его поля in_panel: false) в раздел не идёт -
          // иначе в разделе висит рамка с заголовком и пустотой внутри
          if (!cur.nodes.length) cur.el.remove();
          else cur.nodes.forEach(function(n) { cur.body.appendChild(n); });
        } else if (cur.nodes.length) {
          wrap(out, el("div", "field-card", [el("div", "field-card-body", cur.nodes)]), cur.keys);
        }
        cur = null;
      }
      group.fields.forEach(function(spec) {
        if (spec.in_panel === false) return;
        if (!cur || (spec.box || null) !== cur.name) openBlock(spec.box || null);
        var part = renderField(spec);
        // у блока кнопок нет ни path, ни dom: его узлы в раздел попадают, но в
        // panelFields ему нечего положить, иначе ключом станет "undefined"
        var key = spec.path || spec.dom;
        if (key) cur.keys.push(key);
        if (spec.row !== undefined && spec.row !== null) {
          // поля с одинаковым row встают в одну строку (label + input)
          if (rowNodes && spec.row !== rowIdx) flushRow();
          if (!rowNodes) { rowNodes = []; rowKeys = []; rowIdx = spec.row; rowCls = spec.row_class || "range-row"; }
          if (key) rowKeys.push(key);
          part.nodes.forEach(function(n) { rowNodes.push(n); });
        } else {
          flushRow();
          part.nodes.forEach(function(n) { cur.nodes.push(n); });
        }
        if (key) {
          panelFields[key] = {spec: spec, nodes: part.nodes, input: part.input,
                               range: part.range, get: part.get, set: part.set};
        }
      });
      flush();
      out.forEach(function(n) { section.appendChild(n); });
      host.appendChild(section);
    });
    activeSection = groups.length ? groups[0].id : "";
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
    updateThemeMeta();
  }

  // Метаданные темы (автор/версия) и предупреждения валидации theme.json.
  function updateThemeMeta() {
    var box = document.getElementById("theme-meta");
    if (!box) return;
    var sel = document.getElementById("theme");
    var th = THEMES[(sel && sel.value) || ""] || {};
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
      } else if (missing.length) {
        note.textContent = t("trans.note.missing") + missing.join(", ") + ".";
      } else {
        note.textContent = "";
      }
    }
  }
  function buildLangOptions() {
    fillSelect("lang", LANGS.map(function(k) { return [k, I18N[k]["thisLang"]]; }));
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
        panelFields["ui.dest"].set(picked);
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
  var NOTE_FILLERS = {ftpDirNote: updateFtpDirNote};
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
  function saveValue(key, value) {
    var spec = panelFields[key].spec;
    if (spec.setting) pywebview.api.save_setting(spec.setting, value);
    // папка загрузки - не настройка: Python помнит её до конца сеанса
    if (spec.path === "ui.dest") pywebview.api.set_dest(value);
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
      updateThemeMeta();
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
      updateThemeMeta();
      applyTheme(themeKey());
      pywebview.api.save_setting(spec.setting, node.value);
    });
    onChange("ui.font_sans", function(node) { setFont("font-sans", node.value); });
    onChange("ui.font_mono", function(node) { setFont("font-mono", node.value); });
  }

  // -- темы и шрифты ---------------------------------------------------------
  function reloadThemes() {
    var btn = document.getElementById("reload-themes");
    pywebview.api.reload_themes().then(function(newThemes) {
      THEMES = newThemes;
      buildThemeOptions();
      fillSettings();
      updateThemeMeta();
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
    var slot = id === "font-mono" ? "mono" : "sans";
    pywebview.api.set_font(id === "font-mono" ? "font_mono" : "font_sans", value)
      .then(function(r) {
        if (r && r.error) { console.error("set font:", r.error); return; }
        FONT_PICK[slot] = value || "";
        if (r && r.css !== undefined) applyFontCss(r.css);
        var th = THEMES[themeKey()] || {};
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
    bindCustom();
    bindSettings();
    applySettingsI18n();
    fillSettings();
    applyVisibility();
    refreshNotes();
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
      // язык сменился: разметка с подписями и подсказками строится заново.
      // На каждый poll() это не повторяем - пересборка списков дёргала бы
      // открытый <select> и сбрасывала бы фокус в поле, где печатают.
      renderWindow();
      bindCustom();
      bindSettings();
      applySettingsI18n();
    }
    fillSettings();
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
