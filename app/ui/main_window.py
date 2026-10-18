from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import customtkinter as ctk
from tkinter import filedialog

from app.core.config import ConfigManager
from app.core.spotdl_wrapper import SpotDLManager
from app.utils import system_check

logger = logging.getLogger(__name__)

# Gemini-style color palette (supporting light and dark modes)
WINDOW_BG = ("#ffffff", "#131314")  # Pure white / Gemini deep gray

# Glass frame backgrounds
GLASS_FRAME_BG = ("#f0f4f9", "#1e1f20")  # Google Light Gray / Gemini Surface
GLASS_FRAME_BORDER = ("#dce1e7", "#333537")  # Subtle borders

# Glass button backgrounds
GLASS_BTN_BG = ("#e1e5e9", "#282a2c")
GLASS_BTN_HOVER = ("#d1d5d9", "#3c4043")

# Accent colors
ACCENT_BLUE = "#1a73e8"  # Google Blue
CTA_HOVER = "#1765cc"
ACCENT_RED = "#d93025"
ACCENT_GREEN = "#1e8e3e"
ACCENT_ORANGE = "#f29900"

# Typography colors
TEXT_PRIMARY = ("#1f1f1f", "#e3e3e3")
TEXT_SECONDARY = ("#444746", "#8e918f")

# Standard corner radius for Gemini look
GEMINI_RADIUS = 24

# Log colors
LOG_TEXT_NORMAL = ("#1f1f1f", "#e3e3e3")
LOG_TEXT_ERROR = "#d93025"
LOG_TEXT_WARNING = "#f29900"
LOG_TEXT_SUCCESS = "#1e8e3e"
LOG_TEXT_FALLBACK = "#d93025"
LOG_TEXT_INFO = "#1a73e8"


class GlassFrame(ctk.CTkFrame):
    """A frame with glassmorphism styling supporting light and dark modes."""

    def __init__(self, master: Any, corner_radius: int = GEMINI_RADIUS, border_width: int = 1, **kwargs: Any) -> None:
        super().__init__(
            master,
            corner_radius=corner_radius,
            border_width=border_width,
            fg_color=GLASS_FRAME_BG,
            border_color=GLASS_FRAME_BORDER,
            **kwargs,
        )


class GlassButton(ctk.CTkButton):
    """A button with glassmorphism styling supporting light and dark modes."""

    def __init__(self, master: Any, **kwargs: Any) -> None:
        kwargs.setdefault("corner_radius", 20)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", GLASS_FRAME_BORDER)
        kwargs.setdefault("height", 38)
        kwargs.setdefault("fg_color", GLASS_BTN_BG)
        kwargs.setdefault("hover_color", GLASS_BTN_HOVER)
        kwargs.setdefault("text_color", TEXT_PRIMARY)
        super().__init__(master, **kwargs)


class GlassEntry(ctk.CTkEntry):
    """An entry widget with glassmorphism styling supporting light and dark modes."""

    def __init__(self, master: Any, **kwargs: Any) -> None:
        kwargs.setdefault("corner_radius", GEMINI_RADIUS)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("height", 44)
        kwargs.setdefault("fg_color", GLASS_FRAME_BG)
        kwargs.setdefault("border_color", GLASS_FRAME_BORDER)
        kwargs.setdefault("text_color", TEXT_PRIMARY)
        kwargs.setdefault("placeholder_text_color", TEXT_SECONDARY)
        super().__init__(master, **kwargs)


class MainWindow(ctk.CTk):
    """
    Main application window for the MusicPlayer (spotDL) GUI.

    Provides URL input, output directory selection, download control,
    progress display with speed/ETA, cancellation, live log streaming,
    track search/filtering, settings modal, and system repair quick-fixes.
    """

    def __init__(self) -> None:
        super().__init__()
        self.title("MusicPlayer - spotDL Downloader")
        self.geometry("1000x720")
        self.minsize(900, 650)

        # Apply Modern Theme with glassmorphism (improvement 5.1)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=WINDOW_BG)

        self.config_manager = ConfigManager()
        self.spotdl_manager = SpotDLManager(self.config_manager)

        self.system_status = system_check.check_all()
        self._is_downloading = False
        self._current_url = ""
        self._fallback_active = False

        # Session tracking state (improvement 1.2 & 5.3)
        self._session_start = time.time()
        self._session_files = 0
        self._session_bytes = 0
        self._tracked_session_files: set[str] = set()
        self._last_speed_time = time.time()
        self._last_speed_bytes = 0
        self._current_speed_bps = 0.0

        # Track-selection and batch rendering state (improvement 1.3 & 5.2)
        self._fetched_count = 0
        self._track_vars: List[ctk.BooleanVar] = []
        self._track_texts: List[str] = []
        self._track_checkboxes: List[ctk.CTkCheckBox] = []
        self._pending_tracks: List[Dict[str, Any]] = []
        self._batch_render_id: Optional[str] = None
        self._is_fetching = False
        self._selection_mode = False
        self._fetch_warnings = 0

        # Configure grid weights for responsive layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Main container with padding
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(2, weight=2)
        self.main_container.grid_rowconfigure(4, weight=3)

        self._build_header()
        self._build_download_section()
        self._build_selection_section()
        self._build_progress_section()
        self._build_log_section()
        self._build_status_bar()

        # Keyboard shortcuts (improvement 5.4)
        self.bind("<Control-v>", self._paste_and_focus)
        self.bind("<Escape>", lambda e: self._cancel_download())
        self.bind("<Control-l>", lambda e: self._clear_log())
        self.bind("<Control-s>", lambda e: self._open_settings())

        self._update_system_status()

    def _build_header(self) -> None:
        """Build the header section with title, theme toggle, and system controls."""
        self.header_frame = GlassFrame(self.main_container, corner_radius=20)
        self.header_frame.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        self.header_frame.grid_columnconfigure(1, weight=1)

        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="MusicPlayer",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.title_label.grid(row=0, column=0, padx=15, pady=(12, 0), sticky="sw")

        self.subtitle_label = ctk.CTkLabel(
            self.header_frame,
            text="Spotify Downloader",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
        )
        self.subtitle_label.grid(row=1, column=0, padx=15, pady=(0, 12), sticky="nw")

        self.status_label = ctk.CTkLabel(
            self.header_frame,
            text="",
            font=ctk.CTkFont(size=10),
            anchor="w",
            text_color=TEXT_SECONDARY,
        )
        self.status_label.grid(row=0, column=1, rowspan=2, padx=15, pady=8, sticky="ew")

        # Theme toggle button (improvement 5.5)
        self.theme_toggle = GlassButton(
            self.header_frame,
            text="☀️",
            width=38,
            height=28,
            font=ctk.CTkFont(size=13),
            command=self._toggle_theme,
        )
        self.theme_toggle.grid(row=0, column=2, rowspan=2, padx=4, pady=8, sticky="ns")

        self.ffmpeg_fix_btn = GlassButton(
            self.header_frame,
            text="Install FFmpeg",
            width=100,
            height=28,
            font=ctk.CTkFont(size=10),
            command=self._install_ffmpeg,
        )
        self.ffmpeg_fix_btn.grid(row=0, column=3, rowspan=2, padx=4, pady=8, sticky="ns")

        self.deno_fix_btn = GlassButton(
            self.header_frame,
            text="Install Deno",
            width=100,
            height=28,
            font=ctk.CTkFont(size=10),
            command=self._install_deno,
        )
        self.deno_fix_btn.grid(row=0, column=4, rowspan=2, padx=4, pady=8, sticky="ns")

        self.settings_button = GlassButton(
            self.header_frame,
            text="Settings",
            width=100,
            height=28,
            font=ctk.CTkFont(size=10),
            command=self._open_settings,
        )
        self.settings_button.grid(row=0, column=5, rowspan=2, padx=(4, 15), pady=8, sticky="ns")

    def _toggle_theme(self) -> None:
        """Toggle between Dark and Light appearance modes (improvement 5.5)."""
        current = ctk.get_appearance_mode().lower()
        if current == "dark":
            ctk.set_appearance_mode("light")
            self.theme_toggle.configure(text="🌙")
            self._log("Switched to Light mode", status="info")
        else:
            ctk.set_appearance_mode("dark")
            self.theme_toggle.configure(text="☀️")
            self._log("Switched to Dark mode", status="info")

    def _paste_and_focus(self, event: Optional[Any] = None) -> None:
        """Paste URL from clipboard and focus URL input (improvement 5.4)."""
        try:
            focused = self.focus_get()
            # If user is in another text input, don't overwrite
            if focused is not None and focused != self.url_entry and isinstance(focused, (ctk.CTkEntry, ctk.CTkTextbox)):
                return
            clipboard = self.clipboard_get().strip()
            if clipboard:
                self.url_entry.delete(0, "end")
                self.url_entry.insert(0, clipboard)
                self.url_entry.focus_set()
        except Exception:
            pass

    def _build_download_section(self) -> None:
        """Build the URL input, download control, and output directory section."""
        self.download_frame = GlassFrame(self.main_container, corner_radius=20)
        self.download_frame.grid(row=1, column=0, pady=(0, 10), sticky="ew")
        self.download_frame.grid_columnconfigure(0, weight=1)

        self.url_label = ctk.CTkLabel(
            self.download_frame,
            text="Spotify URL or Track Link",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
            text_color=TEXT_PRIMARY,
        )
        self.url_label.grid(row=0, column=0, padx=15, pady=(10, 2), sticky="w")

        self.url_entry = GlassEntry(
            self.download_frame,
            placeholder_text="Enter Spotify track, album, or playlist URL (Ctrl+V)...",
            height=40,
            font=ctk.CTkFont(size=12),
        )
        self.url_entry.grid(row=1, column=0, padx=15, pady=(0, 8), sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self._start_download())

        self.download_button = ctk.CTkButton(
            self.download_frame,
            text="Download",
            width=140,
            height=40,
            corner_radius=12,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=ACCENT_BLUE,
            hover_color=CTA_HOVER,
            command=self._start_download,
        )
        self.download_button.grid(row=1, column=1, padx=(0, 8), pady=(0, 8), sticky="e")

        self.fetch_button = ctk.CTkButton(
            self.download_frame,
            text="Fetch Tracks",
            width=140,
            height=40,
            corner_radius=12,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=ACCENT_GREEN,
            hover_color="#27ae60",
            text_color="#0f172a",
            command=self._start_fetch,
        )
        self.fetch_button.grid(row=1, column=2, padx=(0, 15), pady=(0, 8), sticky="e")

        self.output_label = ctk.CTkLabel(
            self.download_frame,
            text=f"Output Directory: {self.config_manager.download_directory}",
            anchor="w",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_SECONDARY,
        )
        self.output_label.grid(row=2, column=0, columnspan=2, padx=15, pady=(0, 10), sticky="ew")

        self.browse_button = GlassButton(
            self.download_frame,
            text="Change Folder",
            width=140,
            height=28,
            font=ctk.CTkFont(size=10),
            command=self._browse_folder,
        )
        self.browse_button.grid(row=2, column=2, padx=(0, 15), pady=(0, 10), sticky="e")

    def _build_selection_section(self) -> None:
        """Build the track selection panel with search filter (improvement 5.2)."""
        self.selection_frame = GlassFrame(self.main_container, corner_radius=20)
        self.selection_frame.grid(row=2, column=0, pady=(0, 10), sticky="nsew")
        self.selection_frame.grid_columnconfigure(0, weight=1)
        self.selection_frame.grid_rowconfigure(3, weight=1)

        self.selection_header = ctk.CTkLabel(
            self.selection_frame,
            text="Select Tracks",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
            text_color=TEXT_PRIMARY,
        )
        self.selection_header.grid(row=0, column=0, padx=15, pady=(10, 2), sticky="w")

        self.selection_summary_label = ctk.CTkLabel(
            self.selection_frame,
            text="0 of 0 selected",
            font=ctk.CTkFont(size=10),
            anchor="w",
            text_color=TEXT_SECONDARY,
        )
        self.selection_summary_label.grid(row=1, column=0, padx=15, pady=(0, 4), sticky="w")

        # Toolbar with selection and download actions
        toolbar = ctk.CTkFrame(self.selection_frame, fg_color="transparent")
        toolbar.grid(row=0, column=1, rowspan=2, padx=(0, 15), pady=(10, 4), sticky="ne")
        self.select_all_btn = GlassButton(
            toolbar, text="Select All", width=85, height=26,
            font=ctk.CTkFont(size=10), command=lambda: self._set_all_tracks(True),
        )
        self.select_all_btn.grid(row=0, column=0, padx=3)
        self.select_none_btn = GlassButton(
            toolbar, text="Select None", width=85, height=26,
            font=ctk.CTkFont(size=10), command=lambda: self._set_all_tracks(False),
        )
        self.select_none_btn.grid(row=0, column=1, padx=3)
        self.invert_sel_btn = GlassButton(
            toolbar, text="Invert", width=65, height=26,
            font=ctk.CTkFont(size=10), command=self._invert_tracks,
        )
        self.invert_sel_btn.grid(row=0, column=2, padx=3)
        self.download_selected_btn = ctk.CTkButton(
            toolbar, text="Download Selected", width=140, height=28,
            corner_radius=12, font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=ACCENT_BLUE, hover_color=CTA_HOVER,
            command=self._download_selected,
        )
        self.download_selected_btn.grid(row=1, column=0, columnspan=3, padx=3, pady=(5, 0))

        # Search & Filter bar (improvement 5.2)
        self.track_search_entry = GlassEntry(
            self.selection_frame,
            placeholder_text="Filter tracks by title, artist, or album...",
            height=30,
            font=ctk.CTkFont(size=11),
        )
        self.track_search_entry.grid(row=2, column=0, columnspan=2, padx=15, pady=(0, 6), sticky="ew")
        self.track_search_entry.bind("<KeyRelease>", self._filter_tracks)

        # Scrollable checkbox list
        self.track_scroll = ctk.CTkScrollableFrame(
            self.selection_frame, fg_color="transparent", label_text=""
        )
        self.track_scroll.grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 12), sticky="nsew")
        self.track_scroll.grid_columnconfigure(0, weight=1)

        self.selection_frame.grid_remove()

    def _filter_tracks(self, event: Optional[Any] = None) -> None:
        """Filter visible track checkboxes according to search query (improvement 5.2)."""
        query = self.track_search_entry.get().strip().lower()
        for cb in self._track_checkboxes:
            try:
                text = cb.cget("text").lower()
                if not query or query in text:
                    cb.grid()
                else:
                    cb.grid_remove()
            except Exception:
                pass

    def _build_progress_section(self) -> None:
        """Build progress bar, speed/ETA (improvement 5.3), and cancel button."""
        self.progress_frame = GlassFrame(self.main_container, corner_radius=20)
        self.progress_frame.grid(row=3, column=0, pady=(0, 10), sticky="ew")
        self.progress_frame.grid_columnconfigure(1, weight=1)

        self.track_label = ctk.CTkLabel(
            self.progress_frame,
            text="Ready to download",
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.track_label.grid(row=0, column=0, columnspan=3, padx=15, pady=(10, 4), sticky="ew")

        self.song_counter_label = ctk.CTkLabel(
            self.progress_frame,
            text="Ready",
            width=90,
            anchor="e",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_SECONDARY,
        )
        self.song_counter_label.grid(row=1, column=0, padx=15, pady=(0, 4), sticky="e")

        # Progress bar container with percentage
        self.progress_container = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        self.progress_container.grid(row=1, column=1, padx=(10, 10), pady=(0, 4), sticky="ew")
        self.progress_container.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_container, mode="determinate", height=12
        )
        self.progress_bar.grid(row=0, column=0, padx=(0, 12), sticky="ew")
        self.progress_bar.set(0)

        self.progress_percent_label = ctk.CTkLabel(
            self.progress_container,
            text="0%",
            width=55,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.progress_percent_label.grid(row=0, column=1, sticky="e")

        # Speed and ETA row (improvement 5.3)
        self.speed_eta_frame = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        self.speed_eta_frame.grid(row=2, column=1, padx=(10, 10), pady=(0, 8), sticky="ew")
        self.speed_eta_frame.grid_columnconfigure(1, weight=1)

        self.speed_label = ctk.CTkLabel(
            self.speed_eta_frame,
            text="",
            font=ctk.CTkFont(size=10),
            anchor="w",
            text_color=TEXT_SECONDARY,
        )
        self.speed_label.grid(row=0, column=0, sticky="w")

        self.eta_label = ctk.CTkLabel(
            self.speed_eta_frame,
            text="",
            font=ctk.CTkFont(size=10),
            anchor="e",
            text_color=TEXT_SECONDARY,
        )
        self.eta_label.grid(row=0, column=1, sticky="e")

        # Fallback badge with glass styling
        self.fallback_badge = ctk.CTkLabel(
            self.progress_frame,
            text="FALLBACK MODE",
            font=ctk.CTkFont(size=9, weight="bold"),
            fg_color=ACCENT_RED,
            text_color="white",
            corner_radius=8,
            width=110,
            height=22,
        )
        self.fallback_badge.grid(row=1, column=2, padx=(0, 8), pady=(0, 4))
        self.fallback_badge.grid_remove()

        # Action buttons
        self.cancel_button = GlassButton(
            self.progress_frame,
            text="Cancel (Esc)",
            width=110,
            height=36,
            font=ctk.CTkFont(size=10),
            command=self._cancel_download,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=3, rowspan=2, padx=(5, 15), pady=8, sticky="e")

    def _build_log_section(self) -> None:
        """Build the log display section."""
        self.log_frame = GlassFrame(self.main_container, corner_radius=20)
        self.log_frame.grid(row=4, column=0, pady=(0, 10), sticky="nsew")
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=1)

        self.log_header = ctk.CTkLabel(
            self.log_frame,
            text="Download Log",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
            text_color=TEXT_PRIMARY,
        )
        self.log_header.grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")

        self.clear_log_button = GlassButton(
            self.log_frame,
            text="Clear (Ctrl+L)",
            width=95,
            height=26,
            font=ctk.CTkFont(size=10),
            command=self._clear_log,
        )
        self.clear_log_button.grid(row=0, column=1, padx=(0, 15), pady=(10, 5), sticky="e")

        self.log_textbox = ctk.CTkTextbox(
            self.log_frame,
            wrap="word",
            font=ctk.CTkFont(size=10, family="Consolas"),
            fg_color=GLASS_FRAME_BG,
            border_width=0,
        )
        self.log_textbox.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="nsew")
        self.log_textbox.configure(state="disabled", text_color=TEXT_PRIMARY)
        self._setup_log_tags()

        self.log_scrollbar = ctk.CTkScrollbar(
            self.log_frame,
            command=self.log_textbox.yview,
            width=12,
        )
        self.log_scrollbar.grid(row=1, column=1, padx=(0, 8), pady=(0, 15), sticky="ns")
        self.log_textbox.configure(yscrollcommand=self.log_scrollbar.set)

    def _build_status_bar(self) -> None:
        """Build the bottom status bar with session statistics."""
        self.status_frame = GlassFrame(self.main_container, corner_radius=12)
        self.status_frame.grid(row=5, column=0, pady=(0, 0), sticky="ew")
        self.status_frame.grid_columnconfigure(0, weight=1)

        self.status_bar = ctk.CTkLabel(
            self.status_frame,
            text="Ready",
            font=ctk.CTkFont(size=10),
            anchor="w",
            text_color=TEXT_PRIMARY,
        )
        self.status_bar.grid(row=0, column=0, padx=12, pady=6, sticky="w")

        self.session_stats_label = ctk.CTkLabel(
            self.status_frame,
            text="Session: 0 files | 0.0 MB",
            font=ctk.CTkFont(size=10),
            anchor="e",
            text_color=TEXT_SECONDARY,
        )
        self.session_stats_label.grid(row=0, column=1, padx=12, pady=6, sticky="e")

    def _update_system_status(self) -> None:
        self.system_status = system_check.check_all()
        ffmpeg_ok = self.system_status.get("ffmpeg", {}).get("available", False)
        deno_ok = self.system_status.get("deno", {}).get("available", False)
        internet_ok = self.system_status.get("internet", {}).get("available", True)

        status_parts = [
            f"FFmpeg: {'OK' if ffmpeg_ok else 'MISSING'}",
            f"Deno: {'OK' if deno_ok else 'MISSING'}",
        ]
        if not internet_ok:
            status_parts.append("Network: OFFLINE")

        self.status_label.configure(
            text=" | ".join(status_parts),
            text_color=ACCENT_RED if not (ffmpeg_ok and deno_ok and internet_ok) else TEXT_SECONDARY,
        )
        if hasattr(self, "ffmpeg_fix_btn"):
            if ffmpeg_ok:
                self.ffmpeg_fix_btn.grid_remove()
            else:
                self.ffmpeg_fix_btn.configure(state="normal")
                self.ffmpeg_fix_btn.grid(row=0, column=3, rowspan=2, padx=4, pady=8, sticky="ns")
        if hasattr(self, "deno_fix_btn"):
            if deno_ok:
                self.deno_fix_btn.grid_remove()
            else:
                self.deno_fix_btn.configure(state="normal")
                self.deno_fix_btn.grid(row=0, column=4, rowspan=2, padx=4, pady=8, sticky="ns")

    def _run_install_thread(self, installer_func: Callable[[], subprocess.Popen[bytes]], name: str) -> None:
        def _run():
            try:
                proc = installer_func()
                try:
                    # Fixed: Add timeout handling to prevent indefinite blocking
                    proc.communicate(timeout=600)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                except Exception:
                    pass
            except Exception:
                pass
            self.after(0, self._update_system_status)
            self.after(0, lambda: self._log(f"{name} installation check completed", status="success"))
        threading.Thread(target=_run, daemon=True).start()

    def _install_ffmpeg(self) -> None:
        self._log("Installing FFmpeg via spotdl...", status="info")
        self._run_install_thread(system_check.install_ffmpeg, "FFmpeg")

    def _install_deno(self) -> None:
        self._log("Installing Deno via spotdl...", status="info")
        self._run_install_thread(system_check.install_deno, "Deno")

    def _open_settings(self) -> None:
        """Open settings dialog supporting all configured options."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("640x520")
        dialog.minsize(580, 460)
        dialog.transient(self)
        dialog.configure(fg_color=WINDOW_BG)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(0, weight=1)

        dialog_bg = GlassFrame(dialog, corner_radius=0)
        dialog_bg.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        dialog_bg.grid_columnconfigure(0, weight=1)
        dialog_bg.grid_rowconfigure(0, weight=1)

        tabview = ctk.CTkTabview(dialog_bg, corner_radius=12)
        tabview.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")
        tabview.grid_columnconfigure(0, weight=1)
        tabview.add("Quality")
        tabview.add("Provider & Network")
        tabview.add("Save Location")

        # Quality tab (improvements 3.1 & 4.2)
        quality_tab = tabview.tab("Quality")
        quality_tab.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(quality_tab, text="Audio Quality & Encoding", font=ctk.CTkFont(weight="bold"), text_color=TEXT_PRIMARY).grid(row=0, column=0, columnspan=2, padx=12, pady=(8, 4), sticky="w")

        ctk.CTkLabel(quality_tab, text="Bitrate:", text_color=TEXT_SECONDARY).grid(row=1, column=0, padx=12, pady=5, sticky="w")
        bitrate_var = ctk.StringVar(value=self.config_manager.bitrate)
        bitrate_menu = ctk.CTkOptionMenu(quality_tab, variable=bitrate_var, values=["320k", "256k", "192k", "128k"])
        bitrate_menu.grid(row=1, column=1, padx=12, pady=5, sticky="ew")

        ctk.CTkLabel(quality_tab, text="Audio Format:", text_color=TEXT_SECONDARY).grid(row=2, column=0, padx=12, pady=5, sticky="w")
        format_var = ctk.StringVar(value=self.config_manager.format)
        # Includes opus for zero-CPU passthrough (improvement 4.2)
        format_menu = ctk.CTkOptionMenu(quality_tab, variable=format_var, values=["mp3", "m4a", "flac", "ogg", "opus"])
        format_menu.grid(row=2, column=1, padx=12, pady=5, sticky="ew")

        # Concurrency threads (improvement 3.1)
        ctk.CTkLabel(quality_tab, text="Download Threads:", text_color=TEXT_SECONDARY).grid(row=3, column=0, padx=12, pady=5, sticky="w")
        threads_var = ctk.StringVar(value=str(self.config_manager.download_threads))
        threads_menu = ctk.CTkOptionMenu(quality_tab, variable=threads_var, values=["1", "2", "4", "8", "12", "16"])
        threads_menu.grid(row=3, column=1, padx=12, pady=5, sticky="ew")

        # Skip conversion toggle (improvement 4.2)
        skip_conversion_var = ctk.BooleanVar(value=self.config_manager.skip_conversion)
        ctk.CTkSwitch(
            quality_tab,
            text="Skip audio re-encoding (Zero CPU passthrough, keep original format)",
            variable=skip_conversion_var,
            progress_color=ACCENT_BLUE,
        ).grid(row=4, column=0, columnspan=2, padx=12, pady=5, sticky="w")

        fetch_albums_var = ctk.BooleanVar(value=self.config_manager.fetch_albums)
        ctk.CTkSwitch(
            quality_tab,
            text="Fetch full albums for songs in the query",
            variable=fetch_albums_var,
            progress_color=ACCENT_BLUE,
        ).grid(row=5, column=0, columnspan=2, padx=12, pady=5, sticky="w")

        # Provider & Network tab (improvements 3.2 & 3.3)
        provider_tab = tabview.tab("Provider & Network")
        provider_tab.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(provider_tab, text="Audio Provider & Network Options", font=ctk.CTkFont(weight="bold"), text_color=TEXT_PRIMARY).grid(row=0, column=0, columnspan=2, padx=12, pady=(8, 4), sticky="w")

        ctk.CTkLabel(provider_tab, text="Primary Provider:", text_color=TEXT_SECONDARY).grid(row=1, column=0, padx=12, pady=4, sticky="w")
        provider_var = ctk.StringVar(value=self.config_manager.audio_provider)
        provider_segment = ctk.CTkSegmentedButton(provider_tab, variable=provider_var, values=["youtube-music", "youtube"])
        provider_segment.grid(row=1, column=1, padx=12, pady=4, sticky="ew")

        ctk.CTkLabel(provider_tab, text="Overwrite Mode:", text_color=TEXT_SECONDARY).grid(row=2, column=0, padx=12, pady=4, sticky="w")
        overwrite_var = ctk.StringVar(value=self.config_manager.overwrite_mode)
        overwrite_segment = ctk.CTkSegmentedButton(provider_tab, variable=overwrite_var, values=["skip", "force", "metadata"])
        overwrite_segment.grid(row=2, column=1, padx=12, pady=4, sticky="ew")

        fallback_var = ctk.BooleanVar(value=self.config_manager.auto_fallback)
        ctk.CTkSwitch(provider_tab, text="Auto-fallback to YouTube on provider error", variable=fallback_var, progress_color=ACCENT_BLUE).grid(row=3, column=0, columnspan=2, padx=12, pady=5, sticky="w")

        # Proxy support (improvement 3.2)
        ctk.CTkLabel(provider_tab, text="Proxy (optional):", text_color=TEXT_SECONDARY).grid(row=4, column=0, padx=12, pady=4, sticky="w")
        proxy_entry = GlassEntry(provider_tab, placeholder_text="e.g. socks5://127.0.0.1:1080 or http://proxy:8080", height=30)
        proxy_entry.insert(0, self.config_manager.proxy)
        proxy_entry.grid(row=4, column=1, padx=12, pady=4, sticky="ew")

        # Rate limit throttling (improvement 3.3)
        ctk.CTkLabel(provider_tab, text="Bandwidth Limit:", text_color=TEXT_SECONDARY).grid(row=5, column=0, padx=12, pady=4, sticky="w")
        rate_limit_entry = GlassEntry(provider_tab, placeholder_text="e.g. 5M for 5MB/s, empty for unlimited", height=30)
        rate_limit_entry.insert(0, self.config_manager.rate_limit)
        rate_limit_entry.grid(row=5, column=1, padx=12, pady=4, sticky="ew")

        # Save Location tab (improvement 2.2)
        location_tab = tabview.tab("Save Location")
        location_tab.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(location_tab, text="Download Directory:", text_color=TEXT_SECONDARY).grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")
        dir_entry = GlassEntry(location_tab, height=30)
        dir_entry.insert(0, str(self.config_manager.download_directory))
        dir_entry.grid(row=1, column=0, padx=12, pady=(2, 5), sticky="ew")

        browse_dir_btn = GlassButton(location_tab, text="Browse", width=90, height=26, command=lambda: self._browse_dir_dialog(dialog, dir_entry))
        browse_dir_btn.grid(row=2, column=0, padx=12, pady=(0, 5), sticky="w")

        ctk.CTkLabel(location_tab, text="Output Template (relative to download folder):", text_color=TEXT_SECONDARY).grid(row=3, column=0, padx=12, pady=(5, 2), sticky="w")
        template_entry = GlassEntry(location_tab, height=30)
        template_entry.insert(0, self.config_manager.output_template)
        template_entry.grid(row=4, column=0, padx=12, pady=(2, 5), sticky="ew")
        ctk.CTkLabel(location_tab, text="Variables: {artist}, {artists}, {title}, {album}, {year}, {output-ext}", text_color=TEXT_SECONDARY).grid(row=5, column=0, padx=12, pady=(0, 5), sticky="w")

        # Buttons Section
        btn_frame = GlassFrame(dialog_bg, corner_radius=12)
        btn_frame.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)
        feedback_label = ctk.CTkLabel(btn_frame, text="", text_color=TEXT_SECONDARY)
        feedback_label.grid(row=0, column=0, columnspan=3, padx=12, pady=(8, 5), sticky="ew")

        def save_and_apply() -> None:
            try:
                threads_val = int(threads_var.get())
            except ValueError:
                threads_val = 4

            updates = {
                "bitrate": bitrate_var.get(),
                "format": format_var.get(),
                "download_threads": threads_val,
                "skip_conversion": skip_conversion_var.get(),
                "fetch_albums": fetch_albums_var.get(),
                "audio_provider": provider_var.get(),
                "auto_fallback": fallback_var.get(),
                "proxy": proxy_entry.get().strip(),
                "rate_limit": rate_limit_entry.get().strip(),
                "download_directory": dir_entry.get().strip(),
                "output_template": template_entry.get().strip(),
                "overwrite_mode": overwrite_var.get(),
            }
            results = self.config_manager.update(updates)
            if all(results.values()):
                self.config_manager.save()
                feedback_label.configure(text="Settings saved successfully", text_color=ACCENT_GREEN)
                self.output_label.configure(text=f"Output Directory: {self.config_manager.download_directory}")
                self.spotdl_manager.set_config_manager(self.config_manager)
            else:
                failed = [k for k, v in results.items() if not v]
                feedback_label.configure(text=f"Failed to validate: {', '.join(failed)}", text_color=ACCENT_RED)

        save_btn = ctk.CTkButton(
            btn_frame,
            text="Save & Apply",
            width=130,
            height=30,
            corner_radius=12,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=ACCENT_BLUE,
            hover_color=CTA_HOVER,
            command=save_and_apply,
        )
        save_btn.grid(row=1, column=1, padx=8, pady=8)
        close_btn = GlassButton(btn_frame, text="Close", width=90, height=30, command=dialog.destroy)
        close_btn.grid(row=1, column=2, padx=(0, 12), pady=8)

        dialog.grab_set()
        dialog.after(150, dialog.focus_set)

    def _browse_dir_dialog(self, parent: ctk.CTkToplevel, entry_widget: ctk.CTkEntry) -> None:
        folder = filedialog.askdirectory(
            title="Select Download Directory",
            initialdir=entry_widget.get() or str(self.config_manager.download_directory),
            parent=parent,
        )
        if folder:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, folder)

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(
            title="Select Download Directory",
            initialdir=str(self.config_manager.download_directory),
        )
        if folder:
            path = Path(folder)
            if self.config_manager.set("download_directory", path):
                self.config_manager.save()
                self.output_label.configure(text=f"Output Directory: {self.config_manager.download_directory}")
                self.spotdl_manager.set_config_manager(self.config_manager)
                self._log(f"Output directory set to: {path}", status="success")
            else:
                self._log("Error: Could not set output directory", status="error")

    def _log(self, message: str, status: str = "info") -> None:
        def _append() -> None:
            self.log_textbox.configure(state="normal")
            prefix = ""
            tag = "normal"
            if status == "error":
                prefix = "[ERROR] "
                tag = "error"
            elif status == "warning":
                prefix = "[WARN]  "
                tag = "warning"
            elif status == "success":
                prefix = "[OK]    "
                tag = "success"
            elif status == "fallback":
                prefix = "[FBACK] "
                tag = "fallback"
            elif status == "info":
                prefix = "[INFO]  "
                tag = "info"

            self.log_textbox.insert("end", f"{prefix}{message}\n")
            self.log_textbox.tag_add(tag, "end-2l", "end-1c")
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
        self.after(0, _append)

    def _setup_log_tags(self) -> None:
        """Set up color tags for different log message types."""
        self.log_textbox.tag_config("normal", foreground=LOG_TEXT_NORMAL[1] if ctk.get_appearance_mode().lower() == "dark" else LOG_TEXT_NORMAL[0])
        self.log_textbox.tag_config("error", foreground=LOG_TEXT_ERROR)
        self.log_textbox.tag_config("warning", foreground=LOG_TEXT_WARNING)
        self.log_textbox.tag_config("success", foreground=LOG_TEXT_SUCCESS)
        self.log_textbox.tag_config("fallback", foreground=LOG_TEXT_FALLBACK, underline=True)
        self.log_textbox.tag_config("info", foreground=LOG_TEXT_INFO)

    def _clear_log(self) -> None:
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")
        self.status_bar.configure(text="Log cleared")

    def _refresh_session_stats(self, new_file_path: Optional[str] = None) -> None:
        """
        Incrementally update session download stats without disk thrashing (improvement 1.2).
        Calculates speed and ETA (improvement 5.3).
        """
        now = time.time()
        added_bytes = 0

        if new_file_path:
            try:
                p = Path(new_file_path)
                if not p.is_absolute():
                    p = Path(self.config_manager.download_directory) / p
                norm_str = str(p.resolve())
                if p.is_file() and norm_str not in self._tracked_session_files:
                    size = p.stat().st_size
                    self._tracked_session_files.add(norm_str)
                    self._session_bytes += size
                    added_bytes = size
            except OSError:
                pass
        else:
            # Check download directory for newly modified files since session start
            try:
                dl_dir = Path(self.config_manager.download_directory)
                if dl_dir.is_dir():
                    for item in dl_dir.iterdir():
                        if item.is_file():
                            norm_str = str(item.resolve())
                            if norm_str not in self._tracked_session_files:
                                try:
                                    if item.stat().st_mtime >= self._session_start:
                                        size = item.stat().st_size
                                        self._tracked_session_files.add(norm_str)
                                        self._session_bytes += size
                                        added_bytes += size
                                except OSError:
                                    continue
            except Exception:
                pass

        # Update speed and ETA
        elapsed = now - self._last_speed_time
        if elapsed >= 1.0 or added_bytes > 0:
            if elapsed > 0:
                bytes_delta = self._session_bytes - self._last_speed_bytes
                self._current_speed_bps = max(0.0, bytes_delta / max(0.1, elapsed))
                self._last_speed_time = now
                self._last_speed_bytes = self._session_bytes

                if self._current_speed_bps > 1048576:
                    self.speed_label.configure(text=f"Speed: {self._current_speed_bps / 1048576:.1f} MB/s")
                elif self._current_speed_bps > 1024:
                    self.speed_label.configure(text=f"Speed: {self._current_speed_bps / 1024:.0f} KB/s")
                elif self._is_downloading:
                    self.speed_label.configure(text="Speed: Calculating...")
                else:
                    self.speed_label.configure(text="")

        self.session_stats_label.configure(
            text=f"Session: {self._session_files} files | {self._session_bytes / 1048576:.1f} MB"
        )

    def _callback(self, status: Dict[str, Any]) -> None:
        def _update() -> None:
            msg = status.get("message", "")
            stat = status.get("status", "downloading")
            percent = status.get("percent", None)
            is_fallback = status.get("fallback", False)

            # Fetch-mode protocol events (improvement 1.3 batch rendering)
            if stat == "fetched":
                track = status.get("track") or {}
                self._add_track_row(track)
                self.track_label.configure(text=f"Fetching... {self._fetched_count} tracks loaded")
                return
            if stat == "fetch_error":
                self._end_fetch()
                self.track_label.configure(text="Fetch Failed")
                self.status_bar.configure(text="Fetch failed - see log")
                self._log(status.get("message") or "Fetch failed", status="error")
                return
            if stat == "downloading" and self._is_fetching and status.get("warning"):
                self._fetch_warnings += 1

            # Show fallback badge
            if is_fallback or "[FALLBACK]" in msg:
                self._fallback_active = True
                self.fallback_badge.grid()
                self._log(msg, status="fallback")
            elif msg and stat == "downloading":
                if status.get("success"):
                    self._log(msg, status="success")
                    self._session_files += 1

                    # Parse downloaded file from log line for incremental stat update
                    new_file = None
                    file_match = re.search(r'Downloaded "([^"]+)"', msg)
                    if file_match:
                        raw_target = file_match.group(1)
                        if Path(raw_target).is_file():
                            new_file = raw_target
                    self._refresh_session_stats(new_file)
                elif status.get("warning"):
                    self._log(msg, status="warning")
                else:
                    self._log(msg, status="info")
                display = msg if len(msg) <= 70 else msg[:67] + "..."
                self.track_label.configure(text=f"Downloading: {display}")

            # Live song counter from "N/M complete" progress lines
            songs_total = status.get("songs_total")
            if songs_total is not None:
                done = status.get('songs_done', 0)
                self.song_counter_label.configure(
                    text=f"Song {done} of {songs_total}"
                )
                # Compute ETA if speed is available (improvement 5.3)
                if self._current_speed_bps > 1000 and songs_total > done:
                    remaining_songs = songs_total - done
                    avg_song_bytes = (self._session_bytes / max(1, self._session_files)) if self._session_files > 0 else 5 * 1024 * 1024
                    est_remaining_bytes = remaining_songs * avg_song_bytes
                    eta_seconds = int(est_remaining_bytes / self._current_speed_bps)
                    mins, secs = divmod(eta_seconds, 60)
                    self.eta_label.configure(text=f"ETA: ~{mins}m {secs}s")
                else:
                    self.eta_label.configure(text="")

            # Update progress bar and percentage
            if percent is not None:
                try:
                    progress_value = percent / 100.0
                    self.progress_bar.set(progress_value)
                    self.progress_percent_label.configure(text=f"{percent:.1f}%")
                except Exception:
                    pass

            if stat == "completed":
                if self._is_fetching:
                    # Flush any buffered checkboxes (improvement 1.3)
                    self._flush_pending_tracks()
                    partial = bool(status.get("partial")) or self._fetch_warnings > 0
                    if partial:
                        detail = status.get("message") or (
                            f"Fetched {self._fetched_count} track(s), "
                            f"{self._fetch_warnings} issue(s) reported"
                        )
                        self._log(f"PARTIAL FETCH - {detail}", status="warning")
                        self._end_fetch(message="Fetch incomplete - see log")
                    else:
                        self._log(f"Fetched {self._fetched_count} track(s)", status="success")
                        self._end_fetch()
                    self.track_label.configure(text="Tracks fetched - select and download")
                    return

                self.track_label.configure(text="Download Completed")
                self._set_downloading_state(False)
                self.progress_bar.set(1.0)
                self.progress_percent_label.configure(text="100%")
                self.speed_label.configure(text="")
                self.eta_label.configure(text="")
                self.status_bar.configure(text="Download completed successfully")
                self._log(msg or "Download completed", status="success")
                self._refresh_session_stats()
            elif stat == "error":
                if self._is_fetching:
                    self._flush_pending_tracks()
                    self._end_fetch()
                    self.track_label.configure(text="Fetch Failed")
                    self.status_bar.configure(text="Fetch failed - see log")
                    self._log(msg or "Fetch failed", status="error")
                    return
                err_type = status.get("type", "")
                self.track_label.configure(text=f"Download Failed ({err_type})" if err_type else "Download Failed")
                self._set_downloading_state(False)
                self.speed_label.configure(text="")
                self.eta_label.configure(text="")
                self.status_bar.configure(text="Download failed - see log for details")
                self._log(msg or "Download failed", status="error")
        self.after(0, _update)

    def _end_fetch(self, message: str = "Track list ready") -> None:
        """Restore controls after a fetch finishes (success, error or cancel)."""
        self._flush_pending_tracks()
        self._is_fetching = False
        self.status_bar.configure(text=message)
        try:
            self.progress_bar.stop()
        except Exception:
            pass
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)
        self.url_entry.configure(state="normal")
        self.fetch_button.configure(state="normal")
        self.download_button.configure(state="normal")
        self.browse_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        for btn in (self.select_all_btn, self.select_none_btn, self.invert_sel_btn,
                    self.download_selected_btn):
            btn.configure(state="normal")
        if self._fetched_count == 0:
            self.selection_frame.grid_remove()
            self._selection_mode = False
        else:
            self.selection_summary_label.configure(
                text=f"{sum(1 for v in self._track_vars if v.get())} of {self._fetched_count} selected"
            )

    def _set_downloading_state(self, downloading: bool) -> None:
        self._is_downloading = downloading
        if downloading:
            self.download_button.configure(state="disabled")
            self.fetch_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self.browse_button.configure(state="disabled")
            self.url_entry.configure(state="disabled")
            for btn in (self.select_all_btn, self.select_none_btn, self.invert_sel_btn,
                        self.download_selected_btn):
                btn.configure(state="disabled")
            self.status_bar.configure(text="Downloading...")
            self._last_speed_time = time.time()
            self._last_speed_bytes = self._session_bytes
        else:
            self.download_button.configure(state="normal")
            self.fetch_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self.browse_button.configure(state="normal")
            self.url_entry.configure(state="normal")
            for btn in (self.select_all_btn, self.select_none_btn, self.invert_sel_btn,
                        self.download_selected_btn):
                btn.configure(state="normal")
            self.progress_bar.set(0)
            self.progress_percent_label.configure(text="0%")
            self.song_counter_label.configure(text="Ready")
            self.speed_label.configure(text="")
            self.eta_label.configure(text="")
            self.fallback_badge.grid_remove()
            self._fallback_active = False
            self.status_bar.configure(text="Ready")

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        return text if len(text) <= max_len else text[: max_len - 1] + "…"

    def _add_track_row(self, track: Dict[str, Any]) -> None:
        """Buffer incoming track and schedule batch rendering (improvement 1.3)."""
        self._pending_tracks.append(track)
        if self._batch_render_id is None:
            self._batch_render_id = self.after(40, self._render_track_batch)

    def _render_track_batch(self) -> None:
        """Render a chunk of buffered track checkboxes to prevent UI lag (improvement 1.3)."""
        batch = self._pending_tracks[:25]
        self._pending_tracks = self._pending_tracks[25:]

        search_query = self.track_search_entry.get().strip().lower()

        for track in batch:
            var = ctk.BooleanVar(master=self, value=True)
            label = f"{track.get('artist') or 'Unknown'} - {track.get('title') or 'Unknown'}"
            label = self._truncate(label, 72)
            album = track.get("album")
            if album:
                label += f"  [{self._truncate(album, 30)}]"

            cb = ctk.CTkCheckBox(
                self.track_scroll,
                text=label,
                variable=var,
                command=self._update_select_count,
                font=ctk.CTkFont(size=11),
                checkbox_width=18,
                checkbox_height=18,
            )
            # Filter support while loading
            if not search_query or search_query in label.lower():
                cb.grid(row=self._fetched_count, column=0, padx=8, pady=2, sticky="w")
            else:
                cb.grid(row=self._fetched_count, column=0, padx=8, pady=2, sticky="w")
                cb.grid_remove()

            self._track_vars.append(var)
            self._track_texts.append(track.get("url", ""))
            self._track_checkboxes.append(cb)
            self._fetched_count += 1

        self._update_select_count()

        if self._pending_tracks:
            self._batch_render_id = self.after(40, self._render_track_batch)
        else:
            self._batch_render_id = None

    def _flush_pending_tracks(self) -> None:
        """Immediately render all remaining buffered tracks."""
        if self._batch_render_id is not None:
            self.after_cancel(self._batch_render_id)
            self._batch_render_id = None
        while self._pending_tracks:
            self._render_track_batch()

    def _update_select_count(self) -> None:
        selected = sum(1 for v in self._track_vars if v.get())
        self.selection_summary_label.configure(
            text=f"{selected} of {self._fetched_count} selected"
        )

    def _set_all_tracks(self, value: bool) -> None:
        for v in self._track_vars:
            v.set(value)
        self._update_select_count()

    def _invert_tracks(self) -> None:
        for v in self._track_vars:
            v.set(not v.get())
        self._update_select_count()

    def _reset_selection_panel(self) -> None:
        if self._batch_render_id is not None:
            self.after_cancel(self._batch_render_id)
            self._batch_render_id = None
        self._pending_tracks = []
        for cb in self.track_scroll.winfo_children():
            cb.destroy()
        self._track_vars = []
        self._track_texts = []
        self._track_checkboxes = []
        self._fetched_count = 0
        self.track_search_entry.delete(0, "end")
        self._update_select_count()

    def _start_fetch(self) -> None:
        if self._is_fetching:
            return
        url = self.url_entry.get().strip()
        if not url:
            self._log("Error: Please enter a URL to fetch tracks from", status="error")
            return
        if self.spotdl_manager.is_running():
            self._log("Error: Another operation is in progress", status="error")
            return
        self._reset_selection_panel()
        self._is_fetching = True
        self._fetch_warnings = 0
        self._selection_mode = True
        self.url_entry.configure(state="disabled")
        self.fetch_button.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.browse_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        for btn in (self.select_all_btn, self.select_none_btn, self.invert_sel_btn,
                    self.download_selected_btn):
            btn.configure(state="disabled")
        self.selection_frame.grid()
        self.track_label.configure(text="Fetching track list...")
        self.status_bar.configure(text="Fetching metadata...")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.progress_percent_label.configure(text="")
        self.speed_label.configure(text="")
        self.eta_label.configure(text="")
        self._log(f"Fetching tracks: {url}", status="info")
        self.spotdl_manager.set_config_manager(self.config_manager)
        self.spotdl_manager.fetch_tracks(url=url, callback=self._callback)

    def _download_selected(self) -> None:
        if self._is_downloading or self._is_fetching:
            self._log("Error: An operation is already in progress", status="error")
            return
        selected = [t for v, t in zip(self._track_vars, self._track_texts) if v.get() and t]
        if not selected:
            self._log("Error: No tracks selected", status="error")
            return
        # Fixed: Validate URLs before attempting download
        valid_urls = []
        for url in selected:
            if url and url.strip():
                valid_urls.append(url.strip())
        
        if not valid_urls:
            self._log("Error: No valid URLs found in selection", status="error")
            return
            
        output_path = self.config_manager.download_directory
        self._current_url = " ".join(valid_urls)
        self._log(f"Downloading {len(valid_urls)} selected track(s)", status="info")
        self._log(f"Output: {output_path}", status="info")
        self.track_label.configure(text=f"Downloading {len(valid_urls)} selected track(s)...")
        self._set_downloading_state(True)
        self.spotdl_manager.set_config_manager(self.config_manager)
        self.spotdl_manager.download_track_or_playlist(
            url=valid_urls,
            output_path=Path(output_path),
            extra_args=None,
            callback=self._callback,
            respect_selection=True,
        )

    def _start_download(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self._log("Error: Please enter a URL", status="error")
            return
        if self._selection_mode and self._fetched_count > 0:
            self._download_selected()
            return
        if self.spotdl_manager.is_running():
            self._log("Error: Download already in progress", status="error")
            return
        output_path = self.config_manager.download_directory
        self._current_url = url
        display_url = url if len(url) <= 60 else url[:57] + "..."
        self.track_label.configure(text=f"Downloading: {display_url}")
        self._log(f"Starting download: {url}", status="info")
        self._log(f"Output: {output_path}", status="info")
        self._set_downloading_state(True)
        self.spotdl_manager.set_config_manager(self.config_manager)
        self.spotdl_manager.download_track_or_playlist(
            url=url,
            output_path=Path(output_path),
            extra_args=None,
            callback=self._callback,
        )

    def _cancel_download(self) -> None:
        if self._is_fetching:
            self.spotdl_manager.cancel_download()
            self._end_fetch()
            self._log("Fetch cancelled by user", status="warning")
            self.track_label.configure(text="Fetch Cancelled")
            self.status_bar.configure(text="Fetch cancelled")
            return
        self.spotdl_manager.cancel_download()
        self._log("Download cancelled by user", status="warning")
        self.track_label.configure(text="Download Cancelled")
        self._set_downloading_state(False)
        self.status_bar.configure(text="Download cancelled")
