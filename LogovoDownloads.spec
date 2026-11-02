# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH)
asset_root = project_root / ".build-assets" / "ffmpeg-9.0.2-deno-2.9.5"
binary_dir = asset_root / "bin"
license_dir = asset_root / "licenses"
required_assets = [
    binary_dir / "ffmpeg.exe",
    binary_dir / "ffprobe.exe",
    binary_dir / "deno.exe",
    license_dir / "FFmpeg-GPLv3.txt",
    license_dir / "Deno-MIT.txt",
    license_dir / "asset-manifest.json",
    project_root / "THIRD_PARTY_NOTICES.md",
]
missing_assets = [str(path) for path in required_assets if not path.is_file()]
if missing_assets:
    raise SystemExit(
        "Build assets are missing. Run `python tools/prepare_build_assets.py` first.\n"
        + "\n".join(missing_assets)
    )

a = Analysis(
    [str(project_root / 'main.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / 'media'), 'media'),
        (str(binary_dir), 'bin'),
        (str(project_root / 'THIRD_PARTY_NOTICES.md'), '.'),
        (str(license_dir), 'licenses'),
    ],
    hiddenimports=[
        'mutagen',
        'mutagen.id3',
        'mutagen.mp3',
        'mutagen.flac',
        'mutagen.mp4',
        'mutagen.oggopus',
        'mutagen.oggvorbis',
        'curl_cffi',
        'PIL',
        'PIL.Image',
        'requests',
        'yt_dlp',
        'yt_dlp.compat',
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
    ],
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
    [],
    exclude_binaries=True,
    name='Logovo-Downloads',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(project_root / 'media' / 'icon.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Logovo-Downloads',
)
