# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
for pkg in ("yt_dlp", "webview"):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
datas += [("based_settings.json", ".")]

# Вшитые тестовые шрифты (Inter, JetBrains Mono, Noto Sans; OFL 1.1).
# При первом запуске fonts.seed_bundled_fonts() раскладывает их в
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
)