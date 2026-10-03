# Third-Party Notices

This project (Synfronia) uses the following third-party components.
Their licenses are reproduced or linked below in accordance with the
requirements of each license.

| Component | Version | License | Source |
|---|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 2026.8.19 (bundled) | Unlicense | https://github.com/yt-dlp/yt-dlp |
| [pywebview](https://github.com/r0x0r/pywebview) | 6.2.1 (bundled) | BSD-3-Clause | https://github.com/r0x0r/pywebview |
| [Alpine.js](https://github.com/alpinejs/alpine) | 3.17.4 (bundled, `ui_src/vendor`) | MIT | https://github.com/alpinejs/alpine |
| [Motion](https://github.com/motiondivision/motion) | 12.23.24 (bundled, `ui_src/vendor`) | MIT | https://github.com/motiondivision/motion |
| pythonnet | 3.1.0 (bundled) | MIT | https://github.com/pythonnet/pythonnet |
| clr_loader | 0.3.1 (bundled) | MIT | https://github.com/pythonnet/clr-loader |
| bottle | 0.13.4 (bundled) | MIT | https://github.com/bottlepy/bottle |
| proxy_tools | 0.1.0 (bundled) | MIT | https://github.com/TkTech/proxy_tools |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | 6.22.2 (build-time only) | GPL-2.0-or-later with special exception | https://github.com/pyinstaller/pyinstaller |
| [PyYAML](https://github.com/yaml/pyyaml) | 6.x (dev/CI tooling only, not bundled) | MIT | https://github.com/yaml/pyyaml |
| [webaudio-controls](https://github.com/g200kg/webaudio-controls) | — (behavioral reference only, NOT bundled) | Apache-2.0 | https://github.com/g200kg/webaudio-controls |
| certifi | 2026.7.22 (bundled) | MPL-2.0 | https://github.com/certifi/python-certifi |
| urllib3 | 2.7.0 (bundled) | MIT | https://github.com/urllib3/urllib3 |
| idna | 3.19 (bundled) | BSD-3-Clause | https://github.com/kjd/idna |
| cffi | 2.1.1 (bundled) | MIT-0 | https://github.com/python-cffi/cffi |
| cryptography | 50.0.1 (bundled) | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| CPython | 3.14.2 (bundled) | PSF License Agreement | https://www.python.org/ |
| ffmpeg | any recent build (external, NOT bundled) | GPL-2.0-or-later | https://ffmpeg.org/ |
| [JetBrains Mono](https://www.jetbrains.com/lp/mono/) | variable (bundled, `assets/fonts`) | OFL-1.1 | https://github.com/google/fonts/tree/main/ofl/jetbrainsmono |
| [zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) | 1.10.3 (bundled, `assets/bypass`) | MIT | https://github.com/Flowseal/zapret-discord-youtube/releases/tag/1.10.3 |
| winws.exe (inside the bundled package above) | as shipped | distributed under the bundle's MIT notice (see note) | https://github.com/bol-van/zapret |
| WinDivert (`WinDivert.dll`, `WinDivert64.sys`, inside the bundle) | 2.x (as shipped) | LGPL-3.0-or-later OR GPL-2.0 | https://github.com/basil00/WinDivert |
| cygwin1.dll (inside the bundle) | as shipped | LGPL-2.1-or-later | https://cygwin.com/ |

## yt-dlp — Unlicense

```
This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or
distribute this software, either in source code form or as a compiled
binary, for any purpose, commercial or non-commercial, and by any
means.

In jurisdictions that recognize copyright laws, the author or authors
of this software dedicate any and all copyright interest in the
software to the public domain. We make this dedication for the benefit
of the public at large and to the detriment of our heirs and
successors. We intend this dedication to be an overt act of
relinquishment in perpetuity of all present and future rights to this
software under copyright law.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

For more information, please refer to <https://unlicense.org>
```

## certifi — Mozilla Public License 2.0

MPL-2.0 applies to the certifi library (https://github.com/certifi/python-certifi).
The root of those files includes the MPL license. Full text:
https://www.mozilla.org/en-US/MPL/2.0/

Certifi is a collection of root certificates provided under the
Mozilla Public License 2.0 as published on the certifi repository.
The certificate data itself is provided by Mozilla and other
organizations under their respective copyrights.

## urllib3 — MIT License

```
MIT License

Copyright (c) 2008-2020 Andrey Petrov and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```

## idna — BSD 3-Clause License

Copyright (c) 2013-2024, Kim Davies and contributors.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in
   the documentation and/or other materials provided with the
   distribution.
3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived
   from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

Full text: https://github.com/kjd/idna/blob/master/LICENSE.md

## cffi — MIT-0 License

Copyright (c) 2005-2024 Armin Rigo, Maciej Fijalkowski and contributors.

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Full text: https://github.com/python-cffi/cffi/blob/main/LICENSE.md

## cryptography — Apache-2.0 OR BSD-3-Clause

cryptography is dual-licensed under the Apache License 2.0 and the BSD
3-Clause "Revised" License (you may use either). The final Apache-2.0
and BSD-3-Clause texts: https://github.com/pyca/cryptography/blob/main/LICENSE

```text
This product includes software developed by the Python Cryptographic
Authority and individual contributors (https://github.com/pyca/cryptography).
```

## CPython / tkinter — Python Software Foundation License

Copyright (c) 2001-present Python Software Foundation; All Rights
Reserved. Redistribution and use in source and binary forms, with or
without modification, are permitted provided that the conditions in
the PSF License Agreement are met. The full license text is available
at http://www.python.org/psf/license/ and is distributed with CPython
in the file `LICENSE`.

## pywebview — BSD 3-Clause License

Copyright (c) 2017 Roman Frołow and other contributors.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in
   the documentation and/or other materials provided with the
   distribution.
3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived
   from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

Full text: https://github.com/r0x0r/pywebview/blob/master/LICENSE

## Alpine.js — MIT License

The MIT License (MIT)

Copyright © 2019-2025 Caleb Porzio and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Motion — MIT License

The MIT License (MIT)

Copyright (c) 2024 [Motion](https://motion.dev) B.V.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## pythonnet, clr_loader, proxy_tools — MIT License

Copyright (c) respective authors and contributors (pythonnet/clr_loader:
Python.NET; proxy_tools: TkTech).

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

Full texts:
- pythonnet: https://github.com/pythonnet/pythonnet/blob/master/LICENSE
- clr_loader: https://github.com/pythonnet/clr-loader/blob/main/LICENSE
- proxy_tools: https://github.com/TkTech/proxy_tools/blob/master/LICENSE

## bottle — MIT License

Copyright (c) 2009-2024 Marcel Hellkamp.

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

Full text: https://github.com/bottlepy/bottle/blob/master/LICENSE

## PyInstaller — GPL-2.0-or-later with special exception

PyInstaller is only used to build the standalone executable and is not
part of the distributed program's runtime code. It is licensed under
the GPL with a special exception that explicitly permits distributing
programs built with it, including when those programs are not
licensed under the GPL:

> As a special exception, you may use, modify and redistribute this
> program under the terms of the GNU General Public License version 2
> or its successors, and additionally you may license programs built
> with this program under any license of your choice.

Full text: https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt

## ffmpeg — downloaded at first run, NOT bundled

The built executable uses the `ffmpeg` executable for merging streams,
embedding metadata/subtitles and HEVC conversion. ffmpeg is **not
bundled** with this project. On first launch, the app offers to download
and install ffmpeg automatically into `%LOCALAPPDATA%\Synfronia\bin`
(from https://www.gyan.dev/ffmpeg/builds/); it can also be installed
manually (PATH / winget). ffmpeg is distributed under the GNU
GPL (or LGPL depending on the specific build). The build used for
testing was the GPL build from https://www.gyan.dev/ffmpeg/builds/.
Full text: https://www.gnu.org/licenses/gpl-3.0.html

## Bundled test fonts — SIL Open Font License 1.1

One variable font is bundled in `assets/fonts` and is laid out into
`%LOCALAPPDATA%\Synfronia\fonts` on first launch, so a clean install works
offline and the font list is never empty. The "Reload fonts" button
re-scans the folder; the "Download fonts" button re-downloads the same
file from the source below.

| File | Family | Coverage | Upstream file |
|---|---|---|---|
| `JetBrainsMono.ttf` | JetBrains Mono | Latin, Greek, Cyrillic | `ofl/jetbrainsmono/JetBrainsMono[wght].ttf` |

Source: https://github.com/google/fonts (unmodified upstream binary).
The full license text is shipped next to the font as
`OFL-JetBrainsMono.txt` and is copied into the user's fonts folder on
first launch. Copyright of the font stays with its upstream authors:

- JetBrains Mono — Copyright (c) 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)

Releases up to (but not including) v1.2.7 also bundled Inter and Noto
Sans under the same OFL-1.1; they were removed from the distribution, so
their licenses apply only to those older builds (their texts remain in
the git history and in the corresponding tags).

CJK glyphs (Japanese, Chinese, Korean) are not covered by this file; the
app falls back to the system font for those scripts.

## Bundled bypass package — MIT (with WinDivert / cygwin notices)

A ready-to-run bypass bundle is bundled in `assets/bypass`
(`zapret-discord-youtube-1.10.3.zip`, unmodified upstream release) and is
laid out into `%LOCALAPPDATA%\Synfronia\Bypass\zapret-discord-youtube-1.10.3`
on first launch, so a clean install can enable a basic bypass **without
network access** — exactly like the bundled test fonts. The license text is
copied next to the extracted files as `LICENSE-flowseal.txt`.

Source: https://github.com/Flowseal/zapret-discord-youtube/releases/tag/1.10.3

The package is distributed by its authors under the MIT License
(`LICENSE-flowseal.txt`, reproduced in `assets/bypass/`):

```
MIT License

Copyright (c) 2016-2026 bol-van
Copyright (c) 2024-2026 Flowseal

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Third-party binaries inside that package are redistributed **unmodified, as
part of the package**, under their own terms:

- **WinDivert** (`bin/WinDivert.dll`, `bin/WinDivert64.sys`) is dual-licensed:
  LGPL-3.0-or-later **or** GPL-2.0, at your option. It is aggregated with (not
  linked into) this program; no modifications are made to it.
  Full texts: https://github.com/basil00/WinDivert/blob/master/LICENSE
- **cygwin1.dll** (`bin/cygwin1.dll`) is part of the Cygwin project and is
  distributed under the GNU LGPL v2.1 (with the Cygwin linking exception).
  Full text: https://cygwin.com/licensing.html
- **winws.exe** is built from [bol-van/zapret](https://github.com/bol-van/zapret).
  The upstream zapret repository currently carries **no license file**, so the
  terms on which this executable is redistributed here are those of the
  bundle that ships it (the MIT notice above, which names bol-van as a
  copyright holder). Upstream: https://github.com/bol-van/zapret

This project's own PolyForm Noncommercial License does not apply to these
components; each keeps its own license, and no claim of ownership is made
over them.

## CSS / visual references (rain & liquid-glass effects)

The "rain behind glass" animation and the "Liquid Glass" look are based on
publicly available CSS design references, adapted (not copied verbatim):
- "Liquid Rain Glass" & three-layer seamless rain — technique from
  freefrontend.com collection "CSS Rain" (2018, by TralahMuck; MIT):
  https://freefrontend.com/css-rain/ and the original Pen
  https://codepen.io/TralahMuck/pen/GZvKba
- Freefrontend "Liquid Glass UI" examples referenced for glass panels,
  capsule controls and backdrop-filter layering:
  - "Liquid Glass Morphism UI" https://freefrontend.com/ glass collection
- Glass highlights, inset edges and high-opacity cores follow the common
  "glassmorphism / liquid glass" style (UI gradients), described at
  https://freefrontend.com/
- Control widgets: g200kg "webaudio-controls"
  (https://github.com/g200kg/webaudio-controls, Apache-2.0) is a behavioral
  reference only — interaction idioms for our knobs/switches (vertical drag,
  Shift fine tuning, double-click reset). The project ships its own inline-SVG
  widgets colored by `currentColor`/theme variables; no code, canvas images or
  assets from that library are bundled.

All CSS in this project is original code (own animation frames, own color
palette, own transform/backdrop layers) written after studying the above
references' visual technique; no copyrighted assets, fonts or images are
bundled from these references. Rain tile sizes, animation timings and
drop emission effects were re-implemented from scratch.

## Color palettes (UI themes)

UI themes are based on publicly shared color palettes published on
color-hex.com ("Technology Day", "Technology Pinks").
Palettes are used for UI colors only and are subject to the palettes'
own terms of use (personal/non-commercial use as stated on
color-hex.com). Source: https://color-hex.com/

---

### Known issue (tag 1.2.5): rain rendering

As of tag 1.2.5 the rain animation may render misaligned / flickering on
some GPUs and WebView2/Chromium versions (background-position layers with
different tile heights can produce a visible "seam"/sag). This was a
temporary visual state; the rain layer has since been removed from the
theme (see later tags). See `THIRD_PARTY_NOTICES` above for the original
technique reference.

Project code: Copyright © 2026 vilminessa, licensed under the
PolyForm Noncommercial License 1.0.0 (see `LICENSE`).