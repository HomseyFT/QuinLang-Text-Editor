"""
Auto-updater for QuinLang IDE.
Checks GitHub releases and downloads updates automatically.
"""
from __future__ import annotations
import sys
import os
import json
import threading
import tempfile
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Callable, Tuple
from dataclasses import dataclass
import urllib.request
import urllib.error


# Configuration - UPDATE THESE FOR YOUR REPO
GITHUB_OWNER = "YOUR_GITHUB_USERNAME"  # Change this!
GITHUB_REPO = "QuinLang-IDE"
CURRENT_VERSION = "0.1.0"  # Increment this with each release


@dataclass
class ReleaseInfo:
    """Information about a GitHub release."""
    version: str
    download_url: str
    release_notes: str
    published_at: str


def get_current_version() -> str:
    """Get the current application version."""
    return CURRENT_VERSION


def is_frozen() -> bool:
    """Check if running as a frozen executable (PyInstaller)."""
    return getattr(sys, 'frozen', False)


def get_executable_path() -> Optional[Path]:
    """Get the path to the current executable."""
    if is_frozen():
        return Path(sys.executable)
    return None


def parse_version(version: str) -> Tuple[int, ...]:
    """Parse version string to tuple for comparison."""
    # Remove 'v' prefix if present
    version = version.lstrip('v')
    try:
        return tuple(int(x) for x in version.split('.'))
    except (ValueError, AttributeError):
        return (0,)


def is_newer_version(remote: str, current: str) -> bool:
    """Check if remote version is newer than current."""
    return parse_version(remote) > parse_version(current)


def check_for_updates() -> Optional[ReleaseInfo]:
    """
    Check GitHub for a newer release.
    Returns ReleaseInfo if update available, None otherwise.
    """
    if GITHUB_OWNER == "YOUR_GITHUB_USERNAME":
        # Not configured yet
        return None
    
    api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    
    try:
        request = urllib.request.Request(
            api_url,
            headers={'Accept': 'application/vnd.github.v3+json'}
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        remote_version = data.get('tag_name', '').lstrip('v')
        
        if not is_newer_version(remote_version, CURRENT_VERSION):
            return None
        
        # Find the right asset for this platform
        assets = data.get('assets', [])
        download_url = None
        
        if sys.platform == 'win32':
            for asset in assets:
                if 'windows' in asset['name'].lower() and asset['name'].endswith('.exe'):
                    download_url = asset['browser_download_url']
                    break
        else:  # Linux
            for asset in assets:
                if 'linux' in asset['name'].lower() and not asset['name'].endswith('.exe'):
                    download_url = asset['browser_download_url']
                    break
        
        if not download_url:
            return None
        
        return ReleaseInfo(
            version=remote_version,
            download_url=download_url,
            release_notes=data.get('body', ''),
            published_at=data.get('published_at', ''),
        )
    
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        return None


def download_update(
    release: ReleaseInfo,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> Optional[Path]:
    """
    Download the update to a temporary file.
    Returns path to downloaded file, or None on failure.
    """
    try:
        # Create temp file with appropriate extension
        suffix = '.exe' if sys.platform == 'win32' else ''
        fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix='quinlang_update_')
        os.close(fd)
        temp_path = Path(temp_path)
        
        request = urllib.request.Request(release.download_url)
        
        with urllib.request.urlopen(request, timeout=60) as response:
            total_size = int(response.headers.get('Content-Length', 0))
            downloaded = 0
            chunk_size = 8192
            
            with open(temp_path, 'wb') as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if progress_callback and total_size:
                        progress_callback(downloaded, total_size)
        
        return temp_path
    
    except (urllib.error.URLError, IOError, TimeoutError):
        return None


def apply_update(downloaded_path: Path) -> bool:
    """
    Apply the downloaded update by replacing the current executable.
    Returns True if successful.
    """
    if not is_frozen():
        # Can't auto-update when running from source
        return False
    
    current_exe = get_executable_path()
    if not current_exe:
        return False
    
    try:
        if sys.platform == 'win32':
            # On Windows, we need to use a batch script to replace the exe
            # because the running exe is locked
            batch_script = tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.bat',
                delete=False
            )
            
            script_content = f'''@echo off
timeout /t 2 /nobreak >nul
move /y "{downloaded_path}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
'''
            batch_script.write(script_content)
            batch_script.close()
            
            # Run the batch script and exit
            subprocess.Popen(
                ['cmd', '/c', batch_script.name],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True
        
        else:
            # On Linux, we can replace directly then restart
            # Make the downloaded file executable
            os.chmod(downloaded_path, 0o755)
            
            # Replace the current executable
            shutil.move(str(downloaded_path), str(current_exe))
            
            # Restart the application
            os.execv(str(current_exe), [str(current_exe)] + sys.argv[1:])
            return True
    
    except (IOError, OSError):
        return False


class UpdateChecker:
    """Background update checker with callbacks."""
    
    def __init__(
        self,
        on_update_available: Optional[Callable[[ReleaseInfo], None]] = None,
        on_no_update: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self._on_update_available = on_update_available
        self._on_no_update = on_no_update
        self._on_error = on_error
    
    def check_async(self):
        """Check for updates in background thread."""
        thread = threading.Thread(target=self._check_impl, daemon=True)
        thread.start()
    
    def _check_impl(self):
        """Internal check implementation."""
        try:
            release = check_for_updates()
            if release:
                if self._on_update_available:
                    self._on_update_available(release)
            else:
                if self._on_no_update:
                    self._on_no_update()
        except Exception as e:
            if self._on_error:
                self._on_error(str(e))
