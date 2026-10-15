from __future__ import annotations

import json
import logging
import os
import platform
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from app.utils.platform_utils import get_creationflags

if TYPE_CHECKING:
    from app.core.config import ConfigManager

logger = logging.getLogger(__name__)

try:
    from app.core.config import ConfigManager as _ConfigManagerImpl
except Exception:
    logger.warning("Could not import ConfigManager", exc_info=True)
    _ConfigManagerImpl = None  # type: ignore

# Path to the extracted fetch-tracks child script
_FETCH_CHILD_SCRIPT_PATH = str(Path(__file__).parent / "fetch_tracks_child.py")

# Spotify URL validation regex (improvement 2.1)
SPOTIFY_URL_RE = re.compile(
    r"^https?://open\.spotify\.com/(track|album|playlist|artist)/[a-zA-Z0-9]+(\?.*)?$"
)


class SpotDLManager:
    """
    Thread-safe manager for executing spotDL commands via background subprocesses.

    Provides methods to download tracks/playlists and sync playlists, with
    real-time log parsing, optional callback support, and cancellation.
    Includes auto-fallback on AudioProviderError respecting config.
    """
    # SpotDL arguments that take a value and should not be duplicated when merging
    _NON_DUPLICATE_ARGS = {"--audio", "-a", "--bitrate", "-b", "--format", "-f",
                           "--overwrite", "--output", "-o", "--url", "--threads",
                           "--proxy", "--max-retries"}
    # Standalone flags (no value argument) that should not be duplicated
    _NON_DUPLICATE_FLAGS = {"--force", "--skip-existing", "--dont-filter-results",
                            "--fetch-albums", "--user-auth", "--preload", "--headless",
                            "--simple-tui"}

    def __init__(self, config_manager: Optional["ConfigManager"] = None) -> None:
        """
        Initialize SpotDLManager with no active process.

        Args:
            config_manager: Optional ConfigManager instance to read settings from.
        """
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._thread: Optional[threading.Thread] = None
        self._cancelled: bool = False
        self._fallback_attempts: int = 0
        self._max_fallback_attempts: int = 1
        self._config_manager = config_manager
        if self._config_manager is None and _ConfigManagerImpl is not None:
            try:
                self._config_manager = _ConfigManagerImpl()
            except Exception:
                logger.warning("Could not create fallback ConfigManager", exc_info=True)
                self._config_manager = None
        self._current_url: str = ""
        self._current_output_path: Path | str = ""
        self._current_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        # Thread safety: protect shared state accessed from streaming threads
        self._lock = threading.RLock()
        # Track active streaming threads to properly wait for cleanup
        self._streaming_threads: List[threading.Thread] = []

    @staticmethod
    def _validate_url(url: str) -> bool:
        """Return True if `url` is a valid Spotify URL."""
        return bool(SPOTIFY_URL_RE.match(url))

    def _get_config(self) -> Dict[str, Any]:
        """Get config values safely."""
        if self._config_manager is None:
            return {
                "auto_fallback": True,
                "audio_provider": "youtube-music",
                "overwrite_mode": "skip",
                "bitrate": "320k",
                "format": "mp3",
                "fetch_albums": True,
                "output_template": "{title}.{output-ext}",
                "download_threads": 4,
                "proxy": "",
                "rate_limit": "",
                "skip_conversion": False,
            }
        try:
            return {
                "auto_fallback": bool(self._config_manager.auto_fallback),
                "audio_provider": str(self._config_manager.audio_provider),
                "overwrite_mode": str(self._config_manager.overwrite_mode),
                "bitrate": str(self._config_manager.bitrate),
                "format": str(self._config_manager.format),
                "fetch_albums": bool(self._config_manager.fetch_albums),
                "output_template": str(self._config_manager.output_template),
                "download_threads": int(self._config_manager.download_threads),
                "proxy": str(self._config_manager.proxy),
                "rate_limit": str(self._config_manager.rate_limit),
                "skip_conversion": bool(self._config_manager.skip_conversion),
            }
        except Exception:
            logger.warning("Config read failed, using defaults", exc_info=True)
            return {
                "auto_fallback": True,
                "audio_provider": "youtube-music",
                "overwrite_mode": "skip",
                "bitrate": "320k",
                "format": "mp3",
                "fetch_albums": True,
                "output_template": "{title}.{output-ext}",
                "download_threads": 4,
                "proxy": "",
                "rate_limit": "",
                "skip_conversion": False,
            }

    def _parse_log_line(self, line: str) -> Dict[str, Any]:
        clean_line = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', line).strip()
        if not clean_line:
            return {"status": "downloading", "message": clean_line, "percent": None}
        lower = clean_line.lower()

        # Overall progress lines emitted by spotdl --simple-tui: "3/12 complete"
        count_match = re.search(r'(\d+)\s*/\s*(\d+)\s+complete', lower)
        if count_match:
            done = int(count_match.group(1))
            total = int(count_match.group(2))
            percent = (done / total * 100.0) if total > 0 else None
            return {"status": "downloading", "message": clean_line, "percent": percent,
                    "songs_done": done, "songs_total": total}

        percent_match = re.search(r'(\d+(?:\.\d+)?)%', clean_line)
        percent = float(percent_match.group(1)) if percent_match else None

        # Fetch-mode protocol lines: __TRACK__{json}, __WARN__{msg},
        # __DONE__{json}, __ERR__{msg}
        if clean_line.startswith("__TRACK__"):
            try:
                payload = json.loads(clean_line[len("__TRACK__"):])
                return {"status": "fetched", "track": payload}
            except ValueError:
                return {"status": "fetch_error", "message": f"Unparseable track payload: {clean_line[:120]}"}
        if clean_line.startswith("__WARN__"):
            try:
                message = json.loads(clean_line[len("__WARN__"):])
            except ValueError:
                message = clean_line[len("__WARN__"):][:200]
            return {"status": "downloading", "message": str(message), "percent": None, "warning": True}
        if clean_line.startswith("__DONE__"):
            try:
                data = json.loads(clean_line[len("__DONE__"):])
                count = int(data.get("count", 0))
                errors = int(data.get("errors", 0))
            except (ValueError, AttributeError, TypeError):
                return {"status": "fetch_error", "message": "Malformed fetch completion line"}
            message = f"Fetched {count} track(s)"
            if errors:
                message += f", {errors} query(ies) failed"
            return {"status": "completed", "message": message, "percent": None,
                    "songs_total": count, "errors": errors, "partial": errors > 0}
        if clean_line.startswith("__ERR__"):
            try:
                return {"status": "fetch_error", "message": json.loads(clean_line[len("__ERR__"):])}
            except ValueError:
                return {"status": "fetch_error", "message": clean_line[len("__ERR__"):][:200]}

        if clean_line.startswith('Downloaded "'):
            return {"status": "downloading", "message": clean_line, "percent": percent, "success": True}

        # Per-song errors only mark the line; the process exit code decides
        # whether the whole download failed.
        error_keywords = ['error', 'exception', 'failed', 'fail', 'traceback', 'audioprovidererror', 'audio provider']
        if any(keyword in lower for keyword in error_keywords):
            return {
                "status": "downloading",
                "message": clean_line,
                "percent": percent,
                "warning": True,
                "type": "AudioProviderError" if ('audioprovidererror' in lower or 'audio provider' in lower) else "Error",
            }
        if 'warning' in lower or 'deno' in lower:
            return {"status": "downloading", "message": clean_line, "percent": percent, "warning": True}
        return {"status": "downloading", "message": clean_line, "percent": percent}

    def _try_fallback(self, status: Dict[str, Any]) -> bool:
        """Return whether a provider fallback retry should run for this status.

        Claims the retry attempt (increments the counter) when returning True;
        the caller must then stop the current process and relaunch itself.
        """
        with self._lock:
            if self._cancelled:
                return False
            if self._fallback_attempts >= self._max_fallback_attempts:
                return False
            cfg = self._get_config()
            if not cfg.get("auto_fallback", True):
                return False
            status_type = status.get("type", "")
            msg = status.get("message", "").lower()
            is_audio_err = status_type == "AudioProviderError" or "audioprovidererror" in msg or "audio provider" in msg
            if not is_audio_err:
                return False
            self._fallback_attempts += 1
            return True

    def _force_youtube_provider(self, cmd: List[str]) -> List[str]:
        """Return a copy of cmd with the --audio provider forced to YouTube."""
        new_cmd = list(cmd)
        if "--audio" in new_cmd:
            idx = new_cmd.index("--audio")
            if idx + 1 < len(new_cmd):
                new_cmd[idx + 1] = "youtube"
            else:
                new_cmd.append("youtube")
        else:
            new_cmd.extend(["--audio", "youtube"])
        return new_cmd

    def _merge_args_no_duplicates(self, base_args: List[str], extra_args: List[str]) -> List[str]:
        """Merge argument lists, removing duplicates for known conflicting args.

        When a key exists in both base_args and extra_args, the extra_args version wins.
        Handles both value-taking args (e.g., --audio) and standalone flags (e.g., --force).
        """
        # Extract keys from extra_args (args that take values)
        extra_keys = set()
        extra_flags = set()
        i = 0
        while i < len(extra_args):
            if extra_args[i] in self._NON_DUPLICATE_ARGS and i + 1 < len(extra_args):
                extra_keys.add(extra_args[i])
                i += 2
            elif extra_args[i] in self._NON_DUPLICATE_FLAGS:
                extra_flags.add(extra_args[i])
                i += 1
            else:
                i += 1

        # Filter base_args to remove any keys that are also in extra_args
        filtered_base = []
        i = 0
        while i < len(base_args):
            if base_args[i] in self._NON_DUPLICATE_ARGS and i + 1 < len(base_args):
                if base_args[i] in extra_keys:
                    i += 2  # skip this key-value pair from base
                else:
                    filtered_base.append(base_args[i])
                    filtered_base.append(base_args[i + 1])
                    i += 2
            elif base_args[i] in self._NON_DUPLICATE_FLAGS:
                if base_args[i] not in extra_flags:
                    filtered_base.append(base_args[i])
                i += 1
            else:
                filtered_base.append(base_args[i])
                i += 1

        return filtered_base + extra_args

    def _reset_run_state(self) -> None:
        """Reset all per-run state to defaults. Called between downloads."""
        with self._lock:
            self._process = None
            self._thread = None
            self._cancelled = False
            self._fallback_attempts = 0
            self._current_url = ""
            self._current_output_path = ""
            self._current_callback = None
            self._streaming_threads = []

    def _stop_process(self, process: subprocess.Popen[bytes]) -> None:
        """Terminate a still-running subprocess (escalating to kill) and close its pipes."""
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=2)
                    except Exception:
                        pass
        except Exception:
            pass
        for pipe in (process.stdout, process.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:
                pass

    @staticmethod
    def _build_spotdl_env() -> Dict[str, str]:
        """Build an environment dict with spotDL binary directories in PATH.

        spotDL installs ffmpeg/deno into ~/.spotdl or ~/.config/spotdl which
        are not on the system PATH. We inject these directories so spotDL's
        subprocess calls can find them.
        """
        env = os.environ.copy()
        spotdl_dirs = []
        home = Path.home()
        for base in (home / ".config" / "spotdl", home / ".spotdl"):
            try:
                if base.is_dir():
                    spotdl_dirs.append(str(base))
            except Exception:
                pass
        if spotdl_dirs:
            env["PATH"] = os.pathsep.join(spotdl_dirs) + os.pathsep + env.get("PATH", "")
        return env

    def _run_command_chain(self, cmd: List[str], callback: Optional[Callable[[Dict[str, Any]], None]], error_message: str) -> None:
        """Run a spotDL command, retrying once with the YouTube provider when
        the audio provider fails.

        The whole chain runs in this thread: the failed subprocess is stopped
        before the retry starts, and shared state is reset only after the last
        process finishes, so the manager keeps tracking the active process.

        Uses merged stdout/stderr (improvement 1.1) and injected PATH (improvement 4.1).
        """
        try:
            with self._lock:
                self._streaming_threads.append(threading.current_thread())
            env = self._build_spotdl_env()
            current_cmd = cmd
            while True:
                process = subprocess.Popen(
                    current_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # Merge stderr into stdout (fix 1.1)
                    env=env,                   # Inject spotDL PATH (fix 4.1)
                    creationflags=get_creationflags(),
                )
                with self._lock:
                    self._process = process
                    cancelled = self._cancelled
                if cancelled:
                    self._stop_process(process)
                    break
                fallback_requested = self._stream_output(process, callback)
                if not fallback_requested:
                    break
                # Stop the failed process before retrying so only one spotdl
                # subprocess is alive at a time.
                self._stop_process(process)
                with self._lock:
                    cancelled = self._cancelled
                if cancelled:
                    break
                if callback:
                    self._emit_status(callback, {
                        "status": "downloading",
                        "message": "[FALLBACK] Primary audio provider failed. Retrying with YouTube provider...",
                        "percent": None,
                        "fallback": True,
                    })
                current_cmd = self._force_youtube_provider(current_cmd)
        except OSError as e:
            self._emit_status(callback, {
                "status": "error",
                "message": f"{error_message}: {e}",
                "percent": None,
            })
        except Exception as e:
            logger.exception("spotDL command chain crashed")
            self._emit_status(callback, {
                "status": "error",
                "message": f"{error_message}: {e}",
                "percent": None,
            })
        finally:
            # Reset state only after the active process (and any retry) finished
            self._reset_run_state()

    def _emit_status(
        self,
        callback: Optional[Callable[[Dict[str, Any]], None]],
        status: Dict[str, Any],
    ) -> None:
        """Deliver a status to the callback; a failing callback must not kill
        the worker thread, but the failure is logged and surfaced as a warning."""
        if callback is None:
            return
        try:
            callback(status)
        except Exception:
            logger.exception("status callback raised; delivery may be lost")
            try:
                callback({
                    "status": "downloading",
                    "message": "UI status callback failed for: %s" % status.get("message", "?"),
                    "percent": None,
                    "warning": True,
                })
            except Exception:
                logger.exception("status callback failed again; dropping status")

    def _stream_output_lines(
        self,
        process: subprocess.Popen[bytes],
        callback: Optional[Callable[[Dict[str, Any]], None]],
        status_from_line: Callable[[str], Optional[Dict[str, Any]]],
    ) -> None:
        """Read stdout (then stderr) line by line, forwarding mapped statuses."""
        for pipe in (process.stdout, process.stderr):
            if pipe is None:
                continue
            with self._lock:
                cancelled = self._cancelled
            if cancelled:
                break
            try:
                for line in iter(pipe.readline, b''):
                    with self._lock:
                        if self._cancelled:
                            break
                    decoded = line.decode('utf-8', errors='replace')
                    status = status_from_line(decoded)
                    if status is None:
                        continue
                    self._emit_status(callback, status)
            except OSError as e:
                self._emit_status(callback, {
                    "status": "downloading",
                    "message": f"Pipe read error during fetch: {e}",
                    "percent": None,
                    "warning": True,
                })
        with self._lock:
            cancelled = self._cancelled
        if cancelled:
            self._stop_process(process)
        else:
            try:
                process.wait()
            except Exception:
                pass

    def _read_pipe_stream(
        self,
        pipe,
        callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> Optional[Dict[str, Any]]:
        """Read one pipe line by line, emitting parsed statuses.
        Returns the status that requested a provider fallback, else None."""
        try:
            for line in iter(pipe.readline, b''):
                with self._lock:
                    if self._cancelled:
                        break
                status = self._parse_log_line(line.decode('utf-8', errors='replace'))
                if self._try_fallback(status):
                    return status
                self._emit_status(callback, status)
        except OSError as e:
            self._emit_status(callback, {
                "status": "downloading",
                "message": f"Pipe read error: {e}",
                "percent": None,
                "warning": True,
            })
        return None

    def _stream_output(self, process: subprocess.Popen[bytes], callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> bool:
        """Stream output from a process, calling callback for each parsed line.

        Since stderr is merged into stdout (improvement 1.1), we only need to
        read one pipe. Returns True when streaming stopped early because a
        provider fallback retry was requested.
        """
        if process.stdout:
            if self._read_pipe_stream(process.stdout, callback) is not None:
                return True

        with self._lock:
            cancelled = self._cancelled
        if cancelled:
            self._stop_process(process)
        else:
            try:
                process.wait()
            except Exception:
                pass

        # spotdl prints no overall completion line; report the process exit
        # so the UI can leave the "downloading" state.
        with self._lock:
            cancelled = self._cancelled
        if not cancelled:
            returncode = process.returncode
            if returncode == 0:
                self._emit_status(callback, {
                    "status": "completed",
                    "message": "Download finished",
                    "percent": 100.0,
                })
            else:
                self._emit_status(callback, {
                    "status": "error",
                    "message": f"spotDL exited with code {returncode}",
                    "percent": None,
                    "type": "ProcessError",
                })

    def _build_base_extra_args(self, cfg: Dict[str, Any], fetch_albums: Optional[bool] = None) -> List[str]:
        extra: List[str] = []
        # simple-tui emits plain line-based output; the rich progress bar
        # prints nothing when stdout is a pipe, leaving the UI without signal
        extra.append("--simple-tui")
        bitrate = cfg.get("bitrate", "320k")
        audio_format = cfg.get("format", "mp3")
        skip_conversion = cfg.get("skip_conversion", False)
        if fetch_albums is None:
            fetch_albums = cfg.get("fetch_albums", True)
        overwrite = cfg.get("overwrite_mode", "skip")

        extra.extend(["--bitrate", str(bitrate)])
        if not skip_conversion:
            extra.extend(["--format", str(audio_format)])
        if fetch_albums:
            extra.append("--fetch-albums")
        overwrite_flags = {"skip", "force", "metadata"}
        if overwrite in overwrite_flags:
            if overwrite == "skip":
                extra.append("--overwrite")
                extra.append("skip")
            elif overwrite == "force":
                extra.append("--overwrite")
                extra.append("force")
            elif overwrite == "metadata":
                extra.append("--overwrite")
                extra.append("metadata")

        # Download concurrency (improvement 3.1)
        threads = cfg.get("download_threads", 4)
        extra.extend(["--threads", str(threads)])

        # Retry logic (improvement 3.3)
        extra.extend(["--max-retries", "3"])

        # Proxy support (improvement 3.2)
        proxy = cfg.get("proxy", "")
        if proxy:
            extra.extend(["--proxy", proxy])

        # Bandwidth throttling (improvement 3.3)
        rate_limit = cfg.get("rate_limit", "")
        if rate_limit:
            extra.extend(["--yt-dlp-args", f"--limit-rate {rate_limit}"])

        return extra

    def download_track_or_playlist(
        self,
        url: "str | list[str]",
        output_path: Path,
        extra_args: Optional[List[str]] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        config_manager: Optional["ConfigManager"] = None,
        respect_selection: bool = False,
    ) -> None:
        """Download one or many tracks/playlists. `url` may be a single query
        string or a list of queries (e.g. selected track URLs).
        With respect_selection=True the album-expansion setting is ignored so
        each selected track downloads exactly itself."""
        self.cancel_download()
        # Wait for previous threads to fully terminate
        self._wait_for_streaming_threads(timeout=5)
        url_list = [str(u) for u in url] if isinstance(url, (list, tuple)) else [url]

        # Validate all URLs before execution (improvement 2.1)
        for u in url_list:
            if not self._validate_url(u):
                self._emit_status(callback, {
                    "status": "error",
                    "message": f"Invalid Spotify URL: {u[:80]}",
                    "percent": None,
                })
                return

        with self._lock:
            if config_manager is not None:
                self._config_manager = config_manager
            elif self._config_manager is None and _ConfigManagerImpl is not None:
                try:
                    self._config_manager = _ConfigManagerImpl()
                except (OSError, ValueError):
                    logger.exception("could not create fallback ConfigManager")
            cfg = self._get_config()
            self._current_url = " ".join(url_list)
            self._current_output_path = Path(output_path)
            self._current_callback = callback
            self._fallback_attempts = 0
            self._cancelled = False
            cmd_extra = list(extra_args) if extra_args else []
            provider = cfg.get("audio_provider", "youtube-music")
            has_audio = any(arg in cmd_extra for arg in ["--audio", "-a"])
            if not has_audio:
                cmd_extra.extend(["--audio", provider])
            # Build base args from config
            base_extra = self._build_base_extra_args(
                cfg, fetch_albums=False if respect_selection else None
            )
            # Merge with no duplicates: base first, then user extras
            final_extra = self._merge_args_no_duplicates(base_extra, cmd_extra)
            output_template = cfg.get(
                "output_template", "{title}.{output-ext}"
            ).replace("{ext}", "{output-ext}")
            cmd = [
                sys.executable,
                "-m",
                "spotdl",
                # explicit subcommand: this build treats the first positional
                # as the operation, so extra query URLs would be rejected
                "download",
                *url_list,
                "--output",
                str(self._current_output_path / output_template),
            ]
            cmd.extend(final_extra)

        self._thread = threading.Thread(
            target=self._run_command_chain,
            args=(cmd, callback, "Failed to start spotDL"),
            daemon=True,
        )
        self._thread.start()

    def fetch_tracks(
        self,
        url: "str | list[str]",
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """Fetch Spotify track metadata (no audio search) and stream tracks
        back via callback as {"status": "fetched", "track": {...}} events.

        Runs the fetch_tracks_child.py script in a child process so it never
        blocks or interferes with the GUI thread. Emits a "fetch_error" event on
        failure and a "completed" event with songs_total on success.
        """
        self.cancel_download()
        self._wait_for_streaming_threads(timeout=5)

        url_list = [str(u) for u in url] if isinstance(url, (list, tuple)) else [url]

        # Validate all URLs before execution (improvement 2.1)
        for u in url_list:
            if not self._validate_url(u):
                self._emit_status(callback, {
                    "status": "fetch_error",
                    "message": f"Invalid Spotify URL: {u[:80]}",
                })
                return

        with self._lock:
            self._cancelled = False
            self._current_url = " ".join(url_list) if isinstance(url, (list, tuple)) else url
            self._current_callback = callback

        def _run():
            # Use the extracted child script (improvement 2.3)
            cmd = [sys.executable, _FETCH_CHILD_SCRIPT_PATH, *url_list]
            try:
                with self._lock:
                    self._streaming_threads.append(threading.current_thread())
                env = self._build_spotdl_env()
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    creationflags=get_creationflags(),
                )
                with self._lock:
                    self._process = process
                    cancelled = self._cancelled
                if cancelled:
                    self._stop_process(process)
                    return
                error_seen = [False]
                done_seen = [False]

                def _status(line: str) -> Optional[Dict[str, Any]]:
                    # stdout and stderr are merged; only protocol lines matter
                    clean = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', line).strip()
                    if not clean.startswith(("__TRACK__", "__DONE__", "__ERR__", "__WARN__")):
                        return None
                    status = self._parse_log_line(clean)
                    kind = status.get("status")
                    if kind == "fetch_error":
                        error_seen[0] = True
                    elif kind == "completed" and status.get("songs_total") is not None:
                        done_seen[0] = True
                    return status

                self._stream_output_lines(process, callback, _status)
                with self._lock:
                    cancelled = self._cancelled
                if cancelled or error_seen[0] or done_seen[0]:
                    return
                returncode = process.returncode
                if callback:
                    if returncode == 0:
                        # Child ended without a completion line (e.g. empty list)
                        callback({"status": "completed", "message": "Fetch finished",
                                 "percent": None, "songs_total": 0})
                    else:
                        callback({
                            "status": "fetch_error",
                            "message": f"Track fetch exited with code {returncode}",
                        })
            except Exception as e:
                logger.exception("Fetch tracks failed")
                if callback:
                    try:
                        callback({"status": "fetch_error", "message": f"Failed to start track fetch: {e}"})
                    except Exception:
                        pass
            finally:
                self._reset_run_state()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def sync_playlist(
        self,
        sync_file: Path,
        url: Optional[str] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        config_manager: Optional["ConfigManager"] = None,
    ) -> None:
        self.cancel_download()
        # Wait for previous threads to fully terminate
        self._wait_for_streaming_threads(timeout=5)
        with self._lock:
            if config_manager is not None:
                self._config_manager = config_manager
            elif self._config_manager is None and _ConfigManagerImpl is not None:
                try:
                    self._config_manager = _ConfigManagerImpl()
                except Exception:
                    logger.warning("Could not create ConfigManager for sync", exc_info=True)
            cfg = self._get_config()
            self._current_url = url or str(sync_file)
            self._current_output_path = sync_file.parent
            self._current_callback = callback
            self._fallback_attempts = 0
            self._cancelled = False
            cmd = [
                sys.executable,
                "-m",
                "spotdl",
                "sync",
                str(sync_file),
                "--simple-tui",
            ]
            if url:
                cmd.append(url)
            provider = cfg.get("audio_provider", "youtube-music")
            cmd.extend(["--audio", provider])
            cmd.extend(["--bitrate", cfg.get("bitrate", "320k")])
            if not cfg.get("skip_conversion", False):
                cmd.extend(["--format", cfg.get("format", "mp3")])
            if cfg.get("fetch_albums", True):
                cmd.append("--fetch-albums")
            overwrite = cfg.get("overwrite_mode", "skip")
            if overwrite == "skip":
                cmd.append("--overwrite")
                cmd.append("skip")
            elif overwrite == "force":
                cmd.append("--overwrite")
                cmd.append("force")
            elif overwrite == "metadata":
                cmd.append("--overwrite")
                cmd.append("metadata")

            # Download concurrency
            threads = cfg.get("download_threads", 4)
            cmd.extend(["--threads", str(threads)])
            cmd.extend(["--max-retries", "3"])

            proxy = cfg.get("proxy", "")
            if proxy:
                cmd.extend(["--proxy", proxy])

        self._thread = threading.Thread(
            target=self._run_command_chain,
            args=(cmd, callback, "Failed to start spotDL sync"),
            daemon=True,
        )
        self._thread.start()

    def _wait_for_streaming_threads(self, timeout: float = 5.0) -> None:
        """Wait for all active streaming threads to finish (up to timeout)."""
        with self._lock:
            threads = list(self._streaming_threads)

        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=timeout)

    def cancel_download(self) -> None:
        """Cancel the current download and clean up resources.

        Uses process tree termination on Windows (improvement 1.4) to ensure
        child processes (ffmpeg, yt-dlp) are also killed.
        """
        with self._lock:
            self._cancelled = True
            process = self._process

        if process:
            try:
                if platform.system() == "Windows":
                    # Kill entire process tree on Windows (improvement 1.4)
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            capture_output=True,
                            timeout=5,
                        )
                    except Exception:
                        # Fallback to standard terminate/kill
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                else:
                    import signal
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
            except Exception:
                logger.warning("Error during process cancellation", exc_info=True)

        # Wait for streaming threads to finish
        self._wait_for_streaming_threads(timeout=3)

        with self._lock:
            self._process = None
            self._thread = None
            self._streaming_threads = []

    def is_running(self) -> bool:
        with self._lock:
            if self._process is None:
                return False
            return self._process.poll() is None

    def set_config_manager(self, config_manager: "ConfigManager") -> None:
        with self._lock:
            self._config_manager = config_manager
