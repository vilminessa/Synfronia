  /* Общая часть главного окна и окна настроек (ui_src/common.js).
     Подключается в оба окна, поэтому переводы, палитра темы и шрифты всегда
     ведут себя одинаково: язык, тему и шрифты меняет окно настроек, а главное
     окно подхватывает то же самое по счётчику ui_rev из poll(). */
  var THEMES = __THEMES__;
  var I18N = __I18N__;
  var LANGS = Object.keys(I18N).filter(function(k) { return I18N[k] && I18N[k].thisLang; });
  var curLang = "en";
  // Активная тема. В окне настроек она есть в селекте #theme, в главном окне
  // селекта нет - тема приходит из poll(), поэтому держим её здесь: и applyTheme,
  // и fontFacesForTheme должны знать текущую тему одинаково в обоих окнах.
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

  // Переводы разметки, помеченной data-i18n / data-i18n-title. Списки и
  // подписи полей конкретной страницы дополняют её своими сборщиками.
  function translateStatic() {
    document.querySelectorAll("[data-i18n]").forEach(function(el) {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-title]").forEach(function(el) {
      el.title = t(el.getAttribute("data-i18n-title"));
    });
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

  // @font-face для действующей темы и выбранных шрифтов: нужны обоим окнам,
  // когда шрифт или тема сменились в окне настроек.
  function fontFacesForTheme() {
    var th = THEMES[themeKey()] || {};
    return [th.font, th.font_mono, FONT_PICK.sans, FONT_PICK.mono];
  }
  function themeKey() {
    var sel = document.getElementById("theme");
    return (sel && sel.value) || curTheme || "";
  }
