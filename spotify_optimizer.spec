# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Spotify RAM Optimizer.
Build with:  pyinstaller spotify_optimizer.spec
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect all customtkinter assets (themes, json, fonts)
ctk_datas = collect_data_files('customtkinter')

# Collect all submodules of src to ensure nothing is missed
src_submodules = collect_submodules('src')

a = Analysis(
    ['main.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=ctk_datas,
    hiddenimports=[
        'customtkinter',
        'psutil',
        'winreg',
        'win32com',
        'win32com.client',
        'pywintypes',
    ] + src_submodules,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'tensorflow', 'cv2', 'scipy', 'matplotlib'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SpotifyOptimizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # Standard Windows GUI subsystem
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
