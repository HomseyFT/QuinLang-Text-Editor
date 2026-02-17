# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for QuinLang IDE.

Build with:
    pyinstaller quinlang_ide.spec
"""

block_cipher = None

a = Analysis(
    ['run_ide.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('examples', 'examples'),
    ],
    hiddenimports=[
        'compiler.lexer',
        'compiler.parser',
        'compiler.sema',
        'compiler.codegen_vm',
        'compiler.bytecode',
        'compiler.ast',
        'compiler.types',
        'compiler.builtins',
        'runtime.vm',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

import os

# Icon file (optional - remove if not present)
icon_file = 'icon.ico' if os.path.exists('icon.ico') else None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='QuinLangIDE',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)
