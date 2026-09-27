  /* Окно настроек (ui_src/settings.js).
     Всё содержимое рисуется из схемы (__SETTINGS_SCHEMA__, settings_schema.py):
     список разделов слева, поля справа. Здесь только то, чего схема знать
     не может - что делает кнопка, как поле применяется и чем наполняется
     пояснение. Текстовые поля сохраняются по событию change (потеря фокуса/
     Enter), чтобы не писать в settings.json на каждый символ. */
  var SETTINGS_SCHEMA = __SETTINGS_SCHEMA__;
  var transAvailability = { ffmpeg: true, avail: [] };
  var since = 0;           // курсор журнала: с какого места продолжать
  var LOG_LINES = 2000;    // сколько строк журнала держим
  var LOG_CHARS = 120000;  // порог обрезки без split на каждом poll
  var pollTimer = 0;
  var uiRev = -1;          // счётчик смен языка/темы/шрифтов со стороны Python
  var fontsRev = -1;       // счётчик пересканирования шрифтов
  var activeSection = "";

  var panelFields = {};    // путь настройки -> {spec, nodes, input, range}
  var panelButtons = {};   // id кнопки -> элемент
  var noteFillers = {};    // note_source -> нужно перерисовывать
  var customSave = {};     // путь настройки -> поле со своим обработчиком
  // обёртки (блок .settings-box, строка .range-row) с полями внутри: если все
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

  // Разделы окна: слева кнопки, справа содержимое полей. Внутри раздела рамки
  // блоков и строки собираются теми же правилами, что были у вкладок панели.
  function renderWindow() {
    var nav = document.getElementById("settings-nav");
    var host = document.getElementById("settings-sections");
    nav.innerHTML = "";
    host.innerHTML = "";
    panelWrappers = [];
    SETTINGS_SCHEMA.groups.forEach(function(group, gi) {
      var item = el("button", gi ? "nav-item" : "nav-item active", {type: "button", id: "nav-" + group.id});
      item.appendChild(caption(group.label));
      item.addEventListener("click", function() { switchSection(group.id); });
      nav.appendChild(item);

      var section = el("div", null, {id: "section-" + group.id, role: "tabpanel"});
      if (gi) section.hidden = true;
      var out = [];         // узлы раздела
      var boxNodes = null;  // узлы текущего блока
      var boxKeys = null;   // пути полей блока
      var rowNodes = null;  // узлы текущей строки
      var rowKeys = null;   // пути полей строки
      var rowIdx = null;
      var rowCls = null;
      var boxName = null;
      function wrap(list, node, keys) {
        list.push(node);
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
          var list = boxNodes || out;
          part.nodes.forEach(function(n) { list.push(n); });
        }
        panelFields[key] = {spec: spec, nodes: part.nodes, input: part.input, range: part.range};
      });
      flushBox();
      out.forEach(function(n) { section.appendChild(n); });
      host.appendChild(section);
    });
    activeSection = SETTINGS_SCHEMA.groups.length ? SETTINGS_SCHEMA.groups[0].id : "";
  }

  function switchSection(name) {
    SETTINGS_SCHEMA.groups.forEach(function(group) {
      document.getElementById("section-" + group.id).hidden = group.id !== name;
      document.getElementById("nav-" + group.id).classList.toggle("active", group.id === name);
    });
    activeSection = name;
  }

  // -- списки значений полей -------------------------------------------------
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

  function applyI18n() {
    translateStatic();
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
  }

  // -- команды кнопок и наполнение пояснений --------------------------------
  // В схеме у кнопки есть dom и подпись, здесь - только действие.
  var ACTIONS = {
    "reload-themes": function() { reloadThemes(); },
    "open-themes": function() { openThemesFolder(); },
    "reload-fonts": function() { reloadFonts(); },
    "download-fonts": function() { downloadFonts(); },
    "open-fonts": function() { openFontsFolder(); },
    "browse": async function() {
      var picked = await pywebview.api.browse_folder();
      if (picked) {
        panelFields["ui.dest"].input.value = picked;
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
    var dir = panelFields["ftp.dir"].input.value.trim();
    var note = document.getElementById("ftp-dir-note");
    note.textContent = dir ? t("sheet.ftp.dir.ok") : t("sheet.ftp.dir.empty");
  }

  // -- значения и сохранение -------------------------------------------------
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
        // папка загрузки - не настройка: Python помнит её до конца сеанса
        if (spec.path === "ui.dest") pywebview.api.set_dest(value);
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
    // Рамка блока и строка прячутся, когда скрыты все поля внутри: иначе в
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

  // -- темы и шрифты ---------------------------------------------------------
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
          lbl.textContent = "✓";
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
  // Шрифт применяется подменой блока #fonts-style - без перезагрузки страницы
  // и без потери состояния окна. Главное окно подхватит выбор по ui_rev.
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

  // -- журнал и синхронизация с главным окном -------------------------------
  function scheduleTick(delay) {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(tick, delay);
  }

  async function tick() {
    pollTimer = 0;
    if (typeof pywebview === "undefined") { scheduleTick(300); return; }
    try {
      var st = await pywebview.api.poll_settings(since);
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
      fontDlState(st);
      // Язык, тема или шрифты сменились в этом же окне: главное окно ждёт тот
      // же счётчик, поэтому обновляемся оба.
      if (typeof st.ui_rev === "number" && st.ui_rev !== uiRev) {
        uiRev = st.ui_rev;
        if (st.lang && st.lang !== curLang) {
          curLang = st.lang;
          applyI18n();
        }
        if (st.theme) applyTheme(st.theme);
        loadFontFaces(fontFacesForTheme());
      }
      // Шрифты докачались на стороне Python: перерисовываем списки и @font-face.
      if (typeof st.fonts_rev === "number" && st.fonts_rev !== fontsRev) {
        fontsRev = st.fonts_rev;
        reloadFonts();
      }
    } catch (e) {}
    scheduleTick(400);
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
      renderWindow();
      applyI18n();
      fillSettings(initData.settings, initData);
      applyTheme(themeKey());
      // Поля с собственным поведением помечаются customSave ДО bindSettings(),
      // иначе к теме/языку/шрифтам привяжется ещё и общий обработчик и каждый
      // выбор запишется в settings.json дважды.
      // тема: часть тем со своим entry собирается в Python (полный rebuild
      // обоих окон), остальные применяются на лету
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
          loadFontFaces(fontFacesForTheme());
        }
      });
      onChange("ui.language", function(node, spec) {
        curLang = node.value;
        applyI18n();
        buildFontOptions();   // подпись «системный» в списках шрифтов тоже переводится
        updateThemeMeta();
        applyTheme(themeKey());
        pywebview.api.save_setting(spec.setting, node.value);
      });
      onChange("ui.font_sans", function(node) { setFont("font-sans", node.value); });
      onChange("ui.font_mono", function(node) { setFont("font-mono", node.value); });
      bindSettings();
      applyVisibility();
      refreshNotes();
      document.getElementById("settings-close").addEventListener("click", function() {
        pywebview.api.close_settings();
      });
      document.addEventListener("keydown", function(ev) {
        if (ev.key === "Escape") pywebview.api.close_settings();
      });
    }).catch(function(e) { console.error("init error:", e); });
  }

  if (window.pywebview !== undefined) { init(); }
  else { window.addEventListener("pywebviewready", init); }
  scheduleTick(400);
