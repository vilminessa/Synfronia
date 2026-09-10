# Third-Party Notices

This project (Synfronia) uses the following third-party components.
Their licenses are reproduced or linked below in accordance with the
requirements of each license.

| Component | Version | License | Source |
|---|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 2026.8.19 (bundled) | Unlicense | https://github.com/yt-dlp/yt-dlp |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | 6.22.2 (build-time only) | GPL-2.0-or-later with special exception | https://github.com/pyinstaller/pyinstaller |
| certifi | 2026.7.22 (bundled) | MPL-2.0 | https://github.com/certifi/python-certifi |
| urllib3 | 2.7.0 (bundled) | MIT | https://github.com/urllib3/urllib3 |
| idna | 3.19 (bundled) | BSD-3-Clause | https://github.com/kjd/idna |
| cffi | 2.1.1 (bundled) | MIT-0 | https://github.com/python-cffi/cffi |
| cryptography | 50.0.1 (bundled) | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| CPython / tkinter | 3.14.2 (bundled) | PSF License Agreement | https://www.python.org/ |
| ffmpeg | any recent build (external, NOT bundled) | GPL-2.0-or-later | https://ffmpeg.org/ |

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

## ffmpeg — external tool, NOT distributed

The built executable uses the `ffmpeg` executable for merging streams,
embedding metadata/subtitles and HEVC conversion. ffmpeg is **not
bundled** with this project and must be installed separately (the app
will locate it automatically). ffmpeg is distributed under the GNU
GPL (or LGPL depending on the specific build). The build used for
testing was the GPL build from https://www.gyan.dev/ffmpeg/builds/.
Full text: https://www.gnu.org/licenses/gpl-3.0.html

## Color palettes (UI themes)

UI themes are based on publicly shared color palettes published on
color-hex.com ("Scary Forest", "Technology Day", "Technology Pinks").
Palettes are used for UI colors only and are subject to the palettes'
own terms of use (personal/non-commercial use as stated on
color-hex.com). Source: https://color-hex.com/

---

Project code: Copyright © 2026 vilminessa, licensed under the
PolyForm Noncommercial License 1.0.0 (see `LICENSE`).