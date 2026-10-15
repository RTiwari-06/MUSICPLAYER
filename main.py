from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ui.main_window import MainWindow
from app.utils import system_check


def _setup_logging() -> None:
    """
    Configure application-wide logging with file output and console.

    Logs are written to the platform-appropriate config directory
    (~/.config/musicplayer/logs/ on Linux, %LOCALAPPDATA%/MusicPlayer/logs/ on Windows).
    """
    try:
        home = Path.home()
        if os.name == "nt":
            log_dir = home / "AppData" / "Local" / "MusicPlayer" / "logs"
        else:
            log_dir = home / ".config" / "musicplayer" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"
    except Exception:
        log_file = Path.cwd() / "app.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> None:
    """
    Application entry point.

    Configures logging, verifies system environment on launch and starts
    the main GUI loop.
    """
    _setup_logging()

    # Verify system environment (creates settings context via system_check)
    try:
        _ = system_check.check_all()
    except Exception:
        logging.getLogger(__name__).warning(
            "System check failed at startup", exc_info=True
        )

    app = MainWindow()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        # Ctrl+C in the launching terminal: close the window cleanly
        app.destroy()


if __name__ == "__main__":
    main()
