from __future__ import annotations

import platform
import subprocess


def get_creationflags() -> int:
    """
    Return subprocess creation flags for Windows to hide command windows.

    Returns:
        int: CREATE_NO_WINDOW flag on Windows, else 0.
    """
    if platform.system() == "Windows":
        return subprocess.CREATE_NO_WINDOW
    return 0
