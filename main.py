from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ui.main_window import MainWindow
from app.utils import system_check


def main() -> None:
    """
    Application entry point.
    
    Verifies system environment on launch and starts the main GUI loop.
    """
    # Verify system environment (creates settings context via system_check)
    try:
        _ = system_check.check_all()
    except Exception:
        pass
    
    app = MainWindow()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        # Ctrl+C in the launching terminal: close the window cleanly
        app.destroy()


if __name__ == "__main__":
    main()
