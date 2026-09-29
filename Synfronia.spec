# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import tempfile
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# Версия из version.py - единственный источник истины; попадает в свойства exe
sys.path.insert(0, SPECPATH)
from version import __version__  # noqa: E402

_v = [int(x) for x in __version__.split(".")]
_v4 = tuple(_v[:4]) + (0,) * (4 - len(_v))
_version_file = os.path.join(tempfile.gettempdir(), "synfronia-version-info.txt")
with open(_version_file, "w", encoding="utf-8") as _fh:
    _fh.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({_v4[0]}, {_v4[1]}, {_v4[2]}, {_v4[3]}),
    prodvers=({_v4[0]}, {_v4[1]}, {_v4[2]}, {_v4[3]}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'Vilminessa'),
            StringStruct('FileDescription', 'Synfronia - download YouTube videos and playlists'),
            StringStruct('FileVersion', '{__version__}'),
            StringStruct('InternalName', 'Synfronia'),
            StringStruct('OriginalFilename', 'Synfronia.exe'),
            StringStruct('ProductName', 'Synfronia'),
            StringStruct('ProductVersion', '{__version__}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")

datas = []
binaries = []
hiddenimports = []
for pkg in ("yt_dlp", "webview"):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
datas += [("based_settings.json", ".")]

# Вшитый тестовый шрифт (JetBrains Mono; OFL 1.1).
# При первом запуске fonts.seed_bundled_fonts() раскладывает его в
# %LOCALAPPDATA%\Synfronia\fonts, поэтому свежая установка работает без сети.
_font_dir = Path(SPECPATH) / "assets" / "fonts"
if _font_dir.is_dir():
    datas += [(str(p), "assets/fonts") for p in sorted(_font_dir.iterdir()) if p.is_file()]
else:
    print(f"WARNING: {[_font_dir]} not found - test fonts will not be bundled")


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Synfronia',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_version_file,
)