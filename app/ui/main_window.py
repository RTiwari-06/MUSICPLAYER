from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import customtkinter as ctk
from PIL import Image
from tkinter import PhotoImage, filedialog

from app.core.config import ConfigManager
from app.core.spotdl_wrapper import SpotDLManager
from app.core.platform_utils import apply_windows_icon, is_windows
from app.core import system_check

logger = logging.getLogger(__name__)

WINDOW_BG = ("#f2f6fc", "#080c14")
GLASS_FRAME_BG = ("#f7faff", "#0f172a")
GLASS_FRAME_BORDER = ("#d7e2f0", "#334155")
GLASS_BTN_BG = ("#e5edf7", "#172033")
GLASS_BTN_HOVER = ("#d7e6f7", "#26344e")
LIQUID_HIGHLIGHT = ("#ffffff", "#94a3b8")
LIQUID_SURFACE = ("#edf4ff", "#1e293b")
LIQUID_CYAN = "#06b6d4"
LIQUID_VIOLET = "#8b5cf6"
LIQUID_PINK = "#ec4899"
LIQUID_EMERALD = "#10b981"
LIQUID_AMBER = "#f59e0b"
ACCENT_BLUE = LIQUID_CYAN
CTA_HOVER = LIQUID_VIOLET
ACCENT_RED = "#f43f5e"
ACCENT_GREEN = LIQUID_EMERALD
TEXT_PRIMARY = ("#172033", "#f8fafc")
TEXT_SECONDARY = "#94a3b8"

PREFERRED_COLOR_THEME = "black"
FALLBACK_COLOR_THEME = "blue"


def resolve_color_theme(preferred: str = PREFERRED_COLOR_THEME, fallback: str = FALLBACK_COLOR_THEME) -> str:
    """
    Pick a customtkinter color theme that ships with the installed version.

    Args:
        preferred: Theme name to use when the installed customtkinter provides it.
        fallback: Theme name used otherwise.

    Returns:
        str: Name of an available theme.
    """
    theme_dir = Path(ctk.__file__).parent / "assets" / "themes"
    available = {path.stem for path in theme_dir.glob("*.json")} if theme_dir.is_dir() else set()
    if preferred in available:
        return preferred
    if fallback in available:
        return fallback
    return "blue"


def asset_path(name: str) -> Path:
    """
    Return the absolute path of a bundled asset.

    Resolves inside ``app/assets`` when running from source and inside the
    PyInstaller extraction folder (``sys._MEIPASS``) when running frozen.

    Args:
        name: File name inside ``app/assets``.

    Returns:
        Path: Absolute path of the asset (the file may not exist).
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name


class GlassFrame(ctk.CTkFrame):
    def __init__(self, master: Any, corner_radius: int = 18, **kwargs: Any) -> None:
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("fg_color", GLASS_FRAME_BG)
        kwargs.setdefault("border_color", GLASS_FRAME_BORDER)
        super().__init__(master, corner_radius=corner_radius,
                         **kwargs)


class GlassButton(ctk.CTkButton):
    def __init__(self, master: Any, **kwargs: Any) -> None:
        kwargs.setdefault("corner_radius", 12)
        kwargs.setdefault("height", 34)
        kwargs.setdefault("fg_color", GLASS_BTN_BG)
        kwargs.setdefault("hover_color", GLASS_BTN_HOVER)
        kwargs.setdefault("text_color", TEXT_PRIMARY)
        super().__init__(master, **kwargs)


class GlassEntry(ctk.CTkEntry):
    def __init__(self, master: Any, **kwargs: Any) -> None:
        kwargs.setdefault("corner_radius", 12)
        kwargs.setdefault("height", 42)
        kwargs.setdefault("fg_color", GLASS_FRAME_BG)
        kwargs.setdefault("border_color", GLASS_FRAME_BORDER)
        kwargs.setdefault("text_color", TEXT_PRIMARY)
        kwargs.setdefault("placeholder_text_color", TEXT_SECONDARY)
        super().__init__(master, **kwargs)


class LiquidPill(ctk.CTkLabel):
    """Small translucent-looking status surface used throughout the UI."""

    def __init__(self, master: Any, **kwargs: Any) -> None:
        kwargs.setdefault("corner_radius", 12)
        kwargs.setdefault("fg_color", LIQUID_SURFACE)
        kwargs.setdefault("text_color", TEXT_PRIMARY)
        kwargs.setdefault("height", 28)
        super().__init__(master, **kwargs)


class MetricCard(GlassFrame):
    """Compact dashboard metric matching the reference UI's metric tiles."""

    def __init__(self, master: Any, title: str, accent: str, **kwargs: Any) -> None:
        super().__init__(master, corner_radius=14, fg_color="#020817", border_color="#1e293b", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title.upper(), text_color=TEXT_SECONDARY,
                     font=ctk.CTkFont(size=9, weight="bold")).grid(
                         row=0, column=0, padx=11, pady=(9, 1), sticky="w")
        self.value_label = ctk.CTkLabel(self, text="--", text_color=accent,
                                        font=ctk.CTkFont(size=13, weight="bold"))
        self.value_label.grid(row=1, column=0, padx=11, pady=(0, 9), sticky="w")

    def set(self, value: str) -> None:
        self.value_label.configure(text=value)


class MainWindow(ctk.CTk):
    """Downloader-only MusicPlayer interface backed by spotDL."""

    def __init__(self) -> None:
        super().__init__()
        self.title("SpotDL Downloader")
        self.geometry("1920x1080")
        self.minsize(720, 480)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme(resolve_color_theme())
        self.configure(fg_color=WINDOW_BG)

        self.config_manager = ConfigManager()
        self.spotdl_manager = SpotDLManager(self.config_manager)
        self.system_status: Dict[str, Any] = {}
        self._is_downloading = False
        self._is_fetching = False
        self._fetched_count = 0
        self._fetch_warnings = 0
        self._track_vars: list[ctk.BooleanVar] = []
        self._track_urls: list[str] = []
        self._track_checkboxes: list[ctk.CTkCheckBox] = []
        self._track_status_labels: list[LiquidPill] = []
        self._track_rows: list[ctk.CTkFrame] = []
        self.track_search_text: Dict[ctk.CTkFrame, str] = {}
        self._session_start = time.time()
        self._session_files = 0
        self._session_bytes = 0
        self._tracked_session_files: set[str] = set()
        self._last_speed_time = self._session_start
        self._last_speed_bytes = 0
        self._current_speed_bps = 0.0
        self._terminal_visible = False
        self._icon_image: Optional[PhotoImage] = None
        self._logo_image: Optional[ctk.CTkImage] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
        self.main_container.grid_columnconfigure(0, weight=0, minsize=360)
        self.main_container.grid_columnconfigure(1, weight=1)
        self.main_container.grid_rowconfigure(1, weight=1)
        self.main_container.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_url_section()
        self._build_selection_section()
        self._build_progress_section()
        self._build_log_section()
        self._build_footer()
        self._apply_window_icon()

        self.bind("<Control-v>", self._paste_and_focus)
        self.bind("<Return>", lambda _event: self._start_download())
        self.bind("<Escape>", lambda _event: self._cancel_download())
        self.bind("<Control-l>", lambda _event: self._clear_log())
        self.bind("<Control-s>", lambda _event: self._open_settings())
        self._update_system_status()

    def _apply_window_icon(self) -> None:
        """Apply the bundled icon to the window, title bar and taskbar entry."""
        png = asset_path("icon.png")
        ico = asset_path("icon.ico")

        if is_windows() and ico.is_file():
            try:
                # "wm iconbitmap -default" only reaches windows created later on,
                # so the icon is set on this window explicitly.
                self.iconbitmap(str(ico))
            except Exception:
                logger.debug("Could not apply the ICO window icon", exc_info=True)
            self.bind("<Map>", self._on_window_mapped, add="+")
            self.after(150, self._set_exact_window_icons)
            return

        if png.is_file():
            try:
                self._icon_image = PhotoImage(file=str(png))
                self.iconphoto(True, self._icon_image)
            except Exception:
                logger.debug("Could not apply the PNG window icon", exc_info=True)

    def _on_window_mapped(self, _event: Any = None) -> None:
        """Re-apply the window icons once the top-level window exists."""
        self.after(150, self._set_exact_window_icons)

    def _set_exact_window_icons(self) -> None:
        """Set the title bar and taskbar icons in the exact sizes Windows wants."""
        ico = asset_path("icon.ico")
        if not is_windows() or not ico.is_file():
            return
        try:
            apply_windows_icon(self.winfo_id(), str(ico))
        except Exception:
            logger.debug("Could not apply the scaled Windows icons", exc_info=True)

    def _load_logo_image(self) -> Optional[ctk.CTkImage]:
        """Load the app logo for the header, if the asset is available."""
        png = asset_path("icon.png")
        if not png.is_file():
            return None
        try:
            with Image.open(png) as source:
                light = source.copy()
                dark = source.copy()
            return ctk.CTkImage(light_image=light, dark_image=dark, size=(40, 40))
        except Exception:
            logger.debug("Could not load the logo image", exc_info=True)
            return None

    def _build_header(self) -> None:
        self.header_frame = GlassFrame(self.main_container)
        self.header_frame.grid(row=0, column=0, columnspan=2, pady=(0, 12), sticky="ew")
        self.header_frame.grid_columnconfigure(1, weight=1)
        title_group = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        title_group.grid(row=0, column=0, padx=16, pady=9, sticky="w")
        self._logo_image = self._load_logo_image()
        if self._logo_image is not None:
            ctk.CTkLabel(title_group, image=self._logo_image, width=40, height=40).grid(
                row=0, column=0, rowspan=2, padx=(0, 10))
        else:
            ctk.CTkLabel(title_group, text="DL", width=38, height=38, corner_radius=14,
                         fg_color=LIQUID_VIOLET, text_color="white",
                         font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, rowspan=2, padx=(0, 10))
        title_line = ctk.CTkFrame(title_group, fg_color="transparent")
        title_line.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(title_line, text="Download Dashboard", font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=TEXT_PRIMARY).grid(row=0, column=0, sticky="w")
        LiquidPill(title_line, text="v4.2 PRO", width=65, height=20, text_color=LIQUID_EMERALD,
                   font=ctk.CTkFont(size=9, weight="bold")).grid(row=0, column=1, padx=8)
        ctk.CTkLabel(title_group, text="High-bitrate Spotify metadata extraction engine",
                     text_color=TEXT_SECONDARY, font=ctk.CTkFont(size=10)).grid(row=1, column=1, sticky="w")
        controls = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        controls.grid(row=0, column=1, padx=8, pady=8, sticky="e")
        self.ffmpeg_status = LiquidPill(controls, text="FFmpeg: checking...", width=112, text_color=TEXT_SECONDARY)
        self.ffmpeg_status.grid(row=0, column=0, padx=5)
        self.ffmpeg_fix_btn = GlassButton(controls, text="Install FFmpeg", width=112, command=self._install_ffmpeg)
        self.ffmpeg_fix_btn.grid(row=0, column=1, padx=3)
        self.deno_status = LiquidPill(controls, text="Deno: checking...", width=105, text_color=TEXT_SECONDARY)
        self.deno_status.grid(row=0, column=2, padx=5)
        self.deno_fix_btn = GlassButton(controls, text="Install Deno", width=100, command=self._install_deno)
        self.deno_fix_btn.grid(row=0, column=3, padx=3)
        GlassButton(controls, text="CLI Console", width=102, command=self._toggle_terminal).grid(row=0, column=4, padx=(8, 3))
        GlassButton(controls, text="Settings", width=84, command=self._open_settings).grid(row=0, column=5, padx=(3, 0))

    def _build_url_section(self) -> None:
        self.url_frame = GlassFrame(self.main_container)
        self.url_frame.grid(row=1, column=0, pady=(0, 12), padx=(0, 10), sticky="nsew")
        self.url_frame.grid_columnconfigure(0, weight=1)
        section_header = ctk.CTkFrame(self.url_frame, fg_color="transparent")
        section_header.grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="ew")
        section_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(section_header, text="SPOTIFY EXTRACTION", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_PRIMARY, anchor="w").grid(row=0, column=0, sticky="w")
        LiquidPill(section_header, text="spotDL ENGINE", width=92, height=22, text_color=LIQUID_VIOLET,
                   font=ctk.CTkFont(size=8, weight="bold")).grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(self.url_frame, text="Spotify Link (Track, Album, Playlist)",
                     font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY, anchor="w").grid(
                         row=1, column=0, columnspan=2, padx=16, pady=(0, 4), sticky="w")
        self.url_entry = GlassEntry(self.url_frame, placeholder_text="Paste a Spotify track, album, or playlist URL")
        self.url_entry.grid(row=2, column=0, columnspan=2, padx=16, pady=(0, 10), sticky="ew")
        self.fetch_button = ctk.CTkButton(self.url_frame, text="Fetch Track List", height=40, corner_radius=14,
                                           font=ctk.CTkFont(size=11, weight="bold"), fg_color=LIQUID_CYAN,
                                           hover_color=LIQUID_VIOLET, command=self._start_fetch)
        self.fetch_button.grid(row=3, column=0, padx=(16, 5), pady=(0, 13), sticky="ew")
        self.browse_button = GlassButton(self.url_frame, text="Browse", width=80, height=40, command=self._browse_folder)
        self.browse_button.grid(row=3, column=1, padx=(5, 16), pady=(0, 13), sticky="e")
        ctk.CTkLabel(self.url_frame, text="OUTPUT FOLDER PATH", font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=TEXT_SECONDARY, anchor="w").grid(row=4, column=0, columnspan=2, padx=16, sticky="w")
        self.output_label = LiquidPill(self.url_frame, text="", height=30, anchor="w", text_color=TEXT_SECONDARY)
        self.output_label.grid(row=5, column=0, columnspan=2, padx=16, pady=(4, 15), sticky="ew")
        self._update_output_label()

    def _build_selection_section(self) -> None:
        self.selection_frame = GlassFrame(self.main_container)
        self.selection_frame.grid(row=1, column=1, rowspan=2, pady=(0, 12), sticky="nsew")
        self.selection_frame.grid_columnconfigure(0, weight=1)
        self.selection_frame.grid_rowconfigure(2, weight=1)
        toolbar = ctk.CTkFrame(self.selection_frame, fg_color="#020817", corner_radius=18)
        toolbar.grid(row=0, column=0, padx=1, pady=1, sticky="ew")
        toolbar.grid_columnconfigure(3, weight=1)
        GlassButton(toolbar, text="Select All", width=84, height=31, command=lambda: self._set_all_tracks(True)).grid(row=0, column=0, padx=(13, 3), pady=11)
        GlassButton(toolbar, text="Deselect All", width=98, height=31, command=lambda: self._set_all_tracks(False)).grid(row=0, column=1, padx=3, pady=11)
        self.selection_summary = LiquidPill(toolbar, text="0 / 0 Selected", width=104, height=28, text_color=LIQUID_EMERALD,
                                            font=ctk.CTkFont(size=9, weight="bold"))
        self.selection_summary.grid(row=0, column=2, padx=(9, 12), pady=11)
        self.track_search = GlassEntry(toolbar, height=32, width=205, placeholder_text="Filter title, artist, or album")
        self.track_search.grid(row=0, column=3, padx=8, pady=11, sticky="e")
        self.track_search.bind("<KeyRelease>", self._filter_tracks)
        self.download_selected_button = ctk.CTkButton(toolbar, text="Download Selected", width=145, height=32,
                                                       corner_radius=12, fg_color=LIQUID_CYAN, hover_color=LIQUID_VIOLET,
                                                       command=self._download_selected, state="disabled")
        self.download_selected_button.grid(row=0, column=4, padx=(5, 13), pady=11)
        headings = ctk.CTkFrame(self.selection_frame, fg_color="#111c31", corner_radius=0)
        headings.grid(row=1, column=0, padx=1, sticky="ew")
        headings.grid_columnconfigure(1, weight=3)
        headings.grid_columnconfigure(2, weight=2)
        for column, text, width in ((0, "", 38), (1, "TRACK TITLE & ARTIST", 190), (2, "ALBUM NAME", 110),
                                    (3, "BITRATE", 65), (4, "DURATION", 65), (5, "STATE", 72)):
            ctk.CTkLabel(headings, text=text, width=width, anchor="w", text_color=TEXT_SECONDARY,
                         font=ctk.CTkFont(size=9, weight="bold")).grid(row=0, column=column, padx=8, pady=10, sticky="ew")
        self.track_scroll = ctk.CTkScrollableFrame(self.selection_frame, fg_color="#0b1220", corner_radius=0)
        self.track_scroll.grid(row=2, column=0, padx=1, sticky="nsew")
        self.track_scroll.grid_columnconfigure(1, weight=3)
        self.track_scroll.grid_columnconfigure(2, weight=2)
        self.empty_tracks_label = ctk.CTkLabel(
            self.track_scroll, text="No tracks fetched yet\n\nClick Fetch Track List to populate metadata.",
            text_color=TEXT_SECONDARY, justify="center", font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.empty_tracks_label.grid(row=0, column=0, columnspan=6, pady=70)
        table_footer = ctk.CTkFrame(self.selection_frame, fg_color="#020817", corner_radius=18)
        table_footer.grid(row=3, column=0, padx=1, pady=(0, 1), sticky="ew")
        table_footer.grid_columnconfigure(0, weight=1)
        self.provider_label = ctk.CTkLabel(table_footer, text="Provider: YouTube Music", text_color=TEXT_SECONDARY,
                                           font=ctk.CTkFont(size=10))
        self.provider_label.grid(row=0, column=0, padx=14, pady=10, sticky="w")
        self.batch_size_label = ctk.CTkLabel(table_footer, text="Selected Batch Size: 0 MB", text_color=LIQUID_EMERALD,
                                             font=ctk.CTkFont(size=10, weight="bold"))
        self.batch_size_label.grid(row=0, column=1, padx=14, pady=10, sticky="e")

    def _build_progress_section(self) -> None:
        self.progress_frame = GlassFrame(self.main_container)
        self.progress_frame.grid(row=2, column=0, pady=(0, 12), padx=(0, 10), sticky="ew")
        self.progress_frame.grid_columnconfigure(0, weight=1)
        metrics_header = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        metrics_header.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="ew")
        metrics_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(metrics_header, text="DOWNLOAD METRICS", anchor="w", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_PRIMARY).grid(row=0, column=0, sticky="w")
        self.pipeline_status_badge = LiquidPill(metrics_header, text="IDLE", width=72, height=23, text_color=TEXT_SECONDARY,
                                                font=ctk.CTkFont(size=9, weight="bold"))
        self.pipeline_status_badge.grid(row=0, column=1, sticky="e")
        status_row = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        status_row.grid(row=1, column=0, padx=16, pady=(0, 5), sticky="ew")
        status_row.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(status_row, text="Ready for batch download", anchor="w",
                                         font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_PRIMARY)
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.progress_percent_label = ctk.CTkLabel(status_row, text="0%", text_color=LIQUID_CYAN,
                                                   font=ctk.CTkFont(size=11, weight="bold"))
        self.progress_percent_label.grid(row=0, column=1, sticky="e")
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, height=12, corner_radius=8,
                                               fg_color="#020617", progress_color=LIQUID_CYAN)
        self.progress_bar.grid(row=2, column=0, padx=16, pady=(0, 12), sticky="ew")
        self.progress_bar.set(0)
        metrics = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        metrics.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="ew")
        metrics.grid_columnconfigure(0, weight=1)
        metrics.grid_columnconfigure(1, weight=1)
        self.metric_speed = MetricCard(metrics, "Speed", LIQUID_AMBER)
        self.metric_speed.grid(row=0, column=0, padx=(0, 5), pady=(0, 8), sticky="ew")
        self.metric_eta = MetricCard(metrics, "ETA", LIQUID_CYAN)
        self.metric_eta.grid(row=0, column=1, padx=(5, 0), pady=(0, 8), sticky="ew")
        self.metric_batch = MetricCard(metrics, "Batch Progress", LIQUID_EMERALD)
        self.metric_batch.grid(row=1, column=0, padx=(0, 5), sticky="ew")
        self.metric_storage = MetricCard(metrics, "Free Storage", LIQUID_VIOLET)
        self.metric_storage.grid(row=1, column=1, padx=(5, 0), sticky="ew")
        self.song_counter_label = self.metric_batch.value_label
        self.speed_label = self.metric_speed.value_label
        self.eta_label = self.metric_eta.value_label
        self.cancel_button = ctk.CTkButton(self.progress_frame, text="Cancel Download", width=145, height=34,
                                           corner_radius=12, fg_color=ACCENT_RED, hover_color="#b3261e",
                                           command=self._cancel_download, state="disabled")
        self.cancel_button.grid(row=4, column=0, padx=16, pady=(0, 14), sticky="ew")
        self._update_storage_metric()

    def _build_log_section(self) -> None:
        self.log_frame = GlassFrame(self.main_container, height=270)
        self.log_frame.place(relx=0.985, rely=0.985, relwidth=0.72, anchor="se")
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self.log_frame, text="spotDL Subprocess Stdout Stream", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_PRIMARY, anchor="w").grid(row=0, column=0, padx=16, pady=(12, 6), sticky="w")
        self.clear_log_button = GlassButton(self.log_frame, text="Clear", width=70, command=self._clear_log)
        self.clear_log_button.grid(row=0, column=1, padx=(16, 4), pady=(8, 4), sticky="e")
        GlassButton(self.log_frame, text="Close", width=64, command=self._toggle_terminal).grid(
            row=0, column=2, padx=(4, 16), pady=(8, 4), sticky="e")
        self.log_textbox = ctk.CTkTextbox(self.log_frame, wrap="word", corner_radius=10)
        self.log_textbox.grid(row=1, column=0, columnspan=3, padx=16, pady=(0, 16), sticky="nsew")
        self.log_textbox.configure(state="disabled", text_color=TEXT_PRIMARY)
        self.log_frame.place_forget()

    def _build_footer(self) -> None:
        self.footer_label = ctk.CTkLabel(self.main_container, text="Ready", anchor="w", text_color=TEXT_SECONDARY)
        self.session_stats_label = ctk.CTkLabel(self.main_container, text="Session: 0 files · 0 B", anchor="e", text_color=TEXT_SECONDARY)
        self.footer_label.grid(row=4, column=0, columnspan=2, sticky="w")
        self.session_stats_label.grid(row=4, column=0, columnspan=2, sticky="e")

    def _update_output_label(self) -> None:
        self.output_label.configure(text=str(self.config_manager.download_directory))
        self._update_storage_metric()

    def _update_storage_metric(self) -> None:
        if not hasattr(self, "metric_storage"):
            return
        try:
            free_bytes = shutil.disk_usage(self.config_manager.download_directory).free
            self.metric_storage.set(f"{free_bytes / 1073741824:.1f} GB")
        except OSError:
            self.metric_storage.set("Unavailable")

    def _set_pipeline_status(self, text: str, color: str = TEXT_SECONDARY) -> None:
        self.pipeline_status_badge.configure(text=text, text_color=color)

    def _update_system_status(self) -> None:
        self.system_status = system_check.check_all()
        for name, label, button in (("ffmpeg", self.ffmpeg_status, self.ffmpeg_fix_btn), ("deno", self.deno_status, self.deno_fix_btn)):
            available = self.system_status.get(name, {}).get("available", False)
            display_name = "FFmpeg" if name == "ffmpeg" else "Deno"
            label.configure(text=f"{display_name}: {'OK' if available else 'MISSING'}",
                            text_color=ACCENT_GREEN if available else ACCENT_RED,
                            fg_color="#103a33" if available else "#421c2b")
            if available:
                button.grid_remove()
            else:
                button.grid()

    def _run_install_thread(self, installer_func: Callable[[], subprocess.Popen[bytes]], name: str) -> None:
        def run() -> None:
            process: Optional[subprocess.Popen[bytes]] = None
            try:
                process = installer_func()
                process.communicate(timeout=600)
                message, status = f"{name} installation finished", "success"
            except subprocess.TimeoutExpired:
                if process is not None:
                    process.kill()
                    process.communicate()
                message, status = f"{name} installation timed out", "error"
            except Exception as exc:
                message, status = f"{name} installation failed: {exc}", "error"
            self.after(0, self._update_system_status)
            self._log(message, status=status)
        threading.Thread(target=run, daemon=True).start()

    def _install_ffmpeg(self) -> None:
        self._log("Installing FFmpeg via spotDL...")
        self._run_install_thread(system_check.install_ffmpeg, "FFmpeg")

    def _install_deno(self) -> None:
        self._log("Installing Deno via spotDL...")
        self._run_install_thread(system_check.install_deno, "Deno")

    def _paste_and_focus(self, _event: Optional[Any] = None) -> None:
        try:
            value = self.clipboard_get().strip()
            if value:
                self.url_entry.delete(0, "end")
                self.url_entry.insert(0, value)
                self.url_entry.focus_set()
        except Exception:
            pass

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=str(self.config_manager.download_directory), title="Select Output Folder")
        if not folder:
            return
        if self.config_manager.set("download_directory", Path(folder)):
            self.config_manager.save()
            self.spotdl_manager.set_config_manager(self.config_manager)
            self._update_output_label()
            self._log(f"Output directory set to: {folder}", status="success")
        else:
            self._log("Could not set output directory", status="error")

    def _open_settings(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Engine Configuration")
        dialog.geometry("540x520")
        dialog.transient(self)
        dialog.grab_set()
        dialog.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(dialog, text="ENGINE CONFIGURATION", text_color=LIQUID_CYAN,
                     font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, columnspan=2, padx=16, pady=(18, 8), sticky="w")
        fields = (("Audio Bitrate Quality", "bitrate", self.config_manager.bitrate, ["320k", "256k", "192k", "128k"]),
                  ("Audio Container Format", "format", self.config_manager.format, ["mp3", "m4a", "flac", "ogg", "opus"]),
                  ("Primary Audio Provider", "audio_provider", self.config_manager.audio_provider, ["youtube-music", "youtube"]),
                  ("Overwrite Mode", "overwrite_mode", self.config_manager.overwrite_mode, ["skip", "force", "metadata"]))
        variables: Dict[str, ctk.StringVar] = {}
        for row, (title, key, value, options) in enumerate(fields, start=1):
            ctk.CTkLabel(dialog, text=title, text_color=TEXT_SECONDARY).grid(row=row, column=0, padx=16, pady=8, sticky="w")
            variables[key] = ctk.StringVar(value=value)
            ctk.CTkOptionMenu(dialog, variable=variables[key], values=options).grid(row=row, column=1, padx=16, pady=8, sticky="ew")
        fallback_var = ctk.BooleanVar(value=self.config_manager.auto_fallback)
        ctk.CTkSwitch(dialog, text="Auto-Fallback Engine", variable=fallback_var, progress_color=LIQUID_CYAN).grid(
            row=5, column=0, columnspan=2, padx=16, pady=(8, 2), sticky="w")
        ctk.CTkLabel(dialog, text="Output folder", text_color=TEXT_SECONDARY).grid(row=6, column=0, padx=16, pady=8, sticky="w")
        directory_entry = GlassEntry(dialog)
        directory_entry.insert(0, str(self.config_manager.download_directory))
        directory_entry.grid(row=6, column=1, padx=16, pady=8, sticky="ew")
        ctk.CTkLabel(dialog, text="File Naming Template", text_color=TEXT_SECONDARY).grid(row=7, column=0, padx=16, pady=8, sticky="w")
        template_entry = GlassEntry(dialog)
        template_entry.insert(0, self.config_manager.output_template)
        template_entry.grid(row=7, column=1, padx=16, pady=8, sticky="ew")
        feedback = ctk.CTkLabel(dialog, text="", text_color=TEXT_SECONDARY)
        feedback.grid(row=9, column=0, columnspan=2, padx=16, pady=8)

        def save() -> None:
            updates: Dict[str, Any] = {key: variable.get() for key, variable in variables.items()}
            updates["auto_fallback"] = fallback_var.get()
            updates["download_directory"] = directory_entry.get().strip()
            updates["output_template"] = template_entry.get().strip()
            results = self.config_manager.update(updates)
            if all(results.values()):
                self.config_manager.save()
                self.spotdl_manager.set_config_manager(self.config_manager)
                self._update_output_label()
                self.provider_label.configure(text=f"Provider: {self.config_manager.audio_provider.replace('-', ' ').title()}")
                feedback.configure(text="Settings saved", text_color=ACCENT_GREEN)
            else:
                failed = ", ".join(key for key, ok in results.items() if not ok)
                feedback.configure(text=f"Invalid: {failed}", text_color=ACCENT_RED)

        ctk.CTkButton(dialog, text="Save & Apply", command=save, fg_color=ACCENT_BLUE,
                      hover_color=CTA_HOVER).grid(row=8, column=1, padx=16, pady=12, sticky="e")

    def _log(self, message: str, status: str = "info") -> None:
        def append() -> None:
            prefixes = {"error": "[ERROR] ", "warning": "[WARN]  ", "success": "[OK]    ", "fallback": "[FALLBACK] "}
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", prefixes.get(status, "") + message + "\n")
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
        self.after(0, append)

    def _clear_log(self) -> None:
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def _toggle_terminal(self) -> None:
        self._terminal_visible = not self._terminal_visible
        if self._terminal_visible:
            self.log_frame.place(relx=0.985, rely=0.985, relwidth=0.72, anchor="se")
        else:
            self.log_frame.place_forget()

    def _reset_selection(self) -> None:
        for row in self._track_rows:
            row.destroy()
        self._track_vars.clear()
        self._track_urls.clear()
        self._track_checkboxes.clear()
        self._track_status_labels.clear()
        self._track_rows.clear()
        self.track_search_text.clear()
        self._fetched_count = 0
        self._fetch_warnings = 0
        self.selection_summary.configure(text="0 / 0 Selected")
        self.batch_size_label.configure(text="Selected Batch Size: 0 MB")
        self.empty_tracks_label.grid()

    def _add_track(self, track: Dict[str, Any]) -> None:
        title = str(track.get("title") or "Unknown title")
        artist = str(track.get("artist") or track.get("artists") or "Unknown artist")
        album = str(track.get("album") or "")
        duration = self._format_duration(track.get("duration"))
        self.empty_tracks_label.grid_remove()
        variable = ctk.BooleanVar(value=True)
        row = ctk.CTkFrame(self.track_scroll, fg_color="transparent", corner_radius=0)
        row.grid(row=self._fetched_count, column=0, columnspan=6, sticky="ew")
        self.track_search_text[row] = f"{title} {artist} {album}".lower()
        row.grid_columnconfigure(1, weight=3)
        row.grid_columnconfigure(2, weight=2)
        checkbox = ctk.CTkCheckBox(row, text="", variable=variable, width=22, checkbox_width=18, checkbox_height=18,
                                   fg_color=LIQUID_CYAN, hover_color=LIQUID_VIOLET, command=self._update_selection_summary)
        checkbox.grid(row=0, column=0, padx=(12, 7), pady=8)
        title_cell = ctk.CTkFrame(row, fg_color="transparent")
        title_cell.grid(row=0, column=1, padx=5, pady=6, sticky="ew")
        ctk.CTkLabel(title_cell, text=title[:58], anchor="w", text_color=TEXT_PRIMARY,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(title_cell, text=artist[:48], anchor="w", text_color=TEXT_SECONDARY,
                     font=ctk.CTkFont(size=9)).grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(row, text=album[:34] or "-", anchor="w", text_color=TEXT_SECONDARY,
                     font=ctk.CTkFont(size=10)).grid(row=0, column=2, padx=7, sticky="ew")
        LiquidPill(row, text=f"{self.config_manager.bitrate}", width=58, height=22, text_color=LIQUID_VIOLET,
                   font=ctk.CTkFont(size=8, weight="bold")).grid(row=0, column=3, padx=5)
        ctk.CTkLabel(row, text=duration, width=60, text_color=TEXT_SECONDARY,
                     font=ctk.CTkFont(size=9)).grid(row=0, column=4, padx=4)
        state_badge = LiquidPill(row, text="PENDING", width=65, height=22, text_color=TEXT_SECONDARY,
                                 font=ctk.CTkFont(size=8, weight="bold"))
        state_badge.grid(row=0, column=5, padx=(4, 11))
        self._track_vars.append(variable)
        self._track_urls.append(str(track.get("url") or ""))
        self._track_checkboxes.append(checkbox)
        self._track_status_labels.append(state_badge)
        self._track_rows.append(row)
        self._fetched_count += 1
        self._update_selection_summary()

    @staticmethod
    def _format_duration(value: Any) -> str:
        try:
            seconds = int(float(value))
        except (TypeError, ValueError):
            return "--:--"
        return f"{seconds // 60}:{seconds % 60:02d}"

    def _update_selection_summary(self) -> None:
        selected = sum(variable.get() for variable in self._track_vars)
        self.selection_summary.configure(text=f"{selected} / {self._fetched_count} Selected")
        self.batch_size_label.configure(text=f"Selected Batch Size: {selected * 8.4:.1f} MB")
        if not self._is_downloading and not self._is_fetching:
            self.download_selected_button.configure(state="normal" if selected else "disabled")

    def _set_all_tracks(self, value: bool) -> None:
        for variable in self._track_vars:
            variable.set(value)
        self._update_selection_summary()

    def _filter_tracks(self, _event: Optional[Any] = None) -> None:
        query = self.track_search.get().strip().lower()
        for row in self._track_rows:
            visible = not query or query in self.track_search_text.get(row, "")
            if visible:
                row.grid()
            else:
                row.grid_remove()

    def _start_fetch(self) -> None:
        if self._is_downloading or self._is_fetching or self.spotdl_manager.is_running():
            self._log("Another operation is already in progress", status="warning")
            return
        url = self.url_entry.get().strip()
        if not url:
            self._log("Please enter a Spotify URL to fetch", status="error")
            return
        self._reset_selection()
        self._is_fetching = True
        self.status_label.configure(text="Fetching track metadata...")
        self.footer_label.configure(text="Fetching tracks...")
        self._set_pipeline_status("FETCHING", LIQUID_CYAN)
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.fetch_button.configure(state="disabled")
        self.download_selected_button.configure(state="disabled")
        self.browse_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self._log(f"Fetching tracks: {url}")
        self.spotdl_manager.set_config_manager(self.config_manager)
        self.spotdl_manager.fetch_tracks(url=url, callback=self._callback)

    def _download_selected(self) -> None:
        if self._is_downloading or self._is_fetching:
            self._log("Another operation is already in progress", status="warning")
            return
        selected_urls = [url for variable, url in zip(self._track_vars, self._track_urls) if variable.get() and url]
        if not selected_urls:
            self._log("Select at least one track to download", status="error")
            return
        self._begin_download(selected_urls, respect_selection=True)

    def _refresh_session_stats(self, downloaded_path: Optional[str] = None) -> None:
        if downloaded_path:
            candidate = Path(downloaded_path)
            if not candidate.is_absolute():
                candidate = self.config_manager.download_directory / candidate
            try:
                resolved = str(candidate.resolve())
                if candidate.is_file() and resolved not in self._tracked_session_files:
                    self._tracked_session_files.add(resolved)
                    self._session_bytes += candidate.stat().st_size
                    self._session_files += 1
            except OSError:
                pass
        elapsed = max(0.1, time.time() - self._last_speed_time)
        if elapsed >= 1 or downloaded_path:
            self._current_speed_bps = (self._session_bytes - self._last_speed_bytes) / elapsed
            self._last_speed_bytes = self._session_bytes
            self._last_speed_time = time.time()
        speed = self._current_speed_bps
        if speed >= 1048576:
            speed_text = f"{speed / 1048576:.1f} MB/s"
        elif speed >= 1024:
            speed_text = f"{speed / 1024:.0f} KB/s"
        else:
            speed_text = "0.0 MB/s"
        self.speed_label.configure(text=speed_text)
        self.session_stats_label.configure(text=f"Session: {self._session_files} files | {self._session_bytes / 1048576:.1f} MB")

    def _update_eta(self, done: int, total: int) -> None:
        self.song_counter_label.configure(text=f"{done} / {total} Tracks")
        if self._current_speed_bps > 0 and self._session_files:
            average_size = self._session_bytes / self._session_files
            remaining = max(0, total - done) * average_size
            seconds = int(remaining / self._current_speed_bps)
            self.eta_label.configure(text=f"{seconds // 60:02d}:{seconds % 60:02d} remaining")
        else:
            self.eta_label.configure(text="Calculating...")

    def _begin_download(self, urls: list[str] | str, respect_selection: bool = False) -> None:
        if self._is_downloading:
            return
        output_path = Path(self.config_manager.download_directory)
        self._is_downloading = True
        self._is_fetching = False
        self.status_label.configure(text="Starting download...")
        self.footer_label.configure(text="Downloading...")
        self._set_pipeline_status("EXTRACTING", LIQUID_CYAN)
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)
        self.fetch_button.configure(state="disabled")
        self.download_selected_button.configure(state="disabled")
        self.browse_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        for variable, badge in zip(self._track_vars, self._track_status_labels):
            if variable.get():
                badge.configure(text="QUEUED", text_color=LIQUID_CYAN)
        self._log(f"Output: {output_path}")
        self.spotdl_manager.set_config_manager(self.config_manager)
        self.spotdl_manager.download_track_or_playlist(url=urls, output_path=output_path,
                                                        callback=self._callback,
                                                        respect_selection=respect_selection)

    def _callback(self, status: Dict[str, Any]) -> None:
        def update() -> None:
            message = str(status.get("message", ""))
            state = status.get("status", "downloading")
            percent = status.get("percent")
            if state == "fetched":
                self._add_track(status.get("track") or {})
                self.status_label.configure(text=f"Fetched {self._fetched_count} tracks...")
                return
            if state == "fetch_error":
                self._is_fetching = False
                self.progress_bar.stop()
                self.progress_bar.configure(mode="determinate")
                self._set_idle_state()
                self.status_label.configure(text="Track fetch failed")
                self.footer_label.configure(text="Track fetch failed - see log")
                self._set_pipeline_status("FAILED", ACCENT_RED)
                self._log(message or "Track fetch failed", status="error")
                return
            if message:
                log_status = "fallback" if status.get("fallback") or "[FALLBACK]" in message else "error" if state == "error" else "success" if status.get("success") else "info"
                self._log(message, status=log_status)
                if status.get("success"):
                    match = re.search(r'Downloaded "([^"]+)"', message)
                    self._refresh_session_stats(match.group(1) if match else None)
            if percent is not None:
                try:
                    progress = max(0.0, min(1.0, float(percent) / 100))
                    self.progress_bar.set(progress)
                    self.progress_percent_label.configure(text=f"{progress * 100:.0f}%")
                except (TypeError, ValueError):
                    pass
            songs_total = status.get("songs_total")
            if songs_total is not None:
                self._update_eta(int(status.get("songs_done", 0)), int(songs_total))
            if state == "completed" and self._is_fetching:
                self._is_fetching = False
                self.progress_bar.stop()
                self.progress_bar.configure(mode="determinate")
                self.progress_bar.set(0)
                self._set_idle_state()
                self.status_label.configure(text=f"Fetched {self._fetched_count} tracks")
                self.footer_label.configure(text="Select tracks to download")
                self._set_pipeline_status("READY", LIQUID_EMERALD)
                self._log(message or f"Fetched {self._fetched_count} tracks", status="success")
            elif state == "completed":
                self.progress_bar.set(1)
                self.progress_percent_label.configure(text="100%")
                self.status_label.configure(text="Download complete")
                self.footer_label.configure(text="Download completed successfully")
                self._set_pipeline_status("COMPLETE", LIQUID_EMERALD)
                for variable, badge in zip(self._track_vars, self._track_status_labels):
                    if variable.get():
                        badge.configure(text="COMPLETE", text_color=LIQUID_EMERALD)
                self._set_downloading_state(False)
            elif state == "error":
                self.status_label.configure(text="Download failed")
                self.footer_label.configure(text="Download failed - see log")
                self._set_pipeline_status("FAILED", ACCENT_RED)
                self._set_downloading_state(False)
            elif message:
                self.status_label.configure(text=message[:120])
                self.footer_label.configure(text="Downloading...")
        self.after(0, update)

    def _set_idle_state(self) -> None:
        self.url_entry.configure(state="normal")
        self.fetch_button.configure(state="normal")
        self.download_selected_button.configure(state="normal" if any(variable.get() for variable in self._track_vars) else "disabled")
        self.browse_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")

    def _set_downloading_state(self, downloading: bool) -> None:
        self._is_downloading = downloading
        state = "disabled" if downloading else "normal"
        self.url_entry.configure(state=state)
        self.browse_button.configure(state=state)
        self.download_selected_button.configure(state=state)
        self.fetch_button.configure(state=state)
        self.cancel_button.configure(state="normal" if downloading else "disabled")
        if not downloading and self.footer_label.cget("text") == "Downloading...":
            self.footer_label.configure(text="Ready")

    def _start_download(self) -> None:
        if self._is_downloading or self._is_fetching or self.spotdl_manager.is_running():
            self._log("Another operation is already in progress", status="warning")
            return
        url = self.url_entry.get().strip()
        if not url:
            self._log("Please enter a Spotify URL", status="error")
            self.status_label.configure(text="Enter a Spotify URL to begin")
            return
        self._begin_download(url)

    def _cancel_download(self) -> None:
        if not self._is_downloading and not self._is_fetching:
            return
        self.spotdl_manager.cancel_download()
        self._is_fetching = False
        self._set_downloading_state(False)
        self._set_idle_state()
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.status_label.configure(text="Download cancelled")
        self.footer_label.configure(text="Download cancelled")
        self.progress_percent_label.configure(text="0%")
        self._set_pipeline_status("CANCELLED", ACCENT_RED)
        self.metric_speed.set("0.0 MB/s")
        self.metric_eta.set("00:00 remaining")
        self._log("Download cancelled by user", status="warning")
