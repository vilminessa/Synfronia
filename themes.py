r"""Модульные темы и сборка страницы.

Каждая тема — подпапка в %LOCALAPPDATA%\Synfronia\themes:
theme.json (палитра/мета/extends/entry), custom.css, slots/*.html,
ресурсы (url(...) и {{asset:rel}} -> data:URI). Из этого собирается
итоговый HTML: build_page() наполняет __THEME_ROOT__/__THEME_CSS__/
__UTIL_CSS__/__APP_CSS__/__MAIN_CSS__/__SETTINGS_CSS__/__COMMONJS__/__MOTION__/__APPJS__/
__SETTINGS_JS__/__ALPINE__/__I18N__/__THEMES__/__SETTINGS_SCHEMA__ в ui.BASE_TEMPLATE.
Карточка настроек (ui.SETTINGS_HTML) — часть этой же страницы: отдельного
окна настроек больше нет, а если тема собрала страницу из своего entry без
оверлея, _ensure_settings() вставляет его обратно.
"""

import base64
import json
import os
import re
from pathlib import Path

import settings_schema
import ui as _ui
from version import BUILD_LABEL, __version__

from i18n import I18N
from fonts import _clean_family, families as _loaded_families, font_css, font_vars, load_fonts
from paths import _file_log, base_dir


# -- темы --------------------------------------------------------------------
# Поля темы: label (название), цвета палитры bg/surface/widget/text/accent/warn,
# ok (успех) и err (ошибка) — их используют состояния строк массовой
# загрузки, opacity (общая прозрачность интерфейса 0..1), радиусы скругления
# radius_s / radius_m / radius_l (px), hidden (скрыть из списка).
# Значения — дефолты; пользователь правит копии в
# %LOCALAPPDATA%\Synfronia\themes\{имя_темы}\theme.json.
_THEME_DEFAULTS = {
    "warn": "#ffb454",
    "ok": "#3fbf6b",
    "err": "#e0554f",
    "opacity": 1.0,
    "radius_s": 6,
    "radius_m": 8,
    "radius_l": 12,
}
THEMES = {
    "technology_day": {
        "label": "Technology day",
        "bg": "#01282c",
        "surface": "#00585a",
        "widget": "#003638",
        "text": "#dcdedd",
        "accent": "#00989b",
        "ok": "#3fd994",
        "err": "#ff6b61",
        **_THEME_DEFAULTS,
    },
    "technology_pinks": {
        "label": "Technology Pinks",
        "bg": "#ffebec",
        "surface": "#ffcbe2",
        "widget": "#ffffff",
        "text": "#5d2547",
        "accent": "#c15f9b",
        "ok": "#2fae5e",
        "err": "#d64545",
        **_THEME_DEFAULTS,
    },
    "scarred_mind": {
        "label": "Scarred Mind",
        "bg": "#252b47",
        "surface": "#2f3b65",
        "widget": "#1e2542",
        "text": "#b9c2d6",
        "accent": "#f1b970",
        "ok": "#5ecf8f",
        "err": "#ff7066",
        **_THEME_DEFAULTS,
    },
    "audrey_main": {
        "label": "Audrey Main Colours",
        "bg": "#fff5f0",
        "surface": "#f9f9f9",
        "widget": "#ededed",
        "text": "#5d5d5d",
        "accent": "#96af9b",
        "ok": "#4a9d6a",
        "err": "#cc4d4d",
        **_THEME_DEFAULTS,
    },
    "night_sky": {
        "label": "Basic Night Sky",
        "bg": "#373051",
        "surface": "#483a5f",
        "widget": "#323756",
        "text": "#fffedd",
        "accent": "#fff2c9",
        "ok": "#7fd99a",
        "err": "#ff7a6e",
        **_THEME_DEFAULTS,
    },
    "liquid_glass": {
        "label": "Liquid Glass",
        "bg": "#142244",
        "surface": "#1f345a",
        "widget": "#16223d",
        "text": "#e9f1ff",
        "accent": "#69c1ff",
        "ok": "#4fd08a",
        "err": "#ff6b7a",
        "opacity": 1.0,
        "radius_s": 12,
        "radius_m": 18,
        "radius_l": 26,
    },
}


# -- внешние темы (папки в %LOCALAPPDATA%\Synfronia\themes) ------------------
# Каждая тема — отдельная подпапка {theme_id}/ с файлами:
#   theme.json   — палитра/прозрачность/скругление (поля см. THEMES выше);
#   custom.css   — дополнительный CSS темы (можно менять фон элементов,
#                  подставлять картинки: url("bg.png"), url("anim.gif") и т.д.);
#   любые файлы  — ресурсы темы, на них ссылаются относительными url(...).
# Имя файла CSS можно переопределить полем "css" в theme.json.
_THEME_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")

_THEME_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}

_BASE_CSS = (
    "/* Дополнительный CSS темы. Ресурсы темы кладите рядом и подключайте "
    "относительно: url(\"bg.png\"), url(\"anim.gif\"). */\n"
)


# Liquid Glass: CSS встроенной темы. Лежит здесь, а не в папке тем,
# чтобы новая установка сразу получила тему; _SEED_CSS раскладывает его
# в %LOCALAPPDATA%\Synfronia\themes\liquid_glass\custom.css (правки
# пользователя не перезаписываются). Идея и рецепт — MIT, FreeFrontend:
#   · Liquid Glass Distortion Card (igcorreia, 2026) — SVG-дисплейсмент;
#   · Liquid Toggle Switch (jh3y, 2025) — «капсульный» переключатель.
_LIQUID_GLASS_FILTER = (
    "data:image/svg+xml;base64,"
    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxmaWx0ZXIgaWQ9"
    "ImxnIiB4PSItMzAlIiB5PSItMzAlIiB3aWR0aD0iMTYwJSIgaGVpZ2h0PSIxNjAlIiBj"
    "b2xvci1pbnRlcnBvbGF0aW9uLWZpbHRlcnM9InNSR0IiPjxmZVR1cmJ1bGVuY2UgdHlw"
    "ZT0iZnJhY3RhbE5vaXNlIiBiYXNlRnJlcXVlbmN5PSIwLjAxMiAwLjA4IiBudW1PY3Rh"
    "dmVzPSIyIiBzZWVkPSI0IiByZXN1bHQ9IndhcnAiLz48ZmVEaXNwbGFjZW1lbnRNYXAg"
    "aW49IlNvdXJjZUdyYXBoaWMiIGluMj0id2FycCIgc2NhbGU9IjI2IiB4Q2hhbm5lbFNl"
    "bGVjdG9yPSJSIiB5Q2hhbm5lbFNlbGVjdG9yPSJHIiByZXN1bHQ9ImRpc3AiLz48ZmVH"
    "YXVzc2lhbkJsdXIgaW49ImRpc3AiIHN0ZERldmlhdGlvbj0iNyIvPjwvZmlsdGVyPjwv"
    "c3ZnPg=="
)

_LIQUID_GLASS_CSS = r"""/*
   Liquid Glass — «жидкое стекло» поверх анимированной «воды».

   Вдохновлено подборкой FreeFrontend «CSS Liquid Glass» (примеры MIT):
   · Liquid Glass Distortion Card (igcorreia, 2026) — SVG-дисплейсмент
     фона и многослойные inset-блики на кромке стекла;
   · Liquid Toggle Switch (jh3y, 2025) — капсульные «жидкие» переключатели;
   · Liquid Glass Effect (cubiq, 2025) — турбулентность и движение за стеклом.
*/

:root {
  --lg-tint: rgba(16, 30, 58, .46);
  --lg-tint-deep: rgba(10, 20, 44, .52);
  --lg-line: rgba(255, 255, 255, .14);
  --lg-line-strong: rgba(255, 255, 255, .24);
  --lg-shadow: 0 10px 30px rgba(0, 0, 0, .35);
  --lg-inset: inset 0 1px 0 rgba(255, 255, 255, .16), inset 0 -10px 22px rgba(0, 0, 0, .22);
}

/* --- Liquid Glass: «жидкое стекло», тёмное окно. Дождь удалён в v1.2.6:
   GPU-слой капель рендерился с «провисаниями» и швами на этом движке,
   поэтому Слой-Дождь вырезан полностью. Осталась чистая стеклянная тема. */
html, body { background-color: #05080f; }
html { background-color: #05080f; }
body { background: transparent; background-attachment: fixed; }

/* --- фоновая сцена темы: Дождь ⇄ Огонь. Только обычный CSS, БЕЗ GPU-слоёв
   (нет translate3d / will-change / canvas): анимация — исключительно
   background-position по бесшовным целочисленным тайлам, поэтому на любом
   планшете/телефоне считается дёшево и без «провисаний».
   Режим: body[data-bg="rain"] (по умолчанию) или body[data-bg="fire"].
   «Разгорание» огня крутит ползунок → CSS-переменная --lg-heat (0..1). */
body[data-bg="rain"]::before,
body[data-bg="fire"]::before,
body[data-bg="fire"]::after {
  content: "";
  position: fixed;
  top: -10%; bottom: -10%; left: -12%; right: -12%;
  z-index: -1;
  pointer-events: none;
}

/* --- Дождь за стеклом (референс freefrontend aickle/XKjMZY «Rain»,
       техника переписана самостоятельно): наклонные ленты linear-gradient,
       тайл 94x1220 — перевод ровно на высоту тайла даёт бесшовный цикл. --- */
body[data-bg="rain"]::before {
  background-image:
    linear-gradient(118deg,
      rgba(190, 220, 255, 0) 0%, rgba(190, 220, 255, .10) 3.2%, rgba(190, 220, 255, .04) 4.6%, rgba(190, 220, 255, 0) 6%,
      rgba(190, 220, 255, 0) 49%, rgba(190, 220, 255, .085) 52.2%, rgba(190, 220, 255, .035) 53.6%, rgba(190, 220, 255, 0) 55%);
  background-size: 94px 1220px;
  background-repeat: repeat;
  background-position: 0 0;
  animation: lg-rain-shift 3.4s linear infinite;
  opacity: .5;
}
@keyframes lg-rain-shift {
  from { background-position: 0 0; }
  to   { background-position: 0 -1220px; }   /* бесшовно: ровно одна высота тайла */
}

/* --- Огонь (референс freefrontend freedommayer/vYRmarM «Pixel Fire»,
       техника переписана самостоятельно): языки пламени radial-gradient +
       бесшовный тайл искр; разгорание масштабирует прозрачность. --- */
body[data-bg="fire"]::before {
  background-color: #1a0c04;
  background-image:
    radial-gradient(52% 78% at 22% 110%, rgba(255, 190, 40, .60) 0%, rgba(255, 110, 20, .38) 42%, rgba(255, 70, 10, 0) 78%),
    radial-gradient(58% 84% at 64% 112%, rgba(255, 205, 46, .55) 0%, rgba(255, 130, 24, .44) 46%, rgba(255, 80, 12, 0) 82%),
    radial-gradient(42% 62% at 88% 106%, rgba(255, 176, 34, .46) 0%, rgba(255, 96, 16, .32) 52%, rgba(200, 40, 4, 0) 78%);
  background-size: 340px 620px, 400px 690px, 300px 540px;
  background-repeat: repeat;
  background-position: 0 0;
  animation: lg-fire-linger 5.4s ease-in-out infinite;
  opacity: calc(.55 + var(--lg-heat, .62) * .45);
}
@keyframes lg-fire-linger {
  0%, 100% { background-position: 0 0, 0 0, 0 0; }
  50%      { background-position: -14px -28px, 10px -18px, -6px 0; }
}
body[data-bg="fire"]::after {
  background-image:
    radial-gradient(6px 26px at 22px 26px, rgba(255, 235, 140, .70) 0 12%, rgba(255, 160, 40, 0) 55%),
    radial-gradient(4px 16px at 68px 50px, rgba(255, 210, 90, .5) 0 10%, rgba(255, 140, 30, 0) 55%);
  background-size: 90px 90px;      /* бесшовный тайл искр */
  background-repeat: repeat;
  background-position: 0 0;
  animation: lg-ember-rise 4.2s linear infinite;
  opacity: calc(.42 + var(--lg-heat, .62) * .58);
}
@keyframes lg-ember-rise {
  from { background-position: 0 0; }
  to   { background-position: 0 -90px; }   /* ровно одна высота тайла — бесшовно */
}





/* --- капсульные стеклянные элементы управления --- */
.tab, .clicker, .icon-btn,
#download, #stop, #browse, #settings-close {
  position: relative;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(22, 38, 72, .26);
  -webkit-backdrop-filter: blur(14px) saturate(1.6);
  backdrop-filter: blur(14px) saturate(1.6);
  border: 1px solid var(--lg-line);
  box-shadow: var(--lg-inset), var(--lg-shadow);
  color: var(--text);
  transition: transform .16s ease, background .25s ease, border-color .25s ease,
              box-shadow .25s ease, color .25s ease;
}
.tab:hover, .clicker:hover, .icon-btn:hover,
#download:hover, #stop:hover, #browse:hover, #settings-close:hover {
  background: rgba(34, 58, 104, .55);
  border-color: var(--lg-line-strong);
  box-shadow: var(--lg-inset), 0 12px 34px rgba(0, 0, 0, .42),
              0 0 0 1px rgba(105, 193, 255, .20);
  transform: translateY(-1px);
}
.tab:active, .clicker:active, .icon-btn:active,
#download:active, #stop:active, #browse:active, #settings-close:active {
  transform: scale(.94);
}

/* жидкий блик, пробегающий по поверхности при наведении */
.tab::after, .clicker::after, .icon-btn::after,
#download::after, #stop::after, #browse::after, #settings-close::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  background: linear-gradient(120deg, transparent 32%, rgba(255, 255, 255, .22) 50%, transparent 68%);
  transform: translateX(-130%) skewX(-18deg);
  transition: transform .7s ease;
}
.tab:hover::after, .clicker:hover::after, .icon-btn:hover::after,
#download:hover::after, #stop:hover::after, #browse:hover::after, #settings-close:hover::after {
  transform: translateX(130%) skewX(-18deg);
}

/* главное действие — «заливка» жидкого акцента */
#download {
  background: linear-gradient(135deg, rgba(66, 176, 255, .85), rgba(122, 96, 255, .82));
  color: #fff;
  border-color: transparent;
  text-shadow: 0 1px 10px rgba(8, 30, 70, .45);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .45), inset 0 -10px 22px rgba(0, 40, 110, .35),
              0 10px 30px rgba(70, 150, 255, .45);
}
#download:hover {
  background: linear-gradient(135deg, rgba(80, 190, 255, .92), rgba(134, 108, 255, .90));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .55), inset 0 -10px 22px rgba(0, 40, 110, .30),
              0 14px 40px rgba(80, 170, 255, .55);
}

/* активная вкладка — «жидкая пилюля» с дыханием */
.tab.active {
  background: linear-gradient(135deg, rgba(80, 190, 255, .95), rgba(132, 100, 255, .92));
  color: #fff;
  border-color: rgba(255, 255, 255, .35);
  text-shadow: 0 1px 10px rgba(8, 30, 70, .45);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .5), inset 0 -10px 22px rgba(0, 40, 120, .35),
              0 8px 26px rgba(80, 160, 255, .5);
  animation: lg-breathe 3.2s ease-in-out infinite;
}
@keyframes lg-breathe {
  0%, 100% {
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, .5), inset 0 -10px 22px rgba(0, 40, 120, .35),
                0 8px 26px rgba(80, 160, 255, .5);
    transform: scale(1);
  }
  50% {
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, .6), inset 0 -10px 22px rgba(0, 40, 120, .35),
                0 12px 44px rgba(120, 140, 255, .75);
    transform: scale(1.02);
  }
}

/* --- поля --- */
input[type=text], select, input[type=number] {
  background: rgba(10, 20, 42, .31);
  -webkit-backdrop-filter: blur(12px) saturate(1.5);
  backdrop-filter: blur(12px) saturate(1.5);
  border: 1px solid var(--lg-line);
  border-radius: 16px;
  box-shadow: inset 0 2px 10px rgba(0, 0, 0, .30), inset 0 1px 0 rgba(255, 255, 255, .06);
  transition: border-color .2s ease, box-shadow .2s ease, background .2s ease;
}
input[type=text]:focus, select:focus, input[type=number]:focus {
  border-color: rgba(105, 193, 255, .8);
  background: rgba(14, 28, 56, .55);
  box-shadow: inset 0 2px 10px rgba(0, 0, 0, .28), 0 0 0 3px rgba(105, 193, 255, .18);
}
/* --- выпадающие списки: убираем серую нативную стрелку, рисуем свою ---
   (option/optgroup — тёмное стекло с жидкими бликами) */
select {
  color-scheme: dark;
  appearance: none;
  -webkit-appearance: none;
  padding-right: 36px;
  cursor: pointer;
  background-image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='10' viewBox='0 0 14 10'%3E%3Cpath d='M1 1l6 7 6-7' fill='none' stroke='%238fd4ff' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 14px center;
  background-size: 14px 10px;
  transition: border-color .2s ease, box-shadow .2s ease, background-color .2s ease;
}
select:hover { border-color: rgba(105, 193, 255, .55); }
select option, select optgroup {
  background: rgba(10, 16, 32, .96);
  color: #d6eaff;
}
select option:checked {
  background: linear-gradient(90deg, rgba(70, 140, 230, .9), rgba(120, 120, 255, .9));
  color: #fff;
}
select option:hover, select option:focus {
  background: linear-gradient(90deg, rgba(70, 150, 255, .7), rgba(120, 150, 255, .7));
  color: #fff;
}
select optgroup {
  color: #9fd4ff;
  font-style: normal;
  font-weight: 600;
}

/* --- шапка --- (полупрозрачное стекло: сквозь него виден дождь) */
.head {
  padding: 10px 12px;
  border-radius: 22px;
  background: rgba(14, 26, 56, .13);
  -webkit-backdrop-filter: blur(14px) saturate(1.5);
  backdrop-filter: blur(14px) saturate(1.5);
  border: 1px solid var(--lg-line);
  box-shadow: var(--lg-inset), var(--lg-shadow);
}
.logo { text-shadow: 0 0 14px rgba(80, 190, 255, .55), 0 0 34px rgba(120, 120, 255, .35),
              2px 0 0 rgba(255, 70, 90, .28), -2px 0 0 rgba(90, 200, 255, .30); }
.sub { opacity: .55; }

/* --- стекло журнала (панель настроек теперь отдельное окно) --- */
#log {
  -webkit-backdrop-filter: blur(26px) saturate(1.5);
  backdrop-filter: blur(26px) saturate(1.5);
}
/* где поддерживаются SVG-фильтры — добавляем настоящую «жидкую» рефракцию
   (feTurbulence -> feDisplacementMap -> feGaussianBlur) */
@supports (backdrop-filter: url("data:image/svg+xml")) {
  #log {
    -webkit-backdrop-filter: url("data:image/svg+xml;base64,__LG_FILTER__") saturate(1.55);
    backdrop-filter: url("data:image/svg+xml;base64,__LG_FILTER__") saturate(1.55);
  }
}
.overlay {
  background: rgba(4, 8, 18, .5);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
}

/* --- вложенное стекло --- */
.settings-box {
  background: rgba(20, 36, 70, .26);
  border: 1px solid var(--lg-line);
  border-radius: 20px;
  -webkit-backdrop-filter: blur(12px) saturate(1.4);
  backdrop-filter: blur(12px) saturate(1.4);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .10), inset 0 -8px 18px rgba(0, 0, 0, .18);
}
.settings-box-title { color: rgba(233, 241, 255, .6); }

/* --- журнал --- */
#log {
  background: rgba(10, 20, 44, .34);
  border: 1px solid var(--lg-line);
  border-radius: 22px;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, .07),
    inset 0 0 14px rgba(255, 255, 255, .04),
    inset 0 22px 40px rgba(0, 0, 0, .22),
    0 18px 40px rgba(0, 0, 0, .40);
}
#log::-webkit-scrollbar { width: 10px; }
#log::-webkit-scrollbar-track { background: rgba(255, 255, 255, .04); border-radius: 8px; }
#log::-webkit-scrollbar-thumb {
  background: linear-gradient(rgba(80, 180, 255, .5), rgba(130, 100, 255, .5));
  border-radius: 8px;
  border: 2px solid rgba(10, 20, 44, .6);
}
#log::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(rgba(80, 190, 255, .7), rgba(140, 110, 255, .7));
}

/* --- прогресс --- */
#status { color: rgba(233, 241, 255, .8); }
.pb-wrap {
  height: 14px;
  background: rgba(10, 20, 42, .45);
  -webkit-backdrop-filter: blur(8px) saturate(1.4);
  backdrop-filter: blur(8px) saturate(1.4);
  border: 1px solid var(--lg-line);
  border-radius: 999px;
  box-shadow: inset 0 2px 6px rgba(0, 0, 0, .45), inset 0 1px 0 rgba(255, 255, 255, .05);
}
#pb {
  background: linear-gradient(90deg, #45b8ff, #9b6bff, #3de1f0, #45b8ff);
  background-size: 300% 100%;
  border-radius: 999px;
  box-shadow: 0 0 16px rgba(80, 170, 255, .55), inset 0 1px 0 rgba(255, 255, 255, .55);
  animation: lg-flow 3s linear infinite;
}
#pb.indeterminate { animation: slide 1.2s infinite, lg-flow 3s linear infinite; }
@keyframes lg-flow {
  from { background-position: 0% 0; }
  to   { background-position: -300% 0; }
}

/* --- кликер: упругая капля при нажатии --- */
.clicker { min-width: 150px; height: 48px; font-size: 16px; }
.clicker.pressed { animation: lg-squish .18s ease; }
@keyframes lg-squish {
  0%   { transform: scale(1); }
  40%  { transform: scale(.82) rotate(-2deg); }
  70%  { transform: scale(1.06) rotate(1deg); }
  100% { transform: scale(1); }
}

#warn {
  border-radius: 14px;
  background: rgba(255, 180, 84, .12);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
}
::selection { background: rgba(105, 193, 255, .30); }

@media (prefers-reduced-motion: reduce) {
  body::before, .tab.active, #pb, .clicker, .logo { animation: none !important; }
  .tab:hover, .clicker:hover, .icon-btn:hover,
  #download:hover, #stop:hover, #browse:hover, #settings-close:hover { transform: none; }
  *::after { transition: none !important; }
}
"""

_LIQUID_GLASS_CSS = _LIQUID_GLASS_CSS.replace("__LG_FILTER__", _LIQUID_GLASS_FILTER)

_SEED_CSS: dict[str, str] = {"liquid_glass": _LIQUID_GLASS_CSS}

_URLEX = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)"'\s][^)"']*))\s*\)""")

# Ассеты в шаблоне HTML темы: {{asset:relpath}} -> data:URI.
_ASSET_RE = re.compile(r"\{\{asset:([^}]*)\}\}")
# Секции базового шаблона: <!-- SLOT:name --> ... <!-- /SLOT:name -->
_SLOT_RE = re.compile(r"<!-- SLOT:([a-z0-9_-]+) -->(.*?)<!-- /SLOT:\1 -->", re.S)
_PALETTE_FIELDS = (
    "bg", "surface", "widget", "text", "accent", "warn", "ok", "err",
    "opacity", "radius_s", "radius_m", "radius_l",
)
_THEME_META_FIELDS = (
    "label", "extends", "entry", "css", "author", "version", "hidden",
    "font", "font_mono",
)


# -- валидация theme.json ----------------------------------------------------
# Значения из theme.json попадают прямо в <style> собранной страницы, поэтому
# проверяем их строго: невалидное значение отбрасывается (theme наследует
# значение родителя или значение по умолчанию), а тема помечается
# предупреждением — оно попадает в лог и в список тем в UI (значок ⚠).
_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\Z")
_FUNC_COLOR_RE = re.compile(r"(?:rgb|rgba|hsl|hsla)\([0-9a-z.,%/\s-]{1,64}\)\Z")
_COLOR_WORDS = frozenset((
    "transparent", "currentcolor", "inherit", "initial", "unset", "none",
    "black", "white", "red", "green", "blue", "yellow", "orange", "purple",
    "gray", "grey", "silver", "maroon", "olive", "lime", "aqua", "teal",
    "navy", "fuchsia", "pink", "brown", "beige", "gold", "cyan", "magenta",
))
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_RADIUS = 64.0
_MAX_TEXT = 80


def _clean_text(value, limit: int = _MAX_TEXT) -> str:
    """Строка без управляющих символов, обрезанная до limit."""
    return _CONTROL_RE.sub(" ", str(value)).strip()[:limit]


def _clean_color(value) -> str | None:
    """Цвет для CSS-переменной: #hex, rgb()/hsl() или имя из списка."""
    text = _clean_text(value, 80).replace(" ", "")
    if not text:
        return None
    low = text.lower()
    if _HEX_COLOR_RE.match(text) or _FUNC_COLOR_RE.match(low) or low in _COLOR_WORDS:
        return text
    return None


def _clean_number(value, lo: float, hi: float, digits: int = 3) -> float | None:
    """Число в диапазоне [lo, hi] с клампингом; None для мусора/NaN/inf."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num or num in (float("inf"), float("-inf")):
        return None
    return round(min(max(num, lo), hi), digits)


def _clean_relpath(value, suffix: str) -> str | None:
    """Относительный путь внутри папки темы (без .., диска и ведущих /)."""
    text = _clean_text(value, 120).replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return None
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    rel = "/".join(parts)
    return rel if rel.lower().endswith(suffix) else None


def _palette_defaults() -> dict:
    """Значения палитры по умолчанию (встроенная тема + _THEME_DEFAULTS)."""
    base = dict(_THEME_DEFAULTS)
    base.update({f: v for f, v in THEMES["scarred_mind"].items() if f in _PALETTE_FIELDS})
    return base


def validate_theme(data: dict) -> tuple[dict, list[str]]:
    """Проверяет содержимое theme.json.

    Возвращает (безопасная спецификация, список предупреждений). Невалидные
    значения не копируются — тема наследует их от родителя или от дефолтов.
    """
    spec: dict = {}
    warn: list[str] = []

    for field in _PALETTE_FIELDS:
        value = data.get(field)
        if value is None:
            continue
        if field == "opacity":
            num = _clean_number(value, 0.0, 1.0)
            if num is None:
                warn.append(f"{field}: не число ({value!r})")
                continue
            if not 0.0 <= float(value) <= 1.0:
                warn.append(f"{field}: {value} → {num}")
            spec[field] = num
        elif field.startswith("radius"):
            num = _clean_number(value, 0.0, _MAX_RADIUS, digits=2)
            if num is None:
                warn.append(f"{field}: не число ({value!r})")
                continue
            if not 0.0 <= float(value) <= _MAX_RADIUS:
                warn.append(f"{field}: {value} → {num}")
            spec[field] = num
        else:
            color = _clean_color(value)
            if color is None:
                warn.append(f"{field}: некорректный цвет ({value!r})")
                continue
            if color.lower() != str(value).strip().lower():
                warn.append(f"{field}: {value!r} → {color}")
            spec[field] = color

    for field in ("label", "author", "version"):
        text = _clean_text(data.get(field) or "")
        if text:
            spec[field] = text
        elif field in data and data[field] is not None:
            warn.append(f"{field}: пустое значение")

    for field in ("font", "font_mono"):
        if data.get(field):
            family = _clean_family(data[field])
            if family:
                spec[field] = family
                known = _loaded_families()
                # проверяем только если шрифты уже просканированы (иначе молчим)
                if known and family not in known:
                    warn.append(f"{field}: семейство «{family}» не найдено в папке fonts")
            else:
                warn.append(f"{field}: некорректное имя шрифта ({data[field]!r})")

    parent = data.get("extends")
    if parent:
        text = _clean_text(parent, 40)
        if _THEME_ID_RE.fullmatch(text):
            spec["extends"] = text
        else:
            warn.append(f"extends: некорректный id ({parent!r})")

    entry = data.get("entry")
    if entry:
        rel = _clean_relpath(entry, ".html")
        if rel:
            spec["entry"] = rel
        else:
            warn.append(f"entry: недопустимый путь ({entry!r})")

    css = data.get("css")
    if css:
        files = [css] if isinstance(css, str) else list(css) if isinstance(css, (list, tuple)) else []
        cleaned: list[str] = []
        for item in files:
            rel = _clean_relpath(item, ".css")
            if rel:
                cleaned.append(rel)
            else:
                warn.append(f"css: недопустимый путь ({item!r})")
        if cleaned:
            spec["css"] = cleaned

    hidden = data.get("hidden")
    if hidden is not None:
        spec["hidden"] = hidden if isinstance(hidden, bool) else _clean_text(hidden, 8).lower() in (
            "1", "true", "yes", "on",
        )

    return spec, warn


def _fill_palette(theme: dict) -> dict:
    """Добирает отсутствующие поля палитры значениями по умолчанию."""
    for field, value in _palette_defaults().items():
        if theme.get(field) is None:
            theme[field] = value
    return theme


def _themes_root() -> Path:
    r"""Папка тем: %LOCALAPPDATA%\Synfronia\themes."""
    base = os.environ.get("LOCALAPPDATA") or str(base_dir())
    return Path(base) / "Synfronia" / "themes"


_LOADED_THEMES: dict[str, dict] | None = None


def _asset_data_uri(path: Path) -> str | None:
    """Превращает локальный файл темы (png/gif/jpg/…) в data:URI."""
    mime = _THEME_MIME.get(path.suffix.lower())
    if mime is None:
        return None
    try:
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def _process_theme_css(css: str, folder: Path) -> str:
    """Подставляет локальные файлы темы в url(...) как data:URI.

    Относительные url(имя.расширение) резолвятся внутри папки темы и
    встраиваются в CSS; абсолютные (http/https/data://, пути с диском)
    остаются как есть.
    """
    folder = folder.resolve()

    def repl(m):
        rel = m.group(1) or m.group(2) or m.group(3)
        if not rel:
            return m.group(0)
        low = rel.lower()
        if (low.startswith("data:") or low.startswith("http://")
                or low.startswith("https://") or low.startswith("//")
                or low.startswith("file:") or low.startswith("/")
                or re.match(r"^[A-Za-z]:[\\/]", low) or low.startswith("\\\\")):
            return m.group(0)
        candidate = (folder / rel).resolve()
        if not candidate.is_relative_to(folder):
            return m.group(0)
        uri = _asset_data_uri(candidate)
        return f"url(\"{uri}\")" if uri else m.group(0)

    return _URLEX.sub(repl, css)


def _seed_theme(root: Path, key: str, payload: dict) -> None:
    """Раскладывает встроенную тему в папку (theme.json + custom.css),
    только если их ещё нет — правки пользователя сохраняются."""
    folder = root / key
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    meta = folder / "theme.json"
    if not meta.exists():
        try:
            meta.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8-sig",
            )
        except OSError:
            pass
    css = folder / "custom.css"
    if not css.exists():
        try:
            css.write_text(_SEED_CSS.get(key, _BASE_CSS), encoding="utf-8-sig")
        except OSError:
            pass


def restore_builtin_themes(on_log=None) -> dict:
    """Дописывает недостающие встроенные темы (кнопка «Докачать темы»).

    Темы описаны прямо в этом модуле (THEMES и _SEED_CSS), поэтому интернет не
    нужен: на диск попадает только то, чего ещё нет. Правки пользователя не
    трогаем - если theme.json или custom.css уже есть, тема считается
    установленной и остаётся как есть. То же происходит при каждом
    load_themes(), но в фоне и без ответа; здесь результат нужен интерфейсу.

    Возвращает {"added": [...], "skipped": [...], "failed": [...]}, где в
    added - названия тем, которых раньше не было на диске.
    """
    report = on_log or (lambda level, msg: _file_log(level, msg))
    result = {"added": [], "skipped": [], "failed": []}
    root = _themes_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        report("error", f"themes: не удалось создать папку тем ({exc})")
        result["failed"] = list(THEMES)
        return result
    for key in THEMES:
        folder = root / key
        files = [folder / "theme.json", folder / "custom.css"]
        if all(f.exists() for f in files):
            result["skipped"].append(key)
            continue
        before = {f: f.exists() for f in files}
        try:
            _seed_theme(root, key, THEMES[key])
        except OSError as exc:
            report("error", f"themes: не удалось восстановить тему {key} ({exc})")
            result["failed"].append(key)
            continue
        if all(f.exists() for f in files):
            result["added"].append(key)
        else:
            # записалось не всё: сообщаем именем недостающего файла
            missing = [f.name for f in files if not f.exists() and not before[f]]
            report("error", f"themes: тема {key} записана не полностью ({', '.join(missing)})")
            result["failed"].append(key)
    return result


_THEME_README = """\
Synfronia — модульные темы
==========================
Каждая тема — отдельная подпапка в themes\\. Список тем строится по файлам
theme.json внутри подпапок.

СТРУКТУРА ТЕМЫ
--------------
  {id}\\theme.json    — описание темы (палитра, extends, entry, css, мета)
  {id}\\custom.css    — CSS темы (по умолчанию; можно задать поле "css")
  {id}\\index.html    — (необязательно) СВОЙ полный HTML-шаблон страницы
  {id}\\slots\\*.html — (необязательно) отдельные секции интерфейса
  {id}\\*.png/.gif/...— ресурсы: url("bg.png") в CSS, {{asset:bg.png}} в HTML

theme.json
----------
Палитра (наследуется родителями): bg, surface, widget, text, accent, warn,
ok (успех: зелёная отметка скачанных строк массовой загрузки) и
err (ошибка: неудавшиеся строки),
opacity, radius_s, radius_m, radius_l.

  {
    "extends": "scarred_mind",     // унаследовать палитру/CSS другой темы (можно опустить)
    "entry": "index.html",         // свой полный HTML (плейсхолдеры ниже)
    "css": ["custom.css"],          // файлы CSS (или строка с одним файлом)
    "author": "Имя автора",
    "version": "1.0",
    "bg": "#123456"                // переопределение цвета
  }

CSS
---
Ресурсы подключайте относительно папки темы: url("bg.png"), url("anim.gif").
При сборке страницы они автоматически встраиваются в CSS как data:URI.
CSS наследуется по цепочке extends: файлы родителя идут раньше файлов темы.

ПОЛНЫЙ HTML (entry)
------------------
Если в теме есть index.html, весь интерфейс собирается из него. Место для
плейсхолдеров (подставляются при сборке, без логики на месте):

  __THEME_ROOT__    палитра темы (:root CSS-переменные)
  __THEME_CSS__     собранный CSS темы (с data:URI внутри)
  __UTIL_CSS__      библиотека стили: токены + утилиты u-* (генерирует build_ui)
  __APP_CSS__       базовые стили приложения
  __MAIN_CSS__      стили только главного окна
  __SETTINGS_CSS__  стили карточки настроек
  __COMMONJS__      общий JS (переводы, тема, шрифты)
  __MOTION__        Motion (анимации; vendor, MIT)
  __APPJS__         логика главного окна (обязателен в полном HTML-шаблоне)
  __SETTINGS_JS__   логика карточки настроек (обязательна в полном шаблоне)
  __ALPINE__        Alpine.js (реактивность; vendor, MIT)
  __SETTINGS_HTML__ разметка карточки настроек (оверлей)
  __I18N__          переводы (JSON)
  __THEMES__        список тем (JSON)
  __SETTINGS_SCHEMA__  схема настроек (JSON) - карточка рисуется из неё
  {{asset:rel}}     локальный файл темы -> data:URI

Пример минимального index.html:
  <style>:root{__THEME_ROOT__}</style>
  <style id="theme-style">__THEME_CSS__</style>
  <link rel="stylesheet" href="__APP_CSS__">   <!-- или просто <style>__APP_CSS__</style> -->
  ...ваша разметка (элементы сохраняют id, которые использует __APPJS__)...
  <script>__MOTION__</script>
  <script>__APPJS__</script>
  <script>__SETTINGS_JS__</script>
  <script>__ALPINE__</script>

Три плейсхолдера карточки (__SETTINGS_HTML__, __SETTINGS_CSS__, __SETTINGS_JS__)
подставлять необязательно: если своего entry их нет, themes._ensure_settings
допишет оверлей, его стиль и скрипт сам, иначе шестерёнка в шапке ничего не
открыла бы. __MOTION__/__ALPINE__ тоже необязательны - build_page допишет их
сам. Остальные плейсхолдеры в entry обязательны.

СЕКЦИИ (slots)
--------------
Эти секции базового шаблона можно переопределить файлами slots\\<имя>.html:
  head, tabs, panel-video, panel-playlist, panel-batch, warn, ffmpeg-overlay, actions,
  progress, clicker, modal.
Маркеры в шаблоне: <!-- SLOT:<имя> --> ... <!-- /SLOT:<имя> -->.
Слоты ищутся по цепочке extends: сначала в теме, затем у родителей.

ОКНО НАСТРОЕК
-------------
Настройки открываются отдельным окном. Оно всегда собирается приложением из
собственного шаблона: тема влияет на него палитрой, шрифтами и своим CSS, но
ни полный entry, ни слот settings не переопределяют его разметку - поля
рисует settings.js из схемы настроек. Файл slots\\settings.html игнорируется
(запись об этом появляется в журнале).
"""


def _seed_theme_readme(root: Path) -> None:
    """Раскладывает README справочник по темам в корень папки тем."""
    try:
        readme = root / "README.txt"
        if not readme.exists():
            readme.write_text(_THEME_README, encoding="utf-8-sig")
    except OSError:
        pass


def _migrate_flat(root: Path) -> None:
    """Переносит старые плоские «{theme}.json» (наследие предыдущей версии)
    в папку темы как theme.json; плоский файл после переноса удаляется."""
    for f in sorted(root.glob("*.json")):
        key = f.stem
        if not key or not _THEME_ID_RE.fullmatch(key):
            continue
        if (root / key / "theme.json").exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            (root / key).mkdir(parents=True, exist_ok=True)
            (root / key / "theme.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8-sig",
            )
            f.unlink()
        except OSError:
            pass


def load_themes() -> dict[str, dict]:
    """Сканирует папку тем: каждая подпапка = тема (theme.json + custom.css).

    • при первом запуске (папка пуста/нет файлов) раскладывает базовые темы
      по папкам — файлы можно править, добавлять CSS и картинки;
    • при каждом запуске читается каждая «*/theme.json»: имя папки = id темы,
      содержимое = словарь полей палитры/прозрачности/скругления; рядом
      custom.css с ресурсами темы. Новая тема (новая подпапка) автоматически
      попадает в возвращаемый словарь (базовые идут первыми, затем новые).
    • theme.json может содержать:
        "extends": "<id>"          — унаследовать палитру/CSS от другой темы;
        "entry": "index.html"      — свой полный HTML-шаблон страницы;
        "css": ["custom.css", ...] — файлы CSS (по умолчанию ["custom.css"]);
        "author", "version"        — метаданные (необязательно).
    Значения проверяются (validate_theme): невалидные отбрасываются, тема
    наследует значение родителя, а в лог пишется предупреждение.
    """
    global _LOADED_THEMES
    root = _themes_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return dict(THEMES)
    _migrate_flat(root)
    _seed_theme_readme(root)
    # 1) базовые темы — раскладываем по папкам, только если их ещё нет
    for key, payload in THEMES.items():
        _seed_theme(root, key, payload)
    # 2) сканируем папку: каждая подпапка с theme.json — тема.
    #    Пока только собираем «сырые» спецификации (без CSS и разрешения extends).
    raw = {key: dict(payload) | {"_folder": None} for key, payload in THEMES.items()}
    order = list(THEMES)
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not _THEME_ID_RE.fullmatch(folder.name):
            continue
        key = folder.name
        meta = folder / "theme.json"
        if not meta.exists():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        spec = dict(raw.get(key, {}))
        clean, warn = validate_theme(data)
        spec.update(clean)
        if warn:
            spec["_warnings"] = warn
            _file_log("warning", f"theme {key}: " + "; ".join(warn))
        spec.setdefault("label", key)
        spec["_folder"] = folder
        raw[key] = spec
        if key not in order:
            order.append(key)
    # 3) разрешаем цепочки наследования (base-first) -> эффективные темы
    merged: dict[str, dict] = {}
    for key in order:
        merged[key] = _resolve_theme(key, raw)
    _LOADED_THEMES = {k: merged[k] for k in order}
    return _LOADED_THEMES


def _theme_chain(key: str, raw: dict[str, dict]) -> list[dict]:
    """Возвращает цепочку extends для темы key (base-first), без циклов."""
    chain: list[dict] = []
    seen: set[str] = set()
    cur: str | None = key
    while cur and cur not in seen:
        seen.add(cur)
        spec = raw.get(cur)
        if not spec:
            break
        chain.insert(0, spec)
        cur = spec.get("extends")
    return chain


def _css_files_for(spec: dict) -> list[str]:
    """CSS-файлы темы из её theme.json («css» может быть строкой или списком)."""
    raw_files = spec.get("css") or ["custom.css"]
    if isinstance(raw_files, str):
        raw_files = [raw_files]
    return [str(f) for f in raw_files]


def _resolve_theme(key: str, raw: dict[str, dict]) -> dict:
    """Собирает эффективную тему по цепочке extends:
    • палитра — потомок переопределяет родителя;
    • css — конкатенация файлов всей цепочки (родитель -> ребёнок), data:URI
      встраивается;
    • entry — самый глубокий в цепочке владелец index.html;
    • слоты и ассеты ищутся по всем папкам цепочки (глубина -> корень).
    """
    chain = _theme_chain(key, raw)
    if not chain:
        chain = [dict(raw.get(key, dict(THEMES.get(key, {}))))]
    out: dict = {}
    css_parts: list[str] = []
    warnings: list[str] = []
    entry = None
    entry_folder: Path | None = None
    for spec in chain:
        for f in _PALETTE_FIELDS:
            if f in spec and spec[f] is not None:
                out[f] = spec[f]
        for f in _THEME_META_FIELDS:
            if f in spec and f != "extends" and spec[f] is not None:
                out[f] = spec[f]
        for w in spec.get("_warnings") or []:
            if w not in warnings:
                warnings.append(w)
        folder = spec.get("_folder")
        for fname in _css_files_for(spec):
            if not folder:
                continue
            path = folder / fname
            if not path.is_file():
                continue
            try:
                css_parts.append(_process_theme_css(path.read_text(encoding="utf-8-sig"), folder))
            except (OSError, UnicodeDecodeError):
                pass
        ent = spec.get("entry")
        if ent and folder:
            entry = str(ent)
            entry_folder = folder
    out.setdefault("label", key)
    out["css"] = "\n".join(p for p in css_parts if p.strip())
    if warnings:
        out["_warnings"] = warnings
    if entry and entry_folder is not None:
        out["entry"] = entry
        out["_entry_folder"] = entry_folder
        offset = len(out["_entry_folder"].parts)
        out["_slots"] = out["_entry_folder"]
    # Папки для поиска слотов и ассетов: глубина -> корень.
    slot_folders = [spec.get("_folder") for spec in reversed(chain) if spec.get("_folder")]
    out["_slot_folders"] = slot_folders
    return _fill_palette(out)


def _palette_root_vars(theme: dict, fonts: dict | None = None) -> str:
    """CSS-переменные палитры темы как строка для :root{...}.

    Значения прогоняются через валидаторы ещё раз: страница собирается и для
    тем, спецификация которых создана в памяти, а не прошла validate_theme.
    fonts — выбранные шрифты (--font-sans / --font-mono).
    """
    parts = []
    for f in _PALETTE_FIELDS:
        v = theme.get(f)
        if v is None:
            continue
        if f.startswith("radius"):
            num = _clean_number(v, 0.0, _MAX_RADIUS, digits=2)
            if num is not None:
                parts.append(f"--{f}: {num}px")
        elif f == "opacity":
            num = _clean_number(v, 0.0, 1.0)
            if num is not None:
                parts.append(f"--opacity: {num}")
        else:
            color = _clean_color(v)
            if color is not None:
                parts.append(f"--{f}: {color}")
    if fonts:
        vars_css = font_vars(fonts.get("sans") or "", fonts.get("mono") or "",
                             fonts.get("head") or "", fonts.get("weight") or "")
        if vars_css:
            parts.append(vars_css)
    return " ".join(parts)


def _js_json(data) -> str:
    """JSON для вставки прямо в <script>.

    «</» экранируется («<\\/»), иначе значение вида «</script>» из
    theme.json или language\\*.json закрыло бы тег и выполнилось как разметка.
    """
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _asset_uri_for_page(rel: str, folders: list[Path]) -> str | None:
    """Находит файл rel в одной из папок цепочки тем и возвращает data:URI."""
    for folder in folders or []:
        candidate = (folder / rel).resolve()
        if not candidate.is_relative_to(folder.resolve()):
            continue
        if candidate.is_file():
            uri = _asset_data_uri(candidate)
            if uri:
                return uri
    return None


def _apply_slots(template: str, folders: list[Path]) -> str:
    """Заменяет секции <!-- SLOT:name -->...<!-- /SLOT:name --> базового
    шаблона содержимым файлов slots\\<name>.html (ищет по всей цепочке)."""

    def repl(m: re.Match) -> str:
        name = m.group(1)
        for folder in folders or []:
            slot = folder / "slots" / f"{name}.html"
            if slot.is_file():
                try:
                    return slot.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeDecodeError):
                    return m.group(0)
        return m.group(0)

    return _SLOT_RE.sub(repl, template)


def _warn_ignored_slot(folders: list[Path], name: str, why: str) -> None:
    """Пишет в лог, если тема подсовывает слот, который собирает приложение.

    Карточку настроек рисует settings.js из схемы settings_schema, поэтому свой
    slots/settings.html тема подставить не может - молча проглотили бы файл,
    поэтому пишем в лог (он виден и в журнале, и в themes/README.txt).
    """
    for folder in folders or []:
        if (folder / "slots" / f"{name}.html").is_file():
            _file_log("WARN", f"тема {folder.name}: slots/{name}.html игнорируется, {why}")


def _apply_assets(html: str, folders: list[Path]) -> str:
    """Заменяет {{asset:rel}} на data:URI локального файла темы."""
    if not folders:
        return html

    def repl(m: re.Match) -> str:
        uri = _asset_uri_for_page(m.group(1).strip(), folders)
        return uri if uri else m.group(0)

    return _ASSET_RE.sub(repl, html)


def _page_theme(theme_key: str) -> dict:
    """Спецификация темы для сборки страницы (палитра, CSS, папки слотов)."""
    if not _LOADED_THEMES:
        load_themes()
    available = _LOADED_THEMES or {}
    if theme_key not in available:
        theme_key = "scarred_mind" if "scarred_mind" in available else next(iter(available), theme_key)
    return _fill_palette(dict(available.get(theme_key) or THEMES.get(theme_key) or {}))


def _page_fonts(theme: dict, fonts: dict | None) -> dict:
    """Шрифты страницы: выбор из настроек, но тема может его переопределить."""
    if fonts is None:
        from settings import load_settings
        saved = load_settings()
        fonts = {"sans": saved.get("font_sans") or "", "mono": saved.get("font_mono") or "",
                 "head": saved.get("font_heading") or "",
                 "weight": str(saved.get("font_weight") or "")}
    return {
        "sans": _clean_family(theme.get("font") or fonts.get("sans") or ""),
        "mono": _clean_family(theme.get("font_mono") or fonts.get("mono") or ""),
        "head": _clean_family(fonts.get("head") or ""),
        "weight": str(fonts.get("weight") or ""),
    }


def _fill_placeholders(template: str, theme: dict, picked: dict) -> str:
    """Подставляет в шаблон палитру, CSS темы, шрифты, переводы и данные.

    Карточка настроек приходит тем же плейсхолдером (__SETTINGS_HTML__), что и
    раньше отдельное окно: в своём entry-шаблоне темы его может не быть, и
    тогда разметку добавляет _ensure_settings.
    """
    # Встраиваем все семейства, а не только выбранные: подсказки опций
    # переключателей шрифтов набираются самим шрифтом (data-tip-font),
    # поэтому @font-face нужен каждому семейству из списка. Лимит
    # fonts.MAX_TOTAL_BYTES защищает от раздувания страницы.
    all_fams = list((load_fonts() or {}).keys())
    fonts_css = font_css(list(dict.fromkeys(
        [picked["sans"], picked["mono"], picked.get("head") or ""] + all_fams)))
    page = template.replace("__THEME_ROOT__", _palette_root_vars(theme, picked))
    # авторский CSS темы живёт в слое syn-theme: главнее компонентов
    # (syn-components), но уступает явным утилитам элемента (syn-utilities).
    # Объявление порядка слоёв обязано встретиться на странице раньше первого
    # слоя - держим его здесь, а не только в util.css: у entry-шаблонов темы
    # своего __UTIL_CSS__ может не быть
    theme_css = theme.get("css") or ""
    layers = "@layer syn-components, syn-theme, syn-utilities;"
    page = page.replace(
        "__THEME_CSS__",
        f"{layers}\n@layer syn-theme {{\n{theme_css}\n}}" if theme_css else layers)
    page = page.replace("__FONTS_CSS__", fonts_css)
    if "__FONTS_CSS__" not in template:
        # свой entry-шаблон без плейсхолдера: добавляем стиль шрифтов сами
        page = page.replace("</head>", f'<style id="fonts-style">{fonts_css}</style></head>', 1)
    # vendor: у entry-шаблона темы плейсхолдеров может не быть - дописываем
    # их ДО подстановки, чтобы сохранить критичный порядок: Motion до app.js,
    # Alpine после settings.js (обработчики alpine:init должны быть к этому
    # моменту зарегистрированы; вставки разрывают <script>, не сливая код).
    if "__MOTION__" not in page and "__APPJS__" in page:
        page = page.replace("__APPJS__",
                            "</script><script>__MOTION__</script><script>__APPJS__", 1)
    if "__ALPINE__" not in page and "__SETTINGS_JS__" in page:
        page = page.replace("__SETTINGS_JS__",
                            "__SETTINGS_JS__</script><script>__ALPINE__", 1)
    elif "__ALPINE__" not in page and "__APPJS__" in page:
        page = page.replace("__APPJS__",
                            "__APPJS__</script><script>__ALPINE__", 1)
    page = page.replace("__UTIL_CSS__", _ui.UTIL_CSS)
    page = page.replace("__APP_CSS__", _ui.APP_CSS)
    page = page.replace("__MAIN_CSS__", _ui.MAIN_CSS)
    page = page.replace("__COMMONJS__", _ui.COMMON_JS)
    page = page.replace("__MOTION__", _ui.MOTION_JS)
    page = page.replace("__APPJS__", _ui.APP_JS)
    page = page.replace("__SETTINGS_CSS__", _ui.SETTINGS_CSS)
    page = page.replace("__SETTINGS_JS__", _ui.SETTINGS_JS)
    page = page.replace("__ALPINE__", _ui.ALPINE_JS)
    page = page.replace("__SETTINGS_HTML__", _ui.SETTINGS_HTML)
    page = page.replace("__I18N__", _js_json(I18N))
    page = page.replace("__THEMES__", _js_json(themes_embed()))
    # подпись версии: BUILD_LABEL (тег сборки, проставлен stamp_version.py)
    # либо «unreleased» - коммитов с бампом версии больше не нужно
    page = page.replace("__APP_VERSION__", BUILD_LABEL or "unreleased")
    # __SETTINGS_SCHEMA__ лежит внутри settings.js, поэтому подменяем после него
    page = page.replace("__SETTINGS_SCHEMA__", _js_json(settings_schema.schema_json()))
    return page


def _ensure_settings(html: str) -> str:
    """Гарантирует, что на странице есть карточка настроек и её скрипт.

    Оверлей настроек — часть страницы, а не отдельное окно, поэтому он должен
    быть в любой теме. Тема со своим entry (theme.json -> "entry") собирает
    страницу целиком и может не знать про __SETTINGS_HTML__; тогда вставляем
    разметку сами, иначе шестерёнка в шапке просто ничего не откроет. Стили и
    скрипт добавляем так же, если их тоже нет в своём шаблоне.

    Плейсхолдеры здесь ещё не подставлены: разметка и CSS темы вставляются
    позже обычной заменой, поэтому тема не может перекрыть оверлей.
    """
    anchors = ("</body>", "</html>")
    for placeholder, chunk in (
        ("__SETTINGS_HTML__", _ui.SETTINGS_HTML),
        ("__SETTINGS_JS__", f"<script>{_ui.SETTINGS_JS}</script>"),
    ):
        if placeholder in html:
            continue
        for anchor in anchors:
            pos = html.lower().rfind(anchor)
            if pos != -1:
                html = html[:pos] + chunk + "\n" + html[pos:]
                break
        else:
            html += chunk
    if "__SETTINGS_CSS__" not in html:
        html = html.replace("</head>", f"<style>{_ui.SETTINGS_CSS}</style></head>", 1)
    return html


def build_page(theme_key: str, lang: str | None = None, fonts: dict | None = None) -> str:
    """Собирает итоговый HTML страницы для темы theme_key.

    • если у темы есть entry (index.html в папке) — сборка из него;
    • иначе — из встроенного базового шаблона (ui.BASE_TEMPLATE), причём
      секции SLOT:... можно переопределить файлами slots/<имя>.html;
    • карточка настроек (оверлей) есть в любом случае — см. _ensure_settings;
    • ассеты {{asset:rel}} и url(...) в CSS встраиваются как data:URI;
    • шрифты из папки fonts (font_sans / font_mono, переопределённые полями
      темы font / font_mono) встраиваются как @font-face с data:URI;
    • плейсхолдеры (__THEME_ROOT__, __THEME_CSS__, __UTIL_CSS__, __FONTS_CSS__,
      __APP_CSS__, __MAIN_CSS__, __SETTINGS_CSS__, __COMMONJS__, __MOTION__,
      __APPJS__, __SETTINGS_JS__, __ALPINE__, __SETTINGS_SCHEMA__, __I18N__,
      __THEMES__, __APP_VERSION__) подставляются простой заменой;
      __MOTION__/__ALPINE__ при их отсутствии в entry дописываются сами
      (см. комментарий выше).
    """
    theme = _page_theme(theme_key)
    folders = theme.get("_slot_folders") or []
    picked = _page_fonts(theme, fonts)

    # 1) выбор шаблона: свой index.html либо базовый
    entry = theme.get("entry")
    if entry and theme.get("_entry_folder"):
        try:
            template = (theme["_entry_folder"] / entry).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            template = _ui.BASE_TEMPLATE
    else:
        template = _ui.BASE_TEMPLATE
    template = _apply_slots(template, folders)
    # карточка настроек не слот: разметку рисует settings.js из схемы, поэтому
    # свой slots/settings.html тема подставить не может (см. _ensure_settings)
    _warn_ignored_slot(folders, "settings", "карточка настроек строится из схемы")

    # 2) ассеты в разметке -> data:URI
    template = _apply_assets(template, folders)
    return _fill_placeholders(_ensure_settings(template), theme, picked)


def themes_embed() -> dict:
    """Спецификации тем для встраивания в JS (__THEMES__) без служебных полей."""
    embed: dict = {}
    for k, spec in (_LOADED_THEMES or {}).items():
        item = {f: spec[f] for f in _PALETTE_FIELDS + _THEME_META_FIELDS if f in spec}
        item["label"] = spec.get("label", k)
        item["css"] = spec.get("css", "")
        item["hidden"] = bool(spec.get("hidden", False))
        if spec.get("entry"):
            item["entry"] = spec["entry"]
        if spec.get("_warnings"):
            item["warnings"] = list(spec["_warnings"])
        embed[k] = item
    return embed
