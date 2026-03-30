# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for building standalone paranoid binary.

This creates a single-file executable that bundles Python interpreter
and all dependencies.

Usage:
    pyinstaller paranoid.spec

Output:
    - dist/paranoid (Linux/macOS)
    - dist/paranoid.exe (Windows)
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect all data files from packages that need them
datas = []
datas += collect_data_files('anthropic')
datas += collect_data_files('openai')
datas += collect_data_files('pydantic')
datas += collect_data_files('fastembed')

# Include seeds directory for threat patterns
datas += [('seeds', 'seeds')]

# Collect all submodules that might be dynamically imported
hiddenimports = []
hiddenimports += collect_submodules('anthropic')
hiddenimports += collect_submodules('openai')
hiddenimports += collect_submodules('pydantic')
hiddenimports += collect_submodules('httpx')
hiddenimports += collect_submodules('click')
hiddenimports += collect_submodules('backend')
hiddenimports += collect_submodules('cli')
hiddenimports += collect_submodules('fastembed')
hiddenimports += collect_submodules('PIL')

# Add specific hidden imports that PyInstaller might miss
hiddenimports += collect_submodules('aiofiles')
hiddenimports += [
    'aiosqlite',
    'sqlite3',
    'asyncio',
    'json',
    'pathlib',
    'importlib.metadata',
    'sqlite_vec',
    'PIL.Image',
    'aiofiles',
    'aiofiles.os',
    'aiofiles.threadpool',
]

block_cipher = None

a = Analysis(
    ['cli/main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'tkinter',
        'scipy',
        'IPython',
        'jupyter',
        'notebook',
        'tests',
        'frontend',
    ],
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
    name='paranoid',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Can add icon later if desired
)
