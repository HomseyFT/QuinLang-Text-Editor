#!/usr/bin/env python3
"""
Build script for QuinLang IDE executable.

Requirements:
    pip install pyinstaller

Usage:
    python build_exe.py
"""
import subprocess
import sys
import shutil
from pathlib import Path


def main():
    # Check for PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Clean previous builds
    dist_dir = Path("dist")
    build_dir = Path("build")
    
    if dist_dir.exists():
        print("Cleaning dist/...")
        shutil.rmtree(dist_dir)
    
    if build_dir.exists():
        print("Cleaning build/...")
        shutil.rmtree(build_dir)

    # Run PyInstaller
    print("Building executable...")
    result = subprocess.run([
        sys.executable, "-m", "PyInstaller",
        "quinlang_ide.spec",
        "--clean",
    ])

    if result.returncode == 0:
        print("\n✓ Build successful!")
        print(f"  Executable: dist/QuinLangIDE{'.exe' if sys.platform == 'win32' else ''}")
    else:
        print("\n✗ Build failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
