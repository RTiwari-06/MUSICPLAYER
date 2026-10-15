# Music SpotDL — Improvement Roadmap

> Comprehensive analysis of the MUSICPLAYER project covering **Optimization**, **Security**, **Network/Internet Speed**, **Drivers & System Integration**, **User Interface**, and **Framework Support**.
>
> Each item includes the **root cause**, **affected file(s)**, **current problematic code**, and a **concrete remediation** with implementation guidance.

---

## Table of Contents

1. [Optimization (Performance & Resource Management)](#1-optimization)
2. [Security Vulnerabilities](#2-security-vulnerabilities)
3. [Internet Speed & Network Throughput](#3-internet-speed--network-throughput)
4. [Drivers & Hardware/System Integration](#4-drivers--hardwaresystem-integration)
5. [User Interface (UI/UX)](#5-user-interface-uiux)
6. [Framework Support & Modernization](#6-framework-support--modernization)
7. [Implementation Priority & Action Plan](#7-implementation-priority--action-plan)

---

## 1. Optimization

### 1.1 — Fix Subprocess Pipe Deadlock (Critical)

**File:** `app/core/spotdl_wrapper.py` — `_stream_output()` (lines 507–550)

**Root Cause:**
`stdout` and `stderr` are read **sequentially**. If `spotDL` or `FFmpeg` fills the OS pipe buffer for `stderr` (~64 KB on Windows) while Python is blocked reading `stdout`, the child process blocks waiting for the pipe to drain. Python is simultaneously blocked waiting for `stdout` EOF. The application **deadlocks permanently**.

**Current Code (Problematic):**
```python
if process.stdout:
    if self._read_pipe_stream(process.stdout, callback) is not None:
        return True
if process.stderr and not self._cancelled:
    if self._read_pipe_stream(process.stderr, callback) is not None:
        return True
```

**Remediation — Option A (Simplest):**
Merge stderr into stdout at subprocess creation so only one pipe needs reading:
```python
process = subprocess.Popen(
    current_cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,   # <-- merge streams
    creationflags=_get_creationflags(),
)
```
> **NOTE:** This is already done correctly in `fetch_tracks()` (line 672). Apply the same pattern to `_run_command_chain()`.

**Remediation — Option B (Preserves Separate Streams):**
Read both pipes concurrently in separate daemon threads:
```python
import queue

def _stream_output(self, process, callback=None):
    result_queue = queue.Queue()

    def _reader(pipe, name):
        for line in iter(pipe.readline, b''):
            result_queue.put((name, line))
        result_queue.put((name, None))  # sentinel

    t_out = threading.Thread(target=_reader, args=(process.stdout, "stdout"), daemon=True)
    t_err = threading.Thread(target=_reader, args=(process.stderr, "stderr"), daemon=True)
    t_out.start()
    t_err.start()

    closed = set()
    while len(closed) < 2:
        name, line = result_queue.get()
        if line is None:
            closed.add(name)
            continue
        status = self._parse_log_line(line.decode('utf-8', errors='replace'))
        if self._try_fallback(status):
            return True
        self._emit_status(callback, status)

    process.wait()
    return False
```

---

### 1.2 — Eliminate Disk I/O Thrashing in Session Stats (High)

**File:** `app/ui/main_window.py` — `_refresh_session_stats()` (lines 705–722)

**Root Cause:**
`os.walk()` recursively traverses the **entire music library** on the main GUI thread after every single downloaded song. If the download directory has hundreds/thousands of files, this freezes the UI and degrades disk throughput.

**Current Code (Problematic):**
```python
def _refresh_session_stats(self) -> None:
    total_bytes = 0
    for dirpath, _dirnames, filenames in os.walk(self.config_manager.download_directory):
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            if os.path.getmtime(file_path) >= self._session_start:
                total_bytes += os.path.getsize(file_path)
    self._session_bytes = total_bytes
```

**Remediation:**
Track bytes incrementally instead of scanning the disk:
```python
def _refresh_session_stats(self, new_file_path: str = None) -> None:
    """Incrementally update session stats with a newly downloaded file."""
    if new_file_path:
        try:
            self._session_bytes += os.path.getsize(new_file_path)
        except OSError:
            pass
    self.session_stats_label.configure(
        text=f"Session: {self._session_files} files | {self._session_bytes / 1048576:.1f} MB"
    )
```
Then in `_callback()`, parse the downloaded filename from the spotDL log line (lines starting with `Downloaded "`) and pass it to `_refresh_session_stats(filepath)`.

---

### 1.3 — Batch-Render Track Checkboxes During Fetch (Medium)

**File:** `app/ui/main_window.py` — `_add_track_row()` (lines 874–894)

**Root Cause:**
Each fetched track immediately creates and mounts a full `CTkCheckBox` widget on the Tkinter main loop. Fetching 200–500 tracks causes perceptible UI lag and unresponsiveness.

**Remediation:**
Buffer incoming track metadata and render in batches:
```python
def __init__(self):
    ...
    self._pending_tracks: list = []
    self._batch_render_id = None

def _add_track_row(self, track: Dict[str, Any]) -> None:
    self._pending_tracks.append(track)
    if self._batch_render_id is None:
        self._batch_render_id = self.after(100, self._render_track_batch)

def _render_track_batch(self) -> None:
    batch = self._pending_tracks[:20]
    self._pending_tracks = self._pending_tracks[20:]
    for track in batch:
        # ... create CTkCheckBox as before ...
        pass
    if self._pending_tracks:
        self._batch_render_id = self.after(100, self._render_track_batch)
    else:
        self._batch_render_id = None
```

---

### 1.4 — Fix Incomplete Process Tree Termination (High)

**File:** `app/core/spotdl_wrapper.py` — `cancel_download()` (lines 792–821)

**Root Cause:**
On Windows, calling `process.terminate()` on the parent Python process does **not** kill its child processes. `ffmpeg.exe` and `yt-dlp` continue running in the background, consuming CPU and network bandwidth.

**Remediation — Option A (No External Dependency):**
```python
import os

def cancel_download(self) -> None:
    with self._lock:
        self._cancelled = True
        process = self._process

    if process:
        try:
            if platform.system() == "Windows":
                # Kill entire process tree on Windows
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    capture_output=True,
                )
            else:
                import signal
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
```

**Remediation — Option B (With `psutil`):**
```python
import psutil

def cancel_download(self) -> None:
    ...
    if process:
        try:
            parent = psutil.Process(process.pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
        except psutil.NoSuchProcess:
            pass
```

---

### 1.5 — Duplicate `_get_creationflags()` Function (Low)

**Files:** `app/core/spotdl_wrapper.py` (line 24) **AND** `app/utils/system_check.py` (line 11)

**Root Cause:** Identical function defined in two files. Violation of DRY principle.

**Remediation:**
Move to a shared utility module (e.g., `app/utils/platform_utils.py`) and import in both files:
```python
# app/utils/platform_utils.py
import platform, subprocess

def get_creationflags() -> int:
    if platform.system() == "Windows":
        return subprocess.CREATE_NO_WINDOW
    return 0
```

---

## 2. Security Vulnerabilities

### 2.1 — CLI Argument Injection via Unsanitized URL Input (Critical)

**File:** `app/core/spotdl_wrapper.py` — `download_track_or_playlist()` (lines 624–635)

**Root Cause:**
User input from `url_entry` is unpacked directly into the subprocess command list:
```python
cmd = [
    sys.executable, "-m", "spotdl", "download",
    *url_list,   # <-- Unsanitized user input
    "--output", str(self._current_output_path / output_template),
]
```
A user (or a malicious pasted link) could inject spotDL CLI arguments like `--config /path/to/malicious_config` or `--proxy attacker-server.com`.

**Remediation:**
Add URL validation before any subprocess execution:
```python
import re

SPOTIFY_URL_RE = re.compile(
    r"^https?://open\.spotify\.com/(track|album|playlist|artist)/[a-zA-Z0-9]+(\?.*)?$"
)

def _validate_url(self, url: str) -> bool:
    """Return True if `url` is a valid Spotify URL."""
    return bool(SPOTIFY_URL_RE.match(url))

# In download_track_or_playlist():
for u in url_list:
    if not self._validate_url(u):
        self._emit_status(callback, {
            "status": "error",
            "message": f"Invalid Spotify URL: {u[:80]}",
        })
        return
```

---

### 2.2 — Path Traversal via Output Template (High)

**File:** `app/core/config.py` — `set()` method (lines 183–187)

**Root Cause:**
`output_template` accepts **any** string without path safety validation:
```python
elif key == "output_template":
    if isinstance(value, str) and value:
        self._settings[key] = value
        return True
```
A template like `../../../../Windows/System32/{title}.{output-ext}` would write files outside the download directory.

**Remediation:**
Validate the resolved path stays inside the download directory:
```python
elif key == "output_template":
    if isinstance(value, str) and value:
        # Reject absolute paths and directory traversal
        if value.startswith(("/", "\\")) or ".." in value:
            return False
        # Test with a sample filename
        test_name = value.replace("{title}", "test").replace("{output-ext}", "mp3")
        test_name = test_name.replace("{artist}", "a").replace("{album}", "b")
        dl_dir = Path(self._settings.get("download_directory", "."))
        resolved = (dl_dir / test_name).resolve()
        if not str(resolved).startswith(str(dl_dir.resolve())):
            return False
        self._settings[key] = value
        return True
```

---

### 2.3 — Arbitrary Code Execution via Embedded Python Script (Medium)

**File:** `app/core/spotdl_wrapper.py` — `FETCH_CHILD_SCRIPT` (lines 36–102)

**Root Cause:**
A 65-line Python script is embedded as a raw string and executed via `subprocess.Popen([sys.executable, "-c", FETCH_CHILD_SCRIPT, ...])`. While it is not user-modifiable at runtime, this pattern:
- Bypasses static analysis and linting for the embedded code
- Is fragile against spotDL API changes (no import validation at startup)
- Makes debugging very difficult (no source file, no line numbers in tracebacks)

**Remediation:**
Extract `FETCH_CHILD_SCRIPT` into a standalone Python file:
```
app/core/fetch_tracks_child.py
```
Then invoke it as a module:
```python
cmd = [sys.executable, str(Path(__file__).parent / "fetch_tracks_child.py"), *url_list]
```

---

### 2.4 — Missing Dependency Pinning (High)

**Root Cause:**
The repository has **no** `requirements.txt`, `Pipfile`, or `pyproject.toml`. The README instructs `pip install spotdl customtkinter` with no version constraints.

**Remediation:**
Create `requirements.txt`:
```
spotdl>=4.2.0,<5.0.0
customtkinter>=5.2.0,<6.0.0
```

And/or create `pyproject.toml`:
```toml
[project]
name = "music-spotdl"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "spotdl>=4.2.0,<5.0.0",
    "customtkinter>=5.2.0,<6.0.0",
]
```

---

### 2.5 — Silent Exception Swallowing (Medium)

**Files:** Multiple locations across the codebase

**Root Cause:**
Bare `except Exception: pass` blocks silently discard errors, making debugging and incident response nearly impossible:

| File | Line(s) | Context |
|------|---------|---------|
| `config.py` | 122–123 | Config file load failure silently ignored |
| `config.py` | 132–133 | Download dir creation failure silently ignored |
| `main.py` | 24–25 | System check failure silently ignored |
| `spotdl_wrapper.py` | 136–138 | ConfigManager creation failure silently ignored |

**Remediation:**
At minimum, log the exception:
```python
except Exception:
    logger.warning("Config load failed, using defaults", exc_info=True)
    self._settings = {}
```

---

## 3. Internet Speed & Network Throughput

### 3.1 — Add Download Concurrency Control (High)

**File:** `app/core/spotdl_wrapper.py` — `download_track_or_playlist()` (lines 579–642)

**Root Cause:**
spotDL's `--threads` parameter is never specified. The tool defaults to a conservative concurrency limit. On fast connections (100 Mbps+), downloads are bottlenecked by sequential processing.

**Remediation:**

1. Add to `config.py`:
```python
DEFAULT_SETTINGS = {
    ...
    "download_threads": 4,
}
VALID_THREAD_COUNTS = {1, 2, 4, 8, 12, 16}
```

2. Add to `_build_base_extra_args()`:
```python
threads = cfg.get("download_threads", 4)
extra.extend(["--threads", str(threads)])
```

3. Add a slider in the Settings UI (Quality tab):
```python
ctk.CTkLabel(quality_tab, text="Download Threads:").grid(...)
threads_slider = ctk.CTkSlider(quality_tab, from_=1, to=16, number_of_steps=15)
threads_slider.set(self.config_manager.get("download_threads", 4))
threads_slider.grid(...)
```

---

### 3.2 — Add Proxy Support (Medium)

**Root Cause:**
No proxy configuration exists. YouTube Music rate-limits bulk requests from the same IP, and some tracks are geo-restricted.

**Remediation:**

1. Add to `config.py`:
```python
DEFAULT_SETTINGS = {
    ...
    "proxy": "",  # Empty = no proxy
}
```

2. Pass to spotDL:
```python
proxy = cfg.get("proxy", "")
if proxy:
    extra.extend(["--proxy", proxy])
```

3. Add a proxy field in the Settings UI (Provider tab):
```python
ctk.CTkLabel(provider_tab, text="Proxy (optional):").grid(...)
proxy_entry = GlassEntry(provider_tab, placeholder_text="socks5://127.0.0.1:1080")
```

---

### 3.3 — Add Retry Logic & Bandwidth Throttling (Medium)

**Root Cause:**
No retry or rate-limit configuration. On unstable connections, partial downloads fail silently. On shared connections, downloads consume 100% bandwidth.

**Remediation:**

1. Add `--max-retries 3` to the default extra args:
```python
extra.extend(["--max-retries", "3"])
```

2. Add optional bandwidth limiting via yt-dlp's `--limit-rate` (passed through spotDL's `--yt-dlp-args`):
```python
rate_limit = cfg.get("rate_limit", "")  # e.g. "5M" for 5 MB/s
if rate_limit:
    extra.extend(["--yt-dlp-args", f"--limit-rate {rate_limit}"])
```

---

### 3.4 — Add Network Connectivity Pre-Check (Low)

**Root Cause:**
The application attempts downloads without verifying internet connectivity first, leading to confusing error messages.

**Remediation:**
Add a lightweight connectivity check in `system_check.py`:
```python
import urllib.request

def check_internet(timeout: int = 5) -> Dict[str, Any]:
    try:
        urllib.request.urlopen("https://open.spotify.com", timeout=timeout)
        return {"available": True}
    except Exception:
        return {"available": False}
```

---

## 4. Drivers & Hardware/System Integration

### 4.1 — Inject spotDL Binary Directory into Subprocess PATH (Critical)

**Files:** `app/utils/system_check.py` (lines 90–99) and `app/core/spotdl_wrapper.py` (line 371)

**Root Cause:**
`system_check.py` correctly locates binaries in `~/.spotdl/ffmpeg.exe`, but `spotdl_wrapper.py` spawns subprocesses **without** adding `~/.spotdl` to the subprocess `PATH`. If FFmpeg/Deno are only installed via spotDL (not globally), audio conversion silently fails.

**Remediation:**
In `spotdl_wrapper.py`, modify `_run_command_chain()`:
```python
import os

def _run_command_chain(self, cmd, callback, error_message):
    ...
    # Build environment with spotdl binary directory in PATH
    env = os.environ.copy()
    spotdl_dirs = []
    home = Path.home()
    for base in (home / ".config" / "spotdl", home / ".spotdl"):
        if base.is_dir():
            spotdl_dirs.append(str(base))
    if spotdl_dirs:
        env["PATH"] = os.pathsep.join(spotdl_dirs) + os.pathsep + env.get("PATH", "")

    process = subprocess.Popen(
        current_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,                          # <-- inject PATH
        creationflags=_get_creationflags(),
    )
```

---

### 4.2 — Add Zero-CPU Passthrough Audio Format Option (Medium)

**Root Cause:**
FFmpeg re-encodes all downloaded audio to the configured format (e.g., YouTube OPUS → MP3), causing 100% CPU spikes on low-end hardware. In many cases, the source audio (m4a/opus) is already high quality.

**Remediation:**

1. Add a `"keep_original"` format option:
```python
VALID_FORMATS = {"mp3", "m4a", "flac", "ogg", "opus"}
```

2. Document in the Settings UI that selecting `opus` or `m4a` avoids re-encoding.

3. Optionally add a "Skip conversion (keep original)" toggle:
```python
DEFAULT_SETTINGS = {
    ...
    "skip_conversion": False,
}
```
When enabled, omit the `--format` argument entirely, letting spotDL keep the source format.

---

### 4.3 — Add Audio Playback Engine (Enhancement)

**Root Cause:**
The application is named "MusicPlayer" but currently only functions as a downloader — there is no audio playback capability.

**Recommended Integration Options:**

| Library | Pros | Cons |
|---------|------|------|
| `pygame.mixer` | Lightweight, cross-platform, easy API | Limited format support, no gapless |
| `vlc-python` | Full codec support via libVLC | Requires VLC installation, large dependency |
| `miniaudio` | Pure Python bindings, WASAPI/CoreAudio/PulseAudio | Lower-level API, more code needed |
| `just_playback` | Simple API, cross-platform | Fewer features, less maintained |

**Minimal Integration Example (pygame):**
```python
import pygame

pygame.mixer.init()

def play_preview(filepath: str) -> None:
    pygame.mixer.music.load(filepath)
    pygame.mixer.music.play()

def stop_preview() -> None:
    pygame.mixer.music.stop()
```

---

### 4.4 — Add Version Detection for FFmpeg/Deno (Low)

**File:** `app/utils/system_check.py`

**Root Cause:**
The system check only verifies binary **existence**, not **version compatibility**. Outdated FFmpeg versions may lack required codecs (e.g., `libopus`) causing silent encoding failures.

**Remediation:**
```python
def check_ffmpeg() -> Dict[str, Any]:
    path = shutil.which("ffmpeg") or _find_spotdl_binary("ffmpeg")
    if path is None:
        return {"available": False, "path": None, "version": None}
    try:
        result = subprocess.run(
            [str(path), "-version"],
            capture_output=True, text=True, timeout=5,
            creationflags=_get_creationflags(),
        )
        version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
    except Exception:
        version_line = "unknown"
    return {"available": True, "path": Path(path).resolve().as_posix(), "version": version_line}
```

---

## 5. User Interface (UI/UX)

### 5.1 — Fix Theme Color Inconsistency (High)

**File:** `app/ui/main_window.py` (line 115)

**Root Cause:**
The root window uses a hardcoded dark background:
```python
self.configure(background="#0f172a")
```
But `GlassFrame` and other widgets define light/dark color tuples (`GLASS_FRAME_BG = ("#e8f0fe", "#1e293b")`). If appearance mode is changed to "light", widgets render with light backgrounds against a dark window — destroying contrast and readability.

**Remediation:**
Use a dynamic color tuple or enforce the mode:
```python
# Option A: Dynamic (supports light/dark toggle)
WINDOW_BG = ("#f1f5f9", "#0f172a")
self.configure(fg_color=WINDOW_BG)

# Option B: Force dark-only (simpler)
ctk.set_appearance_mode("dark")
self.configure(fg_color="#0f172a")  # use fg_color, not background
```

---

### 5.2 — Add Track Search & Filter Bar (High)

**File:** `app/ui/main_window.py` — `_build_selection_section()` (lines 287–345)

**Root Cause:**
Fetched tracks display in an unranked, unsearchable list. Users with large playlists (50+ tracks) cannot easily find or filter specific songs.

**Remediation:**
Add a search entry above the scrollable track list:
```python
def _build_selection_section(self) -> None:
    ...
    self.track_search_entry = GlassEntry(
        self.selection_frame,
        placeholder_text="Search tracks...",
        height=30,
    )
    self.track_search_entry.grid(row=1, column=0, padx=15, pady=(0, 5), sticky="ew")
    self.track_search_entry.bind("<KeyRelease>", self._filter_tracks)
    ...

def _filter_tracks(self, event=None) -> None:
    query = self.track_search_entry.get().strip().lower()
    for i, cb in enumerate(self.track_scroll.winfo_children()):
        text = cb.cget("text").lower()
        if query in text or not query:
            cb.grid()
        else:
            cb.grid_remove()
```

---

### 5.3 — Add Download Speed & ETA Display (Medium)

**File:** `app/ui/main_window.py` — `_build_progress_section()` (lines 347–416)

**Root Cause:**
The progress section only shows a bar and percentage. Users have no visibility into download speed or estimated completion time.

**Remediation:**
Add speed and ETA labels:
```python
self.speed_label = ctk.CTkLabel(
    self.progress_container,
    text="",
    width=100,
    font=ctk.CTkFont(size=10),
    text_color=TEXT_SECONDARY_DARK,
)
self.speed_label.grid(row=1, column=0, sticky="w")

self.eta_label = ctk.CTkLabel(
    self.progress_container,
    text="",
    width=100,
    font=ctk.CTkFont(size=10),
    text_color=TEXT_SECONDARY_DARK,
)
self.eta_label.grid(row=1, column=1, sticky="e")
```
Then compute speed from `_session_bytes` delta over time intervals.

---

### 5.4 — Add Keyboard Shortcuts (Low)

**Root Cause:**
Only `<Return>` in the URL entry triggers download. No keyboard shortcuts for common actions.

**Remediation:**
```python
def __init__(self):
    ...
    self.bind("<Control-v>", self._paste_and_focus)
    self.bind("<Escape>", lambda e: self._cancel_download())
    self.bind("<Control-l>", lambda e: self._clear_log())
    self.bind("<Control-s>", lambda e: self._open_settings())
```

---

### 5.5 — Add Appearance Mode Toggle (Low)

**Root Cause:**
The app is hardcoded to dark mode. Some users prefer light mode.

**Remediation:**
Add a toggle button in the header:
```python
self.theme_toggle = GlassButton(
    self.header_frame,
    text="☀️",
    width=36, height=28,
    command=self._toggle_theme,
)

def _toggle_theme(self) -> None:
    current = ctk.get_appearance_mode()
    new_mode = "light" if current == "Dark" else "dark"
    ctk.set_appearance_mode(new_mode)
```

---

## 6. Framework Support & Modernization

### 6.1 — Current Framework Limitations (CustomTkinter / Tkinter)

| Limitation | Impact |
|------------|--------|
| No GPU-accelerated rendering | UI feels sluggish on 4K/HiDPI displays |
| No native glassmorphism | Blur effects are faked with static colors, not true transparency |
| No built-in media player | Cannot preview or play downloaded tracks |
| GIL-bound threading | Background tasks compete with UI rendering for the Python GIL |
| No native bundling | Users must install Python, pip, and dependencies manually |
| Tk event loop limitations | Complex animations and transitions are janky |

### 6.2 — Recommended Migration Path

**Short Term (Keep Python, upgrade GUI to PySide6/Qt6):**

| Feature | CustomTkinter (Current) | PySide6/Qt6 (Proposed) |
|---------|------------------------|----------------------|
| Rendering | CPU (Tk Canvas) | GPU (OpenGL / Direct3D / Metal) |
| Blur/Acrylic | Static RGB frames | Native Windows Mica/Acrylic, macOS Vibrancy |
| Audio | Not built-in | `QMediaPlayer` + `QAudioOutput` |
| Threading | `threading` + `after()` polling | `QThread` + Signals/Slots (no polling) |
| Distribution | Raw script | `pyinstaller` / `nuitka` → single `.exe` |

**Medium Term (Cross-platform distribution):**

Create a `build.spec` or GitHub Actions workflow with PyInstaller:
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "MusicSpotDL" --icon=icon.ico main.py
```

### 6.3 — Add `pyproject.toml` for Modern Python Packaging

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "music-spotdl"
version = "1.0.0"
description = "Desktop GUI for downloading music via spotDL"
requires-python = ">=3.10"
license = {text = "MIT"}
dependencies = [
    "spotdl>=4.2.0,<5.0.0",
    "customtkinter>=5.2.0,<6.0.0",
]

[project.optional-dependencies]
dev = [
    "pyinstaller>=6.0",
    "pytest>=7.0",
    "ruff>=0.1.0",
]

[project.scripts]
music-spotdl = "main:main"
```

### 6.4 — Add Logging Infrastructure

**Root Cause:**
The app uses `logging.getLogger(__name__)` in `spotdl_wrapper.py` but never configures a log handler, file output, or log rotation. All log output is lost.

**Remediation:**
Add to `main.py`:
```python
import logging
from pathlib import Path

def _setup_logging() -> None:
    log_dir = Path.home() / ".config" / "musicplayer" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
```

---

## 7. Implementation Priority & Action Plan

### Phase 1 — Stability & Security (Do First)

| # | Task | Severity | File(s) |
|---|------|----------|---------|
| 1.1 | Fix subprocess pipe deadlock | 🔴 Critical | `spotdl_wrapper.py` |
| 4.1 | Inject `~/.spotdl` into subprocess PATH | 🔴 Critical | `spotdl_wrapper.py` |
| 2.1 | Validate Spotify URLs before execution | 🔴 Critical | `spotdl_wrapper.py` |
| 1.4 | Fix process tree termination (`taskkill /T`) | 🟠 High | `spotdl_wrapper.py` |
| 2.2 | Sanitize output template against path traversal | 🟠 High | `config.py` |
| 2.4 | Add `requirements.txt` with pinned versions | 🟠 High | New file |

### Phase 2 — Performance & Network (Do Next)

| # | Task | Severity | File(s) |
|---|------|----------|---------|
| 1.2 | Replace `os.walk` with incremental file tracking | 🟠 High | `main_window.py` |
| 3.1 | Add download concurrency (`--threads`) setting | 🟠 High | `config.py`, `spotdl_wrapper.py`, `main_window.py` |
| 3.3 | Add retry logic (`--max-retries 3`) | 🟡 Medium | `spotdl_wrapper.py` |
| 1.3 | Batch-render track checkboxes | 🟡 Medium | `main_window.py` |

### Phase 3 — UI & Distribution (Polish)

| # | Task | Severity | File(s) |
|---|------|----------|---------|
| 5.1 | Fix theme color inconsistency | 🟠 High | `main_window.py` |
| 5.2 | Add track search/filter bar | 🟠 High | `main_window.py` |
| 5.3 | Add download speed & ETA display | 🟡 Medium | `main_window.py` |
| 6.3 | Create `pyproject.toml` | 🟡 Medium | New file |
| 6.4 | Add logging infrastructure | 🟡 Medium | `main.py` |
| 5.4 | Add keyboard shortcuts | 🟢 Low | `main_window.py` |
| 5.5 | Add appearance mode toggle | 🟢 Low | `main_window.py` |

---

> **Total Issues Identified:** 22
> **Critical:** 3 | **High:** 8 | **Medium:** 8 | **Low:** 3
