from __future__ import annotations

import ctypes
import platform
import subprocess
import sys
from ctypes import wintypes
from typing import List

WM_SETICON = 0x007E
ICON_SMALL = 0
ICON_BIG = 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
GA_ROOT = 2
SM_CXICON = 11
SM_CYICON = 12
SM_CXSMICON = 49
SM_CYSMICON = 50


def is_windows() -> bool:
    """
    Report whether the app is running on Windows.

    Returns:
        bool: True on Windows, else False.
    """
    return platform.system() == "Windows"


def is_frozen() -> bool:
    """
    Report whether the app runs inside a PyInstaller bundle.

    In a frozen build ``sys.executable`` is the packaged app itself, so any
    accidental ``[sys.executable, ...]`` subprocess re-launches the GUI instead
    of the intended tool - the root cause of the infinite window spawn loop.

    Returns:
        bool: True inside a PyInstaller bundle, else False.
    """
    return getattr(sys, "frozen", False)


def _python_module_command(module: str, module_flag: str, args: List[str]) -> List[str]:
    """
    Build a command that runs a Python module from either runtime context.

    * Development: ``python -m <module> <args>``.
    * Frozen build: re-launch the packaged exe with a dispatch flag; ``main.py``
      routes the flag to the hidden subprocess role so no GUI window is created.

    Args:
        module: Python module name (``spotdl``, ``pip``).
        module_flag: Freeze-mode dispatch flag consumed by ``main.py``.
        args: Arguments forwarded to the module.

    Returns:
        List[str]: Command vector ready for ``subprocess``.
    """
    if is_frozen():
        return [sys.executable, module_flag, *args]
    return [sys.executable, "-m", module, *args]


def get_spotdl_command(args: List[str]) -> List[str]:
    """
    Build a command that runs the spotDL CLI in the current runtime context.

    Args:
        args: spotDL arguments, e.g. ``["download", url, ...]``.

    Returns:
        List[str]: Command vector ready for ``subprocess``.
    """
    return _python_module_command("spotdl", "--spotdl", args)


def get_creationflags() -> int:
    """
    Return subprocess creation flags for Windows to hide command windows.

    Returns:
        int: CREATE_NO_WINDOW flag on Windows, else 0.
    """
    if platform.system() == "Windows":
        return subprocess.CREATE_NO_WINDOW
    return 0


def apply_windows_icon(hwnd: int, ico_path: str) -> bool:
    """
    Apply a multi-resolution Windows icon to a top-level window.

    Tk only ever hands a single icon handle to Windows, which then has to
    scale it down for the title bar. Loading the exact system sizes and sending
    ``WM_SETICON`` separately for the small and big variants keeps the title bar
    and the taskbar button crisp instead of showing a stretched square.

    Args:
        hwnd: Window handle of the Tk widget that owns the toplevel.
        ico_path: Path of the ``.ico`` file to load.

    Returns:
        bool: True when at least one icon was applied, else False.
    """
    if not is_windows():
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = wintypes.LPARAM

    root = user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT)
    target = wintypes.HWND(root) if root else wintypes.HWND(hwnd)

    variants = (
        (user32.GetSystemMetrics(SM_CXSMICON), user32.GetSystemMetrics(SM_CYSMICON), ICON_SMALL),
        (user32.GetSystemMetrics(SM_CXICON), user32.GetSystemMetrics(SM_CYICON), ICON_BIG),
    )

    applied = False
    for width, height, kind in variants:
        handle = user32.LoadImageW(
            None, str(ico_path), IMAGE_ICON, width, height, LR_LOADFROMFILE
        )
        if handle:
            user32.SendMessageW(target, WM_SETICON, kind, wintypes.LPARAM(handle))
            applied = True
    return applied
