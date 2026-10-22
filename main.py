"""SpotDL_GUI application entry point.

Production-safe falloff for running as both a console script in development
and a PyInstaller-frozen ``--windowed`` executable.

In a frozen build the process can be re-entered in three roles:

* default role          – runs the GUI after ``freeze_support()`` guards the
                          multiprocessing bootstrap.
* real child process    – a ``spawn``-based multiprocessing worker created by
                          the ``multiprocessing`` machinery; it runs the main
                          script again as ``__mp_main__``, in which case
                          ``__name__`` is NOT ``"__main__"`` and nothing below
                          the guard executes.
* fetch child process   – ``SpotDLManager.fetch_tracks()`` relaunches the
                          packaged executable as
                          ``<exe> --fetch-child <url>...``; the arg dispatch
                          below routes that to the metadata protocol child.
* spotdl child process  – ``SpotDLManager`` / ``system_check`` relaunch the
                          packaged executable as ``<exe> --spotdl <args>``
                          to run the bundled spotDL CLI without a GUI.
"""

from __future__ import annotations

import os
import sys
import multiprocessing
from pathlib import Path

# Fix relative path resolution for PyInstaller bundle context.
# Notes:
# * ``sys._MEIPASS`` is the onefile extraction dir (or onedir "_internal" in
#   PyInstaller >= 6), so chdir'ing there keeps asset lookups that assume a
#   relative CWD working and stops writes landing next to the .exe,
# * the ``sys.executable``-based fallback (onedir / non-PyInstaller frozen) is
#   the location of the real bundle so relative assets still resolve.
if getattr(sys, "frozen", False):
    _MEIPASS = getattr(sys, "_MEIPASS", None)
    BUNDLE_DIR = Path(_MEIPASS) if _MEIPASS else Path(sys.executable).parent
    os.chdir(BUNDLE_DIR)

# Argv dispatch for the frozen relaunch roles
_FETCH_CHILD_FLAG = "--fetch-child"
_SPOTDL_FLAG = "--spotdl"


def _restore_stdio() -> None:
    """Rebuild std streams nulled out by PyInstaller ``--windowed`` mode.

    The fetch protocol child prints structured lines on stdout; PyInstaller
    ``--noconsole`` builds replace stdout/stderr with ``None``, so messages
    become no-ops and the parent sees an empty (hanging) fetch. This attaches
    a writable, UTF-8 ``TextIOBase`` to every missing (or closed) stream:

    * the real fd 1 / 2 when they are actually open — for protocol children
      the parent spawns them with ``stdout=subprocess.PIPE``, so writes travel
      through the pipe unchanged. ``buffering=1`` (line buffering) guarantees
      the parent's ``readline()`` never starves on an incomplete line;
    * ``os.devnull`` when the underlying fd is unusable (windowed GUI role,
      launched without a console) — guaranteeing ``print()`` and library
      writes never raise ``AttributeError``/``OSError`` afterwards.
    """
    for name, fd in (("stdout", 1), ("stderr", 2)):
        current = getattr(sys, name, None)
        if current is not None and not getattr(current, "closed", False):
            continue  # already a valid writable stream
        new_stream = None
        dup_fd = -1
        try:
            os.fstat(fd)               # raises if fd is closed/invalid
            dup_fd = os.dup(fd)        # claim our own reference
            new_stream = open(
                dup_fd,
                "w",
                encoding="utf-8",
                errors="replace",
                buffering=1,           # line-buffered protocol output
            )
        except OSError:
            if dup_fd >= 0:
                try:
                    os.close(dup_fd)
                except OSError:
                    pass
        if new_stream is None:
            try:
                # No usable fd: the stream protocol has no target pipe here
                # (only true windowed GUI mode reaches this branch — protocol
                # children are always spawned with a real stdout pipe).
                new_stream = open(
                    os.devnull, "w", encoding="utf-8", errors="replace"
                )
            except OSError:
                continue
        setattr(sys, name, new_stream)


def _run_fetch_child(urls: list[str]) -> None:
    """Slave mode: execute the standalone fetch-tracks child protocol.

    Properly exits with the child's exit code so the parent never mistakes a
    crash for an empty track list.
    (Std streams are already restored by main() under PyInstaller.)
    """
    from app.core.fetch_tracks_child import main as fetch_child_main

    sys.argv = [sys.argv[0], *urls]
    fetch_child_main()
    sys.exit(0)


def _run_spotdl_module(args: list[str]) -> None:
    """Frozen relaunch role: run the bundled spotDL CLI.

    spotDL commands cannot be spawned as ``python -m spotdl`` inside a PyInstaller
    bundle, so ``SpotDLManager`` / ``system_check`` re-launch the packaged
    executable with ``--spotdl <args>`` and this role executes the CLI entry
    point in-process (streamable over the child's stdout, killable by PID).
    (Std streams are already restored by main() under PyInstaller.)
    """
    # Replay "python -m spotdl <args>": the console entry point reads sys.argv.
    sys.argv = ["spotdl", *args]

    from spotdl.console import console_entry_point

    console_entry_point()
    sys.exit(0)


def main() -> None:
    """Entry point: route to the fetch child for frozen relaunch, else the GUI."""
    if getattr(sys, "frozen", False):
        # PyInstaller --windowed builds null out sys.stdout / sys.stderr.
        # Restore writable streams up front so every role below (GUI, fetch
        # child, spotdl child) can print / push protocol lines safely.
        _restore_stdio()

    if sys.argv[1:2] == [_FETCH_CHILD_FLAG]:
        _run_fetch_child(sys.argv[2:])
        return

    if sys.argv[1:2] == [_SPOTDL_FLAG]:
        _run_spotdl_module(sys.argv[2:])
        return

    # Import UI modules only after freeze_support / dispatch (kept out of the
    # child role entirely, ensuring no Tk window survives in a spawned child).
    from app.ui.main_window import MainWindow

    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    # Prevent infinite process spawning loops on Windows (PyInstaller freeze_support
    # short-circuits the spawn-style re-exec for real multiprocessing children).
    multiprocessing.freeze_support()
    main()
