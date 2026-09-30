<div align="center">

# Synfronia

Download YouTube videos and playlists **with a friendly interface and no
account** - web UI ([pywebview](https://pywebview.flowrl.com/) /
EdgeChromium) on top of [yt-dlp](https://github.com/yt-dlp/yt-dlp), with
merging, metadata, embedded subtitles and optional **HEVC** re-encode.

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python&logoColor=white)
![UI](https://img.shields.io/badge/UI-web%20%28pywebview%29-8A2BE2)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-important)
![Build](https://img.shields.io/badge/build-PyInstaller-orange)
![Release](https://img.shields.io/github/v/release/vilminessa/Synfronia?label=release)

English · [Русский](README.ru.md)

</div>

---

## Features

- **Videos and playlists, whole or in parts** - paste a URL into the
  «Video» or «Playlist» tab and the download starts: merged streams
  (video + audio), metadata, thumbnails, subtitles embedded into the
  container, and optional playlist archiving. Nothing is required from
  you besides the link: no login, no cookies, no API keys.
- **Bulk download** - the third «Batch» tab takes a whole list of links
  (one per line, `#` for comments, duplicates removed on the fly) and
  works through them **one URL at a time**: a failed link never stops
  the rest, the status shows `[i/N]` with the current link, and the
  same retries, postprocessors and FTP upload apply to every item.
  A common «Download» button with Stop sits below the window.
- **Multilingual interface** - six languages, switchable at runtime:
  **Russian / English / 日本語 / 简体中文 / Español / Deutsch**
  (UI and status messages alike).
- **Modular themes** - six built-in (Technology day, Technology Pinks,
  Scarred Mind, Audrey Main Colours, Basic Night Sky, Liquid Glass)
  plus unlimited custom ones: a folder in
  `%LOCALAPPDATA%\Synfronia\themes\<name>\` with `theme.json`
  (+ `custom.css`, `index.html`, slots and assets).
  A theme defines the palette, radii, transparency, its own fonts and
  even its own HTML.
  More - [Modular themes](#modular-themes).
- **Modular fonts** - JetBrains Mono ships with the app; drop your own
  `.ttf`, `.otf`, `.woff` or `.woff2` into
  `%LOCALAPPDATA%\Synfronia\fonts` and pick a family for the interface
  and for the console (or use the system font).
  More - [Fonts](#fonts).
- **FTP/FTPS upload** - finished files (after merging, re-encoding and
  subtitle embedding) go to your server: FTP or FTPS, passive mode,
  automatic directories, templated path and file name, retries,
  connection test and optional local cleanup after upload.
  More - [FTP upload](#ftp-upload).
- **Progress and cancel** - progress bar driven by yt-dlp logs, a Stop
  button.
- **Everything stays local** - settings in
  `%LOCALAPPDATA%\Synfronia\settings.json`, logs in
  `%LOCALAPPDATA%\Synfronia\logs`, WebView2 data in
  `%LOCALAPPDATA%\Synfronia\webview`, probe pages in
  `%LOCALAPPDATA%\Synfronia\probe` (nothing is ever written to `%TEMP%`).

## Requirements

- Windows 10/11 with **WebView2 Runtime** (ships with Edge by default;
  for the exe build nothing else is needed).
- **ffmpeg** - on first launch the app offers to download and install it
  automatically into `%LOCALAPPDATA%\Synfronia\bin`. Manual install works
  too: put `ffmpeg.exe` on `PATH` or install via winget/Program Files.
  Required for stream merging, metadata and conversion.

## Installation

### Ready-made exe

Download `Synfronia.exe` from the [releases](../../releases) page and run
it - the app is ready. If ffmpeg is missing, a "Download FFmpeg" button
appears on first launch - press it and everything sets itself up.
Keep `THIRD_PARTY_NOTICES.md` (component licenses) next to it.

### From source

```bat
git clone https://github.com/vilminessa/Synfronia.git
cd Synfronia
pip install -r requirements.txt
python gui.py
```

## Usage

| Field / setting | Description |
|---|---|
| Tabs | "Video" - a single video; "Playlist" - the entire playlist; "Batch" - a list of links |
| URL | the link in the matching tab (YouTube video or playlist) |
| ⚙ Settings | gear icon, top right: language, folder, theme, fonts, tooltips, subtitles, quality, re-encode, network |
| Language | Русский / English / 日本語 / 简体中文 / Español / Deutsch |
| Destination | where to save (defaults to `downloads\` next to the app) |
| Theme | Technology day / Technology Pinks / Scarred Mind / Audrey Main / Night Sky / Liquid Glass + your own folders |
| Fonts card | headings / general / console font and weight - knobs on the left, live preview on the right; families from the `fonts` folder or the system font |
| Quality | `lossless` / 8K / 4K / 2K / 1080p / 720p / 480p / 240p |
| Subtitles | off / ru / en / all (embedded into the container) |
| Re-encode | none / libx265 / nvenc / amf / qsv (hardware - by availability) |
| Group playlist | download a playlist as one archive |

### Bulk download

The «Batch» tab takes a list of links - one per line. Rules: empty lines
and `#` comments are skipped, anything without `http(s)://` is ignored
(and counted in the log), duplicates are removed keeping your order; the
counter «Links: N» updates as you type. Press **Download** at the bottom
(Ctrl+Enter in the field works too) and the links are fetched strictly
one after another, each as its own yt-dlp run:

- a failed link does not break the queue - the rest keep going;
- the status line shows `[i/N] <current link>`, the journal gets a
  `bulk [i/N] <url>` row per item;
- Stop interrupts the current link and drops the rest of the queue;
- retries, postprocessors (including re-encode) and FTP upload behave
  exactly like a single download;
- the summary at the end: all good - «Готово», some failed - «Готово с
  ошибками - скачало X из Y», none - «Не удалось скачать».

The draft list lives in the page memory only: switching a theme with
`entry` (a page rebuild) clears the textarea. Destination, subtitles,
quality and re-encode come from the settings card as usual.

### Modular themes

A theme is a folder `%LOCALAPPDATA%\Synfronia\themes\<theme name>\`.
The "Themes folder..." and "Reload themes" buttons in settings open and
re-read it.

```jsonc
// %LOCALAPPDATA%\Synfronia\themes\my_theme\theme.json
{
  "label": "My theme",           // name in the list (required)
  "author": "Nick", "version": "1.0",   // shown in settings
  "extends": "scarred_mind",     // palette on top of a built-in theme
  "bg": "#101418", "surface": "#1b2228", "widget": "#263038",
  "text": "#e6e9ec", "accent": "#7fd1b9", "warn": "#ffb454",
  "radius_s": 6, "radius_m": 8, "radius_l": 12,   // px, 0..40
  "opacity": 0.96,              // 0..1 - window transparency
  "font": "Inter",              // own interface font (from the fonts folder)
  "font_mono": "JetBrains Mono",
  "hidden": false,              // true - hide from the list
  "entry": "index.html",        // own HTML template (optional)
  "css": "body { letter-spacing: .2px; }"          // or custom.css in the folder
}
```

- `entry` - a complete custom main-window page; it supports the
  placeholders `__THEME_ROOT__` (palette in `:root`), `__THEME_CSS__`
  (theme CSS), `__FONTS_CSS__` (`@font-face`), `__APP_CSS__`, `__MAIN_CSS__`,
  `__COMMONJS__`, `__APPJS__`, `__I18N__`, `__THEMES__`,
  `__SETTINGS_SCHEMA__`, plus sections `<!-- SLOT:name -->`
  (`slots\name.html` files) and `{{asset:path}}` - assets are inlined as
  `data:URI`.
- A theme never replaces the settings card: its fields are rendered by
  code from the schema, so the markup always belongs to the app.
  `__SETTINGS_HTML__`, `__SETTINGS_CSS__` and `__SETTINGS_JS__` are
  optional in your `entry` - if they are missing, the app appends the
  overlay, styles and script itself (otherwise the gear in the header
  would open nothing). `slots\settings.html` is ignored (a warning is
  logged), while the palette, fonts and `custom.css` work as usual.
- Values are validated: unknown or broken fields do not break the UI -
  they land in the log and get a `⚠` marker in the theme list.
- The `css` field may be a string or a list of files; without it,
  `custom.css` from the theme folder is read.
- Switching a theme does not reload the page, except for themes with
  `entry` or their own `font` / `font_mono` - they need a fresh
  `@font-face`.

### Fonts

One test font ships with the app (OFL 1.1, ~190 KB): **JetBrains Mono**
from `assets/fonts`. On first launch it is laid out into
`%LOCALAPPDATA%\Synfronia\fonts` together with the license text and a
`README.txt`, so a fresh install works offline. Existing files are never
overwritten: the fonts folder belongs to the user. The "Reload fonts"
button re-scans the folder; "Download fonts" fetches the same file from
the network (`github.com/google/fonts`) - useful if the file was deleted
or you want to test downloading; progress and result show up in the log
and the font list refreshes itself. CJK (Japanese, Chinese) scripts are
not covered by this file - the app falls back to the system font for
them.

Your own fonts go into the same folder - one `.ttf`, `.otf`, `.woff` or
`.woff2` file per face. The app reads the TTF/OTF `name`, `OS/2`, `head`
and `fvar` tables (family, face, weight, variable-weight range), and for
WOFF/WOFF2 falls back to the file name, then inlines the selected fonts
into the page as `@font-face` with `data:URI`.

Left side of the «Fonts» card: a 2x2 panel of FL-style round knobs:
three font knobs (headings, general, console) and the endless weight
knob100..900. The font scale is finite: a270° arc starting at the
bottom-left (the "zero point") with hard end-stops - the wheel cannot
spin forever; position ticks light up on the active detent (a visual
"click"), and the knob's tooltip shows the selected family set in that
very family. Rotation of every knob is smooth with a capped speed
(1080 deg/s) - even a wheel burst cannot spin the knob faster. Turn them
with the wheel while hovering, by dragging the held mouse horizontally,
or with the arrow keys; the weight number lives in the tooltip
«Font weight - N%». On the right: the preview -
«Заголовок - {font}», «Основной текст - {font}», «Консоль - {font}» -
each line is set in its own font and updates on any choice. A theme may
override the general and console fonts with its `font` / `font_mono`
fields. Limits: 8 MB per file and 8 MB per page; oversized files are
not inlined and a message goes to the log.

Font changes, the "Reload fonts" button and theme switches apply live:
Python returns a fresh `@font-face` block and the page swaps the
`#fonts-style` element without reloading - the open section and filled
fields stay intact. A full page rebuild only happens for themes with
their own `index.html` (`entry`); then the settings card returns in the
same state. A choice in the card reaches the main window through the
`ui_rev` counter.

Checks: `python tools/check_test_fonts.py` (offline),
`set SYNFONIA_FONTS_NETWORK=1` - additionally verify real downloading;
`node tools/ui_fonts_probe.js` - main-window layout with the settings
card in headless Edge (needs a page from `python tools/ui_probe_page.py`);
`node tools/ui_themes_probe.js` - the same check across all themes.

### FTP upload

The **FTP** section of the settings card. The upload happens after the
file is complete (stream merging, re-encoding, embedded subtitles,
metadata and cover) - the finished result, not the raw stream.

| Field | Meaning |
| --- | --- |
| Upload to FTP | master switch; no server, no upload |
| Mode | `Batch` - all files in one session at the end of a download; `Per-file` - a separate connection per file right after it is downloaded (details in the mode button tooltip) |
| Host / Port / User / Password | regular connection parameters (port defaults to 21, user `anonymous`) |
| FTPS | explicit TLS (plain login first, then `PROT P`) |
| Verify certificate | turn off only for self-signed servers |
| Passive mode (PASV) | on by default; turn off if the server only supports active mode |
| Remote folder | path template, nested directories are created automatically |
| File name | name template, supports the `{index:02d}` format |
| Delete local file | the file is deleted only after a confirmed upload |
| Timeout / Retries | socket timeout and number of attempts on connection loss |
| Test connection | connects and disconnects immediately; result in the log and under the button |

Templates `{title}`, `{ext}`, `{index}`, `{id}`, `{playlist}`, `{date}`
work in both the folder and the file name (`{index}` also takes a
format, e.g. `{index:02d}` → `07`). Characters that are illegal in file
names (`<>:"/\|?*`, trailing dots, reserved `CON`/`NUL`/`COM1`…)
are replaced, the length is capped at 180 bytes keeping the extension.
Escaping the base folder is impossible: `..` and empty segments are
dropped.

Details:

- two files with the same templated name never overwrite each other:
  the second gets `~2` before the extension;
- on connection loss a fresh connection is made and directories are
  re-created;
- the size on the server is compared with the local one when the server
  reports it;
- a server refusal (e.g. `553`) is not retried - retries are for
  connection loss only;
- the password is stored in `settings.json` in plain text, like every
  other setting.

Everything is built on the standard library (`ftplib`): no extra FTP
packages are required.

### CLI

```bat
python download.py <URL> [--dest C:\videos] [--subtitles ru] [--quality 720] [--transcode nvenc] [--lang en] [--no-ftp]
```

`python core.py <URL> ...` accepts the same arguments - it is the same
engine for when the web UI is not needed. FTP upload comes from
settings; `--no-ftp` disables it for a single run.

### Self-check (for build debugging)

```bat
Synfronia.exe --selftest C:\videos https://youtu.be/GUS0q7gZdNE --subtitles ru --quality 720 --transcode libx265
```

Results go to `selftest.log`, files go to the given folder.

## Debug console

`debug.py` - an interactive numbered menu for maintaining local data
and logs (stdlib only, no third-party packages):

```bat
python debug.py
```

| Item | What it does |
|-------|-----------|
| 1 | wipe `%LOCALAPPDATA%\Synfronia` completely (preview with sizes + confirmation) |
| 2 | the same, but keep only `bin\` (ffmpeg/ffprobe) |
| 3-5 | start / stop / inspect the app (PID, start time) |
| 6-9 | logs: tail of the last file, list, show a file fully, delete |
| 10 | follow the log in real time (Ctrl+C - back to the menu) |
| 11 | remove Synfronia service files from `%TEMP%` (WebView2 folders, probe artifacts) |

## Building the exe

```bat
python -m PyInstaller Synfronia.spec --distpath . --workpath build --noconfirm
```

The spec produces a single file (`--onefile --windowed`), bundling
yt-dlp, webview and the .NET runtime (pythonnet) for EdgeChromium.

**Release by tag.** Pushing a `v*` tag runs the **release** workflow
(`.github/workflows/release.yml`): checks and layout probes → exe build →
publishing the exe to the GitHub Release of the tag → **SLSA provenance**
(`Synfronia.exe.intoto.jsonl`, slsa-github-generator v2.1.0, keyless
signature via OIDC) → signature verification. A manual run
(workflow_dispatch) passes checks, build, **provenance generation and
signature verification without publishing** - the whole pipeline can be
rehearsed before a tag goes out. The workflow itself is linted by
`python tools/check_release_yml.py`; on a tag `verify` also cross-checks
the tag name against `version.py`.

### Releasing a version

The app version lives in one place - `version.py` (`__version__`).
It feeds the UI signature, the `app_version` key in `settings.json`,
the exe VersionInfo and the CI tag check.

1. bump `__version__` in `version.py` and `app_version` in
   `based_settings.json` (the checks will not let you forget - defaults
   are compared);
2. commit;
3. tag `vX.Y.Z` (exactly `v` + the version from `version.py`) and push -
   the release workflow verifies the tag and ships the exe with
   provenance.

## Project structure

```
gui.py            - web UI (pywebview) + hidden --selftest mode
core.py           - facade over modules and `python core.py` entry point
paths.py          - app paths and file log
settings.py       - settings (based_settings.json -> settings.json)
i18n.py           - UI translations and statuses (6 languages)
themes.py         - modular themes, theme.json validation, page build
fonts.py          - modular fonts from the fonts folder (@font-face, data:URI),
                    bundled test fonts and network fallback
ftp.py            - upload of finished files to FTP/FTPS (ftplib)
downloader.py     - downloads via yt-dlp, postprocessors, ffmpeg
download.py       - CLI wrapper
ui_src/           - UI sources: index.html, app.css, app.js
ui.py             - generated UI from ui_src/ (kept in the repository)
assets/fonts/     - bundled test fonts (OFL 1.1) and their licenses
tools/build_ui.py - ui.py builder from ui_src/ (developers only)
tools/utf8_console.py - shared UTF-8 output helper for tools/: the Windows
  console lives in a single-byte code page (cp1251/cp437/cp866) with no
  Cyrillic or "✕", and checks fail with UnicodeEncodeError without it
based_settings.json - default settings (copied to settings.json on the
  first launch; missing keys are appended on update
version.py        - app version (single source of truth: UI signature,
                    app_version in settings.json, exe VersionInfo, CI tag check)
requirements.txt  - yt-dlp, pywebview, pyinstaller, pyyaml (CI tooling)
Synfronia.spec    - exe build config
LICENSE           - project license (PolyForm Noncommercial 1.0.0)
THIRD_PARTY_NOTICES.md - sources and licenses of all components
```

### Editing the UI

`ui.py` is never edited by hand: the app reads the page from this
module, so after touching the sources it must be rebuilt.

```bat
python tools/build_ui.py            # ui_src/ -> ui.py
python tools/build_ui.py --check    # verify ui.py is fresh (runs in CI)
```

Edits in `ui_src/index.html` land in `BASE_TEMPLATE`, `ui_src/app.css`
in `APP_CSS`, `ui_src/main.css` in `MAIN_CSS`, `ui_src/app.js` in
`APP_JS`, and `ui_src/settings.html`, `settings.css`, `settings.js` and
`ui_src/common.js` in `SETTINGS_HTML`, `SETTINGS_CSS`, `SETTINGS_JS` and
`COMMON_JS` respectively. All placeholders (`__THEME_ROOT__`,
`__THEME_CSS__`, `__FONTS_CSS__`, `__APP_CSS__`, `__MAIN_CSS__`,
`__SETTINGS_CSS__`, `__SETTINGS_HTML__`, `__COMMONJS__`, `__APPJS__`,
`__SETTINGS_JS__`, `__I18N__`, `__THEMES__`, `__SETTINGS_SCHEMA__`,
`__APP_VERSION__`) are substituted at page build time.

### Developer checks

```bat
python tools/check_settings.py          # settings schema, translations, card
python tools/check_settings_overlay.py  # overlay: build, Api, single window
python tools/check_test_fonts.py        # bundled fonts and download (offline)
python tools/check_download_button.py   # download button: progress and result
python tools/check_tools_output.py      # scripts print on any code page
python tools/check_release_yml.py      # release.yml lint: pinning, SLSA permissions, ASCII
python tools/check_debug.py            # debug console: cleanup, logs, menu
node  tools/ui_themes_probe.js          # card layout across all themes (headless Edge)
```

## Legal, licenses & open source

### Open source - forever

The sources have been public since the first commit and are meant to
stay public: the author has no plan to close the repository, move it
behind an account or switch the project to a proprietary license.
Forks, offline mirrors, research use and pull requests are welcome;
every release ships with its sources and a build attestation.

Honest note about the license: the project uses the **PolyForm
Noncommercial License 1.0.0** (see [`LICENSE`](LICENSE)). This license
grants free access to the source code but is **source-available, not
"open source" in the OSI sense** - it forbids commercial use. The
statement above is about the *availability and openness of the sources*,
not about an OSI certification.

### Third-party components

The full list with license texts is in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). The key legal facts:

| Component | Status |
|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | bundled, Unlicense (public domain) |
| [pywebview](https://github.com/r0x0r/pywebview), pythonnet, bottle, certifi, urllib3, idna, cffi, cryptography | bundled, permissive licenses (BSD/MIT/Apache/MPL - see notices) |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | **build-time only**, GPL-2.0+ with the special build exception - it is not redistributed |
| [ffmpeg](https://ffmpeg.org/) | **external, NOT bundled** - downloaded by the user or the app at first run; GPL applies to ffmpeg itself, not to this project's binaries |
| [JetBrains Mono](https://www.jetbrains.com/lp/mono/) | bundled font, OFL-1.1 (attribution shipped next to it) |
| CPython | bundled runtime, PSF License Agreement |

UI palette inspirations: [color-hex.com](https://color-hex.com/) (see
notices for the exact palettes and their terms).

### Build provenance - verify what you download

Every `Synfronia.exe` published in the releases is signed with an
SLSA provenance attestation (Sigstore, keyless OIDC from GitHub
Actions), so you can verify that the binary really came from this
public source and was built by the pinned workflow:

```bash
gh release download v1.2.7 -R vilminessa/Synfronia -p Synfronia.exe -p Synfronia.exe.intoto.jsonl
gh attestation verify Synfronia.exe \
  --bundle Synfronia.exe.intoto.jsonl \
  -R vilminessa/Synfronia \
  --predicate-type https://slsa.dev/provenance/v0.2 \
  --signer-repo slsa-framework/slsa-github-generator
```

The provenance file (`.intoto.jsonl`) is attached to every release.

### Privacy

- **No accounts, no telemetry, no analytics, no tracking.** The app has
  no server component; it never sends data anywhere on its own.
- All state lives locally in `%LOCALAPPDATA%\Synfronia` (settings, logs
  with rotation, WebView2 profile, caches) and in your download folder.
- Network access is used only for the things you explicitly ask for:
  the download itself (through yt-dlp), optional font downloads from
  `github.com/google/fonts` and the optional ffmpeg fetch.
- Logs are plain text files on your disk; nothing is uploaded.
- Honest caveat: FTP credentials are stored in `settings.json` in plain
  text - do not use the app on a shared machine or sync that folder
  unencrypted.

## Disclaimer

This project is intended for personal, non-commercial use - for
example, to keep access to content you own or are allowed to keep.
Please respect the [YouTube Terms of Service](https://www.youtube.com/static?template=terms)
and copyright: download only content you have the right to archive, and
do not redistribute obtained files without the rights holder's
permission. Synfronia is not affiliated with, endorsed by or sponsored
by YouTube, Google or any other mentioned brand.

The software is provided **"as is", without warranty of any kind**;
the author is not responsible for illegal use, misuse, or damage arising
from the use of the software. By using Synfronia you accept the
PolyForm Noncommercial License 1.0.0.

**About the code**: this project is a **vibe-coded project** - its code
was written and evolved with the help of AI models (LLM-assisted
development), and that is its honest, intentional style. "As is" also
means "AI can be wrong": if you find a bug, an issue or a pull request
is more valuable than ever.

---

## License

The project is distributed under the **PolyForm Noncommercial License
1.0.0** - use, study, modification and redistribution are allowed for
**non-commercial purposes** (personal projects, education, scientific
and charitable organizations, etc.). **Selling** this product or
products derived from it is prohibited. Full text - in
[`LICENSE`](LICENSE).

Note: this license does not meet the OSI definition of "Open Source"
and is **source-available** (open sources with a commercial restriction).

---

© 2026 [vilminessa](https://github.com/vilminessa) · PolyForm Noncommercial 1.0.0
