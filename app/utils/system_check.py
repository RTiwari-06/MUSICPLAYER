from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from app.utils.platform_utils import get_creationflags

logger = logging.getLogger(__name__)


def _command_exists(cmd: str) -> bool:
    """
    Check if a command exists in the system PATH.

    Args:
        cmd: The command name to check (e.g., "ffmpeg", "deno").

    Returns:
        bool: True if command is found, False otherwise.
    """
    path = shutil.which(cmd)
    return path is not None


def check_python() -> Dict[str, Any]:
    """
    Check if Python is installed and available.

    Returns:
        Dict[str, Any]: {"available": bool, "path": str | None, "version": str | None}.
    """
    try:
        result = subprocess.run(
            [sys.executable, "--version"],
            capture_output=True,
            text=True,
            creationflags=get_creationflags(),
        )
        version = result.stdout.strip() or result.stderr.strip() or None
        return {"available": result.returncode == 0, "path": Path(sys.executable).resolve().as_posix(), "version": version}
    except Exception as e:
        logger.warning("Python check failed: %s", e, exc_info=True)
        return {"available": False, "path": None, "version": f"error: {e}"}


def check_pip() -> Dict[str, Any]:
    """
    Check if pip is installed and available.

    Returns:
        Dict[str, Any]: {"available": bool, "path": str | None, "version": str | None}.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            creationflags=get_creationflags(),
        )
        version = result.stdout.strip() or result.stderr.strip() or None
        return {"available": result.returncode == 0, "path": None, "version": version}
    except Exception as e:
        logger.warning("pip check failed: %s", e, exc_info=True)
        return {"available": False, "path": None, "version": f"error: {e}"}


def _find_spotdl_binary(name: str) -> Optional[Path]:
    """
    Find a spotdl-managed binary in the user's spotdl data directory.

    spotdl installs ffmpeg/deno into ~/.spotdl (or ~/.config/spotdl),
    which is not on PATH, so PATH-only checks report false negatives.

    Args:
        name: Binary name (e.g., "ffmpeg", "deno").

    Returns:
        Optional[Path]: Path to the binary if found, else None.
    """
    suffix = ".exe" if platform.system() == "Windows" else ""
    home = Path.home()
    for base in (home / ".config" / "spotdl", home / ".spotdl"):
        candidate = base / (name + suffix)
        try:
            if candidate.is_file():
                return candidate
        except Exception:
            continue
    return None


def check_ffmpeg() -> Dict[str, Any]:
    """
    Check if ffmpeg is available on PATH or in the spotdl data directory.

    Returns:
        Dict[str, Any]: {"available": bool, "path": str | None, "version": str | None}.
    """
    path = shutil.which("ffmpeg") or _find_spotdl_binary("ffmpeg")
    if path is None:
        return {"available": False, "path": None, "version": None}
    resolved = Path(path).resolve().as_posix()
    # Detect version for compatibility checking
    try:
        result = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=get_creationflags(),
        )
        version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
    except Exception:
        version_line = "unknown"
    return {"available": True, "path": resolved, "version": version_line}


def check_deno() -> Dict[str, Any]:
    """
    Check if deno is available on PATH or in the spotdl data directory.

    Returns:
        Dict[str, Any]: {"available": bool, "path": str | None, "version": str | None}.
    """
    path = shutil.which("deno") or _find_spotdl_binary("deno")
    if path is None:
        return {"available": False, "path": None, "version": None}
    resolved = Path(path).resolve().as_posix()
    # Detect version for compatibility checking
    try:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=get_creationflags(),
        )
        version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
    except Exception:
        version_line = "unknown"
    return {"available": True, "path": resolved, "version": version_line}


def check_internet(timeout: int = 5) -> Dict[str, Any]:
    """
    Perform a lightweight internet connectivity check.

    Args:
        timeout: Connection timeout in seconds.

    Returns:
        Dict[str, Any]: {"available": bool}.
    """
    try:
        urllib.request.urlopen("https://open.spotify.com", timeout=timeout)
        return {"available": True}
    except Exception:
        return {"available": False}


def check_all() -> Dict[str, Any]:
    """
    Check all required system dependencies.

    Returns:
        Dict[str, Any]: Aggregated results for python, pip, ffmpeg, deno, internet.
    """
    return {
        "python": check_python(),
        "pip": check_pip(),
        "ffmpeg": check_ffmpeg(),
        "deno": check_deno(),
        "internet": check_internet(),
    }


def install_ffmpeg() -> subprocess.Popen[bytes]:
    """
    Trigger spotdl to download ffmpeg via subprocess.Popen.

    Runs: python -m spotdl --download-ffmpeg

    Returns:
        subprocess.Popen[bytes]: The Popen instance for the installation process.
    """
    return subprocess.Popen(
        [sys.executable, "-m", "spotdl", "--download-ffmpeg"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=get_creationflags(),
    )


def install_deno() -> subprocess.Popen[bytes]:
    """
    Trigger spotdl to download deno via subprocess.Popen.

    Runs: python -m spotdl --download-deno

    Returns:
        subprocess.Popen[bytes]: The Popen instance for the installation process.
    """
    return subprocess.Popen(
        [sys.executable, "-m", "spotdl", "--download-deno"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=get_creationflags(),
    )
